'use strict';

const state = {
  health: null,
  fixtures: [],
  runId: null,
  source: null,
  seen: new Set(),
  events: [],
  units: [],
  profile: null,
  stats: null,
  budget: null,
  dropped: [],
  task: null,
  searchOff: false,
  finished: false,
  activeFixture: null,
  queryRows: new Map(),
  claimTexts: {},
  traceClaimId: null,
  baseNoticeHtml: '',
  baseNoticeKind: '',
};

const VERDICT = {
  established: { label: '成立', cls: 'ok', card: 'v-established' },
  refuted: { label: '不成立', cls: 'bad', card: 'v-refuted' },
  conflict: { label: '冲突', cls: 'warn', card: 'v-conflict' },
  suspect: { label: '存疑', cls: 'violet', card: 'v-suspect' },
  insufficient: { label: '证据不足', cls: 'gray', card: 'v-insufficient' },
};

const FAILURE = {
  not_exists: '未找到支持该说法的可靠来源',
  not_indexed: '该信息可能未被公开索引',
  query_mismatch: '检索结果与断言的相关性不足',
  search_disabled: '搜索已关闭',
};

const GRADE_ORDER = { A: 0, B: 1, C: 2, D: 3, E: 4 };
const STOP = {
  completed: '完成',
  no_falsifiable_claim: '无可验证断言',
  search_off: '搜索已关闭',
  wall_time: '墙钟超限',
  run_budget: '全局预算',
  assertion_budget: '单断言预算',
  daily_budget: '日额度',
  auth: '鉴权失败',
  config: '配置缺失',
  cache: '缓存未命中',
  cancelled: '已取消',
  enough_evidence: '证据足够',
  no_progress: '无进展',
  continue: '继续',
};

const STRENGTH = {
  'full-ish': '摘要较全',
  snippet: '摘要',
  title: '仅标题',
};

const $ = (id) => document.getElementById(id);
const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ESC[ch]);
const fmt = (value) => new Intl.NumberFormat('zh-CN').format(Number(value || 0));

document.addEventListener('DOMContentLoaded', init);

async function init() {
  bind();
  try {
    const [health, fixtures] = await Promise.all([
      fetchJSON('/api/health'),
      fetchJSON('/api/fixtures'),
    ]);
    state.health = health;
    state.fixtures = fixtures || [];
    renderHealth(health);
    renderExamples(state.fixtures);
    if (new URLSearchParams(location.search).get('fixture')) {
      const fixtureId = new URLSearchParams(location.search).get('fixture');
      const fixture = state.fixtures.find((item) => item.fixture_id === fixtureId);
      if (fixture) {
        fillFixture(fixture);
        startRun(fixture.fixture_id);
      }
    }
  } catch (error) {
    showError(`无法连接本地服务：${error.message}`);
  }
}

function bind() {
  $('runBtn').addEventListener('click', () => startRun(state.activeFixture));
  $('clearBtn').addEventListener('click', () => {
    $('textInput').value = '';
    $('subjectInput').value = '';
    $('cityInput').value = '西安';
    state.activeFixture = null;
    document.querySelectorAll('.example').forEach((button) => button.classList.remove('active'));
    $('textInput').focus();
  });
  $('printBtn').addEventListener('click', () => window.print());
  $('printBtn2').addEventListener('click', () => window.print());
  $('searchOff').addEventListener('change', () => {
    $('composerHint').textContent = $('searchOff').checked
      ? '演示模式：下一次运行不调用搜索，所有断言将显示「无法判读」。'
      : '示例使用本地数据；配置 Key 后会真实调用元宝搜索。';
  });
  document.querySelectorAll('.example').forEach((button) => {
    button.addEventListener('click', () => {
      const fixture = state.fixtures.find((item) => item.fixture_id === button.dataset.fixture);
      if (fixture) {
        fillFixture(fixture);
        startRun(fixture.fixture_id);
      }
    });
  });
}

async function fetchJSON(url, options) {
  const response = await fetch(url, options);
  const text = await response.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!response.ok) {
    const detail = data && typeof data === 'object' && data.detail ? data.detail : (data || response.statusText || '请求失败');
    throw new Error(String(detail));
  }
  return data;
}

