"""Render-only checks: no production database, credentials or account mutations."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from jinja2 import Environment, FileSystemLoader, select_autoescape
import followup

BASE = Path(__file__).resolve().parents[1]

class FollowupUITest(unittest.TestCase):
    def setUp(self):
        self.env = Environment(loader=FileSystemLoader(str(BASE / 'templates')),
                               autoescape=select_autoescape(['html']))
        self.paper = dict(id=10, code='P10', title='Fixture paper', title_cn='示例论文',
                          lead_author='张三', current_journal='Example Journal',
                          paper_id=10, paper_status='投稿中')
        self.state = {**followup.DEFAULTS, **self.paper, 'version': 4,
                      'stage': 'waiting_support', 'waiting_for': '客服',
                      'blocked_reason': '<script>alert(1)</script>',
                      'completion_condition': '原稿可访问并取得正式回执',
                      'last_checked_at': '2026-10-13T09:00:00+08:00',
                      'last_progress_at': '2026-10-12T22:57:00+08:00',
                      'evidence_source': '系统旧快照', 'evidence_at': '2026-10-11T09:00:00+08:00',
                      'days_without_progress': 1, 'days_waiting': 2, 'needs_attention': True}

    def board(self, rows=None, archived=False):
        rows = [self.state] if rows is None else rows
        return self.env.get_template('followups.html').render(
            user={'role':'admin','display_name':'管理员'},site_title='投稿台账',
            request=SimpleNamespace(query_params={}), followups=rows,
            followup_counts={'active':1,'needs_decision':0,'attention':1,'archived':0},
            archived=archived)

    def detail(self, state=None, history=None):
        return self.env.get_template('_followup_detail.html').render(
            paper=self.paper, followup=state or self.state, followup_state_history=history or [],
            followup_events=[{'kind':'incoming','occurred_at':'2026-10-12T22:57:00+08:00',
                              'text':'<img src=x onerror=alert(2)>', 'evidence_ref':'工单 000000-000001'}])

    def test_visible_provenance_and_source_escape(self):
        html = self.board()
        self.assertIn('/paper/10#followup', html)
        self.assertIn('系统旧快照 ·', html)
        self.assertIn('datetime="2026-10-11T09:00:00+08:00"', html)
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', html)
        self.assertIn('已等待 2 天', html)

    def test_detail_keeps_history_and_dates_and_accept_archive(self):
        state = {**self.state, 'stage':'accepted', 'active':False, 'archive_reason':'已录用'}
        html = self.detail(state)
        self.assertIn('已归档 · 历史保留', html)
        self.assertIn('工单 000000-000001', html)
        self.assertNotIn('<img src=x', html)
        self.assertIn('&lt;img src=x', html)
        self.assertNotIn('data-followup-form="restore"', html)
        self.assertNotIn('data-followup-form="archive"', html)

    def test_stage_selector_stays_in_sync_with_backend(self):
        # 只能选流程型阶段；审稿阶段由台账推导，不出现在可写下拉框里
        import re
        html = self.detail()
        select = re.search(r'<select name="stage">(.*?)</select>', html, re.S).group(1)
        self.assertEqual(set(re.findall(r'value="([a-z_]+)"', select)), set(followup.WRITABLE_STAGES))

    def test_zero_reminder_and_version_are_retained(self):
        html = self.detail({**self.state, 'stale_after_days':0})
        self.assertIn('data-version="4"',html)
        self.assertIn('min="0" max="365" value="0"',html)

    def test_empty_and_archived_boards_render(self):
        self.assertIn('暂无活动跟进', self.board([]))
        self.assertIn('暂无归档记录', self.board([], archived=True))

    def test_plan_adjustments_remain_readable_and_escaped(self):
        history=[{'created_at':'2026-10-13T10:00:00+08:00',
                  'snapshot':{**self.state, 'next_action':'<script>wrong()</script>'}}]
        html=self.detail(history=history)
        self.assertIn('计划调整历史（1 次，保留原记录）',html)
        self.assertIn('datetime="2026-10-13T10:00:00+08:00"',html)
        self.assertIn('&lt;script&gt;wrong()&lt;/script&gt;',html)
        self.assertNotIn('<script>wrong()',html)

    def test_target_journal_is_separate_from_submission_history(self):
        state={**self.state,'target_journal':'Example Journal',
               'current_journal':'Example Journal','ledger_journal':'Previous Example Journal'}
        html=self.detail(state)
        self.assertIn('拟投／正在办理的期刊',html)
        self.assertIn('历史投稿轮次的期刊',html)
        self.assertIn('Previous Example Journal',html)

if __name__ == '__main__':
    unittest.main()
