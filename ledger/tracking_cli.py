"""Extended paper CLI commands; transport and auth remain in paper_cli."""
import argparse
import json
import os
import sys
import tempfile
import urllib.parse
from datetime import date
from pathlib import Path
import tracking
import rounds


def text_file(path):
    return sys.stdin.read() if path=='-' else Path(path).read_text(encoding='utf-8-sig')


def json_file(path):
    value=json.loads(text_file(path))
    if not isinstance(value,dict):raise ValueError('JSON 输入必须为对象')
    return value


def params(**kwargs):
    values={k:v for k,v in kwargs.items() if v is not None and v!=''}
    return '?'+urllib.parse.urlencode(values) if values else ''


def arguments(sp):
    c=sp.add_parser('journal-account',help='管理员专用加密期刊账号，不改变投稿状态')
    cs=c.add_subparsers(dest='action',required=True)
    cs.add_parser('list')
    q=cs.add_parser('set');q.add_argument('name');q.add_argument('--from-json',required=True)
    q=cs.add_parser('show');q.add_argument('name');q.add_argument('--reveal',action='store_true');q.add_argument('--out')
    c=sp.add_parser('credentials',help='按投稿轮次设置/读取账号密码与 Cookie（需写权限）')
    cs=c.add_subparsers(dest='action',required=True)
    for action in ('show','set'):
        p=cs.add_parser(action);p.add_argument('code');p.add_argument('--seq',type=int)
        if action=='set':
            p.add_argument('--from-json',help='JSON 文件或 - 从 stdin；避免密码进入命令参数')
            p.add_argument('--account');p.add_argument('--url');p.add_argument('--password-file')
            p.add_argument('--cookie-file');p.add_argument('--extra-file')
        else:
            p.add_argument('--reveal',action='store_true',help='显式输出敏感值，优先配合 --out')
            p.add_argument('--out',help='保存 JSON 到权限 0600 的新文件；拒绝覆盖')
    p=sp.add_parser('progress',help='追加期刊进展；总体状态与当前轮同步')
    p.add_argument('code');p.add_argument('--seq',type=int);p.add_argument('--stage',required=True,choices=tracking.STAGES)
    p.add_argument('--date',default=date.today().isoformat());p.add_argument('--note',default='')
    p.add_argument('--text-file');p.add_argument('--due',default='')
    p=sp.add_parser('check-in',help='记录今日核查；不会重置无进展天数')
    p.add_argument('code');p.add_argument('--seq',type=int);p.add_argument('--date',default=date.today().isoformat())
    p.add_argument('--note',default='')
    for name in ('timeline','reviews'):
        p=sp.add_parser(name,help='读取全部轮次进展/审稿与回复记录')
        p.add_argument('code');p.add_argument('--seq',type=int)
    p=sp.add_parser('review-add',help='追加审稿意见或逐点回复，保留轮次与审稿人')
    p.add_argument('code');p.add_argument('--seq',type=int);p.add_argument('--kind',choices=['review','response'],default='review')
    p.add_argument('--text-file',required=True,help='UTF-8 正文文件或 -')
    p.add_argument('--reviewer',default='');p.add_argument('--round',type=int,default=1)
    p.add_argument('--date',default=date.today().isoformat());p.add_argument('--stage',choices=tracking.STAGES,default='')
    p.add_argument('--due',default='')
    p=sp.add_parser('review-edit',help='修订审稿/回复正文，不覆盖其他字段')
    p.add_argument('eid',type=int);p.add_argument('--text-file');p.add_argument('--reviewer')
    p.add_argument('--round',type=int);p.add_argument('--due')
    p=sp.add_parser('watch',help='按无进展天数/投稿天数/返修截止筛查，默认仅投稿中')
    p.add_argument('--days',type=int,default=30);p.add_argument('--mode',choices=['stalled','submitted','unchecked','due'],default='stalled')
    p.add_argument('--status',default='投稿中');p.add_argument('--include-extra',action='store_true')
    p=sp.add_parser('files',help='附件版本列表（最新=最大文件 ID，可限定轮次与类型）')
    p.add_argument('code');p.add_argument('--kind',choices=tracking.FILE_KINDS);p.add_argument('--seq',type=int)
    p=sp.add_parser('file-edit',help='给旧附件分类或修改说明')
    p.add_argument('code');p.add_argument('fid',type=int);p.add_argument('--kind',choices=tracking.FILE_KINDS);p.add_argument('--label');p.add_argument('--seq',type=int)
    p=sp.add_parser('download',help='下载指定附件或最新版本；默认拒绝覆盖本地文件')
    p.add_argument('code');p.add_argument('--id',type=int);p.add_argument('--latest',action='store_true')
    p.add_argument('--kind',choices=tracking.FILE_KINDS);p.add_argument('--seq',type=int)
    p.add_argument('--out',required=True);p.add_argument('--force',action='store_true')
    for name in ('text','inspect'):
        p=sp.add_parser(name,help='读取最新 LaTeX 正文 / 静态检查引用与章节（不编译）')
        p.add_argument('code');p.add_argument('--id',type=int);p.add_argument('--kind',choices=tracking.FILE_KINDS,default='latex')
        p.add_argument('--seq',type=int);p.add_argument('--member');p.add_argument('--all',action='store_true')
        p.add_argument('--out')


