"""Per-paper follow-up state and append-only evidence, separate from journal status.

All mutations use a paper-level optimistic version. Deletion archives state or
marks an event removed; original events and state revisions remain recoverable.
"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import json
import re
from fastapi import HTTPException
import db
import follow_mode
import tracking

TZ = ZoneInfo(db.TIMEZONE)
STAGES = ['unverified','draft','waiting_support','awaiting_author','submitted','under_review',
          'revision_required','resubmit_ready','awaiting_close','paused','accepted','closed']
LABELS = dict(zip(STAGES, ['未核验','待投稿','等待客服','等待作者','已提交／等待审稿','外审中','待返修','待转投',
                         '等待关闭确认','暂缓','已录用','已结束']))
KINDS = ['check','outgoing','incoming','progress','decision','note']
DEFAULTS = dict(stage='unverified',target_journal='',blocked_reason='',waiting_for='',next_action='',
    action_owner='',completion_condition='',completion_evidence='',decision_required=False,
    decision_request='',last_progress_at='',last_checked_at='',waiting_since='',next_check_at='',due_at='',
    evidence_source='',evidence_at='',
    stale_after_days=3,priority='normal',active=True,archive_reason='',policy_reference='')
# 审稿相关阶段由台账推导（论文状态 + 当前轮审稿阶段），跟进计划不能写
DERIVED_STAGES = ('draft','submitted','under_review','revision_required','resubmit_ready','accepted','closed')
# 流程型卡点：论文仍投稿中时保留跟进计划存储值（审稿阶段反映不了）
HELD_STAGES = ('awaiting_author','waiting_support','paused','awaiting_close')
WRITABLE_STAGES = [s for s in STAGES if s not in DERIVED_STAGES]
STATUS_STAGE = {'撰写中':'draft','已录用':'accepted','撤稿':'closed','被拒':'resubmit_ready'}
REVIEW_STAGE = {'大修':'revision_required','小修':'revision_required',
                '外审中':'under_review','等待决定':'under_review','返修已提交':'under_review'}
TIME_FIELDS = {'last_progress_at','last_checked_at','waiting_since','next_check_at','due_at','evidence_at'}
EDIT_FIELDS = set(DEFAULTS)

def now():
    return datetime.now(TZ).isoformat(timespec='seconds')

def stamp(value, field, allow_empty=True, past=False):
    if value == '' and allow_empty:
        return ''
    if not isinstance(value,str):
        raise HTTPException(422, f'{field} 必须为 ISO 日期或带时区时间')
    try:
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):
            parsed = datetime.combine(date.fromisoformat(value),datetime.min.time(),TZ)
        else:
            parsed = datetime.fromisoformat(value.replace('Z','+00:00'))
            if parsed.tzinfo is None:
                raise ValueError('missing timezone')
            parsed = parsed.astimezone(TZ)
    except (ValueError,TypeError):
        raise HTTPException(422,f'{field} 必须为 YYYY-MM-DD 或 ISO 带时区时间')
    if past and parsed.date() > datetime.now(TZ).date():
        raise HTTPException(422,f'{field} 不能在未来')
    return parsed.isoformat(timespec='seconds')

def migrate(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS paper_followups (
      paper_id INTEGER PRIMARY KEY REFERENCES papers(id) ON DELETE CASCADE,
      version INTEGER NOT NULL CHECK(version>0), data TEXT NOT NULL,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS paper_followup_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
      kind TEXT NOT NULL, occurred_at TEXT NOT NULL, text TEXT NOT NULL DEFAULT '',
      evidence_ref TEXT NOT NULL DEFAULT '', idempotency_key TEXT NOT NULL,
      revision INTEGER NOT NULL DEFAULT 1, deleted INTEGER NOT NULL DEFAULT 0,
      paper_version INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      UNIQUE(paper_id,idempotency_key))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS paper_followup_revisions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
      version INTEGER NOT NULL, action TEXT NOT NULL, snapshot TEXT NOT NULL,
      actor TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(paper_id,version))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS paper_followup_event_revisions (
      event_id INTEGER NOT NULL REFERENCES paper_followup_events(id) ON DELETE CASCADE,
      revision INTEGER NOT NULL, snapshot TEXT NOT NULL, created_at TEXT NOT NULL,
      PRIMARY KEY(event_id,revision))''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_followup_events_paper ON paper_followup_events(paper_id,occurred_at,id)')
    conn.commit()

def state(conn,pid):
    r=conn.execute('SELECT * FROM paper_followups WHERE paper_id=?',(pid,)).fetchone()
    return {**DEFAULTS,**(json.loads(r['data']) if r else {}),
            'version':r['version'] if r else 0,
            'created_at':r['created_at'] if r else '', 'updated_at':r['updated_at'] if r else ''}

def events(conn,pid,include_deleted=False,scrub=lambda x:x):
    rows=conn.execute('SELECT * FROM paper_followup_events WHERE paper_id=? '+
        ('' if include_deleted else 'AND deleted=0 ')+'ORDER BY occurred_at DESC,id DESC',(pid,)).fetchall()
    return [{**dict(r),'text':scrub(r['text']),'evidence_ref':scrub(r['evidence_ref']),
             'deleted':bool(r['deleted'])} for r in rows]

def revisions(conn,pid,scrub=lambda x:x):
    rows=conn.execute('SELECT version,action,snapshot,actor,created_at FROM paper_followup_revisions WHERE paper_id=? ORDER BY version DESC',(pid,)).fetchall()
    return [{**dict(r),'snapshot':{k:scrub(v) if isinstance(v,str) else v
             for k,v in json.loads(r['snapshot']).items()}} for r in rows]

def derived(data):
    today=datetime.now(TZ)
    def elapsed(v):
        return (today-datetime.fromisoformat(v)).days if v else None
    days=elapsed(data['last_progress_at'])
    wait_days=elapsed(data['waiting_since'])
    checked=elapsed(data['last_checked_at'])
    due=-(today.date()-datetime.fromisoformat(data['due_at']).date()).days if data['due_at'] else None
    check_due=bool(data['next_check_at'] and datetime.fromisoformat(data['next_check_at'])<=today)
    actionable=data['stage'] in ('draft','resubmit_ready','revision_required')
    basis=wait_days if data['stage'] in ('waiting_support','awaiting_close','awaiting_author') else days
    stale=bool(data['active'] and data['stage'] not in ('paused','accepted','closed') and data['stale_after_days']>0 and
               (basis is None or basis>=data['stale_after_days']))
    attention=bool(data['active'] and data['stage'] not in ('accepted','closed') and (data['decision_required'] or stale or check_due or
                   actionable or (due is not None and due<=7)))
    return dict(stage_label=LABELS.get(data['stage'],data['stage']),
                days_without_progress=days,days_waiting=wait_days,days_since_last_check=checked,
                due_in_days=due,check_due=check_due,stalled=stale,needs_attention=attention)

def ledger(conn,paper):
    """台账侧事实：当前轮、审稿阶段、返修截止。"""
    sub=conn.execute('SELECT * FROM submissions WHERE paper_id=? ORDER BY seq DESC LIMIT 1',(paper['id'],)).fetchone()
    summary=tracking.summary(conn,sub)
    return sub,summary['review_stage'],summary['revision_due_date']

def ledger_stage(status,review_stage):
    if status in STATUS_STAGE:return STATUS_STAGE[status]
    return REVIEW_STAGE.get(review_stage or '','submitted')

def resolve(stored,paper,review_stage,due):
    """输出用的 stage / due_at / active：审稿部分以台账为准，流程型卡点与跟进方式另算。"""
    if paper['status']=='投稿中' and stored['stage'] in HELD_STAGES:
        stage,stage_source=stored['stage'],'followup'
    else:
        stage,stage_source=ledger_stage(paper['status'],review_stage),'ledger'
    if due:due_at,due_source=stamp(due,'revision_due_date'),'ledger'
    else:due_at,due_source=stored['due_at'],'followup'
    mode=paper['follow_mode']
    return dict(stage=stage,stage_source=stage_source,due_at=due_at,due_source=due_source,
                active=follow_mode.active_for(mode,stored['active']),
                follow_mode=mode,follow_mode_label=follow_mode.label(mode),
                stored_stage=stored['stage'],stored_due_at=stored['due_at'],stored_active=stored['active'])

def get(conn,paper,scrub=lambda x:x):
    d=state(conn,paper['id'])
    for k,v in list(d.items()):
        if isinstance(v,str):d[k]=scrub(v)
    sub,review_stage,due=ledger(conn,paper)
    d.update(resolve(d,paper,review_stage,due))
    return {**d,**derived(d),'paper_id':paper['id'],'code':paper['code'],
       'title':scrub(paper['title']),'title_cn':scrub(paper['title_cn']),
       'lead_author':scrub(paper['lead_author']),'paper_status':paper['status'],
       'review_stage':review_stage,
       'current_journal':d['target_journal'] or (scrub(sub['journal']) if sub else ''),
       'ledger_journal':scrub(sub['journal']) if sub else '',
       'current_submission_seq':sub['seq'] if sub else None,
       'manuscript_id':scrub(sub['manuscript_id']) if sub else ''}

def counts(rows):
    return dict(total=len(rows),active=sum(r['active'] for r in rows),
        waiting=sum(r['active'] and r['stage'] in ('waiting_support','awaiting_author','awaiting_close') for r in rows),
        needs_decision=sum(r['active'] and r['decision_required'] for r in rows),
        attention=sum(r['needs_attention'] for r in rows),archived=sum(not r['active'] for r in rows))

def valid_patch(body):
    if not isinstance(body,dict) or set(body)-EDIT_FIELDS:
        raise HTTPException(422,'未知跟进字段；请使用 followup schema 中的字段')
    b=dict(body)
    for k,v in b.items():
        if k in ('active','decision_required'):
            if type(v) is not bool:raise HTTPException(422,f'{k} 必须为布尔值')
        elif k=='stale_after_days':
            if type(v) is not int or not 0<=v<=365:raise HTTPException(422,'stale_after_days 必须为 0 至 365 的整数')
        elif k in TIME_FIELDS:
            b[k]=stamp(v,k,past=k in ('last_progress_at','last_checked_at','waiting_since','evidence_at'))
        else:
            if not isinstance(v,str) or len(v)>20000:raise HTTPException(422,f'{k} 必须为最多 20000 字符的文本')
    if b.get('stage') is not None and b['stage'] not in STAGES:raise HTTPException(422,'无效跟进 stage')
    if b.get('priority') is not None and b['priority'] not in ('normal','high','urgent'):raise HTTPException(422,'无效 priority')
    return b

def version_check(old,expected):
    if type(expected) is not int or expected<0:raise HTTPException(422,'必须提供非负整数 expected_version')
    if old['version']!=expected:
        raise HTTPException(409,dict(message='跟进记录已变更；先读取最新版本再合并，未覆盖任何数据',current_version=old['version']))

def persist(conn,pid,data,version,actor,action):
    ts=now();raw=json.dumps({k:data[k] for k in EDIT_FIELDS},ensure_ascii=False,sort_keys=True)
    conn.execute('''INSERT INTO paper_followups(paper_id,version,data,created_at,updated_at)
      VALUES(?,?,?,?,?) ON CONFLICT(paper_id) DO UPDATE SET version=excluded.version,
      data=excluded.data,updated_at=excluded.updated_at''',(pid,version,raw,ts,ts))
    conn.execute('INSERT INTO paper_followup_revisions(paper_id,version,action,snapshot,actor,created_at) VALUES(?,?,?,?,?,?)',
      (pid,version,action,raw,actor,ts))

def ledger_rules(conn,pid,patch):
    """普通写入的口径：审稿阶段、返修截止、active 各有唯一真源，冲突就 422 并指路。"""
    if patch.get('stage') in DERIVED_STAGES:
        raise HTTPException(422,f'审稿阶段由台账推导，请用 paper progress；跟进计划 stage 只能写流程型阶段 {WRITABLE_STAGES}')
    paper=conn.execute('SELECT * FROM papers WHERE id=?',(pid,)).fetchone()
    if patch.get('due_at'):
        _,_,due=ledger(conn,paper)
        if due and patch['due_at'][:10]!=due:
            raise HTTPException(422,f'论文已有返修截止 {due}，跟进计划不另设；改截止请用 paper review-add --due 或 paper progress --due')
    mode=paper['follow_mode']
    if 'active' in patch and mode in follow_mode.ACTIVE and patch['active']!=follow_mode.ACTIVE[mode]:
        raise HTTPException(422,follow_mode.conflict_message(paper['code'],mode))

def set_state(conn,pid,body,expected,actor='api',action='state',enforce=True):
    """enforce=False 只给导入用：历史数据照存，不套用台账推导口径。"""
    old=state(conn,pid);version_check(old,expected);patch=valid_patch(body)
    if enforce:ledger_rules(conn,pid,patch)
    data={**old,**patch}
    if data['stage']=='accepted':data['active']=False
    if not data['active'] and not (data['completion_evidence'] or data['archive_reason']):
        raise HTTPException(422,'归档必须提供 completion_evidence 或 archive_reason；发送邮件不算解决')
    if {k:old[k] for k in EDIT_FIELDS}=={k:data[k] for k in EDIT_FIELDS} and old['version']:
        return old,False
    persist(conn,pid,data,old['version']+1,actor,action)
    return state(conn,pid),True

def valid_event(body):
    allowed={'kind','occurred_at','text','evidence_ref','idempotency_key'}
    if not isinstance(body,dict) or set(body)-allowed:raise HTTPException(422,'未知跟进事件字段')
    b={'text':'','evidence_ref':'',**body}
    if b.get('kind') not in KINDS:raise HTTPException(422,'无效事件 kind')
    b['occurred_at']=stamp(b.get('occurred_at'),'occurred_at',allow_empty=False,past=True)
    for k in ('text','evidence_ref'):
        if not isinstance(b[k],str) or len(b[k])>100000:raise HTTPException(422,f'{k} 最多 100000 字符')
    key=b.get('idempotency_key')
    if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9._:-]{1,180}',key):
        raise HTTPException(422,'idempotency_key 必须为 1 至 180 位字母数字或 . _ : -')
    return b

def add_event(conn,pid,body,expected,actor='api'):
    b=valid_event(body);old=state(conn,pid)
    prior=conn.execute('SELECT * FROM paper_followup_events WHERE paper_id=? AND idempotency_key=?',(pid,b['idempotency_key'])).fetchone()
    if prior:
        if any(prior[k]!=b[k] for k in ('kind','occurred_at','text','evidence_ref')):
            raise HTTPException(409,'idempotency_key 已用于不同事件；未重复写入')
        return dict(prior),False
    version_check(old,expected)
    data=dict(old)
    if b['kind']=='check' and b['occurred_at']>data['last_checked_at']:data['last_checked_at']=b['occurred_at']
    if b['kind']=='progress' and b['occurred_at']>data['last_progress_at']:data['last_progress_at']=b['occurred_at']
    ver=old['version']+1;ts=now()
    persist(conn,pid,data,ver,actor,'event.'+b['kind'])
    cur=conn.execute('''INSERT INTO paper_followup_events(paper_id,kind,occurred_at,text,evidence_ref,
      idempotency_key,paper_version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)''',
      (pid,b['kind'],b['occurred_at'],b['text'],b['evidence_ref'],b['idempotency_key'],ver,ts,ts))
    r=dict(conn.execute('SELECT * FROM paper_followup_events WHERE id=?',(cur.lastrowid,)).fetchone())
    conn.execute('INSERT INTO paper_followup_event_revisions(event_id,revision,snapshot,created_at) VALUES(?,?,?,?)',
                 (r['id'],1,json.dumps(r,ensure_ascii=False),ts))
    return r,True

def edit_event(conn,pid,eid,patch,expected,actor='api',remove=False):
    old=state(conn,pid);version_check(old,expected)
    r=conn.execute('SELECT * FROM paper_followup_events WHERE id=? AND paper_id=?',(eid,pid)).fetchone()
    if not r:raise HTTPException(404,'事件不存在')
    if r['deleted']:raise HTTPException(409,'事件已移除；原记录保留在审计历史')
    if not isinstance(patch,dict) or set(patch)-{'text','evidence_ref'} or (not patch and not remove):
        raise HTTPException(422,'只可修订 text/evidence_ref；新进展请追加事件')
    for k,v in patch.items():
        if not isinstance(v,str) or len(v)>100000:raise HTTPException(422,f'{k} 最多 100000 字符')
    data=dict(r);data.update(patch);data['deleted']=1 if remove else 0;data['revision']+=1
    data['updated_at']=now();data['paper_version']=old['version']+1
    conn.execute('UPDATE paper_followup_events SET text=?,evidence_ref=?,deleted=?,revision=?,updated_at=?,paper_version=? WHERE id=?',
       tuple(data[k] for k in ('text','evidence_ref','deleted','revision','updated_at','paper_version'))+(eid,))
    conn.execute('INSERT INTO paper_followup_event_revisions(event_id,revision,snapshot,created_at) VALUES(?,?,?,?)',
                 (eid,data['revision'],json.dumps(data,ensure_ascii=False),data['updated_at']))
    # Removing a mistaken check/progress reconstructs these dates from retained evidence.
    updated=dict(old)
    if remove and r['kind'] in ('check','progress'):
        field='last_checked_at' if r['kind']=='check' else 'last_progress_at'
        latest=conn.execute('SELECT max(occurred_at) FROM paper_followup_events WHERE paper_id=? AND kind=? AND deleted=0',(pid,r['kind'])).fetchone()[0]
        updated[field]=latest or ''
    persist(conn,pid,updated,old['version']+1,actor,'event.remove' if remove else 'event.edit')
    return data
