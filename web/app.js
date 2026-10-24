'use strict';

const $ = (id) => document.getElementById(id);
const state = { health: null, report: null, planId: null, busy: false, eventSource: null, verifyRunId: null, pollTimer: null };

const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ESC[ch]);
const pct = (value) => (Number(value || 0) * 100).toFixed(1) + '%';

const GRADE_LABEL = { A: 'A 政府/官方', B: 'B 主流媒体', C: 'C 平台/百科', D: 'D 自媒体', E: 'E UGC' };
const TIER_LABEL = { 'A/B': 'A/B 来源', 'B/C': 'B/C 降级', insufficient: '未找到可靠来源' };

document.addEventListener('DOMContentLoaded', init);

async function init() {
  bind();
  try {
    const health = await api('/api/health');
    state.health = health;
    renderHealth(health);
  } catch (error) {
    showError('无法连接本地服务：' + error.message);
  }
}

function bind() {
  document.querySelectorAll('.tab').forEach((tab) => {
    tab.addEventListener('click', () => switchTab(tab.dataset.tab));
  });
  $('planBtn').addEventListener('click', loadPlan);
  $('researchRunBtn').addEventListener('click', runResearch);
  $('researchClearBtn').addEventListener('click', clearResearch);
  $('verifyRunBtn').addEventListener('click', runVerify);
  $('verifyCancelBtn').addEventListener('click', cancelVerify);
  $('verifyClearBtn').addEventListener('click', clearVerify);
  $('reportPrint').addEventListener('click', () => window.print());
  $('researchInput').addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') runResearch();
  });
  $('verifyInput').addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') runVerify();
  });
  $('researchInput').addEventListener('input', () => {
    state.planId = null;
    $('planPanel').hidden = true;
  });
}