function renderHealth(health) {
  const settings = health.settings || {};
  const demo = Boolean(settings.demo_mode) || settings.search_provider === 'fake';
  const badge = $('modeBadge');
  badge.className = `badge ${demo ? 'demo' : 'live'}`;
  badge.textContent = demo ? 'DEMO · 本地示例' : `LIVE · ${(settings.search_provider || 'API').toUpperCase()}`;

  const bits = [];
  if (demo) {
    bits.push('DEMO：当前使用本地示例数据，不是真实查询。配置 <code>SEARCH_API_KEY</code> 后重启即可切换真实元宝搜索。');
  } else {
    bits.push(`LIVE：元宝搜索 ${String(settings.search_provider || 'api').toUpperCase()} 通道已配置；缓存命中会单独标注。`);
  }
  if (health.llm) {
    if (!health.llm.key_present) {
      bits.push('LLM 未配置：断言抽取与证据匹配使用启发式规则。');
    } else {
      bits.push(`LLM：${esc(health.llm.provider || 'provider')} / ${esc(health.llm.model || '自动选择')}（第三方供应商）`);
    }
  }
  state.baseNoticeHtml = bits.join(' ');
  state.baseNoticeKind = demo ? '' : 'live';
  showBaseNotice();

  if (demo) {
    $('composerHint').textContent = '当前是 DEMO：示例数据不会消耗额度，也不是真实检索。';
  } else {
    $('composerHint').textContent = '真实检索模式：每次运行都会计入额度，缓存命中会标注。';
  }
  renderBudget();
}

function showBaseNotice() {
  const notice = $('notice');
  if (!state.baseNoticeHtml) {
    notice.hidden = true;
    return;
  }
  notice.hidden = false;
  notice.className = `notice ${state.baseNoticeKind}`;
  notice.innerHTML = state.baseNoticeHtml;
}

function showError(message) {
  const notice = $('notice');
  notice.hidden = false;
  notice.className = 'notice error';
  notice.textContent = String(message);
}

function renderExamples(fixtures) {
  const labels = {
    case_established: '成立',
    case_conflict: '冲突',
    case_insufficient: '证据不足',
  };
  document.querySelectorAll('.example').forEach((button) => {
    const fixture = fixtures.find((item) => item.fixture_id === button.dataset.fixture);
    if (!fixture) {
      button.hidden = true;
      return;
    }
    button.innerHTML = `<strong>${esc(labels[fixture.fixture_id] || fixture.title || '示例')}</strong><span>${esc(fixture.title || '')}</span>`;
  });
}

function fillFixture(fixture) {
  $('textInput').value = fixture.text || '';
  $('subjectInput').value = fixture.subject || '';
  $('cityInput').value = fixture.city || '西安';
  state.activeFixture = fixture.fixture_id;
  document.querySelectorAll('.example').forEach((button) => {
    button.classList.toggle('active', button.dataset.fixture === fixture.fixture_id);
  });
}

