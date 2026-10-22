"""Version conflicts, real API/CLI round trips and preserved follow-up evidence."""
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
TEMP=tempfile.TemporaryDirectory()
os.environ['PORTAL_DATA_DIR']=TEMP.name
import app as portal
import db
import followup
from fastapi.testclient import TestClient

class FollowupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        c=db.connect();db.set_setting(c,'api_token','test-read');db.set_setting(c,'api_write_token','test-write');c.close()
        cls.client=TestClient(portal.app)
        cls.rw={'Authorization':'Bearer test-write'};cls.ro={'Authorization':'Bearer test-read'}

    def new(self):
        return self.client.post('/api/v1/papers',json={'title':'Synthetic follow-up paper'},headers=self.rw).json()['code']

    def url(self,code):return f'/api/v1/papers/{code}/followup'
    def patch(self,code,version,**kw):return self.client.patch(self.url(code),json={'expected_version':version,**kw},headers=self.rw)
    def event(self,code,version,key='synthetic-event',**kw):
        b=dict(expected_version=version,kind='check',occurred_at='2026-10-01',text='checked',evidence_ref='synthetic',idempotency_key=key)
        b.update(kw)
        return self.client.post(self.url(code)+'/events',json=b,headers=self.rw)

    def test_draft_without_submission_and_check_progress_separation(self):
        code=self.new();u=self.url(code)
        self.assertEqual(self.client.get(u,headers=self.ro).json()['version'],0)
        r=self.patch(code,0,stage='waiting_support',waiting_since='2026-10-01',last_progress_at='2026-09-30',next_action='wait',completion_condition='access restored')
        self.assertEqual(r.status_code,200,r.text)
        old=r.json()
        r=self.event(code,1)
        self.assertEqual(r.status_code,200,r.text)
        d=r.json()['followup'];self.assertEqual(d['last_progress_at'],old['last_progress_at'])
        self.assertEqual(d['last_checked_at'],'2026-10-01T00:00:00+08:00')
        d=self.event(code,2,'reminder',kind='outgoing',occurred_at='2026-10-02',text='reminder sent').json()['followup']
        self.assertEqual(d['waiting_since'],old['waiting_since']);self.assertEqual(d['last_progress_at'],old['last_progress_at'])
        d=self.event(code,3,'substantive',kind='progress',occurred_at='2026-10-03').json()['followup']
        self.assertEqual(d['last_progress_at'],'2026-10-03T00:00:00+08:00')

    def test_idempotent_event_and_conflict_does_not_overwrite(self):
        code=self.new();u=self.url(code)
        r=self.event(code,0);self.assertTrue(r.json()['changed'])
        retry=self.event(code,0);self.assertEqual(retry.status_code,200);self.assertFalse(retry.json()['changed'])
        self.assertEqual(retry.json()['followup']['version'],1)
        self.assertEqual(self.event(code,1,text='different content').status_code,409)
        self.assertEqual(self.patch(code,0,stage='paused').status_code,409)
        d=self.client.get(u,headers=self.ro).json()
        self.assertEqual(d['stored_stage'],'unverified');self.assertEqual(d['stage'],'draft')

    def test_atomic_import_conflicts_and_validation(self):
        a=self.new();b=self.new();self.patch(a,0,stage='paused')
        data=dict(papers=[dict(code=b,expected_version=0,followup=dict(stage='waiting_support')),
                          dict(code=a,expected_version=0,followup=dict(stage='paused'))])
        r=self.client.post('/api/v1/followups/import',json=data,headers=self.rw)
        self.assertEqual(r.status_code,409,r.text)
        self.assertEqual(self.client.get(self.url(b),headers=self.ro).json()['version'],0)
        data['papers'][1]['expected_version']=1
        data['papers'][0]['events']=[dict(kind='progress',occurred_at='bad',idempotency_key='bad')]
        self.assertEqual(self.client.post('/api/v1/followups/import',json=data,headers=self.rw).status_code,422)
        self.assertEqual(self.client.get(self.url(b),headers=self.ro).json()['version'],0)

    def test_archive_reopen_and_event_history(self):
        code=self.new();u=self.url(code)
        self.assertEqual(self.patch(code,0,stage='accepted').status_code,422)
        r=self.event(code,0,kind='note',text='original').json();eid=r['event']['id']
        r=self.client.patch(u+f'/events/{eid}',json=dict(expected_version=1,text='corrected'),headers=self.rw)
        self.assertEqual(r.status_code,200)
        r=self.client.request('DELETE',u+f'/events/{eid}',json=dict(expected_version=2),headers=self.rw)
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.client.get(u+'/events',headers=self.ro).json()['count'],0)
        revisions=self.client.get(u+f'/events/{eid}/history',headers=self.ro).json()['revisions']
        self.assertEqual(len(revisions),3);self.assertEqual(revisions[-1]['snapshot']['text'],'original')
        self.assertEqual(self.patch(code,3,active=False,completion_evidence='Synthetic acceptance letter').status_code,200)
        d=self.client.get(u+'?history=true',headers=self.ro).json();self.assertFalse(d['active']);self.assertEqual(len(d['state_history']),4)
        self.assertEqual(self.patch(code,4,stage='unverified',active=True,archive_reason='').status_code,200)

    def test_concurrent_writers_only_one_version_wins(self):
        code=self.new()
        def write(i):return self.patch(code,0,next_action=f'next-{i}').status_code
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:responses=list(pool.map(write,range(4)))
        self.assertEqual(responses.count(200),1);self.assertEqual(responses.count(409),3)

    def test_safe_export_keeps_legacy_events_and_redacts_secrets(self):
        code=self.new();base=f'/api/v1/papers/{code}'
        self.client.post(base+'/submissions',json=dict(journal='Synthetic journal'),headers=self.rw)
        secret='followup-test-secret-789'
        self.client.patch(base+'/credentials',json=dict(sys_password=secret),headers=self.rw)
        self.client.post(base+'/events',json=dict(kind='check',event_date='2026-10-01',text='Legacy check'),headers=self.rw)
        self.patch(code,0,next_action=secret,target_journal='New draft target')
        r=self.client.get('/api/v1/followups/export',headers=self.ro)
        self.assertEqual(r.status_code,200);self.assertNotIn(secret,r.text);self.assertNotIn('sys_password',r.text)
        p=next(p for p in r.json()['papers'] if p['code']==code)
        self.assertEqual(p['ledger']['events'][0]['text'],'Legacy check')
        self.assertEqual(p['current_journal'],'New draft target');self.assertEqual(p['ledger_journal'],'Synthetic journal')
        self.assertEqual(p['ledger']['current_journal'],'Synthetic journal')

    def test_session_scope_csrf_and_board_render(self):
        code=self.new();u=self.url(code)
        self.assertEqual(self.client.patch(u,json=dict(expected_version=0,stage='paused'),headers=self.ro).status_code,403)
        c=db.connect();admin=c.execute("SELECT id FROM users WHERE role='admin'").fetchone()['id']
        student=c.execute("INSERT INTO users(username,password_hash,display_name,role,active,created_at) VALUES('followup-student','unused','Student','student',1,?)",(db.now(),)).lastrowid
        c.commit();c.close()
        with TestClient(portal.app) as browser:
            browser.cookies.set(portal.COOKIE_NAME,portal.signer.dumps({'uid':admin}))
            self.assertEqual(browser.get('/followups').status_code,200)
            self.assertEqual(browser.patch(u,json=dict(expected_version=0,stage='paused')).status_code,403)
            self.assertEqual(browser.patch(u,json=dict(expected_version=0,stage='paused'),headers={'Origin':'https://attacker.invalid'}).status_code,403)
            self.assertEqual(browser.patch(u,json=dict(expected_version=0,stage='paused'),headers={'Origin':'http://testserver'}).status_code,200)
            browser.cookies.set(portal.COOKIE_NAME,portal.signer.dumps({'uid':student}))
            self.assertEqual(browser.get(u).status_code,403)
            self.assertEqual(browser.get('/api/v1/followups').json()['count'],0)

