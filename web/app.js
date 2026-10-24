'use strict';

const $ = (id) => document.getElementById(id);
const state = { health: null, busy: false, report: null };

const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ESC[ch]);
const pct = (value) => `${(Number(value || 0) * 100).toFixed(1)}%`;

const TIER = {
  'A/B': { label: 'A/B 可靠来源', cls: 'tier-ab' },
  'B/C': { label: 'B/C 降级来源', cls: 'tier-bc' },
  insufficient: { label: '未找到可靠来源', cls: 'tier-insufficient' },
};

document.addEventListener('DOMContentLoaded', init);

async function init() {
  bind();
  try {
    const health = await fetchJSON('/api/health');
    state.health = health;
    renderHealth(health);
  } catch (error) {
    showError(`无法连接本地服务：${error.message}`);
  }
}
function bind() {
  $('runBtn').addEventListener('click', runResearch);
  $('planBtn').addEventListener('click', loadPlan);
  $('clearBtn').addEventListener('click', clearForm);
  $('reportPrint').addEventListener('click', () => window.print());
  $('textInput').addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') runResearch();
  });
  document.querySelectorAll('.tab').forEach((tab) => {
    tab.addEventListener('click', () => switchTab(tab.dataset.tab));
  });
}

function switchTab(name) {
  document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t.dataset.tab === name));
  $('tab-research').hidden = name !== 'research';
  $('tab-report').hidden = name !== 'report';
  if (name === 'report' && state.report) {
    $('reportBox').innerHTML = reportCard(state.report);
  }
}