async function startRun(fixtureId = null) {
  const text = $('textInput').value.trim();
  if (!text) {
    showError('请先输入一条说法，或点击右侧的示例。');
    return;
  }
  if (state.source) {
    state.source.close();
    state.source = null;
  }
  resetRunUI();
  $('runPanel').hidden = false;
  $('runTitle').textContent = '正在查证…';
  $('runSub').textContent = text.length > 90 ? `${text.slice(0, 90)}…` : text;
  setLive('连接中');
  $('runBtn').disabled = true;
  $('runBtn').textContent = '查证中…';
  showBaseNotice();

  const payload = {
    text,
    subject: $('subjectInput').value.trim() || null,
    city: $('cityInput').value.trim() || null,
    mode: 'verify_claim',
    search_off: $('searchOff').checked,
    fixture_id: fixtureId || null,
  };
  try {
    const result = await fetchJSON('/api/runs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    state.runId = result.run_id;
    openStream(result.run_id);
  } catch (error) {
    $('runBtn').disabled = false;
    $('runBtn').textContent = '开始查证';
    setLive('失败', true);
    showError(`启动失败：${error.message}`);
  }
}

function resetRunUI() {
  state.seen = new Set();
  state.events = [];
  state.units = [];
  state.profile = null;
  state.stats = null;
  state.budget = null;
  state.dropped = [];
  state.task = null;
  state.searchOff = false;
  state.finished = false;
  state.queryRows = new Map();
  state.claimTexts = {};
  state.traceClaimId = null;
  $('timeline').innerHTML = '';
  $('trace').innerHTML = '';
  $('results').innerHTML = '';
  $('kpi').innerHTML = '<span class="kpi-chip">准备中</span>';
  $('profile').textContent = '';
  $('profile').hidden = true;
  $('budget').textContent = '';
  $('reportActions').hidden = true;
  $('mdLink').href = '#';
  setLive('连接中');
}

function openStream(runId) {
  const source = new EventSource(`/api/runs/${encodeURIComponent(runId)}/events`);
  state.source = source;
  const types = [
    'run.started', 'split.done', 'claim.started', 'round.started',
    'query.planned', 'search.started', 'search.result', 'round.judged',
    'unit.verdict', 'run.stats', 'run.done', 'run.cancelling', 'error',
  ];
  types.forEach((type) => source.addEventListener(type, (event) => handleEvent(type, event)));
  source.addEventListener('open', () => {
    if (!state.finished) setLive('已连接');
  });
  source.addEventListener('error', (event) => {
    if (event && event.data) {
      handleEvent('error', event);
      return;
    }
    if (!state.finished) setLive('连接中断，重连中…', true);
  });
}

function handleEvent(type, event) {
  if (!event || !event.data) return;
  let data;
  try {
    data = JSON.parse(event.data);
  } catch {
    return;
  }
  const eventType = data.type || type;
  if (data.seq !== undefined && data.seq !== null) {
    const seq = Number(data.seq);
    if (state.seen.has(seq)) return;
    state.seen.add(seq);
  }
  state.events.push({ ...data, type: eventType });
  switch (eventType) {
    case 'run.started':
      onStarted(data);
      break;
    case 'split.done':
      onSplit(data);
      break;
    case 'claim.started':
      appendTimeline(`开始核验：${esc(data.text || '')}`);
      break;
    case 'round.started':
      appendTimeline(`第 ${Number(data.round) + 1} 轮 · ${esc(data.intent || data.round_type || '')}`);
      addRoundTrace(data);
      break;
    case 'query.planned':
      addQueryRow(data);
      appendTimeline(`正在搜：<em>${esc(data.query || '')}</em>`);
      break;
    case 'search.result':
      updateQueryRow(data);
      appendTimeline(
        `${esc(data.query || '')} → ${fmt(data.pages)} 条${data.cache_hit ? '（缓存）' : ''}${data.error ? ` · ${esc(data.error)}` : ''}`,
        data.error ? 'error' : '',
      );
      break;
    case 'round.judged':
      appendTimeline(
        `第 ${Number(data.round) + 1} 轮判定：<strong>${esc(verdictLabel(data.verdict))}</strong> · ${esc(data.rule_id || '')} · 新簇 ${fmt(data.new_clusters)} · 新证据 ${fmt(data.new_ab)}`,
      );
      break;
    case 'unit.verdict':
      onUnit(data);
      break;
    case 'run.stats':
      onStats(data);
      break;
    case 'run.done':
      onDone(data);
      break;
    case 'run.cancelling':
      setLive('取消中…', true);
      appendTimeline('收到取消请求，正在收尾。');
      break;
    case 'error':
      onError(data);
      break;
    default:
      break;
  }
}

function onStarted(data) {
  state.task = data;
  state.searchOff = Boolean(data.search_off);
  const title = data.subject || (data.text ? data.text.slice(0, 28) : '查证任务');
  $('runTitle').textContent = title;
  $('runSub').textContent = data.text || '';
  appendTimeline(
    `任务开始 · ${data.demo ? 'DEMO 数据' : 'LIVE 检索'} · ${data.search_off ? '搜索已关闭' : '搜索开启'}`,
  );
}

function onSplit(data) {
  state.profile = data.profile || null;
  state.dropped = data.dropped || [];
  (data.facts || []).forEach((fact) => {
    if (fact.claim_id) state.claimTexts[fact.claim_id] = fact.text || fact.claim_id;
  });
  renderProfile(state.profile);
  const facts = data.facts || [];
  const emotions = data.emotions || [];
  appendTimeline(`拆出 ${fmt(facts.length)} 条可验证断言 · ${fmt(emotions.length)} 条情绪/关切`);
  facts.forEach((fact) => {
    appendTimeline(`· ${esc(fact.text)} <em>(${esc(fact.field)})</em>`);
  });
  if (data.dropped && data.dropped.length) {
    appendTimeline(`已跳过 ${fmt(data.dropped.length)} 个主观/不可验证表述（保留在报告中）`);
  }
}

function onUnit(unit) {
  state.units.push(unit);
  renderUnit(unit);
  appendTimeline(
    `结论：<strong>${esc(verdictLabel(unit.verdict))}</strong> · ${esc(unit.rule_id || '')} · ${esc(unit.assertion ? unit.assertion.text : '')}`,
    unit.verdict === 'refuted' ? 'error' : '',
  );
}

function onStats(data) {
  state.stats = data;
  state.budget = data.budget || state.budget;
  renderKpi(data);
  renderBudget();
}

function onDone(data) {
  state.finished = true;
  if (state.source) {
    state.source.close();
    state.source = null;
  }
  $('runBtn').disabled = false;
  $('runBtn').textContent = '开始查证';
  setLive('完成');
  const report = data.report;
  if (report) {
    state.profile = report.profile || state.profile;
    state.stats = report.stats || state.stats;
    state.units = report.units || state.units;
    renderProfile(state.profile);
    renderKpi(state.stats);
    renderBudget();
    renderAllUnits(state.units);
    if (report.rounds) renderTraceFromReport(report.rounds);
    const counts = {};
    state.units.forEach((unit) => { counts[unit.verdict] = (counts[unit.verdict] || 0) + 1; });
    const summary = Object.entries(counts).map(([key, value]) => `${verdictLabel(key)} ${value}`).join(' · ');
    $('runTitle').textContent = `${report.task && report.task.subject ? report.task.subject : '鉴定结果'} · ${summary}`;
    $('runSub').textContent = report.task && report.task.text ? report.task.text : '';
  }
  if (state.searchOff) {
    const banner = document.createElement('div');
    banner.className = 'notice error';
    banner.style.margin = '0';
    banner.textContent = '搜索已关闭：本次只拆解断言，没有判读任何结论。重新打开搜索后再跑一次。';
    $('results').prepend(banner);
  }
  $('reportActions').hidden = false;
  $('mdLink').href = `/api/report/${encodeURIComponent(state.runId)}?format=md`;
  appendTimeline('完成。');
}

function onError(data) {
  state.finished = true;
  if (state.source) {
    state.source.close();
    state.source = null;
  }
  $('runBtn').disabled = false;
  $('runBtn').textContent = '开始查证';
  setLive('失败', true);
  const message = data.message || '运行失败';
  showError(message);
  appendTimeline(`错误：${esc(message)}`, 'error');
}

function renderProfile(profile) {
  const box = $('profile');
  if (!profile) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  const concerns = (profile.concerns || []).join('、') || '无';
  box.innerHTML = `这条说法：<strong>事实 ${fmt(profile.facts)}</strong> · <strong>情绪 ${fmt(profile.emotions)}</strong> · 落「${esc(profile.quadrant || '')}」档 · 关切：${esc(concerns)}`;
}

function renderKpi(stats) {
  if (!stats) {
    $('kpi').innerHTML = '<span class="kpi-chip">准备中</span>';
    return;
  }
  const calls = Number(stats.calls || 0);
  const hits = Number(stats.cache_hits || 0);
  const chips = [
    ['检索', calls + hits],
    ['API', calls],
    ['缓存', hits],
    ['命中', stats.results],
    ['合并簇', stats.clusters],
    ['A 级', stats.a_level],
    ['B 级', stats.b_level],
    ['用时', stats.duration_ms ? `${(stats.duration_ms / 1000).toFixed(1)}s` : '—'],
    ['停止', stopLabel(stats.stop_reason)],
  ];
  $('kpi').innerHTML = chips
    .map(([label, value]) => `<span class="kpi-chip">${esc(label)} <strong>${esc(value)}</strong></span>`)
    .join('');
}

function renderBudget() {
  const settings = (state.health && state.health.settings) || {};
  const budgets = settings.budgets || {};
  const demo = Boolean(settings.demo_mode) || settings.search_provider === 'fake';
  const budget = state.budget || {};
  const calls = budget.calls !== undefined ? budget.calls : (state.stats ? state.stats.calls : 0);
  const hits = budget.cache_hits !== undefined ? budget.cache_hits : (state.stats ? state.stats.cache_hits : 0);
  const day = budget.daily_calls !== undefined ? budget.daily_calls : '—';
  const maxRun = budget.max_per_run || budgets.per_run || 28;
  const maxDay = budget.max_per_day || budgets.per_day || 400;
  const wall = budget.wall_seconds || budgets.wall_seconds || 90;
  $('budget').innerHTML = `${demo ? 'DEMO 本地数据，不消耗额度<br>' : ''}检索调用 ${esc(calls)} / ${esc(maxRun)} · 缓存 ${esc(hits)}<br>今日 ${esc(day)} / ${esc(maxDay)} · 墙钟 ${esc(wall)}s`;
}

function renderUnit(unit) {
  const verdict = VERDICT[unit.verdict] || VERDICT.insufficient;
  const box = document.createElement('section');
  box.className = `unit ${verdict.card}`;
  const assertion = unit.assertion || {};
  const layered = unit.layered || {};
  const votes = unit.cluster_votes || {};
  const meta = `
    <span class="verdict-pill ${verdict.cls}">${esc(verdict.label)}</span>
    <span class="rule-pill">${esc(unit.rule_id || 'R5')}</span>
    <span class="layered-pill">只看 A 级：${esc(verdictLabel(layered.a_level_only))}</span>
    ${Number(unit.queries_used || 0) ? `<span class="rule-pill">${fmt(unit.queries_used)} 次查询</span>` : ''}
    ${Number(unit.calls_used || 0) ? `<span class="rule-pill">API ${fmt(unit.calls_used)}</span>` : ''}
  `;
  const head = `
    <div class="unit-head">
      <div>
        <h3 class="unit-title">${esc(assertion.text || '该说法')}</h3>
        <div class="unit-meta">${meta}</div>
      </div>
    </div>
  `;

  let body = '';
  const evidence = Array.isArray(unit.evidence) ? unit.evidence : [];
  const relevant = evidence.filter((item) => item.relation === 'support' || item.relation === 'refute');
  if (unit.verdict === 'conflict') {
    body = conflictView(relevant, unit);
  } else if (relevant.length) {
    body = `<div class="evidence-list">${sortEvidence(relevant).map(sourceCard).join('')}</div>`;
    if (votes.note) body += `<p class="conflict-note">${esc(votes.note)}</p>`;
  } else {
    body = insufficientView(unit);
  }

  const action = unit.action ? `<div class="action-line">${esc(unit.action)}</div>` : '';
  box.innerHTML = `${head}${body}${action}`;
  $('results').appendChild(box);
}

function conflictView(evidence, unit) {
  const support = sortEvidence(evidence.filter((item) => item.relation === 'support'));
  const refute = sortEvidence(evidence.filter((item) => item.relation === 'refute'));
  const supportClusters = new Set(support.map((item) => item.cluster_id || item.evidence_id)).size;
  const refuteClusters = new Set(refute.map((item) => item.cluster_id || item.evidence_id)).size;
  const layered = unit.layered || {};
  const votes = unit.cluster_votes || {};
  const note = [];
  if (votes.note) note.push(votes.note);
  note.push(`全部证据：${verdictLabel(layered.all_evidence)}；只看 A 级：${verdictLabel(layered.a_level_only)}`);
  const column = (items, title, cls, count) => `
    <div class="conflict-col">
      <div class="conflict-head ${cls}"><span>${title}</span><span>${fmt(count)} 簇</span></div>
      ${items.length ? items.map(sourceCard).join('') : '<p class="tiny">无</p>'}
    </div>
  `;
  return `
    <div class="conflict-grid">
      ${column(support, '支持侧', 'support', supportClusters)}
      ${column(refute, '反驳侧', 'refute', refuteClusters)}
    </div>
    <p class="conflict-note">${note.map(esc).join(' · ')}</p>
  `;
}

function insufficientView(unit) {
  const failure = FAILURE[unit.failure_type] || '未找到足以判定的来源';
  const attempts = queryAttempts(unit);
  const list = attempts.length
    ? `<ul class="attempts">${attempts.slice(0, 6).map((query) => `<li>${esc(query)}</li>`).join('')}</ul>`
    : '';
  return `
    <div class="insufficient-box">
      <strong>${esc(failure)}</strong>
      ${list ? `<p class="tiny" style="margin:10px 0 0">已尝试的检索路径：</p>${list}` : ''}
    </div>
  `;
}

function queryAttempts(unit) {
  const claimId = unit.claim_id;
  const queries = [];
  state.events.forEach((event) => {
    if (event.type !== 'query.planned') return;
    if (claimId && event.claim_id !== claimId) return;
    if (event.query && !queries.includes(event.query)) queries.push(event.query);
  });
  return queries;
}

function sourceCard(item) {
  const relation = item.relation === 'support' ? '支持' : item.relation === 'refute' ? '反驳' : '无关';
  const relationCls = item.relation === 'support' ? 'relation-support' : item.relation === 'refute' ? 'relation-refute' : '';
  const url = safeUrl(item.url);
  const quote = item.quote || item.passage || item.content || '（摘要为空）';
  const cluster = Number(item.cluster_size || 1) > 1
    ? `<span class="cluster-note">同源 ${fmt(item.cluster_size)} 条 · 计 1 票</span>`
    : '';
  const older = item.older ? '<span>较早</span>' : '';
  const strength = item.strength ? `<span>${esc(STRENGTH[item.strength] || item.strength)}</span>` : '';
  const observed = item.observed_value ? `<span>值 ${esc(fmtValue(item.observed_value))}</span>` : '';
  return `
    <div class="source">
      <div class="source-top">
        <span class="grade-badge grade-${esc(item.grade || 'D')}">${esc(item.grade || 'D')} 级</span>
        <span class="source-meta">${esc(item.site || item.domain || '来源')} · ${esc(item.date || '日期未知')}</span>
        <span class="source-meta ${relationCls}">${relation}</span>
      </div>
      <div class="source-title"><a href="${esc(url)}" target="_blank" rel="noopener">${esc(truncate(item.title || item.url || '未命名来源', 90))}</a></div>
      <blockquote class="source-quote">${esc(truncate(quote, 220))}</blockquote>
      <div class="source-foot">
        ${cluster}${older}${strength}${observed}
        <span>${esc(item.verifiable || '')}</span>
        <a href="${esc(url)}" target="_blank" rel="noopener">打开来源 ↗</a>
      </div>
    </div>
  `;
}

function renderAllUnits(units) {
  $('results').innerHTML = '';
  if (!units || !units.length) {
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.textContent = '没有可被外部事实判定的断言。主观评价被保留为关切项，不参与真伪判定。';
    $('results').appendChild(empty);
    return;
  }
  units.forEach(renderUnit);
}

function renderTraceFromReport(rounds) {
  const trace = $('trace');
  trace.innerHTML = '';
  if (!rounds || !rounds.length) {
    trace.innerHTML = '<p class="tiny">没有检索轮次。</p>';
    return;
  }
  state.units.forEach((unit) => {
    if (unit.claim_id && unit.assertion) state.claimTexts[unit.claim_id] = unit.assertion.text || unit.claim_id;
  });
  let currentClaim = null;
  rounds.forEach((round) => {
    if (round.assertion_id !== currentClaim) {
      currentClaim = round.assertion_id;
      const claimHead = document.createElement('div');
      claimHead.className = 'trace-claim';
      claimHead.textContent = `断言：${state.claimTexts[round.assertion_id] || round.assertion_id}`;
      trace.appendChild(claimHead);
    }
    const head = document.createElement('div');
    head.className = 'trace-round';
    head.textContent = round.intent || round.type || '检索';
    trace.appendChild(head);
    (round.queries || []).forEach((query) => {
      const row = document.createElement('div');
      row.className = 'trace-row';
      row.innerHTML = `
        <div class="trace-q">${esc(query.query || '')}</div>
        <div class="trace-meta">${query.error ? esc(query.error) : `${fmt(query.results)} 条 · ${query.cache_hit ? '缓存' : '实时'} · ${esc(query.status || '')}`}</div>
      `;
      trace.appendChild(row);
    });
    const tail = document.createElement('div');
    tail.className = 'trace-meta';
    tail.textContent = `新簇 ${round.new_clusters || 0} · 新证据 ${round.new_ab || 0} · ${stopLabel(round.stop_reason)}`;
    trace.appendChild(tail);
  });
}

function addRoundTrace(data) {
  const trace = $('trace');
  if (data.claim_id && data.claim_id !== state.traceClaimId) {
    state.traceClaimId = data.claim_id;
    const claimHead = document.createElement('div');
    claimHead.className = 'trace-claim';
    claimHead.textContent = `断言：${state.claimTexts[data.claim_id] || data.claim_id}`;
    trace.appendChild(claimHead);
  }
  const head = document.createElement('div');
  head.className = 'trace-round';
  head.textContent = data.intent || data.round_type || '检索';
  trace.appendChild(head);
}

function addQueryRow(data) {
  const trace = $('trace');
  const row = document.createElement('div');
  row.className = 'trace-row';
  row.dataset.queryId = data.query_id || '';
  row.innerHTML = `
    <div class="trace-q">${esc(data.query || '')}</div>
    <div class="trace-meta"><span class="spin"></span> 检索中 · ${esc(paramsLabel(data.params || {}))}</div>
  `;
  trace.appendChild(row);
  state.queryRows.set(data.query_id || data.query, row);
}

function updateQueryRow(data) {
  let row = state.queryRows.get(data.query_id);
  if (!row) {
    row = Array.from(document.querySelectorAll('.trace-row')).find((item) => item.textContent.includes(data.query || '__none__'));
  }
  if (!row) {
    addQueryRow({ query_id: data.query_id || data.query, query: data.query, params: {} });
    row = state.queryRows.get(data.query_id) || state.queryRows.get(data.query);
  }
  if (!row) return;
  row.innerHTML = `
    <div class="trace-q">${esc(data.query || '')}</div>
    <div class="trace-meta ${data.error ? 'error' : ''}">${data.error ? esc(data.error) : `${fmt(data.pages)} 条 · ${data.cache_hit ? '缓存' : '实时'} · ${Math.round(Number(data.latency_ms || 0))}ms`}</div>
  `;
}

function appendTimeline(html, kind = '') {
  const box = $('timeline');
  const item = document.createElement('div');
  item.className = 'timeline-item';
  const time = document.createElement('div');
  time.className = 'timeline-time';
  time.textContent = new Date().toLocaleTimeString('zh-CN', { hour12: false });
  const body = document.createElement('div');
  body.className = `timeline-text${kind === 'error' ? ' error' : ''}`;
  body.innerHTML = html;
  item.append(time, body);
  box.appendChild(item);
  box.scrollTop = box.scrollHeight;
}

function setLive(text, bad = false) {
  const node = $('liveState');
  node.textContent = text;
  node.style.color = bad ? 'var(--red)' : '';
}

function verdictLabel(value) {
  return (VERDICT[value] && VERDICT[value].label) || (value ? String(value) : '—');
}

function stopLabel(value) {
  return STOP[value] || (value ? String(value) : '—');
}

function paramsLabel(params) {
  const parts = [];
  if (params.mode !== undefined) parts.push(`Mode ${params.mode}`);
  if (params.site) parts.push(`Site ${params.site}`);
  if (params.industry) parts.push(`Industry ${params.industry}`);
  if (params.freshness) parts.push(`Freshness ${params.freshness}`);
  return parts.join(' · ') || '默认参数';
}

function sortEvidence(items) {
  return [...items].sort((a, b) => {
    const grade = (GRADE_ORDER[a.grade] ?? 9) - (GRADE_ORDER[b.grade] ?? 9);
    if (grade !== 0) return grade;
    return String(b.date || '').localeCompare(String(a.date || ''));
  });
}

function safeUrl(value) {
  try {
    const url = new URL(String(value || ''));
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : '#';
  } catch {
    return '#';
  }
}

function truncate(value, max) {
  const text = String(value || '');
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

function fmtValue(value) {
  const text = String(value ?? '');
  const number = Number(text);
  if (Number.isFinite(number) && text.trim() !== '' && (text.includes('.') || text === String(number))) {
    return Number.isInteger(number) ? String(number) : text;
  }
  return text;
}
