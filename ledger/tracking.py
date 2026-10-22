"""Submission progress and review history; no duplicate paper registry."""
from datetime import date, datetime
import json
import re

STAGES = ['未标注', '编辑处理中', '外审中', '等待决定', '大修', '小修', '返修已提交', '已录用', '被拒', '撤稿']
KINDS = ['progress', 'check', 'review', 'response', 'note']
FILE_KINDS = ['other', 'latex', 'manuscript', 'review', 'response', 'supplement']

def migrate(conn):
    """Additive, idempotent migration; never rewrite existing rows."""
    columns = {
        'papers': {'code': "TEXT NOT NULL DEFAULT ''", 'author_pos': "TEXT NOT NULL DEFAULT ''",
                   'is_corresponding': 'INTEGER NOT NULL DEFAULT 0', 'category': "TEXT NOT NULL DEFAULT 'main'",
                   # 跟进方式（follow_mode.py）与一两句「当前情况」；notes 仍是只追加的历史记录
                   'follow_mode': "TEXT NOT NULL DEFAULT ''", 'current_note': "TEXT NOT NULL DEFAULT ''"},
        'submissions': {'sys_cookie': "TEXT NOT NULL DEFAULT ''", 'credential_extra': "TEXT NOT NULL DEFAULT '{}'",
                        'outcome': "TEXT NOT NULL DEFAULT ''"},
        'files': {'kind': "TEXT NOT NULL DEFAULT 'other'"},
    }
    for table, fields in columns.items():
        known = {r[1] for r in conn.execute(f'PRAGMA table_info({table})')}
        for name, definition in fields.items():
            if name not in known:
                conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
    conn.execute('''CREATE TABLE IF NOT EXISTS paper_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
        submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
        kind TEXT NOT NULL, event_date TEXT NOT NULL, stage TEXT NOT NULL DEFAULT '',
        text TEXT NOT NULL DEFAULT '', reviewer TEXT NOT NULL DEFAULT '',
        round INTEGER NOT NULL DEFAULT 1, due_date TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_events_sub ON paper_events(submission_id,event_date,id)')
    conn.commit()


def valid_date(value, field='date', allow_empty=False):
    from fastapi import HTTPException
    if allow_empty and value == '':
        return value
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise HTTPException(422, f'{field} 必须为 YYYY-MM-DD')
    try:
        d = date.fromisoformat(value)
    except ValueError:
        raise HTTPException(422, f'{field} 不是有效日期')
    return d.isoformat()


def events(conn, pid, sid=None, scrub=lambda x: x):
    sql = 'SELECT e.*,s.seq FROM paper_events e JOIN submissions s ON s.id=e.submission_id WHERE e.paper_id=?'
    args = [pid]
    if sid is not None:
        sql += ' AND e.submission_id=?'; args.append(sid)
    rows = conn.execute(sql+' ORDER BY e.event_date DESC,e.id DESC', args).fetchall()
    return [{**{k:r[k] for k in ['id','submission_id','seq','kind','event_date','stage','round','due_date','created_at','updated_at']},
             'text':scrub(r['text']), 'reviewer':scrub(r['reviewer'])} for r in rows]


def summary(conn, sub, today=None):
    if sub is None:
        return dict(review_stage=None,last_progress_date=None,last_checked_date=None,
                    days_without_progress=None,days_since_last_check=None,revision_due_date=None,
                    revision_days_remaining=None,progress_date_basis=None)
    today = today or date.today()
    rows = conn.execute('SELECT * FROM paper_events WHERE submission_id=? ORDER BY event_date DESC,id DESC', (sub['id'],)).fetchall()
    progress = next((r for r in rows if r['kind'] in ('progress','review','response')), None)
    stage_row = next((r for r in rows if r['stage']), None)
    check = next((r for r in rows if r['kind']=='check'), None)
    due_row = next((r for r in rows if r['kind'] in ('progress','review','response') and (r['stage'] or r['due_date'])), None)
    due = due_row['due_date'] if due_row and due_row['stage'] not in ('返修已提交','已录用','被拒','撤稿') else ''
    if sub['status'] in ('已录用','被拒','撤稿'):due=''
    start = progress['event_date'] if progress else sub['submit_date']
    def days(v):
        try:return (today-date.fromisoformat(v)).days
        except (ValueError,TypeError):return None
    return dict(review_stage=sub['status'] if sub['status'] in ('已录用','被拒','撤稿') else (stage_row['stage'] if stage_row else '未标注'),
                last_progress_date=progress['event_date'] if progress else None,
                last_checked_date=check['event_date'] if check else None,
                days_without_progress=days(start),days_since_last_check=days(check['event_date']) if check else None,
                revision_due_date=due or None, revision_days_remaining=-days(due) if due else None,
                progress_date_basis='event' if progress else ('submit_date' if days(start) is not None else None))


def validate_event(b):
    from fastapi import HTTPException
    allowed = {'kind','event_date','stage','text','reviewer','round','due_date'}
    if set(b)-allowed:raise HTTPException(422, '未知事件字段')
    if b.get('kind') not in KINDS:raise HTTPException(422, f'kind 必须为 {KINDS}')
    valid_date(b.get('event_date'), 'event_date')
    if b['event_date'] > date.today().isoformat():raise HTTPException(422, '进展日期不能在未来；截止日期可在未来')
    if b.get('stage','') and b['stage'] not in STAGES:raise HTTPException(422, f'stage 必须为 {STAGES}')
    if b['kind'] in ('check','note') and (b.get('stage') or b.get('due_date')):
        raise HTTPException(422, 'check/note 不改变期刊进展和返修截止日期')
    valid_date(b.get('due_date',''), 'due_date', allow_empty=True)
    if type(b.get('round',1)) is not int or b.get('round',1)<1:raise HTTPException(422, 'round 必须为正整数')
    for k in ('text','reviewer'):
        if not isinstance(b.get(k,''),str):raise HTTPException(422, f'{k} 必须为字符串')
    if len(b.get('text',''))>500000:raise HTTPException(413,'事件正文超过 500000 字符')
    return b


def record_status_change(conn, pid, sid, previous, status):
    """Keep explicit outcome edits visible in the same progress timeline."""
    if previous == status:
        return
    stage = status if status in ('已录用','被拒','撤稿') else '未标注'
    ts=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn.execute('''INSERT INTO paper_events(paper_id,submission_id,kind,event_date,stage,text,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?)''',
                 (pid,sid,'progress',date.today().isoformat(),stage,'总体状态更新为 '+status,ts,ts))
