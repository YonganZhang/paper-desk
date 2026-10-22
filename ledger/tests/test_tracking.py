"""Public API and real CLI round trips against a disposable portal."""
import concurrent.futures
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
from datetime import date,timedelta
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
TEMP=tempfile.TemporaryDirectory()
os.environ['PORTAL_DATA_DIR']=TEMP.name
import app as portal
import db
from fastapi.testclient import TestClient

class PortalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        c=db.connect();db.set_setting(c,'api_token','test-read');db.set_setting(c,'api_write_token','test-write');c.close()
        cls.client=TestClient(portal.app)
        cls.rw={'Authorization':'Bearer test-write'};cls.ro={'Authorization':'Bearer test-read'}

    def new(self):
        r=self.client.post('/api/v1/papers',json={'title':'Synthetic test paper'},headers=self.rw)
        self.assertEqual(r.status_code,201,r.text)
        code=r.json()['code']
        old=(date.today()-timedelta(days=70)).isoformat()
        r=self.client.post(f'/api/v1/papers/{code}/submissions',json={'journal':'Synthetic Journal','submit_date':old},headers=self.rw)
        self.assertEqual(r.status_code,201,r.text)
        return code

    def event(self,code,**kw):
        b={'kind':'progress','event_date':date.today().isoformat(),'stage':'外审中',**kw}
        return self.client.post(f'/api/v1/papers/{code}/events',json=b,headers=self.rw)

    def test_credentials_read_write_redaction(self):
        code=self.new();base=f'/api/v1/papers/{code}'
        b={'sys_password':'synthetic-pass-789','sys_account':'synthetic@example.com','sys_cookie':'session=synthetic-cookie-123','extra':{'access':'synthetic-extra-456'}}
        self.assertEqual(self.client.patch(base+'/credentials',json=b,headers=self.rw).status_code,200)
        self.assertEqual(self.client.get(base+'/credentials',headers=self.ro).status_code,403)
        r=self.client.get(base+'/credentials',headers=self.rw)
        self.assertEqual(r.json()['sys_password'],b['sys_password']);self.assertEqual(r.headers['cache-control'],'no-store')
        self.client.patch(base,json={'notes':'synthetic-pass-789 synthetic-cookie-123 synthetic-extra-456'},headers=self.rw)
        self.event(code,text='synthetic-cookie-123 synthetic-extra-456')
        plain=self.client.get(base,headers=self.ro).text
        for secret in (b['sys_password'],'synthetic-cookie-123','synthetic-extra-456'):self.assertNotIn(secret,plain)
        c=db.connect();logs=' '.join(r['detail'] for r in c.execute('SELECT detail FROM audit'));c.close()
        for value in b.values():
            if isinstance(value,str):self.assertNotIn(value,logs)

    def test_progress_checks_deadlines_and_history(self):
        code=self.new();base=f'/api/v1/papers/{code}'
        past=(date.today()-timedelta(days=40)).isoformat();due=(date.today()+timedelta(days=5)).isoformat()
        self.assertEqual(self.event(code,event_date=past,stage='大修',due_date=due).status_code,201)
        self.assertEqual(self.event(code,kind='check',stage='',text='still waiting').status_code,201)
        p=self.client.get(base,headers=self.ro).json()
        self.assertEqual(p['status'],'投稿中');self.assertEqual(p['days_without_progress'],40)
        self.assertEqual(p['days_since_current_submit'],70);self.assertEqual(p['revision_days_remaining'],5)
        self.event(code,stage='返修已提交',kind='response',text='point by point')
        p=self.client.get(base,headers=self.ro).json();self.assertIsNone(p['revision_due_date'])
        self.event(code,stage='已录用');self.assertEqual(self.client.get(base,headers=self.ro).json()['status'],'已录用')
        self.client.post(base+'/submissions',json={'journal':'Next journal','submit_date':date.today().isoformat()},headers=self.rw)
        p=self.client.get(base,headers=self.ro).json();self.assertEqual(p['status'],'投稿中');self.assertEqual(p['review_stage'],'未标注')
        self.assertEqual(len(p['events']),4);self.assertEqual(p['submissions'][1]['status'],'已转投')
        r=self.client.post(base+'/events?seq=1',json={'kind':'progress','event_date':date.today().isoformat(),'stage':'被拒'},headers=self.rw)
        self.assertEqual(r.status_code,201);self.assertEqual(self.client.get(base,headers=self.ro).json()['status'],'投稿中')

    def test_direct_status_edits_keep_timeline_and_current_round_consistent(self):
        code=self.new();base=f'/api/v1/papers/{code}'
        self.event(code,stage='大修',due_date=(date.today()+timedelta(days=10)).isoformat())
        self.client.patch(base,json={'status':'被拒'},headers=self.rw)
        p=self.client.get(base,headers=self.ro).json()
        self.assertEqual(p['current_submission']['status'],'被拒');self.assertIsNone(p['revision_due_date'])
        sid=p['current_submission']['id']
        self.client.patch(f'/api/v1/submissions/{sid}',json={'status':'投稿中'},headers=self.rw)
        p=self.client.get(base,headers=self.ro).json()
        self.assertEqual(p['review_stage'],'未标注');self.assertEqual(p['status'],'投稿中')
        self.assertEqual(len(p['events']),3)

    def test_file_versions_download_inspect_review(self):
        code=self.new();base=f'/api/v1/papers/{code}'
        raw=io.BytesIO()
        with zipfile.ZipFile(raw,'w') as z:
            z.writestr('main.tex',r'\documentclass{article}\begin{document}\section{Methods}\input{body}\cite{exists,missing}\ref{absent}\end{document}')
            z.writestr('body.tex',r'Model details. \label{present}')
            z.writestr('refs.bib','@article{exists, title={Synthetic}}')
        data=raw.getvalue();ids=[]
        for _ in range(2):
            r=self.client.post(base+'/files',headers=self.rw,data={'kind':'latex','submission_seq':'1'},files={'f':('paper.zip',data)})
            self.assertEqual(r.status_code,201,r.text);ids.append(r.json()['id'])
        files=self.client.get(base+'/files?kind=latex&seq=1',headers=self.ro).json()
        self.assertEqual(files['count'],2);self.assertEqual(files['latest']['id'],ids[-1])
        self.assertEqual(self.client.patch(base+f'/files/{ids[0]}',json={'submission_seq':99},headers=self.rw).status_code,422)
        self.assertEqual(self.client.patch(base+f'/files/{ids[0]}',json={'submission_seq':1,'kind':'latex'},headers=self.rw).status_code,200)
        self.assertEqual(self.client.get(base+'/files/latest/download?kind=latex',headers=self.rw).content,data)
        self.assertEqual(self.client.get(base+'/files/latest/download?kind=latex',headers=self.ro).status_code,403)
        d=self.client.get(base+'/document',headers=self.rw).json()
        self.assertIn('Model details',d['text']);self.assertEqual(d['checks']['unresolved_citations'],['missing'])
        self.assertEqual(d['checks']['undefined_references'],['absent'])
        r=self.event(code,kind='review',stage='大修',text='Reviewer 1: clarify model',reviewer='R1',round=2)
        self.assertEqual(r.status_code,201,r.text);eid=r.json()['id']
        r=self.client.patch(f'/api/v1/events/{eid}',json={'text':'Revised review text'},headers=self.rw)
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.client.get(base+'/events?kind=review',headers=self.ro).json()['events'][0]['text'],'Revised review text')

    def test_web_detail_and_owner_permissions(self):
        code=self.new()
        self.event(code,kind='review',stage='小修',text='Synthetic reviewer comments')
        c=db.connect();pid=c.execute('SELECT id FROM papers WHERE code=?',(code,)).fetchone()['id']
        admin=c.execute("SELECT id FROM users WHERE role='admin'").fetchone()['id']
        student=c.execute("INSERT INTO users(username,password_hash,display_name,role,active,created_at) VALUES('synthetic-student','unused','Student','student',1,?)",(db.now(),)).lastrowid
        c.commit();c.close()
        with TestClient(portal.app) as browser:
            browser.cookies.set(portal.COOKIE_NAME,portal.signer.dumps({'uid':admin}))
            r=browser.get(f'/paper/{pid}');self.assertEqual(r.status_code,200,r.text)
            self.assertIn('Synthetic reviewer comments',r.text)
            browser.cookies.set(portal.COOKIE_NAME,portal.signer.dumps({'uid':student}))
            self.assertEqual(browser.get(f'/paper/{pid}').status_code,403)

    def test_rejections_and_archive_safety(self):
        code=self.new();base=f'/api/v1/papers/{code}'
        self.assertEqual(self.event(code,event_date='2026-02-30').status_code,422)
        self.assertEqual(self.event(code,kind='check',stage='大修').status_code,422)
        self.assertEqual(self.event(code,event_date=(date.today()+timedelta(days=1)).isoformat()).status_code,422)
        self.assertEqual(self.client.post(base+'/submissions',json={'journal':'X','submit_date':'invalid'},headers=self.rw).status_code,422)
        self.assertEqual(self.client.post(base+'/files',headers=self.rw,data={'submission_seq':'oops'},files={'f':('x.tex',b'hello')}).status_code,422)
        raw=io.BytesIO()
        with zipfile.ZipFile(raw,'w') as z:z.writestr('../bad.tex','bad')
        self.client.post(base+'/files',headers=self.rw,data={'kind':'latex'},files={'f':('bad.zip',raw.getvalue())})
        self.assertEqual(self.client.get(base+'/document',headers=self.rw).status_code,422)
        self.assertEqual(self.client.get('/api/v1/papers/NO_SUCH_CODE/files',headers=self.ro).status_code,404)

    def test_concurrent_transfer_rounds(self):
        code=self.new();base=f'/api/v1/papers/{code}'
        def create(i):return self.client.post(base+'/submissions',json={'journal':f'Synthetic {i}'},headers=self.rw).status_code
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:statuses=list(ex.map(create,range(4)))
        self.assertEqual(statuses,[201]*4)
        seq=[s['seq'] for s in self.client.get(base,headers=self.ro).json()['submissions']]
        self.assertEqual(seq,[5,4,3,2,1])

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
        c=db.connect();db.set_setting(c,'api_token','test-read');db.set_setting(c,'api_write_token','test-write');c.close()

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit=True;cls.thread.join(5)

    def cli(self,*args,input_data=None,ok=True):
        r=subprocess.run([sys.executable,str(ROOT/'paper_cli.py'),*args],env=self.env,input=input_data,capture_output=True,text=True,timeout=20)
        self.assertEqual(r.returncode==0,ok,r.stderr)
        if ok:return json.loads(r.stdout)
        self.assertEqual(r.stdout,'');return r

    def test_real_cli_roundtrip_and_failures(self):
        p=self.cli('--json','new','--title','CLI synthetic paper');code=p['code']
        p=self.cli('--json','submit',code,'--journal','CLI Journal','--date',(date.today()-timedelta(days=60)).isoformat())
        sid=p['current_submission']['id']
        self.cli('--json','sub-edit',str(sid),'--from-json','-',input_data=json.dumps({'sys_password':'cli-synthetic-pass','sys_account':'cli@example.com'}))
        self.cli('--json','credentials','set',code,'--from-json','-',input_data=json.dumps({'sys_cookie':'id=cli-synthetic-cookie','extra':{'tenant':'test'}}))
        creds=self.cli('--json','credentials','show',code);self.assertEqual(creds['sys_password'],'[已保存]')
        creds=self.cli('--json','credentials','show',code,'--reveal');self.assertEqual(creds['sys_password'],'cli-synthetic-pass')
        self.cli('--json','progress',code,'--stage','大修','--date',(date.today()-timedelta(days=40)).isoformat(),'--due',(date.today()+timedelta(days=7)).isoformat())
        self.cli('--json','check-in',code,'--note','checked still pending')
        p=self.cli('--json','show',code);self.assertEqual(p['days_without_progress'],40)
        w=self.cli('--json','watch','--days','30');self.assertIn(code,[x['code'] for x in w['papers']])
        self.cli('--json','review-add',code,'--text-file','-','--reviewer','Reviewer 2','--round','2',input_data='Clarify experiments')
        reviews=self.cli('--json','reviews',code);self.assertEqual(reviews['events'][0]['text'],'Clarify experiments')
        source=Path(TEMP.name)/'cli-source.tex';source.write_text(r'\documentclass{article}\section{Results} CLI body')
        f=self.cli('--json','upload',code,str(source),'--kind','latex','--seq','1')
        download=Path(TEMP.name)/'cli-downloaded.tex'
        self.cli('--json','download',code,'--latest','--kind','latex','--out',str(download))
        self.assertEqual(source.read_bytes(),download.read_bytes())
        self.cli('--json','download',code,'--latest','--kind','latex','--out',str(download),ok=False)
        self.cli('--json','download',code,'--out',str(download)+'-unused',ok=False)
        text=self.cli('--json','text',code);self.assertIn('CLI body',text['text'])
        inspected=self.cli('--json','inspect',code);self.assertNotIn('text',inspected);self.assertEqual(inspected['checks']['sections'],['Results'])
        self.cli('--json','show','NOT_EXISTS',ok=False)
        self.cli('--json','progress',code,'--stage','大修','--date','bad',ok=False)

    def test_laptop_wrapper_transfers_and_stdin(self):
        fake=Path(TEMP.name)/'transport-bin';fake.mkdir(exist_ok=True)
        ssh_script=f"""#!{sys.executable}
import shlex,subprocess,sys
args=shlex.split(sys.argv[-1])
if args[0]=='paper' or args[0].endswith('/bin/paper'):
    args=[sys.executable,{str(ROOT/'paper_cli.py')!r}]+args[1:]
sys.exit(subprocess.call(args,stdin=sys.stdin.buffer))
"""
        scp_script=f"""#!{sys.executable}
import shutil,sys
src,dst=sys.argv[-2:]
if src.startswith('synthetic-host:'):src=src.split(':',1)[1]
if dst.startswith('synthetic-host:'):dst=dst.split(':',1)[1]
shutil.copyfile(src,dst)
"""
        for name,content in [('ssh',ssh_script),('scp',scp_script)]:
            p=fake/name;p.write_text(content);p.chmod(0o700)
        env={**self.env,'PATH':str(fake)+os.pathsep+os.environ['PATH']}
        wrapper=ROOT/'examples'/'paper_remote.py'
        def remote(*args):
            r=subprocess.run([sys.executable,str(wrapper),'--host','synthetic-host',*args],env=env,capture_output=True,text=True,timeout=20)
            self.assertEqual(r.returncode,0,r.stderr)
            return json.loads(r.stdout)
        code=self.cli('--json','new','--title','Remote synthetic paper')['code']
        self.cli('--json','submit',code,'--journal','Remote Journal')
        private=Path(TEMP.name)/'remote-private.json';private.write_text(json.dumps({'sys_password':'remote-synthetic-pass'}))
        remote('--json','credentials','set',code,'--from-json',str(private))
        self.assertEqual(self.cli('--json','credentials','show',code,'--reveal')['sys_password'],'remote-synthetic-pass')
        source=Path(TEMP.name)/'remote-source.tex';source.write_text('Remote synthetic body')
        remote('--json','upload',code,str(source),'--kind','latex')
        target=Path(TEMP.name)/'remote-result.tex'
        remote('--json','download',code,'--latest','--kind','latex','--out',str(target))
        self.assertEqual(target.read_bytes(),source.read_bytes())
        remote('--json','review-add',code,'--text-file',str(source))
        self.assertEqual(self.cli('--json','reviews',code)['events'][0]['text'],'Remote synthetic body')

if __name__=='__main__':unittest.main()
