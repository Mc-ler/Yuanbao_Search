'use strict';

const $ = (id) => document.getElementById(id);
const state = {
  health: null,
  mode: 'research',
  busy: false,
  lang: localStorage.getItem('ui.lang') || 'zh',
  theme: localStorage.getItem('ui.theme') || 'light',
  logs: { research: [], verify: [] },
  reports: { research: null, verify: null },
  data: { research: null, verify: null },
  eventSource: null,
  verifyRunId: null,
  pollTimer: null,
  runState: 'ready'
};

const I18N = {
  zh: {
    'app.title': '万物皆可查 · Confirming Everything',
    'brand.name': '万物皆可查',
    'brand.sub': 'Confirming Everything',
    'status.llm': 'LLM', 'status.search': '搜索', 'status.screenshot': '截图',
    'status.llmTitle': 'LLM 配置状态', 'status.searchTitle': '元宝搜索配置状态',
    'status.screenshotTitle': '截图证据开关（需要 Chrome）', 'status.theme': '切换主题',
    'status.lang': '切换语言', 'status.settings': '配置',
    'status.checking': '检查中', 'status.missing': '未配置', 'status.ready': '就绪',
    'status.unavailable': '不可用', 'status.available': '可用',
    'status.screenshotOn': '截图 · 已启用', 'status.screenshotOff': '截图 · 已关闭', 'status.screenshotUnavailable': '截图 · 不可用',
    'hero.title': '今天想查什么？',
    'mode.research': '深度研究', 'mode.researchHint': '检索、来源分册、研究综述',
    'mode.verify': '一句话查证', 'mode.verifyHint': 'R1–R5 确定性判定',
    'input.label': '输入', 'input.placeholderResearch': '输入一个想查证的问题…',
    'input.placeholderVerify': '输入一句需要核实的话…',
    'input.hintResearch': '研究综述不是判决；需要成立/不成立请切到「一句话查证」。',
    'input.hintVerify': '判定由 R1–R5 代码完成；证据不足时才附加模型参考意见。',
    'action.runResearch': '开始研究', 'action.runVerify': '开始查证', 'action.clear': '清空',
    'action.clearLog': '清空日志', 'action.configure': '配置', 'action.print': '打印', 'action.save': '保存',
    'state.ready': '就绪', 'state.researching': '研究中…', 'state.verifying': '查证中…',
    'state.done': '已完成', 'state.failed': '失败', 'state.saving': '保存中…',
    'setup.llmMissing': 'LLM 未配置：请填写 API Key、Base URL 与模型。',
    'log.eyebrow': 'Trace', 'log.title': '执行日志', 'log.emptyMeta': '运行后在这里保留每一步', 'log.noLogs': '当前模式还没有日志。',
    'report.eyebrow': 'Report', 'report.title': '最终报告', 'report.emptyTitle': '还没有报告',
    'report.emptyText': '选择模式、输入问题并运行；日志和报告会分别保留。',
    'report.summary': '研究综述', 'report.metrics': '指标', 'report.citations': '引用来源',
    'report.sources': '来源分册', 'report.gaps': '证据缺口', 'report.issues': '引用校验',
    'report.verdict': '判定', 'report.rule': '规则', 'report.cluster': '计票',
    'report.evidence': '证据', 'report.action': '行动含义', 'report.disclaimer': '免责声明',
    'report.aiAdvisory': '模型参考意见（非判定）', 'report.noSources': '没有可用来源。',
    'metric.requirements': '需求覆盖 A/B', 'metric.ab': 'A/B 来源占比', 'metric.unique': '去重后页数',
    'metric.duplicates': '去重条数', 'metric.directed': '定向查询占比', 'metric.screenshots': '截图',
    'footer.disclaimer': '只核对公开信息与来源，不评价个人，不构成消费或法律建议。',
    'config.llmTitle': 'LLM 配置', 'config.eyebrow': 'Settings', 'config.title': '配置', 'config.provider': 'Provider',
    'config.apiKey': 'API Key', 'config.baseUrl': 'Base URL', 'config.model': 'Model',
    'config.searchTitle': '元宝搜索', 'config.screenshotTitle': '截图证据',
    'config.screenshotEnable': '启用页面截图',
    'config.llmHint': 'Key 只写入本地 .env；保存后立即重建 LLM 客户端，不写入前端存储。',
    'config.searchHint': '用于元宝 SearchPro；保存后立即重建检索客户端。',
    'config.screenshotHint': '需要 Chrome/Edge 与 websockets；不可用时按钮禁用并显示原因。',
    'config.statusReady': '已配置', 'config.statusMissing': '未配置', 'config.saved': '已保存',
    'config.saveFailed': '保存失败', 'config.keyStored': 'Key 仅保存在本地 .env',
    'config.searchReady': '已连接', 'config.searchMissing': '未配置',
    'config.shotEnabled': '已启用', 'config.shotDisabled': '已关闭', 'config.shotUnavailable': '不可用',
    'log.startResearch': '已提交深度研究请求', 'log.startVerify': '已提交一句话查证请求',
    'log.plan': '计划：{n} 条需求，方法 {method}', 'log.query': '查询：{query}',
    'log.ledger': '来源分册：{field} / {tier} / 去重后 {unique} 页 / {clusters} 簇',
    'log.dedup': '去重：原始 {raw} 页 → 唯一 {unique} 页，移除 {removed} 条重复', 'log.screenshot': '截图证据：{n} 张',
    'log.answer': '研究综述：引擎 {engine}，引用 {citations} 条', 'log.done': '完成：{reason}',
    'log.split': '拆出 {n} 条断言', 'log.searchResult': '检索：{pages} 页{error}', 'log.round': '第 {round} 轮：{verdict}（{rule}）',
    'log.unit': '判定：{text} → {verdict}（{rule}）', 'log.stats': '统计：检索 {calls} 次，缓存 {hits} 次，簇 {clusters} 个',
    'log.advisory': '已生成 R5 参考意见（非判定）', 'log.connected': 'SSE 已连接，等待事件…', 'log.polling': 'SSE 中断，切换轮询',
    'log.requestSubmitted': '请求已提交：{id}', 'log.error': '错误：{message}',
    'stage.start': '开始', 'stage.plan': '计划', 'stage.query': '查询', 'stage.search': '检索',
    'stage.dedup': '去重', 'stage.ledger': '分册', 'stage.screenshot': '截图', 'stage.answer': '综述',
    'stage.split': '拆分', 'stage.judge': '判定', 'stage.advisory': '参考', 'stage.stats': '统计',
    'stage.done': '完成', 'stage.error': '错误', 'stage.connected': '连接',
    'status.mode': '模式'
  },
  en: {
    'app.title': 'Confirming Everything · 万物皆可查',
    'brand.name': 'Confirming Everything',
    'brand.sub': '万物皆可查',
    'status.llm': 'LLM', 'status.search': 'Search', 'status.screenshot': 'Shots',
    'status.llmTitle': 'LLM configuration status', 'status.searchTitle': 'Yuanbao Search status',
    'status.screenshotTitle': 'Screenshot evidence toggle (Chrome required)', 'status.theme': 'Toggle theme',
    'status.lang': 'Switch language', 'status.settings': 'Settings',
    'status.checking': 'checking', 'status.missing': 'not configured', 'status.ready': 'ready',
    'status.unavailable': 'unavailable', 'status.available': 'available',
    'status.screenshotOn': 'Shots · on', 'status.screenshotOff': 'Shots · off', 'status.screenshotUnavailable': 'Shots · n/a',
    'hero.title': 'What would you like to verify?',
    'mode.research': 'Deep research', 'mode.researchHint': 'sources, source ledger, synthesis',
    'mode.verify': 'One-sentence check', 'mode.verifyHint': 'deterministic R1–R5 verdict',
    'input.label': 'Input', 'input.placeholderResearch': 'Ask a question to research…',
    'input.placeholderVerify': 'Enter a sentence to verify…',
    'input.hintResearch': 'A research synthesis is not a verdict. Switch to One-sentence check for a verdict.',
    'input.hintVerify': 'R1–R5 is deterministic code. A model note is added only when evidence is insufficient.',
    'action.runResearch': 'Start research', 'action.runVerify': 'Start check', 'action.clear': 'Clear',
    'action.clearLog': 'Clear log', 'action.configure': 'Configure', 'action.print': 'Print', 'action.save': 'Save',
    'state.ready': 'ready', 'state.researching': 'researching…', 'state.verifying': 'checking…',
    'state.done': 'done', 'state.failed': 'failed', 'state.saving': 'saving…',
    'setup.llmMissing': 'LLM is not configured: enter an API key, base URL and model.',
    'log.eyebrow': 'Trace', 'log.title': 'Execution log', 'log.emptyMeta': 'Each step is kept here after a run', 'log.noLogs': 'No log for this mode yet.',
    'report.eyebrow': 'Report', 'report.title': 'Final report', 'report.emptyTitle': 'No report yet',
    'report.emptyText': 'Choose a mode, enter a question and run. Logs and reports are kept separately.',
    'report.summary': 'Research summary', 'report.metrics': 'Metrics', 'report.citations': 'Citations',
    'report.sources': 'Source ledger', 'report.gaps': 'Evidence gaps', 'report.issues': 'Citation checks',
    'report.verdict': 'Verdict', 'report.rule': 'Rule', 'report.cluster': 'Cluster votes',
    'report.evidence': 'Evidence', 'report.action': 'Action', 'report.disclaimer': 'Disclaimer',
    'report.aiAdvisory': 'Model note (not a verdict)', 'report.noSources': 'No usable sources.',
    'metric.requirements': 'Requirements A/B', 'metric.ab': 'A/B source rate', 'metric.unique': 'Unique pages',
    'metric.duplicates': 'Duplicates removed', 'metric.directed': 'Directed queries', 'metric.screenshots': 'Screenshots',
    'footer.disclaimer': 'Only public information and sources are checked. No personal evaluation, no consumer or legal advice.',
    'config.llmTitle': 'LLM configuration', 'config.eyebrow': 'Settings', 'config.title': 'Configuration', 'config.provider': 'Provider',
    'config.apiKey': 'API Key', 'config.baseUrl': 'Base URL', 'config.model': 'Model',
    'config.searchTitle': 'Yuanbao Search', 'config.screenshotTitle': 'Screenshot evidence',
    'config.screenshotEnable': 'Enable page screenshots',
    'config.llmHint': 'The key is written only to local .env; the client is rebuilt immediately and never stored in the browser.',
    'config.searchHint': 'Used by Yuanbao SearchPro; the search client is rebuilt immediately.',
    'config.screenshotHint': 'Requires Chrome/Edge and websockets; disabled with a reason when unavailable.',
    'config.statusReady': 'configured', 'config.statusMissing': 'not configured', 'config.saved': 'saved',
    'config.saveFailed': 'save failed', 'config.keyStored': 'Key is stored only in local .env',
    'config.searchReady': 'connected', 'config.searchMissing': 'not configured',
    'config.shotEnabled': 'enabled', 'config.shotDisabled': 'disabled', 'config.shotUnavailable': 'unavailable',
    'log.startResearch': 'Deep research submitted', 'log.startVerify': 'One-sentence check submitted',
    'log.plan': 'Plan: {n} requirements, method {method}', 'log.query': 'Query: {query}',
    'log.ledger': 'Source ledger: {field} / {tier} / {unique} unique pages / {clusters} clusters',
    'log.dedup': 'Dedupe: {raw} raw pages → {unique} unique, {removed} duplicates', 'log.screenshot': 'Screenshot evidence: {n}',
    'log.answer': 'Synthesis: engine {engine}, {citations} citations', 'log.done': 'Done: {reason}',
    'log.split': 'Extracted {n} claims', 'log.searchResult': 'Search: {pages} pages{error}', 'log.round': 'Round {round}: {verdict} ({rule})',
    'log.unit': 'Verdict: {text} → {verdict} ({rule})', 'log.stats': 'Stats: {calls} searches, {hits} cache hits, {clusters} clusters',
    'log.advisory': 'R5 model note generated (not a verdict)', 'log.connected': 'SSE connected, waiting for events…', 'log.polling': 'SSE interrupted; falling back to polling',
    'log.requestSubmitted': 'Request submitted: {id}', 'log.error': 'Error: {message}',
    'stage.start': 'start', 'stage.plan': 'plan', 'stage.query': 'query', 'stage.search': 'search',
    'stage.dedup': 'dedupe', 'stage.ledger': 'ledger', 'stage.screenshot': 'shot', 'stage.answer': 'answer',
    'stage.split': 'split', 'stage.judge': 'judge', 'stage.advisory': 'note', 'stage.stats': 'stats',
    'stage.done': 'done', 'stage.error': 'error', 'stage.connected': 'connect',
    'status.mode': 'Mode'
  }
};

