/* Per-paper follow-up: authenticated session requests, with optimistic conflict checks. */
(function () {
  'use strict';
  const rows = Array.from(document.querySelectorAll('[data-tracking-row]'));
  const query = document.getElementById('tracking-query');
  const focus = document.getElementById('tracking-focus');
  const stage = document.getElementById('tracking-stage');
  function filter() {
    const term = query ? query.value.trim().toLocaleLowerCase() : '';
    const scope = focus ? focus.value : 'all';
    const value = stage ? stage.value : '';
    let count = 0;
    rows.forEach(function (row) {
      const current = row.dataset.stage;
      const matchesScope = scope === 'all' ||
        (scope === 'decision' && row.dataset.decision === '1') ||
        (scope === 'attention' && row.dataset.attention === '1') ||
        (scope === 'waiting' && ['waiting_support', 'awaiting_author', 'awaiting_close'].includes(current)) ||
        (scope === 'action' && ['draft', 'revision_required', 'resubmit_ready'].includes(current)) ||
        (scope === 'paused' && current === 'paused');
      row.hidden = !(matchesScope && (!value || current === value) && (!term || row.textContent.toLocaleLowerCase().includes(term)));
      if (!row.hidden) count += 1;
    });
    const countLabel = document.getElementById('tracking-count');
    if (countLabel) countLabel.textContent = '显示 ' + count + ' / ' + rows.length + ' 篇';
    const empty = document.getElementById('tracking-empty');
    if (empty) empty.hidden = count !== 0;
  }
  if (query) query.addEventListener('input', filter);
  if (stage) stage.addEventListener('change', filter);
  if (focus) {
    const requested = new URLSearchParams(window.location.search).get('focus');
    if (Array.from(focus.options).some(function (option) { return option.value === requested; })) focus.value = requested;
    focus.addEventListener('change', filter);
  }
  filter();

  document.querySelectorAll('[data-followup-toggle]').forEach(function (button) {
    button.addEventListener('click', function () {
      const target = document.getElementById(button.dataset.followupToggle);
      if (target) { target.hidden = !target.hidden; if (!target.hidden) target.scrollIntoView({behavior: 'smooth', block: 'nearest'}); }
    });
  });
  // Dates entered here use the server's configured zone (PAPER_DESK_TZ), independent of the device zone.
  const clockParts = new Intl.DateTimeFormat('sv-SE', {timeZone: document.body.dataset.timezone || undefined, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false}).format(new Date()).replace(' ', 'T');
  document.querySelectorAll('[data-default-now]').forEach(function (input) { if (!input.value) input.value = clockParts; });

  const detail = document.querySelector('[data-paper-code]');
  let editing = false;
  if (detail) {
    const message = detail.querySelector('[data-followup-message]');
    function show(text) { message.textContent = text; message.hidden = false; }
    detail.querySelectorAll('[data-followup-form]').forEach(function (form) {
      form.addEventListener('submit', async function (event) {
        event.preventDefault();
        const data = new FormData(form);
        const type = form.dataset.followupForm;
        let method = 'PATCH';
        let url = '/api/v1/papers/' + encodeURIComponent(detail.dataset.paperCode) + '/followup';
        const body = {expected_version: Number(detail.dataset.version)};
        if (type === 'state') {
          data.forEach(function (value, key) { if (key !== 'decision_required') body[key] = value; });
          body.decision_required = data.has('decision_required');
          body.stale_after_days = Number(data.get('stale_after_days'));
        } else if (type === 'event') {
          method = 'POST'; url += '/events';
          data.forEach(function (value, key) { body[key] = value; });
          body.occurred_at = data.get('occurred_at') + ':00' + (document.body.dataset.tzOffset || '');
          body.idempotency_key = form.dataset.eventKey || (form.dataset.eventKey = typeof window.crypto.randomUUID === 'function' ? window.crypto.randomUUID() : 'ui-' + Date.now() + '-' + Array.from(window.crypto.getRandomValues(new Uint32Array(4))).join('-'));
        } else if (type === 'archive') {
          body.active = false; body.archive_reason = data.get('archive_reason');
        } else if (type === 'restore') { body.active = true; }
        const buttons = Array.from(form.querySelectorAll('button'));
        buttons.forEach(function (button) { button.disabled = true; });
        show('正在保存…');
        try {
          const response = await fetch(url, {method: method, credentials: 'same-origin', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
          let result;
          try { result = await response.json(); } catch (_) { throw new Error('服务返回异常，请稍后重新核查记录。'); }
          if (!response.ok) {
            if (response.status === 409) throw new Error('这篇论文已被其他操作更新。请刷新后核对新记录，再保存，避免覆盖。');
            if (response.status === 401) throw new Error('登录已过期，请重新登录后保存。');
            throw new Error(typeof result.detail === 'string' ? result.detail : '保存失败，请核对填写内容或联系管理员。');
          }
          show('保存成功，正在显示最新记录。');
          window.location.reload();
        } catch (error) {
          show(error.message || '连接失败，本次更新未确认保存。请核查后重试。');
          buttons.forEach(function (button) { button.disabled = false; });
        }
      });
    });
    detail.addEventListener('input', function () { editing = true; });
  }
  const live = document.getElementById('live');
  if (live) {
    let last = null;
    async function pulse() {
      try {
        const response = await fetch('/api/pulse', {cache: 'no-store', credentials: 'same-origin'});
        if (!response.ok) throw new Error('connection');
        const result = await response.json();
        if (!result.v) { live.textContent = '○ 请重新登录'; return; }
        if (last !== null && result.v !== last && !editing) window.location.reload();
        last = result.v; live.textContent = '● 自动刷新中';
      } catch (_) { live.textContent = '○ 连接断开'; }
    }
    pulse(); window.setInterval(pulse, 15000);
  }
})();