class CLI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import socket,time,uvicorn
        sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(128)
        cls.server=uvicorn.Server(uvicorn.Config(portal.app,log_level='error'))
        cls.thread=threading.Thread(target=cls.server.run,kwargs={'sockets':[sock]},daemon=True);cls.thread.start()
        for _ in range(100):
            if cls.server.started:break
            time.sleep(.02)
        cls.env={**os.environ,'PORTAL_DATA_DIR':str(db.DATA_DIR),'PORTAL_LOCAL_BASE':f'http://127.0.0.1:{sock.getsockname()[1]}/api/v1'}
        c=db.connect();db.set_setting(c,'api_token','test-read');db.set_setting(c,'api_write_token','test-write');c.close()
    @classmethod
    def tearDownClass(cls):cls.server.should_exit=True;cls.thread.join(5)
    def cli(self,*args,data=None):
        r=subprocess.run([sys.executable,str(ROOT/'paper_cli.py'),'--json',*args],input=json.dumps(data) if data is not None else None,env=self.env,capture_output=True,text=True,timeout=20)
        self.assertEqual(r.returncode,0,r.stderr);return json.loads(r.stdout)
    def test_cli_roundtrip(self):
        p=self.cli('new','--title','Synthetic follow-up CLI');code=p['code']
        d=self.cli('followup','set',code,'--from-json','-',data=dict(expected_version=0,stage='paused',next_action='Prepare'))
        self.assertEqual(d['version'],1)
        self.cli('followup','event',code,'--from-json','-',data=dict(expected_version=1,kind='check',occurred_at='2026-10-01',text='Checked',idempotency_key='cli-check'))
        self.assertEqual(self.cli('followup','show',code,'--history')['version'],2)
        self.assertIn(code,[p['code'] for p in self.cli('followup','export')['papers']])
        self.cli('followup','archive',code,'--expected-version','2','--reason','Synthetic archive')
        self.assertFalse(self.cli('followup','show',code)['active'])
        self.cli('followup','reopen',code,'--expected-version','3')
        self.assertTrue(self.cli('followup','show',code)['active'])
        self.assertEqual(self.cli('followup','schema')['schema_version'],1)

if __name__=='__main__':unittest.main()
