"""Additional routes registered against the existing API/authentication contract."""
import json
import sqlite3
from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
import db
import documents
import tracking


def register(app, api):
    conn_dep=api.get_conn
    def sub(conn,code,seq=None):
        p=api._paper_by_code(conn,code)
        s=conn.execute('SELECT * FROM submissions WHERE paper_id=? '+('AND seq=? ' if seq else '')+'ORDER BY seq DESC LIMIT 1',
                       (p['id'],seq) if seq else (p['id'],)).fetchone()
        if not s:raise HTTPException(404,'没有对应投稿轮次')
        return p,s

    def file_info(conn,r):
        scrub=lambda v:api._scrub(v,api._stored_secrets(conn))
        return dict(id=r['id'],name=scrub(r['orig_name']),size_bytes=r['size'],size_mb=round(r['size']/1048576,2),
                    kind=r['kind'],label=scrub(r['label']),submission_id=r['submission_id'],
                    submission_seq=r['seq'],uploaded_at=r['created_at'])

    def file_row(conn,code,fid=None,kind='',seq=None):
        p=api._paper_by_code(conn,code)
        sql='SELECT f.*,s.seq FROM files f LEFT JOIN submissions s ON s.id=f.submission_id WHERE f.paper_id=?'
        args=[p['id']]
        if fid is not None:sql+=' AND f.id=?';args.append(fid)
        if kind:sql+=' AND f.kind=?';args.append(kind)
        if seq is not None:sql+=' AND s.seq=?';args.append(seq)
        r=conn.execute(sql+' ORDER BY f.id DESC LIMIT 1',args).fetchone()
        if not r:raise HTTPException(404,'未找到附件；旧附件 kind=other，请先分类')
        path=(db.DATA_DIR/r['stored_path']).resolve()
        if not path.is_relative_to(db.UPLOAD_DIR.resolve()):raise HTTPException(422,'附件路径不合法')
        if not path.is_file():raise HTTPException(404,'附件磁盘文件不存在')
        return r,path

    @app.get('/api/v1/papers/{code}/credentials')
    def credentials_get(code:str,request:Request,seq:int=None,conn:sqlite3.Connection=Depends(conn_dep)):
        api.api_auth(request,conn,need_write=True)
        p,s=sub(conn,code,seq)
        db.log(conn,'api','credentials.read',f"{p['code']} sub#{s['id']}")
        return JSONResponse(dict(submission_id=s['id'],seq=s['seq'],site_url=s['site_url'],
                                 sys_account=s['sys_account'],sys_password=s['sys_password'],
                                 sys_cookie=s['sys_cookie'],extra=json.loads(s['credential_extra'])),
                            headers={'Cache-Control':'no-store'})

    @app.patch('/api/v1/papers/{code}/credentials')
    async def credentials_patch(code:str,request:Request,seq:int=None,conn:sqlite3.Connection=Depends(conn_dep)):
        api.api_auth(request,conn,need_write=True)
        p,s=sub(conn,code,seq)
        b=await api._body(request)
        allowed={'site_url','sys_account','sys_password','sys_cookie','extra'}
        if not b or set(b)-allowed:raise HTTPException(422,'凭证字段只接受 site_url/sys_account/sys_password/sys_cookie/extra')
        if any(not isinstance(v,str) for k,v in b.items() if k!='extra'):raise HTTPException(422,'凭证字段必须为字符串')
        if 'extra' in b and not isinstance(b['extra'],dict):raise HTTPException(422,'extra 必须为 JSON 对象')
        sets=[];args=[]
        for k,v in b.items():
            sets.append(('credential_extra' if k=='extra' else k)+'=?')
            args.append(json.dumps(v,ensure_ascii=False) if k=='extra' else v)
        conn.execute('UPDATE submissions SET '+','.join(sets)+',updated_at=? WHERE id=?',args+[db.now(),s['id']])
        conn.execute('UPDATE papers SET updated_at=? WHERE id=?',(db.now(),p['id']))
        conn.commit()
        db.log(conn,'api','credentials.edit',f"{p['code']} sub#{s['id']} fields={sorted(b)}")
        return {'ok':True,'paper':p['code'],'submission_id':s['id'],'updated_fields':sorted(b)}

    @app.get('/api/v1/papers/{code}/events')
    def event_list(code:str,request:Request,seq:int=None,kind:str='',conn:sqlite3.Connection=Depends(conn_dep)):
        api.api_auth(request,conn)
        p=api._paper_by_code(conn,code)
        sid=sub(conn,code,seq)[1]['id'] if seq else None
        rows=tracking.events(conn,p['id'],sid,lambda t:api._scrub(t,api._stored_secrets(conn)))
        if kind:rows=[e for e in rows if e['kind']==kind]
        return {'paper':p['code'],'events':rows,'count':len(rows)}

    @app.post('/api/v1/papers/{code}/events',status_code=201)
    async def event_add(code:str,request:Request,seq:int=None,conn:sqlite3.Connection=Depends(conn_dep)):
        api.api_auth(request,conn,need_write=True)
        p,s=sub(conn,code,seq)
        b=tracking.validate_event(await api._body(request))
        fields=['kind','event_date','stage','text','reviewer','round','due_date']
        values=[b.get(k,1 if k=='round' else '') for k in fields]
        ts=db.now()
        cur=conn.execute('INSERT INTO paper_events(paper_id,submission_id,'+','.join(fields)+',created_at,updated_at) VALUES('+','.join(['?']*11)+')',
                         [p['id'],s['id']]+values+[ts,ts])
        # Progress stages may imply the top-level outcome; current round only.
        latest=conn.execute('SELECT id FROM submissions WHERE paper_id=? ORDER BY seq DESC LIMIT 1',(p['id'],)).fetchone()['id']
        if s['id']==latest and b.get('stage'):
            newest=conn.execute("SELECT stage FROM paper_events WHERE submission_id=? AND stage!='' ORDER BY event_date DESC,id DESC LIMIT 1",(s['id'],)).fetchone()['stage']
            status=newest if newest in ('已录用','被拒','撤稿') else '投稿中'
            conn.execute('UPDATE submissions SET status=?,updated_at=? WHERE id=?',(status,ts,s['id']))
            api.sync_paper_status(conn,p['id'])
        conn.execute('UPDATE papers SET updated_at=? WHERE id=?',(ts,p['id']))
        conn.commit()
        db.log(conn,'api','event.add',f"{p['code']} event#{cur.lastrowid} kind={b['kind']}")
        e=next(e for e in tracking.events(conn,p['id'],scrub=lambda t:api._scrub(t,api._stored_secrets(conn))) if e['id']==cur.lastrowid)
        return JSONResponse(e,status_code=201)

    @app.patch('/api/v1/events/{eid}')
    async def event_edit(eid:int,request:Request,conn:sqlite3.Connection=Depends(conn_dep)):
        api.api_auth(request,conn,need_write=True)
        old=conn.execute('SELECT * FROM paper_events WHERE id=?',(eid,)).fetchone()
        if not old:raise HTTPException(404,'事件不存在')
        b=await api._body(request)
        allowed={'text','reviewer','round','due_date'}
        if not b or set(b)-allowed:raise HTTPException(422,'只可修订 text/reviewer/round/due_date；新进展请新增事件')
        merged={k:old[k] for k in ['kind','event_date','stage','text','reviewer','round','due_date']};merged.update(b)
        tracking.validate_event(merged)
        conn.execute('UPDATE paper_events SET '+','.join(k+'=?' for k in b)+',updated_at=? WHERE id=?',list(b.values())+[db.now(),eid])
        conn.execute('UPDATE papers SET updated_at=? WHERE id=?',(db.now(),old['paper_id']))
        conn.commit();db.log(conn,'api','event.edit',f'event#{eid} fields={sorted(b)}')
        return {'ok':True,'event_id':eid,'updated_fields':sorted(b)}

    @app.get('/api/v1/papers/{code}/files')
    def files_list(code:str,request:Request,kind:str='',seq:int=None,conn:sqlite3.Connection=Depends(conn_dep)):
        api.api_auth(request,conn)
        p=api._paper_by_code(conn,code)
        rows=conn.execute('SELECT f.*,s.seq FROM files f LEFT JOIN submissions s ON s.id=f.submission_id WHERE f.paper_id=? ORDER BY f.id DESC',(p['id'],)).fetchall()
        items=[file_info(conn,r) for r in rows if (not kind or r['kind']==kind) and (seq is None or r['seq']==seq)]
        return {'paper':p['code'],'files':items,'count':len(items),'latest':items[0] if items else None}

    @app.get('/api/v1/papers/{code}/files/latest/download')
    def latest_download(code:str,request:Request,kind:str='',seq:int=None,conn:sqlite3.Connection=Depends(conn_dep)):
        api.api_auth(request,conn,need_write=True)
        r,path=file_row(conn,code,kind=kind,seq=seq)
        return FileResponse(path,filename=r['orig_name'],headers={'Cache-Control':'no-store','X-File-Id':str(r['id'])})

    @app.get('/api/v1/papers/{code}/files/{fid}/download')
    def file_download(code:str,fid:int,request:Request,conn:sqlite3.Connection=Depends(conn_dep)):
        api.api_auth(request,conn,need_write=True)
        r,path=file_row(conn,code,fid=fid)
        return FileResponse(path,filename=r['orig_name'],headers={'Cache-Control':'no-store','X-File-Id':str(r['id'])})

    @app.get('/api/v1/papers/{code}/document')
    def document(code:str,request:Request,fid:int=None,kind:str='latex',seq:int=None,member:str='',all_text:bool=False,conn:sqlite3.Connection=Depends(conn_dep)):
        api.api_auth(request,conn,need_write=True)
        r,path=file_row(conn,code,fid,kind if fid is None else '',seq)
        d=documents.inspect(path,r['orig_name'],member,all_text)
        scrub=lambda t:api._scrub(t,api._stored_secrets(conn))
        d['text']=scrub(d['text'])
        # Every string in inspection results follows the ordinary redaction policy.
        def clean(v):
            if isinstance(v,str):return scrub(v)
            if isinstance(v,list):return [clean(x) for x in v]
            if isinstance(v,dict):return {k:clean(x) for k,x in v.items()}
            return v
        return JSONResponse({'file':file_info(conn,r),**clean(d)},headers={'Cache-Control':'no-store'})

    @app.patch('/api/v1/papers/{code}/files/{fid}')
    async def file_edit(code:str,fid:int,request:Request,conn:sqlite3.Connection=Depends(conn_dep)):
        api.api_auth(request,conn,need_write=True)
        r,_=file_row(conn,code,fid=fid)
        b=await api._body(request)
        if not b or set(b)-{'kind','label','submission_seq'}:raise HTTPException(422,'只可修改 kind/label/submission_seq')
        if 'kind' in b and b['kind'] not in tracking.FILE_KINDS:raise HTTPException(422,'无效附件 kind')
        if 'label' in b and not isinstance(b['label'],str):raise HTTPException(422,'label 必须是字符串')
        if 'submission_seq' in b:
            value=b.pop('submission_seq')
            if type(value) is not int or value<1:raise HTTPException(422,'submission_seq 必须为正整数')
            target=conn.execute('SELECT id FROM submissions WHERE paper_id=? AND seq=?',(r['paper_id'],value)).fetchone()
            if not target:raise HTTPException(422,'该论文不存在指定投稿轮次')
            b['submission_id']=target['id']
        conn.execute('UPDATE files SET '+','.join(k+'=?' for k in b)+' WHERE id=?',list(b.values())+[fid])
        conn.execute('UPDATE papers SET updated_at=? WHERE id=?',(db.now(),r['paper_id']))
        conn.commit();db.log(conn,'api','file.edit',f"{code} file#{fid} fields={sorted(b)}")
        return {'ok':True,'file_id':fid,'updated_fields':sorted(b)}

    @app.delete('/api/v1/files/{fid}')
    def file_delete(fid:int,request:Request,confirm:str='',paper:str='',conn:sqlite3.Connection=Depends(conn_dep)):
        """删一个附件：删记录 + 删磁盘文件。删前打库快照（快照不含 uploads/，文件本身删了就回不来）。"""
        api.api_auth(request,conn,need_write=True)
        r=conn.execute('SELECT f.*,p.code FROM files f JOIN papers p ON p.id=f.paper_id WHERE f.id=?',(fid,)).fetchone()
        if not r:raise HTTPException(404,f'没有 id={fid} 的附件')
        if paper and r['code'].lower()!=paper.lower():
            raise HTTPException(422,f"附件 #{fid} 属于 {r['code']}，不属于 {paper}")
        if confirm!=str(fid):raise HTTPException(428,f'删除不可恢复。确认请带 ?confirm={fid}')
        path=(db.DATA_DIR/r['stored_path']).resolve()
        if not path.is_relative_to(db.UPLOAD_DIR.resolve()):raise HTTPException(422,'附件路径不合法，拒绝删除')
        snap=api._snapshot(f'before-del-file{fid}')
        conn.execute('DELETE FROM files WHERE id=?',(fid,))
        existed=path.is_file()
        try:
            path.unlink(missing_ok=True)
        except OSError as e:
            conn.rollback()
            raise HTTPException(500,f'磁盘文件删除失败，记录未删：{e.strerror}')
        conn.execute('UPDATE papers SET updated_at=? WHERE id=?',(db.now(),r['paper_id']))
        conn.commit()
        db.log(conn,'api','file.delete',f"{r['code']} file#{fid} {r['orig_name']} 磁盘文件{'已删' if existed else '本就不存在'} 快照 {snap}")
        return {'ok':True,'paper':r['code'],'deleted_file':fid,'name':api._scrub(r['orig_name'],api._stored_secrets(conn)),
                'disk_file_existed':existed,'snapshot':snap}
