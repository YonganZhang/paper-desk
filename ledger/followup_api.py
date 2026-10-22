"""Versioned follow-up API and authenticated website views."""
import json
import sqlite3
from urllib.parse import urlsplit
from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
import db
import followup
import follow_mode

def register(app,api):
    dep=api.get_conn

    def auth(request,conn,code=None,write=False):
        if request.headers.get('Authorization'):
            api.api_auth(request,conn,need_write=write)
            return None,'api'
        user=api.current_user(request,conn)
        if not user:raise HTTPException(401,'请登录后访问跟进计划')
        if write:
            origin=request.headers.get('origin','')
            if not origin or urlsplit(origin).netloc.lower()!=request.headers.get('host','').lower():
                raise HTTPException(403,'写入必须来自本站页面')
        if code:
            paper=api._paper_by_code(conn,code)
            api._load_paper(conn,user,paper['id'])
        return user,user['username']

    def scrubber(conn):
        secrets=api._stored_secrets(conn)
        return lambda v:api._scrub(v,secrets)

    def all_rows(conn,user=None):
        papers=conn.execute('SELECT * FROM papers '+('WHERE owner_id=? ' if user and user['role']!='admin' else '')+'ORDER BY code',
                            (user['id'],) if user and user['role']!='admin' else ()).fetchall()
        scrub=scrubber(conn)
        return [followup.get(conn,p,scrub) for p in papers]

    def output(conn,code,history=False):
        p=api._paper_by_code(conn,code);scrub=scrubber(conn)
        d=followup.get(conn,p,scrub)
        if history:
            d['events']=followup.events(conn,p['id'],scrub=scrub)
            d['state_history']=followup.revisions(conn,p['id'],scrub)
        return d

    def response(body):
        return JSONResponse(body,headers={'Cache-Control':'no-store'})

    @app.get('/followups')
    def board(request:Request,archived:bool=False,conn:sqlite3.Connection=Depends(dep)):
        user=api.require_user(request,conn)
        rows=all_rows(conn,user)
        return api.render(request,conn,'followups.html',user=user,
            followups=[r for r in rows if r['active']!=archived],
            followup_counts=followup.counts(rows),archived=archived,
            followup_stages=followup.LABELS,server_time=followup.now())

    @app.get('/api/v1/followups/schema')
    def schema(request:Request,conn:sqlite3.Connection=Depends(dep)):
        auth(request,conn)
        return response(dict(schema_version=1,stages=followup.LABELS,fields=followup.DEFAULTS,
            writable_stages=followup.WRITABLE_STAGES,derived_stages=list(followup.DERIVED_STAGES),
            held_stages=list(followup.HELD_STAGES),follow_modes=follow_mode.MODES,
            event_kinds=followup.KINDS,timezone=db.TIMEZONE,
            rules=['stage/due_at/active 输出由台账推导：stage_source/due_source 标明来源；审稿阶段用 paper progress，返修截止用 --due，active 用 paper edit --follow-mode',
              '所有变更须 expected_version；冲突返回 409 并保留现有数据',
              'check 更新 last_checked_at；只有 progress 更新 last_progress_at',
              'outgoing/incoming 不自动代表解决；waiting_since 由阻碍实际改变时更新',
              'DELETE 仅归档/移除，事件与每版计划保留历史']))

    @app.get('/api/v1/followups')
    def listing(request:Request,active:bool=None,stage:str='',needs_attention:bool=False,follow_mode_filter:str=Query('',alias='follow_mode'),conn:sqlite3.Connection=Depends(dep)):
        user,_=auth(request,conn)
        mode=follow_mode.parse(follow_mode_filter) if follow_mode_filter else None  # none = 未登记
        rows=all_rows(conn,user);totals=followup.counts(rows)
        rows=[r for r in rows if (active is None or r['active']==active) and (not stage or r['stage']==stage) and
              (not needs_attention or r['needs_attention']) and (mode is None or r['follow_mode']==mode)]
        return response(dict(papers=rows,count=len(rows),counts=totals,server_time=followup.now(),schema_version=1))

    @app.get('/api/v1/followups/export')
    def export(request:Request,conn:sqlite3.Connection=Depends(dep)):
        user,_=auth(request,conn);rows=all_rows(conn,user)
        for r in rows:
            p=api._paper_by_code(conn,r['code']);r['events']=followup.events(conn,p['id'],include_deleted=True,scrub=scrubber(conn))
            safe=api._paper_json(conn,p)
            for s in safe.get('submissions',[]):s.pop('credentials_present',None)
            safe['events']=api.tracking.events(conn,p['id'],scrub=scrubber(conn))
            r['ledger']=safe
            history=output(conn,r['code'],history=True)
            r['state_history']=history['state_history']
        return response(dict(schema_version=1,source='paper-desk',timezone=db.TIMEZONE,server_time=followup.now(),papers=rows,count=len(rows)))

    @app.post('/api/v1/followups/import')
    async def import_data(request:Request,conn:sqlite3.Connection=Depends(dep)):
        user,actor=auth(request,conn,write=True)
        b=await api._body(request)
        if set(b)-{'papers','schema_version'} or not isinstance(b.get('papers'),list) or len(b['papers'])>1000:
            raise HTTPException(422,'导入需要 {papers:[{code,expected_version,followup,events}]}，最多 1000 篇')
        prepared=[];seen=set()
        for item in b['papers']:
            if not isinstance(item,dict) or set(item)-{'code','expected_version','followup','events'}:raise HTTPException(422,'未知导入字段')
            code=item.get('code')
            if not isinstance(code,str) or code in seen:raise HTTPException(422,'code 必须是唯一论文编号')
            seen.add(code);p=api._paper_by_code(conn,code)
            if user:api._load_paper(conn,user,p['id'])
            state=followup.valid_patch(item.get('followup',{}))
            events=item.get('events',[])
            if not isinstance(events,list) or len(events)>5000:raise HTTPException(422,'events 必须为列表，最多 5000 条')
            validated=[followup.valid_event(e) for e in events]
            prepared.append((p,item.get('expected_version'),state,validated))
        conn.execute('BEGIN IMMEDIATE')
        try:
            # Check the entire batch before any mutation. Conflicting copies never overwrite the server.
            for p,expected,_,_ in prepared:followup.version_check(followup.state(conn,p['id']),expected)
            for p,expected,state,events in prepared:
                # 导入只存不判：历史数据可能含已改为台账推导的 stage/due_at/active
                current,_=followup.set_state(conn,p['id'],state,expected,actor,'sync.state',enforce=False)
                for event in events:
                    followup.add_event(conn,p['id'],event,current['version'],actor)
                    current=followup.state(conn,p['id'])
            conn.commit()
        except Exception:
            conn.rollback();raise
        db.log(conn,actor,'followup.import',f'papers={len(prepared)}')
        return response(dict(ok=True,papers=[output(conn,p['code']) for p,_,_,_ in prepared],server_time=followup.now()))

    @app.get('/api/v1/papers/{code}/followup')
    def show(code:str,request:Request,history:bool=False,conn:sqlite3.Connection=Depends(dep)):
        auth(request,conn,code)
        return response(output(conn,code,history))

    @app.put('/api/v1/papers/{code}/followup')
    @app.patch('/api/v1/papers/{code}/followup')
    async def set_state(code:str,request:Request,conn:sqlite3.Connection=Depends(dep)):
        _,actor=auth(request,conn,code,write=True);p=api._paper_by_code(conn,code)
        b=await api._body(request);expected=b.pop('expected_version',None)
        conn.execute('BEGIN IMMEDIATE')
        try:
            followup.set_state(conn,p['id'],b,expected,actor)
            conn.commit()
        except Exception:conn.rollback();raise
        db.log(conn,actor,'followup.set',f'{code} fields={sorted(b)}')
        return response(output(conn,code))

    @app.delete('/api/v1/papers/{code}/followup')
    async def archive(code:str,request:Request,conn:sqlite3.Connection=Depends(dep)):
        _,actor=auth(request,conn,code,write=True);p=api._paper_by_code(conn,code)
        b=await api._body(request);expected=b.pop('expected_version',None)
        if set(b)-{'archive_reason','completion_evidence'}:raise HTTPException(422,'归档只接受 archive_reason/completion_evidence')
        b['active']=False
        conn.execute('BEGIN IMMEDIATE')
        try:followup.set_state(conn,p['id'],b,expected,actor,'archive');conn.commit()
        except Exception:conn.rollback();raise
        db.log(conn,actor,'followup.archive',code)
        return response(output(conn,code))

    @app.get('/api/v1/papers/{code}/followup/events')
    def events(code:str,request:Request,include_deleted:bool=False,conn:sqlite3.Connection=Depends(dep)):
        auth(request,conn,code);p=api._paper_by_code(conn,code)
        rows=followup.events(conn,p['id'],include_deleted,scrubber(conn))
        return response(dict(code=code,version=followup.state(conn,p['id'])['version'],events=rows,count=len(rows)))

    @app.post('/api/v1/papers/{code}/followup/events')
    async def add_event(code:str,request:Request,conn:sqlite3.Connection=Depends(dep)):
        _,actor=auth(request,conn,code,write=True);p=api._paper_by_code(conn,code)
        b=await api._body(request);expected=b.pop('expected_version',None)
        conn.execute('BEGIN IMMEDIATE')
        try:r,changed=followup.add_event(conn,p['id'],b,expected,actor);conn.commit()
        except Exception:conn.rollback();raise
        db.log(conn,actor,'followup.event',f'{code} event#{r["id"]} changed={changed}')
        return response(dict(event=next(e for e in followup.events(conn,p['id'],True,scrubber(conn)) if e['id']==r['id']),
                              changed=changed,followup=output(conn,code)))

    @app.get('/api/v1/papers/{code}/followup/events/{eid}/history')
    def event_history(code:str,eid:int,request:Request,conn:sqlite3.Connection=Depends(dep)):
        auth(request,conn,code);p=api._paper_by_code(conn,code)
        event=conn.execute('SELECT id FROM paper_followup_events WHERE paper_id=? AND id=?',(p['id'],eid)).fetchone()
        if not event:raise HTTPException(404,'事件不存在')
        rows=conn.execute('SELECT revision,snapshot,created_at FROM paper_followup_event_revisions WHERE event_id=? ORDER BY revision DESC',(eid,)).fetchall()
        scrub=scrubber(conn)
        return response(dict(event_id=eid,revisions=[{'revision':r['revision'],'created_at':r['created_at'],
             'snapshot':{k:scrub(v) if isinstance(v,str) else v for k,v in json.loads(r['snapshot']).items()}} for r in rows]))

    @app.patch('/api/v1/papers/{code}/followup/events/{eid}')
    @app.delete('/api/v1/papers/{code}/followup/events/{eid}')
    async def change_event(code:str,eid:int,request:Request,conn:sqlite3.Connection=Depends(dep)):
        _,actor=auth(request,conn,code,write=True);p=api._paper_by_code(conn,code)
        b=await api._body(request);expected=b.pop('expected_version',None)
        conn.execute('BEGIN IMMEDIATE')
        try:r=followup.edit_event(conn,p['id'],eid,b,expected,actor,request.method=='DELETE');conn.commit()
        except Exception:conn.rollback();raise
        db.log(conn,actor,'followup.event.edit',f'{code} event#{eid}')
        return response(dict(ok=True,event_id=r['id'],followup=output(conn,code)))
