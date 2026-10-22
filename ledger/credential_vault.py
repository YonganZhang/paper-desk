"""Administrator-only journal logins, independent of submission rounds."""
import os
from pathlib import Path
from cryptography.fernet import Fernet
from fastapi import Depends, Request, HTTPException, Form
from fastapi.responses import JSONResponse
import db

def cipher():
    # 默认放在数据目录里（和库一起备份、互不串用）；生产部署建议用 PORTAL_VAULT_KEY 指到数据目录之外的私有位置
    path=Path(os.environ.get('PORTAL_VAULT_KEY',str(db.DATA_DIR/'vault.key')))
    if not path.exists():
        path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        try:
            fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd,'wb') as f:f.write(Fernet.generate_key())
    if path.stat().st_mode & 0o077:raise RuntimeError('Vault key permissions must be 0600')
    return Fernet(path.read_bytes())

def initialize(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS private_journal_accounts (name TEXT PRIMARY KEY, url TEXT NOT NULL, payload TEXT NOT NULL, updated_at TEXT NOT NULL)")
    conn.commit()

def put(conn,name,url,account,password):
    import json
    if not name.strip() or len(name)>120:raise HTTPException(422,'账号名称不能为空且不超过120字')
    if not all(isinstance(v,str) for v in (url,account,password)):raise HTTPException(422,'字段必须为字符串')
    if url and not url.startswith('https://'):raise HTTPException(422,'登录网址必须使用 https')
    payload=cipher().encrypt(json.dumps({'account':account,'password':password},ensure_ascii=False).encode()).decode()
    conn.execute('INSERT INTO private_journal_accounts VALUES(?,?,?,?) ON CONFLICT(name) DO UPDATE SET url=excluded.url,payload=excluded.payload,updated_at=excluded.updated_at',(name,url,payload,db.now()))
    conn.commit()
    db.log(conn,'admin','journal-account.save','private credential updated')

def get(conn,name,reveal=False):
    import json
    r=conn.execute('SELECT * FROM private_journal_accounts WHERE name=?',(name,)).fetchone()
    if not r:raise HTTPException(404,'期刊账号未登记')
    secret=json.loads(cipher().decrypt(r['payload'].encode()))
    return dict(name=r['name'],url=r['url'],updated_at=r['updated_at'],**(secret if reveal else {k:'[已保存]' if v else '' for k,v in secret.items()}))

def secret_values(conn):
    return [v for r in conn.execute('SELECT name FROM private_journal_accounts') for k,v in get(conn,r['name'],True).items() if k in ('account','password') and v]

def register(app,api):
    c=db.connect();initialize(c);c.close()
    @app.get('/api/v1/journal-accounts')
    def listing(request:Request,conn=Depends(api.get_conn)):
        api.api_auth(request,conn,need_write=True)
        return JSONResponse({'accounts':[get(conn,r['name']) for r in conn.execute('SELECT name FROM private_journal_accounts ORDER BY name')]},headers={'Cache-Control':'no-store'})
    @app.get('/api/v1/journal-accounts/{name}')
    def show(name:str,request:Request,reveal:bool=False,conn=Depends(api.get_conn)):
        api.api_auth(request,conn,need_write=True)
        data=get(conn,name,reveal)
        db.log(conn,'api','journal-account.read','revealed' if reveal else 'masked')
        return JSONResponse(data,headers={'Cache-Control':'no-store'})
    @app.put('/api/v1/journal-accounts/{name}')
    async def save(name:str,request:Request,conn=Depends(api.get_conn)):
        api.api_auth(request,conn,need_write=True)
        b=await api._body(request)
        if set(b)!={'url','account','password'}:raise HTTPException(422,'需要 url/account/password')
        put(conn,name,b['url'],b['account'],b['password'])
        return {'ok':True,'name':name}
    @app.get('/private-accounts')
    def page(request:Request,conn=Depends(api.get_conn)):
        user=api.require_admin(request,conn)
        rows=[get(conn,r['name']) for r in conn.execute('SELECT name FROM private_journal_accounts ORDER BY name')]
        response=api.render(request,conn,'private_accounts.html',user=user,rows=rows)
        response.headers['Cache-Control']='no-store'
        return response
    @app.post('/private-accounts/save')
    def page_save(request:Request,name:str=Form(...),url:str=Form(''),account:str=Form(''),password:str=Form(''),conn=Depends(api.get_conn)):
        api.require_admin(request,conn)
        put(conn,name,url,account,password)
        return api.back('/private-accounts','已加密保存')
    @app.post('/private-accounts/reveal')
    def page_reveal(request:Request,name:str=Form(...),conn=Depends(api.get_conn)):
        api.require_admin(request,conn)
        db.log(conn,'admin','journal-account.read','revealed')
        response=api.render(request,conn,'private_accounts.html',user=api.require_admin(request,conn),rows=[],revealed=get(conn,name,True))
        response.headers['Cache-Control']='no-store'
        return response