function switchTab(name) {
  document.querySelectorAll('.tab').forEach((tab) => {
    const active = tab.dataset.tab === name;
    tab.classList.toggle('active', active);
    tab.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  $('tab-research').hidden = name !== 'research';
  $('tab-verify').hidden = name !== 'verify';
  $('tab-report').hidden = name !== 'report';
  if (name === 'report') renderReport();
}

async function api(url, options) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 120000);
  try {
    const response = await fetch(url, { ...(options || {}), signal: controller.signal });
    const text = await response.text();
    let data = null;
    if (text) {
      try { data = JSON.parse(text); } catch { data = text; }
    }
    if (!response.ok) {
      const detail = data && typeof data === 'object' && data.detail ? data.detail : (data || response.statusText || '请求失败');
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
    return data;
  } finally {
    clearTimeout(timer);
  }
}

function showNotice(message, kind) {
  const notice = $('notice');
  notice.hidden = false;
  notice.className = 'notice ' + (kind || 'ok');
  notice.textContent = String(message);
}

function showError(message) {
  showNotice(message, 'error');
}

function renderHealth(health) {
  const settings = health.settings || {};
  const ready = Boolean(health.search_ready || settings.search_ready);
  const llm = health.llm || {};
  const badge = $('modeBadge');
  badge.className = 'badge ' + (ready ? 'live' : 'warn');
  badge.textContent = ready ? 'LIVE · API' : '未配置检索';
  if (!ready) {
    showNotice('未配置 SEARCH_API_KEY：无法执行真实检索。请配置 .env 后重启服务。', 'warn');
    return;
  }
  const llmText = llm.key_present
    ? (llm.provider || 'provider') + ' / ' + (llm.model || '自动选择')
    : '未配置 LLM（只输出来源分册/规则摘要）';
  const shot = health.screenshots || {};
  const shotText = shot.enabled ? ('截图证据：' + (shot.reason ? shot.reason : '已启用')) : '截图证据：未启用（' + (shot.reason || '未知') + '）';
  showNotice('真实检索已连接：元宝 SearchPro API。LLM：' + llmText + '。' + shotText, 'ok');
}

function setBusy(busy, mode) {
  state.busy = busy;
  ['planBtn', 'researchRunBtn', 'researchClearBtn', 'verifyRunBtn', 'verifyClearBtn'].forEach((id) => {
    const node = $(id);
    if (node) node.disabled = busy;
  });
  $('planBtn').textContent = busy && mode === 'plan' ? '生成中…' : '生成查询计划';
  $('researchRunBtn').textContent = busy && mode === 'research' ? '研究中…' : '开始研究';
  $('verifyRunBtn').textContent = busy && mode === 'verify' ? '查证中…' : '开始查证';
  $('verifyCancelBtn').disabled = !(busy && mode === 'verify');
}

function formPayload(inputId) {
  return { text: $(inputId).value.trim() };
}

function clearResearch() {
  $('researchInput').value = '';
  $('planPanel').hidden = true;
  $('researchPanel').hidden = true;
  state.planId = null;
  $('researchInput').focus();
}

function clearVerify() {
  stopVerify();
  $('verifyInput').value = '';
  $('verifyPanel').hidden = true;
  $('verifyLog').innerHTML = '';
  $('verifyResults').innerHTML = '';
  $('verifyInput').focus();
}

async function loadPlan() {
  const payload = formPayload('researchInput');
  if (!payload.text) { showError('请先输入研究问题。'); return; }
  $('planPanel').hidden = false;
  $('researchPanel').hidden = true;
  $('planState').textContent = '生成中…';
  $('planSub').textContent = payload.text;
  $('planSummary').textContent = '';
  $('planId').textContent = '-';
  $('planQueries').textContent = '正在拆分需求并构造查询…';
  $('planFallbacks').textContent = '';
  setBusy(true, 'plan');
  try {
    const data = await api('/api/plan', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    state.planId = data.plan_id;
    renderPlan(data);
    $('planState').textContent = '已生成';
  } catch (error) {
    $('planState').textContent = '失败';
    $('planQueries').textContent = '';
    showError('查询计划失败：' + error.message);
  } finally {
    setBusy(false);
  }
}

function renderPlan(data) {
  const requirements = data.requirements || [];
  const initial = data.queries || [];
  const fallbacks = data.fallback_queries || [];
  $('planSummary').textContent = (data.method || '规则') + ' · ' + requirements.length + ' 条需求 · ' + initial.length + ' 条初始查询 · ' + fallbacks.length + ' 条候选回退';
  $('planId').textContent = data.plan_id || '-';
  const byId = new Map(requirements.map((item) => [item.requirement_id, item]));
  $('planQueries').innerHTML = queryList(initial, byId);
  $('planFallbacks').innerHTML = queryList(fallbacks, byId);
}

function queryList(items, byId) {
  if (!items.length) return '<p class="muted">暂无</p>';
  return items.map((item) => {
    const requirement = byId.get(item.requirement_id);
    const field = requirement ? requirement.field : '';
    const focus = requirement ? (requirement.focus || '') : '';
    const directed = item.site || item.industry || '无定向';
    return '<div class="query-row"><div class="query-text">' + esc(item.query) + '</div>' +
      '<div class="query-meta">' + esc(field) + ' · ' + esc(item.precision || '') + ' · ' + esc(directed) + ' · ' + esc(item.freshness || '') + (focus ? ' · focus=' + esc(focus) : '') + '</div></div>';
  }).join('');
}

async function runResearch() {
  const payload = formPayload('researchInput');
  if (!payload.text) { showError('请先输入研究问题。'); return; }
  $('researchPanel').hidden = false;
  $('planPanel').hidden = true;
  $('researchState').textContent = '研究中…';
  $('researchSub').textContent = payload.text;
  $('researchAnswer').innerHTML = '<p class="muted">正在执行需求拆分、查询构造、检索、去重、分级和截图；通常需要十几秒。</p>';
  $('researchMetrics').innerHTML = '';
  $('sourceLedger').innerHTML = '';
  $('researchIssues').innerHTML = '';
  state.report = null;
  setBusy(true, 'research');
  try {
    const body = { text: payload.text };
    if (state.planId) body.plan_id = state.planId;
    const data = await api('/api/research', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    state.report = data.report || null;
    if (data.plan_id) state.planId = data.plan_id;
    renderResearch(data);
    $('researchState').textContent = '已完成';
  } catch (error) {
    $('researchState').textContent = '失败';
    $('researchAnswer').innerHTML = '';
    showError('研究失败：' + error.message);
  } finally {
    setBusy(false);
  }
}

function metricCard(label, value) {
  return '<div class="metric"><span>' + esc(label) + '</span><strong>' + esc(value) + '</strong></div>';
}

function renderResearch(data) {
  const metrics = data.metrics || {};
  const answer = data.answer || {};
  const citations = answer.citations || [];
  const valid = new Set(citations.map((item) => Number(item.n)));
  $('researchSub').textContent = (data.domain || '研究问题') + ' · ' + (data.method || 'llm') + ' · ' + (data.question || '');
  $('researchAnswer').innerHTML = answerCard(answer, valid);
  const issues = data.citation_issues || answer.citation_issues || [];
  $('researchIssues').innerHTML = issues.length
    ? '<div class="notice warn">引用校验：' + issues.map((item) => '[' + esc(item.n) + '] ' + esc(item.reason)).join('；') + '</div>'
    : '';
  $('researchMetrics').innerHTML = [
    metricCard('需求覆盖 A/B', (metrics.requirements_with_ab || 0) + '/' + (metrics.requirements || 0)),
    metricCard('A/B 来源占比', pct(metrics.ab_source_rate)),
    metricCard('去重后页数', String(metrics.pages_unique || 0)),
    metricCard('去重条数', String(metrics.duplicates_removed || 0)),
    metricCard('定向查询占比', pct(metrics.directed_query_rate)),
    metricCard('截图', String(metrics.screenshots || 0)),
  ].join('');
  $('sourceLedger').innerHTML = (data.source_ledger || []).map(ledgerCard).join('') || '<p class="muted">没有可展示的来源分册。</p>';
}

function answerCard(answer, valid) {
  const raw = esc(String(answer.text || answer.answer || ''));
  const text = raw.replace(/\n/g, '<br>').replace(/\[(\d+)\]/g, (match, number) => {
    return valid.has(Number(number)) ? '<a class="cite-ref" href="#cite-' + number + '">[' + number + ']</a>' : match;
  });
  const citations = (answer.citations || []).map((citation) => sourceCard(citation, citation.n)).join('');
  const fallback = answer.engine === 'llm' ? '' : '<span class="muted">（规则摘要，未调用大模型）</span>';
  return '<div class="answer-box"><div class="answer-head"><span class="eyebrow">研究综述（非断言判定）</span>' + fallback + '</div>' +
    '<div class="answer-text">' + text + '</div>' +
    (answer.uncertainty ? '<p class="answer-note">' + esc(answer.uncertainty) + '</p>' : '') +
    (citations ? '<details class="citations" open><summary>引用来源（' + answer.citations.length + '）</summary><ul class="sources">' + citations + '</ul></details>' : '') +
    '</div>';
}

function ledgerCard(entry) {
  const sources = (entry.sources || []).map((source) => sourceCard(source, source.n)).join('');
  const tier = TIER_LABEL[entry.tier] || entry.tier || '未知';
  return '<article class="result-card"><div class="result-head"><div><p class="eyebrow">' + esc(entry.field || '') + '</p>' +
    '<h3>' + esc(entry.text || entry.field || '') + '</h3></div><span class="tier">' + esc(tier) + '</span></div>' +
    '<p class="result-summary">去重后 ' + (entry.unique_pages || 0) + ' 页 · ' + (entry.clusters || 0) + ' 个来源簇 · ' +
    'A/B ' + ((entry.grade_counts && (entry.grade_counts.A + entry.grade_counts.B)) || 0) + ' 条</p>' +
    (sources ? '<ul class="sources">' + sources + '</ul>' : '<p class="empty-source">没有找到可用的 A/B 或 C 级来源。</p>') +
    '</article>';
}

function sourceCard(source, number) {
  const id = number ? ' id="cite-' + number + '"' : '';
  const cluster = source.cluster_size > 1 ? ' · ' + source.cluster_size + ' 条同源' : '';
  const screenshot = source.screenshot_url
    ? '<a class="shot-link" href="' + esc(safeUrl(source.screenshot_url)) + '" target="_blank" rel="noopener"><img class="shot" loading="lazy" src="' + esc(safeUrl(source.screenshot_url)) + '" alt="来源截图"></a>'
    : '';
  const passage = source.passage ? '<p class="snippet">' + esc(source.passage.slice(0, 220)) + '</p>' : '';
  return '<li class="source"' + id + '><span class="grade grade-' + esc(source.grade) + '">' + esc(source.grade || '?') + '</span>' +
    '<div class="source-body"><a href="' + esc(safeUrl(source.url)) + '" target="_blank" rel="noopener">' +
    (number ? '[' + number + '] ' : '') + esc(source.title || source.domain) + '</a>' +
    '<p>' + esc(source.domain || '') + (source.date ? ' · ' + esc(source.date) : '') + esc(cluster) + '</p>' +
    passage + screenshot + '</div></li>';
}

async function runVerify() {
  const payload = formPayload('verifyInput');
  if (!payload.text) { showError('请先输入待查证说法。'); return; }
  stopVerify();
  $('verifyPanel').hidden = false;
  $('verifySub').textContent = payload.text;
  $('verifyState').textContent = '查证中…';
  $('verifyLog').innerHTML = '';
  $('verifyResults').innerHTML = '';
  state.report = null;
  setBusy(true, 'verify');
  try {
    const data = await api('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    state.verifyRunId = data.run_id;
    connectEvents(data.run_id);
  } catch (error) {
    $('verifyState').textContent = '失败';
    showError('查证失败：' + error.message);
    setBusy(false);
  }
}

function connectEvents(runId) {
  if (!window.EventSource) {
    startPolling(runId);
    return;
  }
  const source = new EventSource('/api/runs/' + encodeURIComponent(runId) + '/events');
  state.eventSource = source;
  const types = ['run.started', 'split.done', 'query.planned', 'search.result', 'round.judged', 'unit.verdict', 'advisory.ready', 'run.stats', 'run.done', 'error'];
  types.forEach((type) => source.addEventListener(type, (event) => handleEvent(type, event.data)));
  source.onerror = () => {
    stopEvents();
    startPolling(runId);
  };
}

function handleEvent(type, raw) {
  let data = {};
  try { data = JSON.parse(raw || '{}'); } catch { data = {}; }
  if (type === 'split.done') {
    appendLog('拆分出 ' + (data.facts || []).length + ' 条断言');
  } else if (type === 'query.planned') {
    appendLog('查询：' + (data.query || ''));
  } else if (type === 'search.result') {
    appendLog('检索：' + (data.pages || 0) + ' 页' + (data.error ? '，错误：' + data.error : ''));
  } else if (type === 'round.judged') {
    appendLog('第 ' + ((data.round || 0) + 1) + ' 轮：' + (data.verdict || '') + '（' + (data.rule_id || '') + '）');
  } else if (type === 'unit.verdict') {
    renderUnit(data);
  } else if (type === 'advisory.ready') {
    applyAdvisories(data.items || {});
  } else if (type === 'run.stats') {
    appendLog('统计：检索 ' + (data.calls || 0) + ' 次，缓存 ' + (data.cache_hits || 0) + ' 次，簇 ' + (data.clusters || 0) + ' 个');
  } else if (type === 'run.done') {
    state.report = data.report || null;
    $('verifyState').textContent = '已完成';
    appendLog('完成：' + (data.stop_reason || 'completed'));
    stopVerify();
    setBusy(false);
    renderReport();
  } else if (type === 'error') {
    $('verifyState').textContent = '失败';
    showError('查证失败：' + (data.message || '未知错误'));
    stopVerify();
    setBusy(false);
  }
}

function appendLog(text) {
  const item = document.createElement('li');
  item.textContent = String(text);
  $('verifyLog').appendChild(item);
}

function renderUnit(unit) {
  const id = unit.unit_id || ('unit-' + Date.now());
  const layered = unit.layered || {};
  const votes = unit.cluster_votes || {};
  const evidence = (unit.evidence || []).map((item) => {
    const quote = item.quote ? '<blockquote>' + esc(item.quote) + '</blockquote>' : '';
    return '<li class="source"><span class="grade grade-' + esc(item.grade) + '">' + esc(item.grade || '?') + '</span>' +
      '<div class="source-body"><a href="' + esc(safeUrl(item.url)) + '" target="_blank" rel="noopener">' + esc(item.title || item.domain) + '</a>' +
      '<p>' + esc(item.relation || '') + (item.date ? ' · ' + esc(item.date) : '') + '</p>' + quote + '</div></li>';
  }).join('');
  const advisory = unit.advisory ? '<p class="advisory">模型参考意见（非判定）：' + esc(unit.advisory.text || '') + '</p>' : '';
  const card = '<article class="result-card" id="' + esc(id) + '"><div class="result-head"><div><p class="eyebrow">' + esc(unit.assertion && unit.assertion.field || '') + '</p>' +
    '<h3>' + esc(unit.assertion && unit.assertion.text || '') + '</h3></div>' +
    '<span class="tier">' + esc(unit.verdict || '') + ' · ' + esc(unit.rule_id || '') + '</span></div>' +
    '<p class="result-summary">只看 A 级：' + esc(layered.a_level_only || '') + ' · 支持 ' + (votes.support || 0) + ' / 反驳 ' + (votes.refute || 0) +
    ' · 检索 ' + (unit.calls_used || 0) + ' 次' + (votes.note ? ' · ' + esc(votes.note) : '') + '</p>' +
    '<p>' + esc(unit.action || '') + '</p>' + advisory +
    (evidence ? '<ul class="sources">' + evidence + '</ul>' : '<p class="empty-source">没有可用证据。</p>') + '</article>';
  const existing = document.getElementById(id);
  if (existing) existing.outerHTML = card;
  else $('verifyResults').insertAdjacentHTML('beforeend', card);
}

function applyAdvisories(items) {
  Object.keys(items || {}).forEach((unitId) => {
    const card = document.getElementById(unitId);
    if (!card || card.querySelector('.advisory')) return;
    const item = items[unitId] || {};
    card.insertAdjacentHTML('beforeend', '<p class="advisory">模型参考意见（非判定）：' + esc(item.text || '') + '</p>');
  });
}

function stopEvents() {
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }
}

function stopPolling() {
  if (state.pollTimer) {
    clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
}

function stopVerify() {
  stopEvents();
  stopPolling();
}

function startPolling(runId) {
  stopPolling();
  state.pollTimer = setInterval(async () => {
    try {
      const data = await api('/api/runs/' + encodeURIComponent(runId));
      if (data.status === 'done' || data.status === 'error' || data.status === 'cancelled') {
        if (data.report) state.report = data.report;
        $('verifyState').textContent = data.status === 'done' ? '已完成' : data.status;
        stopVerify();
        setBusy(false);
        renderReport();
      }
    } catch (error) {
      stopVerify();
      setBusy(false);
      showError('查证轮询失败：' + error.message);
    }
  }, 1500);
}

async function cancelVerify() {
  if (!state.verifyRunId) return;
  try {
    await api('/api/runs/' + encodeURIComponent(state.verifyRunId) + '/cancel', { method: 'POST' });
    appendLog('已请求取消');
  } catch (error) {
    showError('取消失败：' + error.message);
  }
}

function renderReport() {
  if (!state.report) return;
  $('reportBox').innerHTML = reportCard(state.report);
}

function reportCard(report) {
  if (!report) return '';
  if (report.kind === 'verification') return verificationReport(report);
  return researchReport(report);
}

function researchReport(report) {
  const citations = (report.citations || []).map((citation) => sourceCard(citation, citation.n)).join('');
  const ledger = (report.source_ledger || []).map(ledgerCard).join('');
  const issues = (report.citation_issues || []).length
    ? '<p class="answer-note">引用校验：' + report.citation_issues.map((item) => '[' + esc(item.n) + '] ' + esc(item.reason)).join('；') + '</p>'
    : '';
  return '<div class="answer-box"><div class="answer-head"><span class="eyebrow">研究报告 · 非断言判定</span></div>' +
    '<div class="answer-text">' + esc(String(report.summary || '')).replace(/\n/g, '<br>') + '</div>' +
    (report.uncertainty ? '<p class="answer-note">' + esc(report.uncertainty) + '</p>' : '') + issues +
    (citations ? '<details class="citations" open><summary>引用来源（' + report.citations.length + '）</summary><ul class="sources">' + citations + '</ul></details>' : '') +
    (ledger ? '<h4>来源分册</h4>' + ledger : '') +
    '<p class="answer-note">' + esc(report.disclaimer || '') + '</p></div>';
}

function verificationReport(report) {
  const units = (report.units || []).map((unit) => {
    const evidence = (unit.evidence || []).map((item) => {
      const quote = item.quote ? '<blockquote>' + esc(item.quote) + '</blockquote>' : '';
      return '<li class="source"><span class="grade grade-' + esc(item.grade) + '">' + esc(item.grade || '?') + '</span>' +
        '<div class="source-body"><a href="' + esc(safeUrl(item.url)) + '" target="_blank" rel="noopener">' + esc(item.title || item.domain) + '</a>' +
        '<p>' + esc(item.relation || '') + (item.date ? ' · ' + esc(item.date) : '') + '</p>' + quote + '</div></li>';
    }).join('');
    const advisory = unit.advisory ? '<p class="advisory">模型参考意见（非判定）：' + esc(unit.advisory.text || '') + '</p>' : '';
    return '<article class="result-card"><div class="result-head"><div><h3>' + esc(unit.assertion && unit.assertion.text || '') + '</h3></div>' +
      '<span class="tier">' + esc(unit.verdict || '') + ' · ' + esc(unit.rule_id || '') + '</span></div>' +
      '<p class="result-summary">只看 A 级：' + esc(unit.layered && unit.layered.a_level_only || '') + ' · 支持 ' + (unit.cluster_votes && unit.cluster_votes.support || 0) +
      ' / 反驳 ' + (unit.cluster_votes && unit.cluster_votes.refute || 0) + '</p><p>' + esc(unit.action || '') + '</p>' + advisory +
      (evidence ? '<ul class="sources">' + evidence + '</ul>' : '') + '</article>';
  }).join('');
  return '<div class="answer-box"><div class="answer-head"><span class="eyebrow">断言查证报告</span></div>' +
    '<div class="answer-text">' + esc(report.task && report.task.text || '') + '</div>' + units +
    '<p class="answer-note">' + esc(report.disclaimer || '') + '</p></div>';
}

function safeUrl(value) {
  const raw = String(value || '').trim();
  return /^https?:\/\//i.test(raw) || /^\/api\/evidence\//.test(raw) ? raw : '#';
}