function t(key, vars) {
  const lang = I18N[state.lang] ? state.lang : 'zh';
  let text = I18N[lang][key] || I18N.zh[key] || key;
  if (vars) {
    Object.keys(vars).forEach((name) => {
      text = text.split('{' + name + '}').join(String(vars[name]));
    });
  }
  return text;
}

const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ESC[ch]);
const pct = (value) => (Number(value || 0) * 100).toFixed(1) + '%';

document.addEventListener('DOMContentLoaded', init);

async function init() {
  applyTheme();
  applyI18n();
  bind();
  setMode('research');
  try {
    await refreshHealth();
  } catch (error) {
    showToast(t('log.error', { message: error.message }), 'error');
    $('llmStatus').className = 'status-chip warn';
    $('searchStatus').className = 'status-chip warn';
  }
}

function bind() {
  $('modeResearch').addEventListener('click', () => setMode('research'));
  $('modeVerify').addEventListener('click', () => setMode('verify'));
  $('runBtn').addEventListener('click', execute);
  $('clearBtn').addEventListener('click', clearActive);
  $('clearLogBtn').addEventListener('click', clearActiveLog);
  $('printBtn').addEventListener('click', () => window.print());
  $('themeToggle').addEventListener('click', toggleTheme);
  $('langToggle').addEventListener('click', toggleLang);
  $('llmStatus').addEventListener('click', openLlmDialog);
  $('searchStatus').addEventListener('click', openSearchDialog);
  $('setupLlmBtn').addEventListener('click', openLlmDialog);
  $('closeLlm').addEventListener('click', () => $('llmDialog').close());
  $('closeSearch').addEventListener('click', () => $('searchDialog').close());
  ['llmDialog', 'searchDialog'].forEach((id) => {
    const dialog = $(id);
    dialog.addEventListener('click', (event) => {
      if (event.target === dialog) dialog.close();
    });
  });
  $('saveLlm').addEventListener('click', saveLlm);
  $('saveSearch').addEventListener('click', saveSearch);
  $('screenshotToggle').addEventListener('change', (event) => setScreenshots(event.target.checked));
  $('queryInput').addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') execute();
  });
  $('queryInput').addEventListener('input', () => {
    if (state.busy) return;
    setRunState('ready');
  });
}