def save_new(path,content):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as f:f.write(content)


def execute(a,api):
    cmd=a.cmd
    if cmd not in {'journal-account','credentials','progress','check-in','timeline','reviews','review-add','review-edit','watch','files','file-edit','download','text','inspect'}:
        return False
    out=None
    if cmd=='journal-account':
        path='/journal-accounts'
        if a.action!='list':path+='/'+urllib.parse.quote(a.name,safe='')
        if a.action=='set':out=api.call('PUT',path,json_file(a.from_json),write=True)
        else:
            if a.action=='show':path+=params(reveal='true' if a.reveal else 'false')
            out=api.call('GET',path,write=True)
            if getattr(a,'out',None):
                save_new(a.out,json.dumps(out,ensure_ascii=False,indent=2)+'\n')
                out={'ok':True,'saved_to':a.out}
    elif cmd=='credentials':
        path=f'/papers/{a.code}/credentials'+params(seq=a.seq)
        if a.action=='set':
            b=json_file(a.from_json) if a.from_json else {}
            for key,val in [('sys_account',a.account),('site_url',a.url)]:
                if val is not None:b[key]=val
            for field,fp in [('sys_password',a.password_file),('sys_cookie',a.cookie_file)]:
                if fp:b[field]=text_file(fp).rstrip('\r\n')
            if a.extra_file:b['extra']=json_file(a.extra_file)
            if not b:raise ValueError('至少提供一个待修改字段')
            out=api.call('PATCH',path,b,write=True)
        else:
            out=api.call('GET',path,write=True)
            if not a.reveal:
                for k in ('sys_account','sys_password','sys_cookie'):
                    out[k]='[已保存]' if out[k] else ''
                out['extra']={'saved_keys':list(out['extra'])}
            if a.out:
                save_new(a.out,json.dumps(out,ensure_ascii=False,indent=2)+'\n')
                out={'ok':True,'saved_to':a.out,'revealed':a.reveal}
    elif cmd in ('progress','check-in','review-add'):
        b={'kind':{'progress':'progress','check-in':'check','review-add':getattr(a,'kind','review')}[cmd],
           'event_date':a.date,'text':text_file(a.text_file) if getattr(a,'text_file',None) else a.note if hasattr(a,'note') else ''}
        if cmd!='check-in':b.update(stage=a.stage,due_date=a.due)
        if cmd=='review-add':b.update(reviewer=a.reviewer,round=a.round)
        out=api.call('POST',f'/papers/{a.code}/events'+params(seq=a.seq),b,write=True)
    elif cmd=='review-edit':
        b={k:v for k,v in [('reviewer',a.reviewer),('round',a.round),('due_date',a.due)] if v is not None}
        if a.text_file:b['text']=text_file(a.text_file)
        if not b:raise ValueError('至少提供一个修改字段')
        out=api.call('PATCH',f'/events/{a.eid}',b,write=True)
    elif cmd in ('timeline','reviews'):
        out=api.call('GET',f'/papers/{a.code}/events'+params(seq=a.seq))
        if cmd=='reviews':out['events']=[e for e in out['events'] if e['kind'] in ('review','response')];out['count']=len(out['events'])
        if not a.json:
            for e in out['events']:
                print(f"#{e['id']} {e['event_date']} 第{e['seq']}次 {e['kind']} {e['stage']} 审稿人:{e['reviewer'] or '—'} R{e['round']} 截止:{e['due_date'] or '—'}\n{e['text']}\n")
            print(f"共 {out['count']} 条")
            return True
    elif cmd=='watch':
        if a.days<0:raise ValueError('--days 不能为负')
        data=api.call('GET','/papers'+params(status=a.status))
        field={'stalled':'days_without_progress','submitted':'days_since_current_submit','unchecked':'days_since_last_check','due':'revision_days_remaining'}[a.mode]
        rows=[]
        for p in data['papers']:
            if not a.include_extra and p['code'].startswith('X'):continue
            v=p.get(field)
            selected=(v is not None and v<=a.days) if a.mode=='due' else (v is None or v>=a.days)
            if selected:
                p['tracking_warning']='日期未登记，请补录' if v is None else ''
                rows.append(p)
        rows.sort(key=lambda p:(p.get(field) is None, p.get(field) if a.mode=='due' else -(p.get(field) or 0)))
        # 防一稿多投：投稿中的论文若有旧轮 outcome=未关闭，不论筛选模式都单独列出
        active=data if a.status=='投稿中' else api.call('GET','/papers'+params(status='投稿中'))
        unclosed=rounds.unclosed_old_rounds(active['papers'])
        out={'mode':a.mode,'threshold_days':a.days,'count':len(rows),'papers':rows,'server_time':data['server_time'],
             'unclosed_old_rounds':unclosed}
        if not a.json:
            print('编号  当前期刊 / 审稿阶段 / 已投天数 / 无进展天数 / 最近核查 / 返修截止')
            for p in rows:
                print(f"{p['code']}  {p['current_journal'] or '待补'} / {p['review_stage'] or '未标注'} / {p['days_since_current_submit']} / {p['days_without_progress']} / {p['last_checked_date'] or '未核查'} / {p['revision_due_date'] or '—'} {p['tracking_warning']}")
            print(f"共 {len(rows)} 篇；未登记日期会单独提示；不代表已自动查询期刊网站")
            if unclosed:
                print('\n旧流程未关闭（防一稿多投）：编号 / 期刊 / 稿号 / 投稿日')
                for u in unclosed:
                    print(f"{u['code']}  第{u['seq']}次 {u['journal']} / {u['manuscript_id'] or '无稿号'} / {u['submit_date'] or '无日期'}  [记录号 {u['submission_id']}]")
            return True
    elif cmd=='files':
        out=api.call('GET',f'/papers/{a.code}/files'+params(kind=a.kind,seq=a.seq))
        if not a.json:
            for f in out['files']:print(f"#{f['id']} {f['kind']} 第{f['submission_seq'] or '未绑定'}次 {f['name']} {f['size_mb']}MB {f['uploaded_at']} {f['label']}")
            print(f"共 {out['count']} 个附件；最新文件 ID: {out['latest']['id'] if out['latest'] else '无'}")
            return True
    elif cmd=='file-edit':
        b={k:v for k,v in [('kind',a.kind),('label',a.label),('submission_seq',a.seq)] if v is not None}
        if not b:raise ValueError('至少提供 --kind/--label/--seq')
        out=api.call('PATCH',f'/papers/{a.code}/files/{a.fid}',b,write=True)
    elif cmd=='download':
        if (a.id is None)==(not a.latest):raise ValueError('必须二选一：--id 或 --latest')
        if a.id is not None and (a.kind or a.seq):raise ValueError('--id 不与 --kind/--seq 同用')
        path=f'/papers/{a.code}/files/'+(str(a.id) if a.id is not None else 'latest')+'/download'+params(kind=a.kind,seq=a.seq)
        target=Path(a.out)
        if target.exists() and not a.force:raise FileExistsError('目标已存在；使用新文件名或 --force')
        fd,tmp=tempfile.mkstemp(prefix='.paper-download-',dir=target.parent)
        try:
            with os.fdopen(fd,'wb') as f:
                fid=api.download(path,f)
                f.flush();os.fsync(f.fileno())
            if a.force:os.replace(tmp,target)
            else:os.link(tmp,target);os.unlink(tmp)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
        out={'ok':True,'saved_to':str(target),'file_id':fid,'size_bytes':target.stat().st_size}
    elif cmd in ('text','inspect'):
        out=api.call('GET',f'/papers/{a.code}/document'+params(fid=a.id,kind=a.kind,seq=a.seq,member=a.member,all_text=str(a.all).lower()),write=True)
        if cmd=='inspect':out.pop('text',None)
        if a.out:
            content=out['text'] if cmd=='text' else json.dumps(out,ensure_ascii=False,indent=2)
            save_new(a.out,content)
            out={'ok':True,'saved_to':a.out}
        elif not a.json and cmd=='text':print(out['text']);return True
    if out is not None:print(json.dumps(out,ensure_ascii=False,indent=2))
    return True