async function fetchJSON(url, options) {
  const response = await fetch(url, options);
  const text = await response.text();
  let data = null;
  if (text) {
    try { data = JSON.parse(text); } catch { data = text; }
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
  badge.textContent = demo ? 'DEMO' : 'LIVE · API';
  const notice = $('notice');
  if (demo) {
    notice.hidden = false;
    notice.className = 'notice warn';
    notice.innerHTML = '当前是 DEMO：本地示例数据，不是真实检索。配置 <code>SEARCH_API_KEY</code> 后重启服务。';
    return;
  }
  notice.hidden = false;
  notice.className = 'notice ok';
  const llm = health.llm && health.llm.key_present
    ? `${esc(health.llm.provider || 'provider')} / ${esc(health.llm.model || '自动选择')}`
    : '未配置 LLM（需求拆分使用规则回退）';
  notice.innerHTML = `真实检索已连接：元宝 SearchPro API。LLM：${llm}。`;
}

function clearForm() {
  $('textInput').value = '';
  $('planPanel').hidden = true;
  $('researchPanel').hidden = true;
  state.report = null;
  $('reportBox').innerHTML = '<p class="muted">尚未生成调查报告。请先在「研究」页运行一次检索。</p>';
  $('textInput').focus();
}
function formPayload() {
  return {
    text: $('textInput').value.trim(),
    refresh: false,
  };
}
function setBusy(busy, mode = '') {
  state.busy = busy;
  $('runBtn').disabled = busy;
  $('planBtn').disabled = busy;
  $('clearBtn').disabled = busy;
  $('runBtn').textContent = busy && mode === 'run' ? '检索中…' : '开始检索';
  $('planBtn').textContent = busy && mode === 'plan' ? '生成中…' : '生成查询计划';
}

async function loadPlan() {
  const payload = formPayload();
  if (!payload.text) { showError('请先输入研究问题。'); return; }
  $('planPanel').hidden = false;
  $('researchPanel').hidden = true;
  $('planState').textContent = '生成中…';
  $('planSub').textContent = payload.text;
  $('planSummary').textContent = '';
  $('planQueries').innerHTML = '<p class="muted">正在拆分需求并构造查询…</p>';
  $('planFallbacks').innerHTML = '';
  setBusy(true, 'plan');
  try {
    const data = await fetchJSON('/api/plan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    renderPlan(data);
    $('planState').textContent = '已生成';
  } catch (error) {
    $('planState').textContent = '失败';
    $('planQueries').innerHTML = '';
    showError(`查询计划失败：${error.message}`);
  } finally {
    setBusy(false);
  }
}

function renderPlan(data) {
  const requirements = data.requirements || [];
  const initials = data.queries || [];
  const extras = [...(data.fallback_queries || []), ...(data.requery_queries || [])];
  $('planSummary').textContent = `${data.method || '规则'} · ${requirements.length} 条需求 · ${initials.length} 条初始查询 · ${extras.length} 条 B/C/再查询`;
  const reqById = new Map(requirements.map((item) => [item.requirement_id, item]));
  $('planQueries').innerHTML = queryList(initials, reqById);
  $('planFallbacks').innerHTML = queryList(extras, reqById);
}

function queryList(items, reqById) {
  if (!items.length) return '<p class="muted">暂无</p>';
  return items.map((item) => {
    const requirement = reqById.get(item.requirement_id);
    const field = requirement ? requirement.field : '';
    const directed = item.site || item.industry || '无定向';
    return `
      <div class="query-row">
        <div class="query-text">${esc(item.query)}</div>
        <div class="query-meta">${esc(field)} · ${esc(item.precision || '')} · ${esc(directed)} · ${esc(item.freshness || '')}</div>
      </div>`;
  }).join('');
}

async function runResearch() {
  const payload = formPayload();
  if (!payload.text) { showError('请先输入研究问题。'); return; }
  $('researchPanel').hidden = false;
  $('planPanel').hidden = true;
  $('researchState').textContent = '检索中…';
  $('researchTitle').textContent = '检索结果';
  $('researchSub').textContent = payload.text;
  $('metrics').innerHTML = '<p class="muted">正在执行需求拆分、查询构造和真实检索；通常需要十几秒。</p>';
  $('answer').innerHTML = '';
  $('results').innerHTML = '';
  state.report = null;
  setBusy(true, 'run');
  try {
    const data = await fetchJSON('/api/research', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    renderResearch(data);
    state.report = data.report || null;
    $('researchState').textContent = data.demo ? '演示 · 预置结果' : '已完成';
  } catch (error) {
    $('researchState').textContent = '失败';
    $('metrics').innerHTML = '';
    showError(`检索失败：${error.message}`);
  } finally {
    setBusy(false);
  }
}

function renderResearch(data) {
  const metrics = data.metrics || {};
  const answer = data.answer || null;
  $('answer').innerHTML = answer ? answerCard(answer) : '';
  $('researchSub').textContent = `${data.domain || '研究问题'} · ${data.method || 'llm'} · ${data.question || ''}`;
  $('metrics').innerHTML = [
    metricCard('字段覆盖', `${metrics.fields_with_ab || 0}/${metrics.fields || 0}`),
    metricCard('不同字段', `${metrics.distinct_fields_with_ab || 0}/${metrics.distinct_fields || 0}`),
    metricCard('相关官方率', pct(metrics.relevant_official_rate)),
    metricCard('零结果字段', String(metrics.zero_requirements || 0)),
  ].join('');

  const results = data.results || [];
  if (!results.length) {
    $('results').innerHTML = '<p class="muted">没有可展示的字段。</p>';
    return;
  }
  $('results').innerHTML = results.map((row) => {
    const tier = TIER[row.tier] || TIER.insufficient;
    const sources = (row.top_sources || []).map((source) => `
      <li class="source">
        <span class="grade grade-${esc(source.grade)}">${esc(source.grade)}</span>
        <div>
          <a href="${esc(safeUrl(source.url))}" target="_blank" rel="noopener">${esc(source.title || source.domain)}</a>
          <p>${esc(source.domain)}${source.date ? ' · ' + esc(source.date) : ''}</p>
        </div>
      </li>`).join('');
    const queries = (row.executed || []).map((item) => `
      <li><span class="strategy">${esc(item.strategy)}</span> ${esc(item.query)} <em>${item.pages} 页${item.cache_hit ? ' · 缓存' : ''}</em>${item.error ? ' · ' + esc(item.error) : ''}</li>
    `).join('');
    return `
      <article class="result-card">
        <div class="result-head">
          <div>
            <p class="eyebrow">${esc(row.field)}</p>
            <h3>${esc(row.text || row.field)}</h3>
          </div>
          <span class="tier ${tier.cls}">${tier.label}</span>
        </div>
        <p class="result-summary">${row.pages} 页 · 相关 ${row.relevant_pages} 页 · A/B ${(row.relevant_grades?.A || 0) + (row.relevant_grades?.B || 0)} · C ${row.relevant_grades?.C || 0}</p>
        ${sources ? `<ul class="sources">${sources}</ul>` : '<p class="empty-source">没有找到可用的 A/B 或 C 级来源。</p>'}
        <details class="queries"><summary>执行过的查询（${(row.executed || []).length}）</summary><ul>${queries}</ul></details>
      </article>`;
  }).join('');
}

function answerCard(answer) {
  const raw = esc(String(answer.answer || ''));
  const text = raw.replace(/\n/g, '<br>').replace(/\[(\d+)\]/g, '<a class="cite-ref" href="#cite-$1">[$1]</a>');
  const verdict = answer.verdict || '';
  const citations = (answer.citations || []).map((c) => `
    <li class="source" id="cite-${c.n}">
      <span class="grade grade-${esc(c.grade)}">${esc(c.grade)}</span>
      <div>
        <a href="${esc(safeUrl(c.url))}" target="_blank" rel="noopener">[${c.n}] ${esc(c.title || c.domain)}</a>
        <p>${esc(c.domain)}${c.date ? ' · ' + esc(c.date) : ''}</p>
      </div>
    </li>`).join('');
  const fallback = answer.engine === 'llm' ? '' : '<span class="muted">（规则回退，未调用大模型）</span>';
  return `
    <div class="answer-box">
      <div class="answer-head">
        <span class="eyebrow">结论</span>
        ${verdict ? `<span class="verdict">${esc(verdict)}</span>` : ''}
        ${fallback}
      </div>
      <div class="answer-text">${text}</div>
      ${answer.uncertainty ? `<p class="answer-note">${esc(answer.uncertainty)}</p>` : ''}
      ${citations ? `<details class="citations"><summary>引用来源（${answer.citations.length}）</summary><ul class="sources">${citations}</ul></details>` : ''}
    </div>`;
}

function renderReport() {
  if (!state.report) return;
  $('reportBox').innerHTML = reportCard(state.report);
  switchTab('report');
}

function reportCard(report) {
  if (!report) return '';
  const verdict = report.verdict || '';
  const answer = esc(String(report.answer || '')).replace(/\n/g, '<br>');
  const citations = (report.citations || []).map(function (c) {
    return '<li class="source" id="cite-' + c.n + '">' +
      '<span class="grade grade-' + esc(c.grade) + '">' + esc(c.grade) + '</span>' +
      '<div><a href="' + esc(safeUrl(c.url)) + '" target="_blank" rel="noopener">[' + c.n + '] ' + esc(c.title || c.domain) + '</a>' +
      '<p>' + esc(c.domain) + (c.date ? ' · ' + esc(c.date) : '') + '</p></div></li>';
  }).join('');
  const fields = (report.fields || []).map(function (f) {
    const srcs = (f.top_sources || []).map(function (s) {
      return '<li class="source"><span class="grade grade-' + esc(s.grade) + '">' + esc(s.grade) + '</span>' +
        '<div><a href="' + esc(safeUrl(s.url)) + '" target="_blank" rel="noopener">' + esc(s.title || s.domain) + '</a>' +
        '<p>' + esc(s.domain || '') + '</p></div></li>';
    }).join('');
    return '<div class="report-field"><p class="eyebrow">' + esc(f.field || '') + ' · ' + esc(f.tier || '') + '</p>' +
      '<p>' + esc(f.text || '') + '</p>' +
      (srcs ? '<ul class="sources">' + srcs + '</ul>' : '') + '</div>';
  }).join('');
  return '<div class="answer-box">' +
    '<div class="answer-head"><span class="eyebrow">调查报告</span>' +
    (verdict ? '<span class="verdict">' + esc(verdict) + '</span>' : '') + '</div>' +
    '<div class="answer-text">' + answer + '</div>' +
    (report.uncertainty ? '<p class="answer-note">' + esc(report.uncertainty) + '</p>' : '') +
    (citations ? '<details class="citations" open><summary>引用来源（' + report.citations.length + '）</summary><ul class="sources">' + citations + '</ul></details>' : '') +
    (fields ? '<h4>字段来源</h4>' + fields : '') +
    '<p class="answer-note">' + esc(report.disclaimer || '') + '</p>' +
    '</div>';
}

function metricCard(label, value) {
  return `<div class="metric"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`;
}

function safeUrl(value) {
  const raw = String(value || '').trim();
  return /^https?:\/\//i.test(raw) ? raw : '#';
}

function showError(message) {
  const notice = $('notice');
  notice.hidden = false;
  notice.className = 'notice error';
  notice.textContent = String(message);
}
