"""补录历史轮、旧轮真实结局、合作方分类、删除附件：API / 网页 / 真实 CLI，全部用临时库。"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
TEMP=tempfile.TemporaryDirectory()
os.environ['PORTAL_DATA_DIR']=TEMP.name
import app as portal
import db
import tracking
from fastapi.testclient import TestClient

RW={'Authorization':'Bearer test-write'};RO={'Authorization':'Bearer test-read'}


def setup_tokens():
    c=db.connect();db.set_setting(c,'api_token','test-read');db.set_setting(c,'api_write_token','test-write');c.close()


def users():
    c=db.connect()
    admin=c.execute("SELECT id FROM users WHERE role='admin'").fetchone()['id']
    row=c.execute("SELECT id FROM users WHERE username='rounds-student'").fetchone()
    student=row['id'] if row else c.execute("INSERT INTO users(username,password_hash,display_name,role,active,created_at) VALUES('rounds-student','unused','Student','student',1,?)",(db.now(),)).lastrowid
    c.commit();c.close()
    return admin,student


class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        setup_tokens();cls.client=TestClient(portal.app)

    def paper(self,**kw):
        r=self.client.post('/api/v1/papers',json={'title':'Synthetic rounds paper',**kw},headers=RW)
        self.assertEqual(r.status_code,201,r.text);return r.json()['code']

    def sub(self,code,expect=201,**kw):
        r=self.client.post(f'/api/v1/papers/{code}/submissions',json=kw,headers=RW)
        self.assertEqual(r.status_code,expect,r.text);return r

    def get(self,code):return self.client.get(f'/api/v1/papers/{code}',headers=RO).json()

    def two_rounds(self):
        code=self.paper()
        self.sub(code,journal='J1',submit_date='2026-01-10')
        self.sub(code,journal='J2',submit_date='2026-05-01')
        return code

    # ---------------------------------------------------------------- A
    def test_history_insert_shifts_later_rounds_and_keeps_links(self):
        code=self.two_rounds();p=self.get(code)
        current=p['current_submission']['id']
        self.client.patch(f'/api/v1/submissions/{current}',json={'status':'被拒'},headers=RW)
        up=self.client.post(f'/api/v1/papers/{code}/files',headers=RW,data={'kind':'latex','submission_seq':'2'},files={'f':('j2.tex',b'J2 body')})
        self.assertEqual(up.status_code,201,up.text);fid=up.json()['id']
        ev=self.client.post(f'/api/v1/papers/{code}/events?seq=2',json={'kind':'check','event_date':'2026-06-01','text':'j2 check'},headers=RW)
        self.assertEqual(ev.status_code,201,ev.text)
        before=self.get(code)
        p=self.sub(code,journal='J-mid',submit_date='2026-03-01',history=True,outcome='被拒',manuscript_id='MID-1').json()
        self.assertEqual([(s['seq'],s['journal']) for s in p['submissions']],[(3,'J2'),(2,'J-mid'),(1,'J1')])
        self.assertEqual(p['current_submission']['id'],current)
        self.assertEqual(p['status'],before['status']);self.assertEqual(p['status'],'被拒')
        mid=p['submissions'][1]
        self.assertEqual(mid['status'],'已转投');self.assertEqual(mid['display_status'],'已转投（被拒）')
        files=self.client.get(f'/api/v1/papers/{code}/files',headers=RO).json()['files']
        f=next(x for x in files if x['id']==fid)
        self.assertEqual(f['submission_id'],current);self.assertEqual(f['submission_seq'],3)
        events=self.client.get(f'/api/v1/papers/{code}/events',headers=RO).json()['events']
        self.assertEqual({(e['submission_id'],e['seq']) for e in events if e['text']=='j2 check'},{(current,3)})
        # 插到最前：全部顺延
        p=self.sub(code,journal='J0',submit_date='2025-12-01',history=True).json()
        self.assertEqual([s['journal'] for s in p['submissions']],['J2','J-mid','J1','J0'])
        self.assertEqual([s['seq'] for s in p['submissions']],[4,3,2,1])
        c=db.connect();logs=[r['detail'] for r in c.execute("SELECT detail FROM audit WHERE action='submission.history'")];c.close()
        self.assertTrue(any(code in d and 'seq2' in d for d in logs),logs)

    def test_history_rejects_later_than_current_and_bad_input(self):
        code=self.two_rounds();before=self.get(code)['submissions']
        r=self.sub(code,422,journal='Late',submit_date='2026-06-01',history=True)
        self.assertIn('补录的历史轮不能晚于当前轮',r.json()['detail'])
        self.sub(code,422,journal='No date',history=True)
        self.sub(code,422,journal='Bad flag',submit_date='2026-02-01',history='yes')
        self.sub(code,422,journal='Bad outcome',submit_date='2026-02-01',history=True,outcome='拒稿')
        self.assertEqual(self.get(code)['submissions'],before)
        # 没有任何轮次时也不能补录
        self.sub(self.paper(),422,journal='Nothing',submit_date='2026-02-01',history=True)
        # history=false 照旧追加为最新一轮
        p=self.sub(code,journal='J3',submit_date='2026-02-01',history=False).json()
        self.assertEqual(p['current_submission']['journal'],'J3');self.assertEqual(p['current_submission']['seq'],3)

    # ---------------------------------------------------------------- B
    def test_outcome_display_and_validation(self):
        code=self.two_rounds()
        p=self.sub(code,journal='J3',submit_date='2026-07-01').json()
        cur,second,first=p['submissions']
        self.assertEqual((first['outcome'],first['display_status'],first['status']),('','已转投','已转投'))
        self.assertEqual(cur['display_status'],cur['status'])
        for value,shown in [('被拒','已转投（被拒）'),('撤回','已转投（撤回）'),('编辑建议转投','已转投（编辑建议转投）'),
                            ('编辑移除','已转投（编辑移除）'),('未关闭','未关闭（原刊流程仍在）'),('','已转投')]:
            r=self.client.patch(f"/api/v1/submissions/{first['id']}",json={'outcome':value},headers=RW)
            self.assertEqual(r.status_code,200,r.text)
            s=r.json()['submissions'][2]
            self.assertEqual((s['outcome'],s['display_status'],s['status']),(value,shown,'已转投'))
        self.assertEqual(self.client.patch(f"/api/v1/submissions/{first['id']}",json={'outcome':'拒稿'},headers=RW).status_code,422)
        # 最新轮即使带 outcome 也显示真实状态
        r=self.client.patch(f"/api/v1/submissions/{cur['id']}",json={'outcome':'被拒'},headers=RW).json()
        self.assertEqual(r['current_submission']['display_status'],'投稿中')

    def test_outcome_migration_is_idempotent_and_keeps_rows(self):
        path=Path(TEMP.name)/'legacy-schema.db'
        c=sqlite3.connect(path);c.row_factory=sqlite3.Row
        c.executescript(db.SCHEMA)
        c.execute("INSERT INTO users(username,password_hash,created_at) VALUES('u','x','t')")
        c.execute("INSERT INTO papers(owner_id,title,created_at,updated_at) VALUES(1,'legacy','t','t')")
        c.execute("INSERT INTO submissions(paper_id,seq,journal,created_at,updated_at) VALUES(1,1,'Old J','t','t')")
        c.commit()
        self.assertNotIn('outcome',{r[1] for r in c.execute('PRAGMA table_info(submissions)')})
        tracking.migrate(c);tracking.migrate(c)
        self.assertIn('outcome',{r[1] for r in c.execute('PRAGMA table_info(submissions)')})
        row=c.execute('SELECT journal,outcome FROM submissions').fetchone();c.close()
        self.assertEqual((row['journal'],row['outcome']),('Old J',''))
        db.init_db();db.init_db()  # 正式入口重复执行也不报错

    def test_web_detail_shows_outcome_and_only_admin_sets_it(self):
        admin,student=users()
        code=self.two_rounds();p=self.get(code);old=p['submissions'][1]
        self.client.patch(f"/api/v1/submissions/{old['id']}",json={'outcome':'编辑移除'},headers=RW)
        c=db.connect();pid=c.execute('SELECT id FROM papers WHERE code=?',(code,)).fetchone()['id']
        c.execute('UPDATE papers SET owner_id=? WHERE id=?',(student,pid));c.commit();c.close()
        form=lambda outcome:{'journal':'J1','submit_date':'2026-01-10','status':'投稿中','outcome':outcome}
        with TestClient(portal.app) as browser:
            browser.cookies.set(portal.COOKIE_NAME,portal.signer.dumps({'uid':admin}))
            html=browser.get(f'/paper/{pid}').text
            self.assertIn('已转投（编辑移除）',html);self.assertIn('name="outcome"',html)
            r=browser.post(f"/submission/{old['id']}/edit",data=form('未关闭'),follow_redirects=False)
            self.assertEqual(r.status_code,303)
            self.assertEqual(self.get(code)['submissions'][1]['outcome'],'未关闭')
            self.assertIn('未关闭（原刊流程仍在）',browser.get(f'/paper/{pid}').text)
            browser.cookies.set(portal.COOKIE_NAME,portal.signer.dumps({'uid':student}))
            html=browser.get(f'/paper/{pid}').text
            self.assertIn('未关闭（原刊流程仍在）',html);self.assertNotIn('name="outcome"',html)
            browser.post(f"/submission/{old['id']}/edit",data=form('被拒'),follow_redirects=False)
            self.assertEqual(self.get(code)['submissions'][1]['outcome'],'未关闭')

    # ---------------------------------------------------------------- C
    def test_partner_category_code_stats_and_filter(self):
        before=self.client.get('/api/v1/stats',headers=RO).json()
        r=self.client.post('/api/v1/papers',json={'title':'Synthetic partner paper','category':'partner','author_pos':'第二作者','is_corresponding':True},headers=RW)
        self.assertEqual(r.status_code,201,r.text);partner=r.json()
        self.assertEqual(partner['category'],'合作方论文');self.assertTrue(partner['code'].startswith('P'))
        extra=self.client.post('/api/v1/papers',json={'title':'Synthetic extra paper','category':'其他论文（不计入主序列）'},headers=RW).json()
        self.assertTrue(extra['code'].startswith('X'));self.assertEqual(extra['category'],'其他论文（不计入主序列）')
        main=self.paper(author_pos='第二作者')
        after=self.client.get('/api/v1/stats',headers=RO).json()
        delta=lambda path:after_get(after,path)-after_get(before,path)
        self.assertEqual(delta(('by_category','合作方论文')),1);self.assertEqual(delta(('by_category','其他论文（不计入主序列）')),1)
        self.assertEqual(delta(('by_category','主序列')),1);self.assertEqual(delta(('main_series','total')),1)
        self.assertEqual(delta(('main_series','by_author_position','第二作者')),1)
        self.assertEqual(delta(('main_series','corresponding_count')),0)
        self.assertEqual(delta(('total',)),3)  # 原有字段口径不变
        self.assertEqual(self.client.post('/api/v1/papers',json={'title':'bad','category':'friend'},headers=RW).status_code,422)
        r=self.client.patch(f'/api/v1/papers/{main}',json={'category':'partner'},headers=RW)
        self.assertEqual(r.json()['category'],'合作方论文');self.assertEqual(r.json()['code'],main)
        self.assertEqual(self.client.patch(f'/api/v1/papers/{main}',json={'category':'friend'},headers=RW).status_code,422)
        admin,student=users()
        with TestClient(portal.app) as browser:
            browser.cookies.set(portal.COOKIE_NAME,portal.signer.dumps({'uid':admin}))
            html=browser.get('/?role=__partner__').text
            self.assertIn(partner['code'],html);self.assertNotIn(extra['code'],html);self.assertIn('合作方',html)
            self.assertIn('<option value="partner">合作方论文</option>',browser.get('/paper/new').text)
            self.assertIn('合作方论文 · 不计入主序列',browser.get(f"/paper/{partner_pid(partner['code'])}").text)
            browser.cookies.set(portal.COOKIE_NAME,portal.signer.dumps({'uid':student}))
            r=browser.post('/paper/new',data={'title':'Student tries partner','category':'partner'},follow_redirects=False)
            pid=int(r.headers['location'].split('/paper/')[1].split('?')[0])
            c=db.connect();cat=c.execute('SELECT category FROM papers WHERE id=?',(pid,)).fetchone()['category'];c.close()
            self.assertEqual(cat,'main')
            browser.post(f'/paper/{pid}/edit',data={'title':'Student tries partner','category':'partner'},follow_redirects=False)
            c=db.connect();cat=c.execute('SELECT category FROM papers WHERE id=?',(pid,)).fetchone()['category'];c.close()
            self.assertEqual(cat,'main')
            browser.cookies.set(portal.COOKIE_NAME,portal.signer.dumps({'uid':admin}))
            browser.post(f'/paper/{pid}/edit',data={'title':'Admin sets partner','category':'partner'},follow_redirects=False)
            c=db.connect();cat=c.execute('SELECT category FROM papers WHERE id=?',(pid,)).fetchone()['category'];c.close()
            self.assertEqual(cat,'partner')
            browser.post(f'/paper/{pid}/edit',data={'title':'Admin legacy extra box','is_extra':'1'},follow_redirects=False)
            c=db.connect();cat=c.execute('SELECT category FROM papers WHERE id=?',(pid,)).fetchone()['category'];c.close()
            self.assertEqual(cat,'extra')

    # ---------------------------------------------------------------- D
    def test_delete_file_api_permissions_snapshot_and_audit(self):
        code=self.two_rounds();other=self.paper()
        fid=self.client.post(f'/api/v1/papers/{code}/files',headers=RW,files={'f':('del.txt',b'delete me')}).json()['id']
        c=db.connect();stored=db.DATA_DIR/c.execute('SELECT stored_path FROM files WHERE id=?',(fid,)).fetchone()['stored_path'];c.close()
        self.assertTrue(stored.is_file())
        url=f'/api/v1/files/{fid}'
        self.assertEqual(self.client.delete(url+f'?confirm={fid}',headers=RO).status_code,403)
        self.assertEqual(self.client.delete(url+f'?confirm={fid}').status_code,401)
        self.assertEqual(self.client.delete(url+f'?confirm={fid}&paper={other}',headers=RW).status_code,422)
        self.assertEqual(self.client.delete(url,headers=RW).status_code,428)
        self.assertEqual(self.client.delete('/api/v1/files/999999?confirm=999999',headers=RW).status_code,404)
        self.assertTrue(stored.is_file())
        r=self.client.delete(url+f'?confirm={fid}&paper={code.lower()}',headers=RW)
        self.assertEqual(r.status_code,200,r.text);d=r.json()
        self.assertEqual((d['deleted_file'],d['paper'],d['disk_file_existed']),(fid,code,True))
        self.assertFalse(stored.exists())
        self.assertTrue((db.DATA_DIR/'backups'/d['snapshot']).is_file())
        snap=sqlite3.connect(db.DATA_DIR/'backups'/d['snapshot'])
        self.assertEqual(snap.execute('SELECT COUNT(*) FROM files WHERE id=?',(fid,)).fetchone()[0],1);snap.close()
        c=db.connect()
        self.assertIsNone(c.execute('SELECT 1 FROM files WHERE id=?',(fid,)).fetchone())
        logs=[r['detail'] for r in c.execute("SELECT detail FROM audit WHERE action='file.delete'")];c.close()
        self.assertTrue(any(f'file#{fid}' in x and d['snapshot'] in x for x in logs),logs)


def partner_pid(code):
    c=db.connect();pid=c.execute('SELECT id FROM papers WHERE code=?',(code,)).fetchone()['id'];c.close()
    return pid


def after_get(d,path):
    for k in path:d=d.get(k,0) if isinstance(d,dict) else 0
    return d or 0


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

    def run_cli(self,*args,ok=True):
        r=subprocess.run([sys.executable,str(ROOT/'paper_cli.py'),*args],env=self.env,capture_output=True,text=True,timeout=20)
        self.assertEqual(r.returncode==0,ok,r.stderr+r.stdout);return r

    def cli(self,*args):return json.loads(self.run_cli('--json',*args).stdout)

    def test_cli_history_outcome_show_and_watch(self):
        code=self.cli('new','--title','CLI rounds paper')['code']
        self.cli('submit',code,'--journal','First J','--date','2026-01-05','--ms-id','FIRST-1')
        self.cli('submit',code,'--journal','Current J','--date','2026-05-05')
        self.run_cli('submit',code,'--journal','Late J','--date','2026-08-01','--history',ok=False)
        self.run_cli('submit',code,'--journal','No date','--history',ok=False)
        p=self.cli('submit',code,'--journal','Middle J','--date','2026-03-01','--history','--outcome','被拒')
        self.assertEqual([s['journal'] for s in p['submissions']],['Current J','Middle J','First J'])
        first=p['submissions'][2]['id']
        p=self.cli('sub-edit',str(first),'--outcome','未关闭')
        self.assertEqual(p['submissions'][2]['display_status'],'未关闭（原刊流程仍在）')
        text=self.run_cli('show',code).stdout
        self.assertIn('已转投（被拒）',text);self.assertIn('未关闭（原刊流程仍在）',text)
        listing=self.run_cli('list').stdout
        self.assertIn(code,listing)
        w=self.cli('watch','--days','30')
        hit=[u for u in w['unclosed_old_rounds'] if u['code']==code]
        self.assertEqual(hit,[{'code':code,'seq':1,'submission_id':first,'journal':'First J','manuscript_id':'FIRST-1','submit_date':'2026-01-05'}])
        text=self.run_cli('watch','--days','30','--mode','due').stdout
        self.assertIn('旧流程未关闭（防一稿多投）',text);self.assertIn('FIRST-1',text)
        self.cli('sub-edit',str(first),'--outcome','')
        self.assertFalse([u for u in self.cli('watch')['unclosed_old_rounds'] if u['code']==code])

    def test_cli_partner_category_and_stats(self):
        p=self.cli('new','--title','CLI partner paper','--category','partner')
        self.assertEqual(p['category'],'合作方论文');self.assertTrue(p['code'].startswith('P'))
        self.assertEqual(self.cli('new','--title','CLI extra paper','--extra')['category'],'其他论文（不计入主序列）')
        self.run_cli('new','--title','conflict','--extra','--category','partner',ok=False)
        self.run_cli('new','--title','bad','--category','friend',ok=False)
        self.assertEqual(self.cli('edit',p['code'],'--category','main')['category'],'主序列')
        self.assertEqual(self.cli('edit',p['code'],'--category','partner')['category'],'合作方论文')
        text=self.run_cli('stats').stdout
        self.assertIn('合作方论文',text);self.assertIn('不计入主序列',text);self.assertIn('主序列 · 按状态',text)

    def test_cli_rm_file_requires_yes_owner_and_snapshots(self):
        code=self.cli('new','--title','CLI file paper')['code'];other=self.cli('new','--title','CLI other paper')['code']
        src=Path(TEMP.name)/'cli-rm.txt';src.write_text('to delete')
        fid=self.cli('upload',code,str(src))['id']
        r=self.run_cli('rm-file',code,str(fid),ok=False);self.assertIn('--yes',r.stderr)
        r=self.run_cli('rm-file',other,str(fid),'--yes',ok=False);self.assertIn('422',r.stderr)
        self.assertEqual([f['id'] for f in self.cli('files',code)['files']],[fid])
        d=self.cli('rm-file',code,str(fid),'--yes')
        self.assertEqual(d['deleted_file'],fid);self.assertTrue((db.DATA_DIR/'backups'/d['snapshot']).is_file())
        self.assertEqual(self.cli('files',code)['count'],0)
        self.run_cli('rm-file',code,str(fid),'--yes',ok=False)


if __name__=='__main__':unittest.main()
