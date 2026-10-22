"""paper followup: safe versioned CRUD, evidence history and local sync."""
import json
import sys
import urllib.parse
from pathlib import Path
import followup
import follow_mode

def read_json(path):
    data=json.loads(sys.stdin.read() if path=='-' else Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(data,dict):raise ValueError('输入必须是 JSON 对象')
    return data

def arguments(sp):
    p=sp.add_parser('followup',help='逐篇跟进计划、等待事项与证据历史；乐观版本冲突防覆盖')
    ss=p.add_subparsers(dest='action',required=True)
    q=ss.add_parser('list');q.add_argument('--active',choices=['true','false']);q.add_argument('--stage',choices=followup.STAGES)
    q.add_argument('--attention',action='store_true')
    q.add_argument('--follow-mode',dest='follow_mode',choices=follow_mode.CLI_CHOICES,help='按论文跟进方式过滤；none = 未登记')
    q=ss.add_parser('show');q.add_argument('code');q.add_argument('--history',action='store_true')
    q=ss.add_parser('set');q.add_argument('code');q.add_argument('--from-json',required=True)
    q.add_argument('--expected-version',type=int)
    q=ss.add_parser('event');q.add_argument('code');q.add_argument('--from-json',required=True)
    q.add_argument('--expected-version',type=int)
    q=ss.add_parser('events');q.add_argument('code');q.add_argument('--include-deleted',action='store_true')
    for action in ('event-edit','event-remove'):
        q=ss.add_parser(action);q.add_argument('code');q.add_argument('eid',type=int)
        q.add_argument('--expected-version',type=int,required=True)
        if action=='event-edit':q.add_argument('--from-json',required=True)
    q=ss.add_parser('archive');q.add_argument('code');q.add_argument('--expected-version',type=int,required=True)
    q.add_argument('--reason',required=True);q.add_argument('--evidence',default='')
    q=ss.add_parser('reopen');q.add_argument('code');q.add_argument('--expected-version',type=int,required=True)
    q.add_argument('--stage',choices=followup.WRITABLE_STAGES,default='unverified',
                   help='只能是流程型阶段；审稿阶段由台账推导')
    q=ss.add_parser('export');q.add_argument('--out')
    q=ss.add_parser('import');q.add_argument('--from-json',required=True)
    ss.add_parser('schema')

def execute(a,api):
    if a.cmd!='followup':return False
    root='/followups';base=f'/papers/{urllib.parse.quote(getattr(a,"code",""),safe="")}/followup'
    act=a.action
    if act=='list':
        vals={k:v for k,v in [('active',a.active),('stage',a.stage),('needs_attention','true' if a.attention else None),('follow_mode',a.follow_mode)] if v is not None}
        out=api.call('GET',root+('?' + urllib.parse.urlencode(vals) if vals else ''))
    elif act=='show':out=api.call('GET',base+('?history=true' if a.history else ''))
    elif act in ('set','event'):
        b=read_json(a.from_json)
        if a.expected_version is not None:b['expected_version']=a.expected_version
        out=api.call('PATCH' if act=='set' else 'POST',base+('/events' if act=='event' else ''),b,write=True)
    elif act=='events':out=api.call('GET',base+'/events'+('?include_deleted=true' if a.include_deleted else ''))
    elif act in ('event-edit','event-remove'):
        b=read_json(a.from_json) if act=='event-edit' else {}
        b['expected_version']=a.expected_version
        out=api.call('PATCH' if act=='event-edit' else 'DELETE',base+'/events/'+str(a.eid),b,write=True)
    elif act=='archive':out=api.call('DELETE',base,dict(expected_version=a.expected_version,archive_reason=a.reason,completion_evidence=a.evidence),write=True)
    elif act=='reopen':out=api.call('PATCH',base,dict(expected_version=a.expected_version,active=True,archive_reason='',stage=a.stage),write=True)
    elif act=='export':out=api.call('GET',root+'/export')
    elif act=='import':out=api.call('POST',root+'/import',read_json(a.from_json),write=True)
    elif act=='schema':out=api.call('GET',root+'/schema')
    if act=='export' and a.out:
        target=Path(a.out)
        with target.open('x',encoding='utf-8') as f:json.dump(out,f,ensure_ascii=False,indent=2);f.write('\n')
        print(json.dumps({'ok':True,'saved_to':str(target),'count':out['count']},ensure_ascii=False));return True
    if a.json or act not in ('list','show','events'):
        print(json.dumps(out,ensure_ascii=False,indent=2));return True
    if act=='list':
        print('编号 | 跟进方式 | 当前期刊 | 跟进阶段 | 等待对象 | 下一步 | 版本')
        for r in out['papers']:
            flag=' [需处理]' if r['needs_attention'] else ''
            print(f"{r['code']} | {r['follow_mode_label']} | {r['current_journal'] or '—'} | {r['stage_label']}{flag} | {r['waiting_for'] or '—'} | {r['next_action'] or '—'} | {r['version']}")
        print(f"共 {out['count']} 篇；数据时间 {out['server_time']}")
    elif act=='show':
        src={'ledger':'台账','followup':'跟进计划'}
        print(f"[{out['code']}] {out['stage_label']}（来源：{src[out['stage_source']]}） 版本 {out['version']} 活跃 {out['active']}"
              f" 跟进方式 {out['follow_mode_label']}\n{out['title']}")
        for k in ('blocked_reason','waiting_for','next_action','action_owner','completion_condition','completion_evidence',
                  'last_progress_at','last_checked_at','waiting_since','next_check_at','due_at','decision_request'):
            print(f'{k}: {out[k] or "—"}'+(f"（来源：{src[out['due_source']]}）" if k=='due_at' and out[k] else ''))
        if a.history:
            for e in out['events']:print(f"{e['occurred_at']} {e['kind']} #{e['id']} {e['text']} [{e['evidence_ref']}]")
    else:
        for e in out['events']:print(f"{e['occurred_at']} {e['kind']} #{e['id']} {e['text']} [{e['evidence_ref']}]")
    return True
