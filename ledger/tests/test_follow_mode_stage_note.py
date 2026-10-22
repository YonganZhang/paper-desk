"""跟进方式 follow_mode、跟进计划 stage/due 由台账推导、当前情况 current_note：API / 网页 / 真实 CLI，全部用临时库。"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
TEMP=tempfile.TemporaryDirectory()
os.environ['PORTAL_DATA_DIR']=TEMP.name
import app as portal
import db
import followup
import tracking
from fastapi.testclient import TestClient

RW={'Authorization':'Bearer test-write'};RO={'Authorization':'Bearer test-read'}
TODAY=date.today().isoformat()
FUTURE=(date.today()+timedelta(days=30)).isoformat()


def setup_tokens():
    c=db.connect();db.set_setting(c,'api_token','test-read');db.set_setting(c,'api_write_token','test-write');c.close()


def users():
    c=db.connect()
    admin=c.execute("SELECT id FROM users WHERE role='admin'").fetchone()['id']
    row=c.execute("SELECT id FROM users WHERE username='mode-student'").fetchone()
    student=row['id'] if row else c.execute("INSERT INTO users(username,password_hash,display_name,role,active,created_at) VALUES('mode-student','unused','Student','student',1,?)",(db.now(),)).lastrowid
    c.commit();c.close()
    return admin,student


def pid_of(code):
    c=db.connect();pid=c.execute('SELECT id FROM papers WHERE code=?',(code,)).fetchone()['id'];c.close();return pid


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        setup_tokens();cls.client=TestClient(portal.app)

    def paper(self,expect=201,**kw):
        r=self.client.post('/api/v1/papers',json={'title':'Synthetic mode paper',**kw},headers=RW)
        self.assertEqual(r.status_code,expect,r.text);return r.json().get('code') if expect==201 else r

    def get(self,code):return self.client.get(f'/api/v1/papers/{code}',headers=RO).json()
    def edit(self,code,**kw):return self.client.patch(f'/api/v1/papers/{code}',json=kw,headers=RW)
    def fu(self,code,history=False):
        return self.client.get(f'/api/v1/papers/{code}/followup'+('?history=true' if history else ''),headers=RO).json()
    def fu_patch(self,code,**kw):
        kw.setdefault('expected_version',self.fu(code)['version'])
        return self.client.patch(f'/api/v1/papers/{code}/followup',json=kw,headers=RW)
    def submit(self,code,**kw):
        r=self.client.post(f'/api/v1/papers/{code}/submissions',json={'journal':'Synthetic J','submit_date':'2026-09-01',**kw},headers=RW)
        self.assertEqual(r.status_code,201,r.text)
    def progress(self,code,stage,due=''):
        r=self.client.post(f'/api/v1/papers/{code}/events',json={'kind':'progress','event_date':TODAY,'stage':stage,'due_date':due},headers=RW)
        self.assertEqual(r.status_code,201,r.text)


class FollowModeTests(Base):
    def test_create_and_switch_mode_syncs_active_with_revision(self):
        code=self.paper(follow_mode='self',lead_author='张三')
        p=self.get(code)
        self.assertEqual((p['follow_mode'],p['follow_mode_label'],p['lead_author']),('self','本人自查','张三'))
        f=self.fu(code,history=True)
        self.assertFalse(f['active']);self.assertFalse(f['stored_active']);self.assertEqual(f['version'],1)
        self.assertEqual((f['follow_mode'],f['follow_mode_label']),('self','本人自查'))
        self.assertEqual(f['archive_reason'],'跟进方式：本人自查')
        self.assertEqual(f['state_history'][0]['action'],'follow_mode.self')
        r=self.edit(code,follow_mode='ai');self.assertEqual(r.status_code,200,r.text)
        f=self.fu(code,history=True)
        self.assertTrue(f['active']);self.assertEqual(f['version'],2);self.assertEqual(f['archive_reason'],'')
        self.assertEqual(f['state_history'][0]['action'],'follow_mode.ai')
        self.edit(code,follow_mode='watch')  # 同为 active=true，不新增版本
        self.assertEqual(self.fu(code)['version'],2)
        self.assertEqual(self.get(code)['follow_mode_label'],'学生自管·AI盯截止')
        for mode,active in (('student',False),('partner',False),('ai',True)):
            self.edit(code,follow_mode=mode);self.assertEqual(self.fu(code)['active'],active,mode)

    def test_mode_values_labels_none_and_invalid(self):
        code=self.paper()
        self.assertEqual(self.get(code)['follow_mode'],'')
        self.assertEqual(self.get(code)['follow_mode_label'],'未登记')
        self.assertEqual(self.edit(code,follow_mode='学生自管').json()['follow_mode'],'student')
        self.assertEqual(self.edit(code,follow_mode='none').json()['follow_mode'],'')
        self.assertEqual(self.edit(code,follow_mode='self').json()['follow_mode'],'self')
        self.assertEqual(self.edit(code,follow_mode='').json()['follow_mode'],'')
        # 非法值 422，同一请求里的其他改动也不落库
        self.submit(code)
        r=self.edit(code,follow_mode='robot',status='被拒');self.assertEqual(r.status_code,422,r.text)
        p=self.get(code);self.assertEqual(p['status'],'投稿中');self.assertEqual(p['follow_mode'],'')
        self.paper(expect=422,follow_mode='robot')

    def test_unregistered_mode_keeps_stored_active(self):
        code=self.paper()
        r=self.client.request('DELETE',f'/api/v1/papers/{code}/followup',json={'expected_version':0,'archive_reason':'synthetic'},headers=RW)
        self.assertEqual(r.status_code,200,r.text);self.assertFalse(r.json()['active'])
        r=self.fu_patch(code,active=True,archive_reason='');self.assertEqual(r.status_code,200,r.text)
        self.assertTrue(r.json()['active'])

    def test_followup_active_conflicts_with_mode_return_422(self):
        code=self.paper(follow_mode='ai')
        r=self.fu_patch(code,active=False,archive_reason='x')
        self.assertEqual(r.status_code,422);self.assertIn('paper edit',r.json()['detail']);self.assertIn('--follow-mode',r.json()['detail'])
        r=self.client.request('DELETE',f'/api/v1/papers/{code}/followup',json={'expected_version':0,'archive_reason':'x'},headers=RW)
        self.assertEqual(r.status_code,422)
        self.assertEqual(self.fu_patch(code,active=True,next_action='go').status_code,200)  # 与推导一致可写
        self.edit(code,follow_mode='student')
        r=self.fu_patch(code,active=True);self.assertEqual(r.status_code,422)
        self.assertEqual(self.fu_patch(code,next_action='other field ok').status_code,200)

    def test_followup_list_filter_and_fields(self):
        a=self.paper(follow_mode='watch');b=self.paper(follow_mode='partner');c=self.paper()
        rows=self.client.get('/api/v1/followups?follow_mode=watch',headers=RO).json()['papers']
        codes={r['code'] for r in rows};self.assertIn(a,codes);self.assertNotIn(b,codes)
        self.assertTrue(all(r['follow_mode']=='watch' and r['follow_mode_label']=='学生自管·AI盯截止' for r in rows))
        none={r['code'] for r in self.client.get('/api/v1/followups?follow_mode=none',headers=RO).json()['papers']}
        self.assertIn(c,none);self.assertNotIn(a,none)
        self.assertEqual(self.client.get('/api/v1/followups?follow_mode=bogus',headers=RO).status_code,422)
        listed=self.client.get('/api/v1/papers',headers=RO).json()['papers']
        self.assertEqual(next(p for p in listed if p['code']==b)['follow_mode'],'partner')

    def test_web_only_admin_sets_mode_and_sync_runs(self):
        admin,student=users()
        code=self.paper();pid=pid_of(code)
        c=db.connect();c.execute('UPDATE papers SET owner_id=? WHERE id=?',(student,pid));c.commit();c.close()
        form=lambda **kw:{'title':'Synthetic mode paper','status':'撰写中','code':code,**kw}  # 管理员表单总带编号
        with TestClient(portal.app) as browser:
            browser.cookies.set(portal.COOKIE_NAME,portal.signer.dumps({'uid':admin}))
            self.assertIn('name="follow_mode"',browser.get(f'/paper/{pid}').text)
            r=browser.post(f'/paper/{pid}/edit',data=form(follow_mode='self'),follow_redirects=False)
            self.assertEqual(r.status_code,303)
            self.assertEqual(self.get(code)['follow_mode'],'self');self.assertFalse(self.fu(code)['active'])
            self.assertIn('跟进方式：本人自查',browser.get(f'/paper/{pid}').text)
            self.assertEqual(browser.post(f'/paper/{pid}/edit',data=form(follow_mode='bad')).status_code,422)
            browser.cookies.set(portal.COOKIE_NAME,portal.signer.dumps({'uid':student}))
            self.assertNotIn('name="follow_mode"',browser.get(f'/paper/{pid}').text)
            browser.post(f'/paper/{pid}/edit',data=form(follow_mode='ai'),follow_redirects=False)
            self.assertEqual(self.get(code)['follow_mode'],'self')
            r=browser.post('/paper/new',data={'title':'Student new','follow_mode':'ai'},follow_redirects=False)
            self.assertEqual(r.status_code,303)
            c=db.connect();row=c.execute("SELECT follow_mode FROM papers WHERE title='Student new'").fetchone();c.close()
            self.assertEqual(row['follow_mode'],'')

    def test_migration_adds_columns_idempotently(self):
        path=Path(TEMP.name)/'legacy-mode.db'
        c=sqlite3.connect(path);c.row_factory=sqlite3.Row
        c.executescript(db.SCHEMA)
        c.execute("INSERT INTO users(username,password_hash,created_at) VALUES('u','x','t')")
        c.execute("INSERT INTO papers(owner_id,title,notes,created_at,updated_at) VALUES(1,'legacy','old note','t','t')")
        c.commit()
        tracking.migrate(c);tracking.migrate(c)
        cols={r[1] for r in c.execute('PRAGMA table_info(papers)')}
        self.assertTrue({'follow_mode','current_note'}<=cols)
        row=c.execute('SELECT notes,follow_mode,current_note FROM papers').fetchone();c.close()
        self.assertEqual(tuple(row),('old note','',''))
        db.init_db();db.init_db()


class StageDerivationTests(Base):
    def test_mapping_table(self):
        cases=[('撰写中','',  'draft'),('已录用','外审中','accepted'),('撤稿','','closed'),('被拒','大修','resubmit_ready'),
               ('投稿中','大修','revision_required'),('投稿中','小修','revision_required'),
               ('投稿中','外审中','under_review'),('投稿中','等待决定','under_review'),('投稿中','返修已提交','under_review'),
               ('投稿中','编辑处理中','submitted'),('投稿中','未标注','submitted'),('投稿中','','submitted'),('投稿中',None,'submitted')]
        for status,review,want in cases:
            self.assertEqual(followup.ledger_stage(status,review),want,(status,review))

    def test_ledger_drives_stage_and_due(self):
        code=self.paper()
        f=self.fu(code);self.assertEqual((f['stage'],f['stage_source'],f['due_source']),('draft','ledger','followup'))
        self.submit(code)
        self.assertEqual(self.fu(code)['stage'],'submitted')
        self.progress(code,'外审中');self.assertEqual(self.fu(code)['stage'],'under_review')
        self.progress(code,'大修',FUTURE)
        f=self.fu(code)
        self.assertEqual((f['stage'],f['stage_label'],f['review_stage']),('revision_required','待返修','大修'))
        self.assertEqual((f['due_at'],f['due_source']),(FUTURE+'T00:00:00+08:00','ledger'))
        self.assertEqual(f['due_in_days'],30);self.assertTrue(f['needs_attention'])
        rows=self.client.get('/api/v1/followups?stage=revision_required',headers=RO).json()['papers']
        self.assertIn(code,[r['code'] for r in rows])
        self.progress(code,'返修已提交');f=self.fu(code)
        self.assertEqual((f['stage'],f['due_source']),('under_review','followup'))
        self.edit(code,status='被拒');self.assertEqual(self.fu(code)['stage'],'resubmit_ready')
        self.edit(code,status='撤稿');self.assertEqual(self.fu(code)['stage'],'closed')
        self.edit(code,status='已录用');f=self.fu(code)
        self.assertEqual(f['stage'],'accepted');self.assertFalse(f['stalled']);self.assertFalse(f['needs_attention'])

    def test_held_flow_stage_only_while_under_submission(self):
        code=self.paper();self.submit(code);self.progress(code,'外审中')
        for held in followup.HELD_STAGES:
            r=self.fu_patch(code,stage=held);self.assertEqual(r.status_code,200,r.text)
            self.assertEqual((r.json()['stage'],r.json()['stage_source']),(held,'followup'))
        self.assertEqual(self.fu_patch(code,stage='unverified').json()['stage'],'under_review')
        self.fu_patch(code,stage='awaiting_close')
        self.edit(code,status='被拒');f=self.fu(code)
        self.assertEqual((f['stage'],f['stage_source'],f['stored_stage']),('resubmit_ready','ledger','awaiting_close'))
        draft=self.paper();self.fu_patch(draft,stage='paused')
        self.assertEqual(self.fu(draft)['stage'],'draft')

    def test_writing_derived_stage_returns_422(self):
        code=self.paper()
        for stage in followup.DERIVED_STAGES:
            r=self.fu_patch(code,stage=stage)
            self.assertEqual(r.status_code,422,stage);self.assertIn('paper progress',r.json()['detail'])
        self.assertEqual(self.fu(code)['version'],0)
        for stage in followup.WRITABLE_STAGES:
            self.assertEqual(self.fu_patch(code,stage=stage).status_code,200,stage)

    def test_due_at_rules(self):
        code=self.paper();self.submit(code)
        r=self.fu_patch(code,due_at='2026-12-01');self.assertEqual(r.status_code,200,r.text)
        self.assertEqual((r.json()['due_at'],r.json()['due_source']),('2026-12-01T00:00:00+08:00','followup'))
        self.progress(code,'小修',FUTURE)
        f=self.fu(code);self.assertEqual((f['due_at'][:10],f['due_source'],f['stored_due_at'][:10]),(FUTURE,'ledger','2026-12-01'))
        r=self.fu_patch(code,due_at='2026-12-02')
        self.assertEqual(r.status_code,422);self.assertIn('--due',r.json()['detail'])
        self.assertEqual(self.fu_patch(code,due_at=FUTURE).status_code,200)
        self.assertEqual(self.fu_patch(code,due_at='').status_code,200)

    def test_import_stores_legacy_values_without_422(self):
        code=self.paper(follow_mode='ai');self.submit(code);self.progress(code,'大修',FUTURE)
        data={'papers':[{'code':code,'expected_version':0,'followup':{'stage':'accepted','due_at':'2026-12-09','active':False,'archive_reason':'legacy'}}]}
        r=self.client.post('/api/v1/followups/import',json=data,headers=RW);self.assertEqual(r.status_code,200,r.text)
        f=self.fu(code)
        self.assertEqual((f['stored_stage'],f['stored_due_at'][:10],f['stored_active']),('accepted','2026-12-09',False))
        self.assertEqual((f['stage'],f['due_at'][:10],f['active']),('revision_required',FUTURE,True))
        exported=next(p for p in self.client.get('/api/v1/followups/export',headers=RO).json()['papers'] if p['code']==code)
        self.assertEqual(exported['stored_stage'],'accepted');self.assertEqual(exported['state_history'][0]['snapshot']['stage'],'accepted')

    def test_counts_and_board_use_derived_stage(self):
        code=self.paper(title='Board derived paper');self.submit(code);self.progress(code,'大修',FUTURE)
        self.fu_patch(code,next_action='write response')
        out=self.client.get('/api/v1/followups',headers=RO).json()
        row=next(r for r in out['papers'] if r['code']==code)
        self.assertEqual(row['stage'],'revision_required')
        admin,_=users()
        with TestClient(portal.app) as browser:
            browser.cookies.set(portal.COOKIE_NAME,portal.signer.dumps({'uid':admin}))
            html=browser.get('/followups').text
            self.assertIn('data-stage="revision_required"',html)
            detail=browser.get(f'/paper/{pid_of(code)}').text
            self.assertIn('按台账审稿阶段（大修）',detail);self.assertIn('台账返修截止',detail)
            self.assertNotIn('name="due_at"',detail)


class CurrentNoteTests(Base):
    def test_api_read_write_overwrite_and_scrub(self):
        code=self.paper(current_note='外审中',notes='2026-09 投出')
        p=self.get(code);self.assertEqual((p['current_note'],p['notes']),('外审中','2026-09 投出'))
        p=self.edit(code,current_note='大修，11 月截止').json()
        self.assertEqual((p['current_note'],p['notes']),('大修，11 月截止','2026-09 投出'))
        p=self.edit(code,current_note='password: hunter22').json()
        self.assertNotIn('hunter22',p['current_note']);self.assertIn('[已脱敏]',p['current_note'])
        listed=next(x for x in self.client.get('/api/v1/papers',headers=RO).json()['papers'] if x['code']==code)
        self.assertIn('current_note',listed)

    def test_web_student_edits_own_note_and_pages_show_it(self):
        admin,student=users()
        code=self.paper(title='Note web paper');pid=pid_of(code)
        other=self.paper(title='Not student paper');other_pid=pid_of(other)
        c=db.connect();c.execute('UPDATE papers SET owner_id=? WHERE id=?',(student,pid));c.commit();c.close()
        long_note='甲'*59+'乙丙丁'
        with TestClient(portal.app) as browser:
            browser.cookies.set(portal.COOKIE_NAME,portal.signer.dumps({'uid':student}))
            r=browser.post(f'/paper/{pid}/edit',data={'title':'Note web paper','status':'撰写中','current_note':long_note,'notes':'history'},follow_redirects=False)
            self.assertEqual(r.status_code,303)
            self.assertEqual(self.get(code)['current_note'],long_note)
            detail=browser.get(f'/paper/{pid}').text
            self.assertIn('id="current-note"',detail);self.assertIn(long_note,detail);self.assertIn('name="current_note"',detail)
            index=browser.get('/').text
            self.assertIn('甲'*59+'乙…',index);self.assertNotIn('乙丙丁</div>',index)
            # 旧页面不带 current_note 字段时保留原值
            browser.post(f'/paper/{pid}/edit',data={'title':'Note web paper','status':'撰写中','notes':'history'},follow_redirects=False)
            self.assertEqual(self.get(code)['current_note'],long_note)
            r=browser.post(f'/paper/{other_pid}/edit',data={'title':'x','current_note':'hijack'},follow_redirects=False)
            self.assertEqual(r.status_code,403);self.assertEqual(self.get(other)['current_note'],'')
            browser.cookies.set(portal.COOKIE_NAME,portal.signer.dumps({'uid':admin}))
            browser.post(f'/paper/{pid}/edit',data={'title':'Note web paper','status':'撰写中','code':code,'current_note':'admin set'},follow_redirects=False)
            self.assertEqual(self.get(code)['current_note'],'admin set')


class CLITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import socket,time,uvicorn
        sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(128)
        cls.server=uvicorn.Server(uvicorn.Config(portal.app,log_level='error'))
        cls.thread=threading.Thread(target=cls.server.run,kwargs={'sockets':[sock]},daemon=True);cls.thread.start()
        for _ in range(100):
            if cls.server.started:break
            time.sleep(.02)
        if not cls.server.started:raise RuntimeError('isolated server failed to start')
        cls.env={**os.environ,'PORTAL_DATA_DIR':str(db.DATA_DIR),'PORTAL_LOCAL_BASE':f'http://127.0.0.1:{sock.getsockname()[1]}/api/v1'}
        setup_tokens()

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit=True;cls.thread.join(5)

    def run_cli(self,*args,ok=True,data=None):
        r=subprocess.run([sys.executable,str(ROOT/'paper_cli.py'),*args],input=json.dumps(data) if data is not None else None,
                         env=self.env,capture_output=True,text=True,timeout=20)
        self.assertEqual(r.returncode==0,ok,r.stderr+r.stdout);return r

    def cli(self,*args,data=None):return json.loads(self.run_cli('--json',*args,data=data).stdout)

    def test_cli_follow_mode_current_note_and_followup_filter(self):
        p=self.cli('new','--title','CLI mode paper','--follow-mode','self','--current','刚建')
        code=p['code'];self.assertEqual((p['follow_mode'],p['current_note']),('self','刚建'))
        self.assertFalse(self.cli('followup','show',code)['active'])
        p=self.cli('edit',code,'--follow-mode','watch','--current','外审中','--notes','2026-10 历史')
        self.assertEqual((p['follow_mode'],p['follow_mode_label']),('watch','学生自管·AI盯截止'))
        f=self.cli('followup','show',code);self.assertTrue(f['active']);self.assertEqual(f['follow_mode'],'watch')
        self.assertIn(code,[r['code'] for r in self.cli('followup','list','--follow-mode','watch')['papers']])
        self.assertNotIn(code,[r['code'] for r in self.cli('followup','list','--follow-mode','none')['papers']])
        text=self.run_cli('show',code).stdout
        self.assertIn('跟进方式 学生自管·AI盯截止',text)
        self.assertLess(text.index('当前情况 外审中'),text.index('备注 2026-10 历史'))
        self.assertIn('学生自管·AI盯截止',self.run_cli('followup','list','--follow-mode','watch').stdout)
        self.assertIn('来源：台账',self.run_cli('followup','show',code).stdout)
        self.assertEqual(self.cli('edit',code,'--follow-mode','none')['follow_mode'],'')
        self.run_cli('edit',code,'--follow-mode','robot',ok=False)
        r=self.run_cli('followup','set',code,'--from-json','-',data={'expected_version':self.cli('followup','show',code)['version'],'stage':'submitted'},ok=False)
        self.assertIn('422',r.stderr);self.assertIn('paper progress',r.stderr)
        self.run_cli('followup','reopen',code,'--expected-version','9','--stage','draft',ok=False)


if __name__=='__main__':unittest.main()