function applyI18n() {
  document.documentElement.lang = state.lang === 'zh' ? 'zh-CN' : 'en';
  document.title = t('app.title');
  const brandLink = document.querySelector('.brand');
  if (brandLink) brandLink.setAttribute('aria-label', t('brand.name') + ' · ' + t('brand.sub'));
  const ambient = $('ambientWord');
  if (ambient) ambient.textContent = state.lang === 'zh' ? '万物皆可查' : 'CONFIRMING';
  document.querySelectorAll('[data-i18n]').forEach((node) => {
    node.textContent = t(node.dataset.i18n);
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach((node) => {
    node.setAttribute('placeholder', t(node.dataset.i18nPlaceholder));
  });
  document.querySelectorAll('[data-i18n-title]').forEach((node) => {
    node.setAttribute('title', t(node.dataset.i18nTitle));
  });
  $('langToggle').textContent = state.lang === 'zh' ? 'EN' : '中';
  $('themeToggle').textContent = state.theme === 'dark' ? '☀' : '☾';
  renderModeUI();
  if (state.health) renderStatus();
  renderLogs();
  renderReport();
}

function toggleLang() {
  state.lang = state.lang === 'zh' ? 'en' : 'zh';
  localStorage.setItem('ui.lang', state.lang);
  applyI18n();
}

function applyTheme() {
  document.documentElement.dataset.theme = state.theme;
  localStorage.setItem('ui.theme', state.theme);
}

function toggleTheme() {
  state.theme = state.theme === 'dark' ? 'light' : 'dark';
  applyTheme();
  $('themeToggle').textContent = state.theme === 'dark' ? '☀' : '☾';
}

async function api(url, options, timeoutMs = 300000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { ...(options || {}), signal: controller.signal, cache: 'no-store' });
    const text = await response.text();
    let data = null;
    if (text) {
      try { data = JSON.parse(text); } catch { data = text; }
    }
    if (!response.ok) {
      const detail = data && typeof data === 'object' && data.detail ? data.detail : (data || response.statusText || 'Request failed');
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
    return data;
  } catch (error) {
    if (error && error.name === 'AbortError') {
      throw new Error(state.lang === 'zh' ? '请求超时（300 秒）：服务可能仍在处理，请稍后查看或重试。' : 'Request timed out after 300s; the service may still be working.');
    }
    if (error && (error.name === 'TypeError' || /Failed to fetch|NetworkError|fetch failed/i.test(String(error.message)))) {
      throw new Error(state.lang === 'zh' ? '本地服务连接中断（可能已停止或重启）。请确认 http://127.0.0.1:8000 正在运行。' : 'Local service connection lost (stopped or restarting). Confirm http://127.0.0.1:8000 is running.');
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

async function refreshHealth() {
  const health = await api('/api/health', {}, 30000);
  state.health = health;
  renderStatus();
  return health;
}

function renderStatus() {
  const health = state.health;
  if (!health) return;
  const settings = health.settings || {};
  const llm = health.llm || {};
  const llmReady = Boolean(llm.key_present);
  const llmChip = $('llmStatus');
  llmChip.className = 'status-chip ' + (llmReady ? 'ok' : 'warn');
  $('llmStatusText').textContent = llmReady
    ? (llm.provider || 'LLM') + ' / ' + (llm.model || t('status.ready'))
    : t('status.missing');
  llmChip.title = t('status.llmTitle');

  const searchReady = Boolean(health.search_ready || settings.search_ready);
  const searchChip = $('searchStatus');
  searchChip.className = 'status-chip ' + (searchReady ? 'ok' : 'warn');
  $('searchStatusText').textContent = searchReady ? t('status.ready') : t('status.missing');
  searchChip.title = t('status.searchTitle');

  const shots = health.screenshots || {};
  const canShots = Boolean(shots.chrome) && !String(shots.reason || '').includes('websockets');
  const enabled = Boolean(shots.enabled);
  const shotToggle = $('screenshotToggle');
  shotToggle.checked = enabled;
  const shotSwitch = shotToggle.closest('.switch');
  if (shotSwitch) shotSwitch.classList.toggle('on', enabled);
  shotToggle.disabled = !canShots || state.busy;
  shotToggle.title = !canShots
    ? (shots.reason || t('status.unavailable'))
    : (enabled ? t('config.shotEnabled') : t('config.shotDisabled'));
  $('screenshotLabel').textContent = !canShots
    ? t('status.screenshotUnavailable')
    : (enabled ? t('status.screenshotOn') : t('status.screenshotOff'));

  $('llmConfigStatus').textContent = llmReady ? t('config.statusReady') : t('config.statusMissing');
  $('llmConfigStatus').className = 'config-status ' + (llmReady ? 'ok' : 'warn');
  $('searchConfigStatus').textContent = searchReady ? t('config.searchReady') : t('config.searchMissing');
  $('searchConfigStatus').className = 'config-status ' + (searchReady ? 'ok' : 'warn');

  const providers = llm.providers || [];
  const current = providers.find((item) => item.name === llm.provider) || providers[0];
  if (current) {
    $('llmProvider').value = current.name;
    $('llmBase').value = current.base_url || '';
    if (!$('llmModel').value) $('llmModel').value = llm.model || current.default_model || '';
  }
  $('searchBase').value = settings.search_base_url || $('searchBase').value;

  const callout = $('setupCallout');
  callout.hidden = llmReady;
  if (!llmReady) $('setupText').textContent = t('setup.llmMissing');
}

function setMode(mode) {
  if (state.busy && mode !== state.mode) return;
  state.mode = mode;
  document.querySelectorAll('.mode-btn').forEach((btn) => {
    const active = btn.dataset.mode === mode;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  renderModeUI();
  renderLogs();
  renderReport();
}

function renderModeUI() {
  const research = state.mode === 'research';
  $('queryInput').setAttribute('placeholder', t(research ? 'input.placeholderResearch' : 'input.placeholderVerify'));
  $('runBtn').textContent = state.busy
    ? t(research ? 'state.researching' : 'state.verifying')
    : t(research ? 'action.runResearch' : 'action.runVerify');
  setRunState(state.runState);
}

function setRunState(kind) {
  state.runState = kind;
  const node = $('runState');
  node.className = 'state-pill ' + kind;
  node.textContent = t('state.' + kind);
  if ($('logMeta')) {
    const logs = state.logs[state.mode] || [];
    $('logMeta').textContent = t(state.mode === 'research' ? 'mode.research' : 'mode.verify') + ' · ' + logs.length + ' · ' + t('state.' + kind);
  }
}

function setBusy(busy) {
  state.busy = busy;
  $('runBtn').disabled = busy;
  $('clearBtn').disabled = busy;
  $('modeResearch').disabled = busy;
  $('modeVerify').disabled = busy;
  $('screenshotToggle').disabled = busy || !canShots();
  $('saveLlm').disabled = busy;
  $('saveSearch').disabled = busy;
  renderModeUI();
  if (state.health) renderStatus();
}

function canShots() {
  const shots = (state.health && state.health.screenshots) || {};
  return Boolean(shots.chrome) && !String(shots.reason || '').includes('websockets');
}

async function execute() {
  if (state.busy) return;
  const text = $('queryInput').value.trim();
  if (!text) {
    showToast(state.lang === 'zh' ? '请先输入问题或说法。' : 'Enter a question or claim first.', 'error');
    $('queryInput').focus();
    return;
  }
  const mode = state.mode;
  state.logs[mode] = [];
  state.reports[mode] = null;
  state.data[mode] = null;
  setBusy(true);
  setRunState(mode === 'research' ? 'researching' : 'verifying');
  addLog(mode, 'start', t(mode === 'research' ? 'log.startResearch' : 'log.startVerify'));
  if (mode === 'research') {
    try {
      const data = await api('/api/research', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text })
      });
      state.data.research = data;
      state.reports.research = data.report || null;
      buildResearchLogs(data);
      renderLogs();
      renderReport();
      setRunState('done');
    } catch (error) {
      addLog('research', 'error', error.message, 'error');
      setRunState('failed');
      showToast(error.message, 'error');
    } finally {
      setBusy(false);
    }
    return;
  }

  try {
    const run = await api('/api/runs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text })
    });
    state.verifyRunId = run.run_id;
    addLog('verify', 'connected', t('log.requestSubmitted', { id: run.run_id }));
    connectEvents(run.run_id);
  } catch (error) {
    addLog('verify', 'error', error.message, 'error');
    setRunState('failed');
    setBusy(false);
    showToast(error.message, 'error');
  }
}

function clearActive() {
  if (state.busy) return;
  $('queryInput').value = '';
  state.logs[state.mode] = [];
  state.reports[state.mode] = null;
  state.data[state.mode] = null;
  setRunState('ready');
  renderLogs();
  renderReport();
  $('queryInput').focus();
}

function clearActiveLog() {
  state.logs[state.mode] = [];
  renderLogs();
}

function addLog(mode, stage, message, level) {
  const now = new Date();
  state.logs[mode].push({
    time: now.toLocaleTimeString(),
    stage: stage,
    message: message,
    level: level || 'info'
  });
  if (mode === state.mode) renderLogs();
}

function renderLogs() {
  const list = $('logList');
  const logs = state.logs[state.mode] || [];
  $('logMeta').textContent = t(state.mode === 'research' ? 'mode.research' : 'mode.verify') + ' · ' + logs.length + ' · ' + t('state.' + state.runState);
  if (!logs.length) {
    list.innerHTML = '<li class="log-empty">' + esc(t('log.noLogs')) + '</li>';
    return;
  }
  list.innerHTML = logs.map((entry) => {
    const stage = t('stage.' + entry.stage) || entry.stage;
    return '<li class="log-entry ' + esc(entry.level || 'info') + '">' +
      '<time>' + esc(entry.time) + '</time>' +
      '<span class="log-stage">' + esc(stage) + '</span>' +
      '<span class="log-message">' + esc(entry.message) + '</span></li>';
  }).join('');
}

function buildResearchLogs(data) {
  const metrics = data.metrics || {};
  const answer = data.answer || {};
  state.logs.research = [];
  addLog('research', 'plan', t('log.plan', { n: metrics.requirements || 0, method: data.method || '-' }));
  (data.queries || []).forEach((query) => {
    addLog('research', 'query', t('log.query', { query: query.query || '' }));
  });
  addLog('research', 'dedup', t('log.dedup', {
    raw: metrics.pages_raw || 0,
    unique: metrics.pages_unique || 0,
    removed: metrics.duplicates_removed || 0
  }));
  (data.source_ledger || []).forEach((entry) => {
    addLog('research', 'ledger', t('log.ledger', {
      field: entry.field || '',
      tier: entry.tier || '',
      unique: entry.unique_pages || 0,
      clusters: entry.clusters || 0
    }));
  });
  addLog('research', 'screenshot', t('log.screenshot', { n: metrics.screenshots || 0 }));
  addLog('research', 'answer', t('log.answer', {
    engine: answer.engine || '-',
    citations: (answer.citations || []).length
  }));
  addLog('research', 'done', t('log.done', { reason: data.stop_reason || 'completed' }));
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
    addLog('verify', 'connected', t('log.polling'));
    stopEvents();
    startPolling(runId);
  };
}

function handleEvent(type, raw) {
  let data = {};
  try { data = JSON.parse(raw || '{}'); } catch { data = {}; }
  if (type === 'run.started') {
    addLog('verify', 'connected', t('log.connected'));
  } else if (type === 'split.done') {
    addLog('verify', 'split', t('log.split', { n: (data.facts || []).length }));
  } else if (type === 'query.planned') {
    addLog('verify', 'query', t('log.query', { query: data.query || '' }));
  } else if (type === 'search.result') {
    addLog('verify', 'search', t('log.searchResult', {
      pages: data.pages || 0,
      error: data.error ? ' / ' + data.error : ''
    }));
  } else if (type === 'round.judged') {
    addLog('verify', 'judge', t('log.round', {
      round: (data.round || 0) + 1,
      verdict: data.verdict || '',
      rule: data.rule_id || ''
    }));
  } else if (type === 'unit.verdict') {
    addLog('verify', 'judge', t('log.unit', {
      text: (data.assertion && data.assertion.text) || '',
      verdict: data.verdict || '',
      rule: data.rule_id || ''
    }));
  } else if (type === 'advisory.ready') {
    addLog('verify', 'advisory', t('log.advisory'));
  } else if (type === 'run.stats') {
    addLog('verify', 'stats', t('log.stats', {
      calls: data.calls || 0,
      hits: data.cache_hits || 0,
      clusters: data.clusters || 0
    }));
  } else if (type === 'run.done') {
    state.reports.verify = data.report || null;
    addLog('verify', 'done', t('log.done', { reason: data.stop_reason || 'completed' }));
    setRunState('done');
    stopVerify();
    setBusy(false);
    renderReport();
  } else if (type === 'error') {
    addLog('verify', 'error', data.message || 'unknown error', 'error');
    setRunState('failed');
    stopVerify();
    setBusy(false);
    showToast(data.message || 'Run failed', 'error');
  }
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
  state.verifyRunId = null;
}

function startPolling(runId) {
  stopPolling();
  state.pollTimer = setInterval(async () => {
    try {
      const data = await api('/api/runs/' + encodeURIComponent(runId), {}, 30000);
      if (data.status === 'done' || data.status === 'error' || data.status === 'cancelled') {
        if (data.report) state.reports.verify = data.report;
        addLog('verify', data.status === 'done' ? 'done' : 'error', t('log.done', { reason: data.status }));
        setRunState(data.status === 'done' ? 'done' : 'failed');
        stopVerify();
        setBusy(false);
        renderReport();
      }
    } catch (error) {
      addLog('verify', 'error', error.message, 'error');
      setRunState('failed');
      stopVerify();
      setBusy(false);
      showToast(error.message, 'error');
    }
  }, 1500);
}

function renderReport() {
  const report = state.reports[state.mode];
  if (!report) {
    $('reportBox').innerHTML = '<div class="empty-state"><strong>' + esc(t('report.emptyTitle')) + '</strong><p>' + esc(t('report.emptyText')) + '</p></div>';
    return;
  }
  $('reportBox').innerHTML = state.mode === 'research' ? researchReport(report) : verificationReport(report);
}

function researchReport(report) {
  const metrics = report.metrics || {};
  const citations = (report.citations || []).map((item) => sourceCard(item, item.n)).join('');
  const ledger = (report.source_ledger || []).map((entry) => ledgerCard(entry)).join('');
  const issues = (report.citation_issues || []).length
    ? '<p class="answer-note">' + esc(t('report.issues')) + ': ' + report.citation_issues.map((item) => '[' + esc(item.n) + '] ' + esc(item.reason)).join('; ') + '</p>'
    : '';
  return '<section class="report-content">' +
    '<div class="report-summary"><h3>' + esc(t('report.summary')) + '</h3><p>' + esc(String(report.summary || '')).replace(/\n/g, '<br>') + '</p></div>' +
    (report.uncertainty ? '<p class="answer-note">' + esc(report.uncertainty) + '</p>' : '') + issues +
    '<div class="metric-grid">' +
      metricCard(t('metric.requirements'), (metrics.requirements_with_ab || 0) + '/' + (metrics.requirements || 0)) +
      metricCard(t('metric.ab'), pct(metrics.ab_source_rate)) +
      metricCard(t('metric.unique'), String(metrics.pages_unique || 0)) +
      metricCard(t('metric.duplicates'), String(metrics.duplicates_removed || 0)) +
      metricCard(t('metric.directed'), pct(metrics.directed_query_rate)) +
      metricCard(t('metric.screenshots'), String(metrics.screenshots || 0)) +
    '</div>' +
    (citations ? '<details class="citations" open><summary>' + esc(t('report.citations')) + ' (' + report.citations.length + ')</summary><ul class="sources">' + citations + '</ul></details>' : '') +
    (ledger ? '<h3 class="report-subhead">' + esc(t('report.sources')) + '</h3><div class="source-ledger">' + ledger + '</div>' : '') +
    (report.disclaimer ? '<p class="answer-note">' + esc(report.disclaimer) + '</p>' : '') +
    '</section>';
}

function verificationReport(report) {
  const units = (report.units || []).map((unit) => {
    const evidence = (unit.evidence || []).map((item) => {
      const quote = item.quote ? '<blockquote>' + esc(item.quote) + '</blockquote>' : '';
      return '<li class="source"><span class="grade grade-' + esc(item.grade) + '">' + esc(item.grade || '?') + '</span>' +
        '<div class="source-body"><a href="' + esc(safeUrl(item.url)) + '" target="_blank" rel="noopener">' + esc(item.title || item.domain) + '</a>' +
        '<p>' + esc(item.relation || '') + (item.date ? ' · ' + esc(item.date) : '') + '</p>' + quote + '</div></li>';
    }).join('');
    const advisory = unit.advisory ? '<p class="advisory">' + esc(t('report.aiAdvisory')) + ': ' + esc(unit.advisory.text || '') + '</p>' : '';
    return '<article class="result-card"><div class="result-head"><div><p class="eyebrow">' + esc(unit.assertion && unit.assertion.field || '') + '</p>' +
      '<h3>' + esc(unit.assertion && unit.assertion.text || '') + '</h3></div>' +
      '<span class="tier tier-' + esc(String(unit.verdict || '').toLowerCase()) + '">' + esc(unit.verdict || '') + ' · ' + esc(unit.rule_id || '') + '</span></div>' +
      '<p class="result-summary">' + esc(t('report.verdict')) + ': ' + esc(unit.layered && unit.layered.a_level_only || '') +
      ' · ' + esc(t('report.cluster')) + ': ' + (unit.cluster_votes && unit.cluster_votes.support || 0) + ' / ' + (unit.cluster_votes && unit.cluster_votes.refute || 0) + '</p>' +
      '<p>' + esc(unit.action || '') + '</p>' + advisory +
      (evidence ? '<ul class="sources">' + evidence + '</ul>' : '') + '</article>';
  }).join('');
  return '<section class="report-content"><div class="report-summary"><h3>' + esc(t('report.verdict')) + '</h3>' +
    '<p>' + esc(report.task && report.task.text || '') + '</p></div>' + units +
    '<p class="answer-note">' + esc(report.disclaimer || '') + '</p></section>';
}

function ledgerCard(entry) {
  const sources = (entry.sources || []).map((source) => sourceCard(source, source.n)).join('');
  return '<article class="result-card"><div class="result-head"><div><p class="eyebrow">' + esc(entry.field || '') + '</p>' +
    '<h3>' + esc(entry.text || entry.field || '') + '</h3></div><span class="tier">' + esc(entry.tier || '') + '</span></div>' +
    '<p class="result-summary">' + (entry.unique_pages || 0) + ' pages · ' + (entry.clusters || 0) + ' clusters</p>' +
    (sources ? '<ul class="sources">' + sources + '</ul>' : '<p class="empty-source">' + esc(t('report.noSources')) + '</p>') + '</article>';
}

function sourceCard(source, number) {
  const cluster = source.cluster_size > 1 ? ' · ' + source.cluster_size + ' same-cluster' : '';
  const screenshot = source.screenshot_url
    ? '<a class="shot-link" href="' + esc(safeUrl(source.screenshot_url)) + '" target="_blank" rel="noopener"><img class="shot" loading="lazy" src="' + esc(safeUrl(source.screenshot_url)) + '" alt="source screenshot"></a>'
    : '';
  const passage = source.passage ? '<p class="snippet">' + esc(String(source.passage).slice(0, 220)) + '</p>' : '';
  return '<li class="source"><span class="grade grade-' + esc(source.grade) + '">' + esc(source.grade || '?') + '</span>' +
    '<div class="source-body"><a href="' + esc(safeUrl(source.url)) + '" target="_blank" rel="noopener">' +
    (number ? '[' + number + '] ' : '') + esc(source.title || source.domain) + '</a>' +
    '<p>' + esc(source.domain || '') + (source.date ? ' · ' + esc(source.date) : '') + esc(cluster) + '</p>' + passage + screenshot + '</div></li>';
}

function metricCard(label, value) {
  return '<div class="metric"><span>' + esc(label) + '</span><strong>' + esc(value) + '</strong></div>';
}

function safeUrl(value) {
  const raw = String(value || '').trim();
  return /^https?:\/\//i.test(raw) || /^\/api\/evidence\//.test(raw) ? raw : '#';
}

function openLlmDialog() {
  const dialog = $('llmDialog');
  if (!dialog.open) dialog.showModal();
  setTimeout(() => $('llmKey').focus(), 80);
}

function openSearchDialog() {
  const dialog = $('searchDialog');
  if (!dialog.open) dialog.showModal();
  setTimeout(() => $('searchKey').focus(), 80);
}

async function saveLlm() {
  const provider = $('llmProvider').value;
  const key = $('llmKey').value.trim();
  const base = $('llmBase').value.trim();
  const model = $('llmModel').value.trim();
  const payload = { provider };
  if (key) payload.api_key = key;
  if (base) payload.base_url = base;
  if (model) payload.model = model;
  $('llmSaveState').textContent = t('state.saving');
  try {
    await api('/api/config/llm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    $('llmKey').value = '';
    $('llmSaveState').textContent = t('config.saved');
    showToast(t('config.saved'), 'ok');
    await refreshHealth();
  } catch (error) {
    $('llmSaveState').textContent = t('config.saveFailed');
    showToast(error.message, 'error');
  }
}

async function saveSearch() {
  const key = $('searchKey').value.trim();
  const base = $('searchBase').value.trim();
  const payload = {};
  if (key) payload.api_key = key;
  if (base) payload.base_url = base;
  $('searchSaveState').textContent = t('state.saving');
  try {
    await api('/api/config/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    $('searchKey').value = '';
    $('searchSaveState').textContent = t('config.saved');
    showToast(t('config.saved'), 'ok');
    await refreshHealth();
  } catch (error) {
    $('searchSaveState').textContent = t('config.saveFailed');
    showToast(error.message, 'error');
  }
}

async function setScreenshots(enabled) {
  if (!canShots()) {
    $('screenshotToggle').checked = false;
    showToast(t('config.shotUnavailable') + ': ' + ((state.health && state.health.screenshots && state.health.screenshots.reason) || ''), 'error');
    return;
  }
  try {
    await api('/api/config/screenshots', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: enabled })
    });
    showToast(enabled ? t('config.shotEnabled') : t('config.shotDisabled'), 'ok');
    await refreshHealth();
  } catch (error) {
    await refreshHealth().catch(() => null);
    showToast(error.message, 'error');
  }
}

function showToast(message, kind) {
  const node = $('toast');
  node.textContent = String(message);
  node.className = 'toast ' + (kind || 'info');
  node.hidden = false;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => { node.hidden = true; }, 5000);
}
