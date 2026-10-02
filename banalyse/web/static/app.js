/* Banalyse 网页端：配置 + 生成报告。无依赖，原生 fetch。 */
'use strict';

// ---------------------------------------------------------------- 状态
const state = {
  providers: [],      // provider 元数据（来自 /api/providers）
  lastProvider: null, // 用于判断是否「切换了 provider」→ 自动填默认值
  lastResult: null,   // 最近一次生成结果（拿 company_name 等回填用）
  selected: null,     // Set<dimension key>：当前显示哪几个维度
  paneShares: null,   // Map<dimension key, number>：各栏占中间栏宽度的份额
  startView: false,   // 有结果时是否手动切回初始页（历史记录那一屏）
  history: null,      // 最近一次 /api/history 的返回（已保存报告清单）
};

const $ = (id) => document.getElementById(id);

const FORM_FIELDS = [
  'llm_provider', 'backend_url', 'deep_think_llm', 'quick_think_llm',
  'temperature', 'max_tokens', 'output_language',
];

// 四个分析维度（key/title 与后端 agents/dimensions.py 的 label 保持一致）
// brief / points 只用于中栏「四个框」说明界面：改后端维度时，这里跟着改。
const DIMENSIONS = [
  {
    key: 'business_model',
    title: '商业模式',
    brief: '这门生意靠什么赚钱、怎么一路走到今天、相对同行强在哪里。',
    points: [
      '赚钱方式：收入构成与收费模式、客户是谁、定价权来自什么',
      '经营历史：逐年的收入利润方向、主营与战略重心的变化',
      '相对同行的优势：成本 / 品牌 / 渠道 / 技术，有没有被收窄',
    ],
  },
  {
    key: 'management',
    title: '管理层',
    brief: '管理层实际做了什么、怎么对外交代：人是谁、钱怎么配、事怎么定。',
    points: [
      '管理层基本信息：核心高管、任期履历、持股与薪酬结构',
      '资本配置行为：分红、回购、并购是否提升每股长期价值',
      '对外披露：对股东 / 员工 / 大众是否如实、及时、口径一致',
      '管理层决策：重大决策的依据、结果兑现与言行一致性',
    ],
  },
  {
    key: 'capital_return',
    title: '财务状况',
    brief: '利润率在什么水平、每块钱投入挣回多少、ROE 的质量、真正能装进口袋的现金。',
    points: [
      '利润率：毛利率 / 营业利润率 / 净利率的位置与走向',
      '投资收益比：投入资本回报率 ROIC 与资金成本 WACC 比较',
      '近五年 ROE：杜邦拆分，区分盈利能力与财务杠杆',
      '股东盈余：净利润 + 非现金支出 − 维持性资本开支',
    ],
  },
  {
    key: 'margin_of_safety',
    title: '安全边际',
    brief: '现在的股价，相对这家企业值多少钱，打了几折。',
    points: [
      '股市现有价格：现价、总市值与所处历史水位',
      '公司资产价值：账面净资产与市值给出的溢价 / 折价',
      '内在价值：股东盈余折现（DCF）的悲观 / 基准 / 乐观区间',
      '折现率基准：按标的市场取长期国债收益率，再叠加风险溢价',
      '安全边际空间：相对现价的折扣幅度与最大下行空间',
    ],
  },
];

// ---------------------------------------------------------------- 工具
function toast(message, kind = '') {
  const el = $('toast');
  el.textContent = message;
  el.className = `toast ${kind}`;
  el.hidden = false;
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => { el.hidden = true; }, 6000);
}

function token() {
  return localStorage.getItem('ba_web_token') || '';
}

async function api(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (token()) headers['X-Web-Token'] = token();
  const resp = await fetch(path, { ...options, headers });
  let body = null;
  try { body = await resp.json(); } catch { /* 无 body */ }
  if (!resp.ok) {
    const detail = (body && (body.detail || body.error)) || `HTTP ${resp.status}`;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return body;
}

// ---------------------------------------------------------------- provider
function providerByName(name) {
  return state.providers.find((p) => p.name === name);
}

async function loadProviders() {
  const { providers } = await api('/api/providers');
  state.providers = providers;
  const select = $('llm_provider');
  select.innerHTML = '';
  providers.forEach((p) => {
    const opt = document.createElement('option');
    opt.value = p.name;
    opt.textContent = p.label;
    select.appendChild(opt);
  });
}

/* 切 provider 时同步 base_url / 模型名。
   判断「这个框要不要换」而不是「用户改没改过」——后者无法从值本身得知，
   只能看它像不像"自动填进去的东西"：

   · base_url 按**主机名**比：写不写 /v1 都算同一家。命中任何一家 Provider
     的默认主机 → 是自动填的，可以换；否则视为用户自定义（内网代理等），不动。
   · 模型名按**厂商标识前缀**认：deepseek-* / gpt-* / glm-* / qwen-* …。
     只要当前值带着**别家**的前缀，就是切 Provider 后留下的残值，换掉。
     认不出的名字（自建模型、微调名）一律保留。

   旧写法用 `value === prev.default_base_url`，在 prev 没有默认值时永远为假，
   于是从 mock 切到 openai，框里还留着 deepseek 的地址和模型名，
   保存下去就成了「provider=openai 却指向 api.deepseek.com」，极难排查。 */
const MODEL_PREFIXES = {
  mock: ['mock'],
  deepseek: ['deepseek'],
  qwen: ['qwen'],
  zhipu: ['glm'],
  openai: ['gpt', 'o1', 'o3', 'chatgpt', 'text-embedding'],
  ollama: ['llama', 'mistral', 'phi', 'gemma'],
};

function urlHost(url) {
  try { return new URL(url).host; } catch { return ''; }
}

/* 这个框里的值是否只是"以前自动填进去的默认值" */
function looksAutoFilled(id, selectedProvider) {
  const current = $(id).value.trim();
  if (!current) return true;

  if (id === 'backend_url') {
    const host = urlHost(current);
    return !!host && state.providers.some((p) => urlHost(p.default_base_url) === host);
  }

  // 模型名：等于任何一家的默认模型，或带着别家的前缀，都算残值
  const isCatalogDefault = state.providers.some(
    (p) => p.default_deep_model === current || p.default_quick_model === current
  );
  if (isCatalogDefault) return true;

  const lower = current.toLowerCase();
  return Object.entries(MODEL_PREFIXES).some(
    ([name, prefixes]) =>
      name !== selectedProvider && prefixes.some((pre) => lower.startsWith(pre))
  );
}

function fillField(id, nextValue, selectedProvider, { force = false } = {}) {
  if (!force && !looksAutoFilled(id, selectedProvider)) return;   // 用户自己填的，不动
  $(id).value = nextValue || '';
}

/* 所选 Provider 与 Base URL 是否对不上（比如选了 openai 却指向 deepseek） */
function updateUrlHint(provider) {
  const el = $('url-hint');
  if (!el) return;
  const meta = providerByName(provider);
  const current = $('backend_url').value.trim();
  el.className = 'hint';
  el.textContent = '';

  if (!current || !meta) return;

  const now = urlHost(current);
  if (!now) {
    el.textContent = '这个地址不是合法的 URL，模型调用会失败。';
    el.className = 'hint err';
    return;
  }
  if (urlHost(meta.default_base_url) === now) return;

  // 指向了别家 Provider 的地址 → 明确提示，避免"选了却不生效"的错觉
  const other = state.providers.find(
    (p) => p.name !== meta.name && urlHost(p.default_base_url) === now
  );
  if (other) {
    el.textContent = `注意：当前地址指向 ${other.label}，与所选 ${meta.label} 不一致。`
      + '如果不确定，先点「测试连通性」。';
    el.className = 'hint warn';
  }
}

/* 切换 provider 时：同步 base_url 与模型名，并检查地址是否对得上。

   ``syncFields: false`` 用于「刚载入配置」——那时表单必须**原样显示已保存的值**。
   否则会出现：界面显示 openai 的默认模型，磁盘上还留着上一家的，
   而生成时用的是磁盘那份 —— 表单在骗人，比不修更难查。 */
function applyProviderDefaults(provider, { force = false, syncFields = true } = {}) {
  const meta = providerByName(provider);
  if (!meta) return;
  const hint = $('provider-hint');
  hint.textContent = meta.requires_key
    ? `需要 Key（环境变量 ${meta.key_env}${meta.key_env_set ? '，已检测到' : ''}）`
    : '无需 Key';
  hint.className = 'hint';

  if (syncFields) {
    fillField('backend_url', meta.default_base_url, provider, { force });
    fillField('deep_think_llm', meta.default_deep_model, provider, { force });
    fillField('quick_think_llm', meta.default_quick_model, provider, { force });
  }
  state.lastProvider = provider;
  updateUrlHint(provider);
}

// ---------------------------------------------------------------- 配置载入
function fillForm(cfg) {
  FORM_FIELDS.forEach((key) => { if (cfg[key] !== undefined && cfg[key] !== null) $(key).value = cfg[key]; });
  $('api_key').value = '';  // 明文永不回填

  const hint = $('key-hint');
  if (cfg.api_key_set) {
    hint.textContent = `已保存 Key：${cfg.api_key_masked}（留空提交则保持不变）`;
    hint.className = 'hint ok';
  } else if (cfg.key_env && cfg.key_env_set) {
    hint.textContent = `未在网页保存；将使用环境变量 ${cfg.key_env}`;
    hint.className = 'hint warn';
  } else {
    hint.textContent = cfg.llm_provider === 'mock' ? 'Mock 模式无需 Key' : '尚未保存 Key';
    hint.className = cfg.llm_provider === 'mock' ? 'hint' : 'hint warn';
  }

  $('store-path').textContent = cfg.stored_at ? `配置落盘：${cfg.stored_at}` : '';
}

async function loadConfig({ applyDefaults = false } = {}) {
  const cfg = await api('/api/config');
  fillForm(cfg);
  state.lastProvider = cfg.llm_provider;
  // 不覆盖表单值：载入时要如实反映「磁盘上是什么」，生成用的就是那一份
  applyProviderDefaults(cfg.llm_provider, { force: applyDefaults, syncFields: applyDefaults });
  return cfg;
}

// ---------------------------------------------------------------- 配置动作
function collectForm() {
  const payload = {};
  FORM_FIELDS.forEach((key) => {
    const raw = $(key).value.trim();
    if (key === 'temperature' || key === 'max_tokens') {
      if (raw !== '') payload[key] = Number(raw);
    } else if (raw !== '') {
      payload[key] = raw;
    }
  });
  const key = $('api_key').value.trim();
  if (key) payload.api_key = key;   // 留空 = 后端保留原值
  return payload;
}

async function saveConfig() {
  const btn = $('save-config');
  btn.disabled = true;
  try {
    const cfg = await api('/api/config', { method: 'PUT', body: JSON.stringify(collectForm()) });
    fillForm(cfg);
    applyProviderDefaults(cfg.llm_provider);
    toast('配置已保存到本地', 'ok');
  } catch (err) {
    toast(`保存失败：${err.message}`, 'err');
  } finally {
    btn.disabled = false;
  }
}

async function testConfig() {
  const btn = $('test-config');
  btn.disabled = true;
  btn.textContent = '测试中…';
  try {
    const r = await api('/api/config/test', { method: 'POST', body: JSON.stringify(collectForm()) });
    toast(`连通正常 · ${r.provider} / ${r.model} · ${r.latency_ms}ms\n模型回复：${r.reply}`, 'ok');
  } catch (err) {
    toast(`连通失败：${err.message}`, 'err');
  } finally {
    btn.disabled = false;
    btn.textContent = '测试连通性';
  }
}

async function clearKey() {
  if (!confirm('确定清除已保存的 API Key？')) return;
  try {
    const cfg = await api('/api/config/key', { method: 'DELETE' });
    fillForm(cfg);
    toast('已清除保存的 Key', 'ok');
  } catch (err) {
    toast(`清除失败：${err.message}`, 'err');
  }
}

async function resetConfig() {
  if (!confirm('确定重置全部网页配置？此操作不可撤销。')) return;
  try {
    const cfg = await api('/api/config/reset', { method: 'POST' });
    fillForm(cfg);
    applyProviderDefaults(cfg.llm_provider, { force: true });
    toast('配置已重置', 'ok');
  } catch (err) {
    toast(`重置失败：${err.message}`, 'err');
  }
}

// ---------------------------------------------------------------- 标的代码
/* 代码填法决定走哪条数据链：纯数字 → A 股（AKShare），含字母 → 美股（SEC）。
   把公司名或 sh600519 填进来会被判成美股走 SEC，于是四个维度全部"材料未取到"，
   看起来像数据源坏了。所以这里实时把判定结果写出来，填错立刻可见。 */
const CJK = /[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/;
const EXCHANGE_PREFIX = /^(sh|sz|bj)[0-9]{6}$/i;
const A_SUFFIXES = ['.SS', '.SZ', '.SH', '.BJ'];

function tickerProblem(ticker) {
  const text = String(ticker || '').trim();
  if (!text) return '请填写股票代码。';
  if (CJK.test(text)) {
    return `「${text}」看着像公司名。代码请填纯数字（A 股，如 600519）`
      + '或字母代码（美股，如 AAPL）；公司名填在下面「公司名称」栏。';
  }
  if (EXCHANGE_PREFIX.test(text)) {
    return `「${text}」带了交易所前缀，请去掉 sh/sz/bj 直接填 ${text.slice(2)}`
      + '——带字母会被判为美股并走 SEC，取不到 A 股数据。';
  }
  let core = text.toUpperCase();
  const hit = A_SUFFIXES.find((s) => core.endsWith(s));
  if (hit) core = core.slice(0, -hit.length);
  if (/^[0-9]+$/.test(core) && core.length === 5) {
    return `「${text}」是 5 位数字，更像港股代码。目前只支持 A 股（6 位数字）与美股（字母代码）。`;
  }
  return null;
}

function updateTickerHint() {
  const el = $('ticker-hint');
  if (!el) return;
  const text = $('ticker').value.trim();
  const problem = tickerProblem(text);

  if (problem) {
    el.textContent = problem;
    el.className = 'hint err';
    return;
  }

  let core = text.toUpperCase();
  const hit = A_SUFFIXES.find((s) => core.endsWith(s));
  if (hit) core = core.slice(0, -hit.length);
  const china = /^[0-9]+$/.test(core);

  el.className = 'hint';
  el.textContent = china
    ? `判定为 A 股（纯数字）→ 数据源 AKShare`
    : `判定为美股（含字母）→ 数据源 SEC EDGAR`;
}

// ---------------------------------------------------------------- 生成分析
function dimTitle(key) {
  const meta = DIMENSIONS.find((d) => d.key === key);
  return meta ? meta.title : key;
}

/* 中栏要显示哪些维度：完全由左侧按钮决定。
   显示多个时横着均分，只显示一个就占满整栏。 */
function paneSpecs() {
  const result = state.lastResult;
  if (!result) return [];
  const reports = result.reports || {};
  const specs = [];
  DIMENSIONS.forEach(({ key, title }) => {
    if (!state.selected.has(key)) return;
    const text = String(reports[key] || '').trim();
    specs.push({ key, title, body: text || '（该维度报告缺失）' });
  });
  return specs;
}

// ---------------------------------------------------------------- 每栏占比
/* 每栏宽度 = 份额 × 可用宽度，份额存在 state.paneShares（默认 1/n，正好铺满）。
   关键点：份额之和**允许超过 1**。拖动分隔条把左栏撑大、右栏已经到下限之后，
   多出来的宽度就让整排超出中间栏，出现横向滚动——想细读某一栏时不用被挤着。

   份额而不是像素：窗口尺寸变了按份额重算，比例照旧。 */
const MIN_PANE_W = 160;        // 单栏最窄，跟 .pane 的 min-width 保持一致

/* 份额之和 < 1 时（窄栏被拖窄了）用 flex-grow 补满，不留空档；
   之和 > 1 时 flex-shrink:0 阻止压缩，于是整排溢出、可以左右滚动。 */
function paneShare(key, fallback) {
  const s = state.paneShares ? state.paneShares.get(key) : 0;
  return s > 0 ? s : fallback;
}

/* 分给各栏的总宽度 = 容器宽 − 拖动条自己占的宽。
   布局和拖动换算都必须用这个值，两边不一致就会出现“永远差 36px”的溢出。 */
function paneAvailableWidth() {
  const host = $('result-panels');
  if (!host) return 0;
  const gutterW = [...host.querySelectorAll('.pane-gutter')]
    .reduce((sum, g) => sum + g.getBoundingClientRect().width, 0);
  return Math.max(0, host.clientWidth - gutterW);
}

function applyPaneLayout() {
  const host = $('result-panels');
  if (!host || host.hidden) return;
  // 堆叠模式（窄屏）是纵向一栏一行，宽度由 CSS 全宽接管，不按份额算
  if (!splitterVisible()) { syncRowOverflow(); return; }
  const available = paneAvailableWidth();
  if (!available) return;

  const panes = [...host.querySelectorAll('.pane')];
  const fallback = panes.length ? 1 / panes.length : 1;
  panes.forEach((pane) => {
    const px = Math.max(MIN_PANE_W, paneShare(pane.dataset.pane, fallback) * available);
    pane.style.flex = `1 0 ${Math.round(px)}px`;
  });
  syncRowOverflow();
}

/* 整排是否超出中间栏 —— 用来决定要不要把横向滚动条显形 */
function syncRowOverflow() {
  const body = document.querySelector('.stage-body');
  const host = $('result-panels');
  if (!body || !host) return;
  // 窄屏是纵向堆叠，一栏一行，不存在横向滚动
  if (!splitterVisible()) { body.classList.remove('pan-x'); return; }
  const parts = host.querySelectorAll('.pane, .pane-gutter');
  let need = 0;
  parts.forEach((el) => { need += el.getBoundingClientRect().width; });
  const over = !host.hidden && need > body.clientWidth + 1;
  body.classList.toggle('pan-x', over);
}

/* 两栏之间的拖动条 */
function makePaneGutter(leftKey, rightKey) {
  const gutter = document.createElement('div');
  gutter.className = 'pane-gutter';
  gutter.title = '拖动调整左右两栏宽度（可以拖到超出中间栏，双击恢复这两栏均分）';

  let dragging = false;

  gutter.addEventListener('pointerdown', (e) => {
    const width = paneAvailableWidth();
    if (!width) return;
    e.preventDefault();
    dragging = true;

    const startX = e.clientX;
    const minShare = MIN_PANE_W / width;
    const fallback = state.selected.size ? 1 / state.selected.size : 0.25;
    const startLeft = paneShare(leftKey, fallback);
    const startRight = paneShare(rightKey, fallback);
    const pairTotal = startLeft + startRight;   // 这一对的份额之和

    gutter.classList.add('active');
    document.body.classList.add('dragging');
    gutter.setPointerCapture?.(e.pointerId);

    const onMove = (ev) => {
      let left = startLeft + (ev.clientX - startX) / width;
      // 先把左栏夹到下限，再让右栏吃剩下的；
      // 右栏也到下限后就只能让份额之和变大 —— 整排溢出，横向滚动查看。
      left = Math.max(left, minShare);
      const right = Math.max(pairTotal - left, minShare);
      state.paneShares.set(leftKey, left);
      state.paneShares.set(rightKey, right);
      applyPaneLayout();
    };

    const stop = () => {
      if (!dragging) return;
      dragging = false;
      gutter.classList.remove('active');
      document.body.classList.remove('dragging');
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', stop);
      window.removeEventListener('pointercancel', stop);
    };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', stop);
    window.addEventListener('pointercancel', stop);
  });

  // 双击：这两栏回到默认的 1/n 均分。
  // 注意不是取两者平均 —— 那样只会内部重分配，撑大的总宽度回不去。
  // 归位到 1/n 会把这一对多占的宽度还回去，逐根双击就能完全恢复刚铺满的样子。
  gutter.addEventListener('dblclick', () => {
    const n = state.selected.size || 1;
    const base = 1 / n;
    state.paneShares.set(leftKey, base);
    state.paneShares.set(rightKey, base);
    applyPaneLayout();
  });

  return gutter;
}

/* 整排超宽时，按住中键或 Alt+左键拖动就能左右平移。
   普通左键拖动留给选中文字 —— 报告正文要能复制出来。 */
function bindRowPan() {
  const body = document.querySelector('.stage-body');
  if (!body) return;

  let panning = false;
  let startX = 0;
  let startScroll = 0;

  body.addEventListener('pointerdown', (e) => {
    const wantPan = e.button === 1 || (e.button === 0 && e.altKey);
    if (!wantPan || !body.classList.contains('pan-x')) return;
    e.preventDefault();                    // 同时压掉中键的自动滚动
    panning = true;
    startX = e.clientX;
    startScroll = body.scrollLeft;
    body.classList.add('panning');
    body.setPointerCapture?.(e.pointerId);
  });

  body.addEventListener('pointermove', (e) => {
    if (!panning) return;
    body.scrollLeft = startScroll - (e.clientX - startX);
  });

  const stop = () => {
    if (!panning) return;
    panning = false;
    body.classList.remove('panning');
  };
  body.addEventListener('pointerup', stop);
  body.addEventListener('pointercancel', stop);
  window.addEventListener('blur', stop);
  window.addEventListener('resize', applyPaneLayout);
}

/* 一个维度一个 .pane，栏与栏之间插一根可拖动的分隔条 */
function renderPanes() {
  const host = $('result-panels');
  const result = state.lastResult;

  // 初始页：还没生成过时必然停在这里；有结果但用户点了「初始页」也回到这里
  if (!result || state.startView) {
    host.innerHTML = '';
    host.hidden = true;
    $('stage-intro').hidden = false;
    applyEmptyView();          // 引导文字 + 四个框，常驻初始页
    $('panes-empty').hidden = true;
    syncStartToggle();
    return;
  }

  const specs = paneSpecs();
  // 有结果了：初始页整块让位给报告。
  // 顺带把里面两个空状态视图也收起来——它们整块已被隐藏，但标记留着
  // 下次回到初始页时才会「莫名其妙」地少一块内容。
  $('stage-intro').hidden = true;
  $('placeholder').hidden = true;
  $('dims-intro').hidden = true;
  host.hidden = specs.length === 0;
  $('panes-empty').hidden = specs.length > 0;
  host.innerHTML = '';

  specs.forEach(({ key, title, body }, index) => {
    if (index > 0) host.appendChild(makePaneGutter(specs[index - 1].key, key));

    const pane = document.createElement('article');
    pane.className = 'pane';
    pane.dataset.pane = key;
    pane.id = `pane-${key}`;

    const h3 = document.createElement('h3');
    h3.textContent = title;

    const pre = document.createElement('pre');
    pre.textContent = body;
    pane.append(h3, pre);

    // 综合结论已移除；这里只剩四个维度，各自带自己那一段正文
    host.appendChild(pane);
  });

  applyPaneLayout();
  syncStartToggle();
}

function renderResult(result) {
  state.lastResult = result;
  state.startView = false;       // 有新结果 / 刚点开一份历史报告 → 直接看报告，不停在初始页
  renderPanes();
  syncSaveAction(result);        // 有结果才亮出左栏的「保存报告到本地」
  const body = document.querySelector('.stage-body');
  if (body) { body.scrollTop = 0; body.scrollLeft = 0; }
  $('result-path').textContent = result.result_path || '';
}

/* 维度开关：生成时四个维度一次跑完（不传 dimensions），
   这里的按钮只决定中栏显示哪几个。默认都不显示，点哪个出哪个。 */
function buildDimensionPicker() {
  const host = $('dimension-picker');
  host.innerHTML = '';
  state.selected = new Set();
  state.paneShares = new Map();      // 空 Map → 份额均为 1/n，正好铺满

  DIMENSIONS.forEach(({ key, title }) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'dim-btn';
    btn.dataset.dim = key;

    const mark = document.createElement('span');
    mark.className = 'mark';

    const label = document.createElement('span');
    label.className = 'label';
    label.textContent = title;

    const status = document.createElement('span');
    status.className = 'state';

    btn.append(mark, label, status);
    btn.addEventListener('click', () => toggleDimension(key));
    host.appendChild(btn);
  });
  syncDimensionPicker();
}

function toggleDimension(key) {
  if (state.selected.has(key)) state.selected.delete(key);
  else state.selected.add(key);
  syncDimensionPicker();
  renderPanes();   // 已生成过就立即重排；未生成时空跑一次，无副作用
}

function syncDimensionPicker() {
  $('dimension-picker').querySelectorAll('.dim-btn').forEach((btn) => {
    const on = state.selected.has(btn.dataset.dim);
    btn.classList.toggle('on', on);
    btn.querySelector('.mark').textContent = on ? '✓' : '○';
    btn.querySelector('.state').textContent = on ? '显示' : '隐藏';
    // 窄栏会隐藏文字状态，用原生 tooltip 兜底
    btn.title = on
      ? `${dimTitle(btn.dataset.dim)}：正在中栏显示。点击隐藏。`
      : `${dimTitle(btn.dataset.dim)}：隐藏中。点击显示。`;
  });
}

async function generateReport() {
  const ticker = $('ticker').value.trim();
  const problem = tickerProblem(ticker);
  if (problem) { toast(problem, 'err'); updateTickerHint(); return; }

  const btn = $('generate');
  btn.disabled = true;
  btn.textContent = '生成中…';
  try {
    // 不传 dimensions：后端用配置里的全部四维度，一次跑完
    const payload = {
      ticker,
      company: $('company').value.trim(),
      report_date: $('report_date').value,
    };

    const r = await api('/api/reports', { method: 'POST', body: JSON.stringify(payload) });
    renderResult(r);
    // 新报告已由后端落盘，刷新初始页的历史列表（失败也不影响，只是列表没变）
    loadHistory();
    // 把实际用的 provider / 模型报出来："我明明选了 X 却跑出 Y" 这类问题一眼可查
    toast(
      `已用 ${r.provider} 生成四个维度（${r.model || '默认模型'}）；点左侧按钮切换显示哪几个`,
      ''
    );
  } catch (err) {
    toast(`生成失败：${err.message}`, 'err');
    state.lastResult = null;
    syncSaveAction(null);        // 收起保存区：失败后还能点保存就会存到上一次的旧报告
    // 失败是「有内容」的一屏，初始页（含历史列表）整块让位给错误面板
    $('stage-intro').hidden = true;
    $('placeholder').hidden = true;
    $('dims-intro').hidden = true;
    $('panes-empty').hidden = true;
    const host = $('result-panels');
    host.hidden = false;
    host.innerHTML = '<article class="pane"><h3>生成失败</h3><pre></pre></article>';
    host.querySelector('pre').textContent = err.message;
    $('result-path').textContent = '';
  } finally {
    btn.disabled = false;
    btn.textContent = '生成分析';
  }
}

// ---------------------------------------------------------------- 保存到本地
/* 文件名：代码_基准日_分析报告.md。
   代码和日期都来自用户输入，Windows 文件名不允许 \ / : * ? " < > | 与换行，
   统一换成下划线——否则浏览器会静默丢弃这次下载，看起来像按钮没反应。 */
function safeFilePart(text) {
  return String(text || '').trim().replace(/[\\/:*?"<>|\s]+/g, '_').slice(0, 60);
}

function reportFileName(result) {
  const ticker = safeFilePart(result.ticker || $('ticker').value) || 'report';
  const date = safeFilePart(result.report_date || $('report_date').value) || 'undated';
  return `${ticker}_${date}_分析报告.md`;
}

/* 优先用后端拼好的整篇 markdown；万一为空（旧结果或只跑了子集），
   就用「综合结论 + 各维度正文」自己拼一份，保证按钮点了总有东西落地。 */
function reportMarkdown(result) {
  const full = String(result.markdown || '').trim();
  if (full) return full;
  const parts = [];
  if (String(result.conclusion || '').trim()) {
    parts.push(`## 综合结论\n\n${String(result.conclusion).trim()}`);
  }
  const reports = result.reports || {};
  DIMENSIONS.forEach(({ key, title }) => {
    const text = String(reports[key] || '').trim();
    if (text) parts.push(`## ${title}\n\n${text}`);
  });
  return parts.join('\n\n---\n\n');
}

/* 纯前端下载：Blob + 临时 <a download>，不经过后端。
   好处是生成完就能存，断网/后端停了也不影响手里这份结果。 */
function saveReport() {
  const result = state.lastResult;
  if (!result) { toast('还没有可保存的结果，先点「生成分析」', 'err'); return; }

  const text = reportMarkdown(result);
  if (!text) { toast('这份结果里没有可保存的正文', 'err'); return; }

  const name = reportFileName(result);
  const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // 立刻 revoke 在部分浏览器（Safari）会取消下载，延迟释放更稳
  setTimeout(() => URL.revokeObjectURL(url), 4000);
  toast(`已保存到本地：${name}`, 'ok');
}

/* 保存区只在「有结果的正文」时出现。
   生成失败必须收起来——否则存下去的是上一次的旧报告，极易误用。 */
function syncSaveAction(result) {
  const box = $('save-action');
  if (!box) return;
  const has = !!(result && reportMarkdown(result));
  box.hidden = !has;
  $('save-hint').textContent = has ? `将保存：${reportFileName(result)}` : '';
}

// ---------------------------------------------------------------- 四个框说明
/* 四个框直接平铺在初始页上，不再有「信息框 → 四个框」的进出切换。
   保留这个函数是为了统一管理它在各状态下的显隐。 */
function applyEmptyView() {
  $('placeholder').hidden = false;   // 初始页一直显示这段引导文字
  $('dims-intro').hidden = false;    // 四个框同理，常驻
}

/* 四个框按 DIMENSIONS 表渲染，不在 HTML 里再抄一份维度名 */
function buildDimsIntro() {
  const host = $('dims-grid');
  if (!host) return;
  host.innerHTML = '';
  const ordinals = ['一', '二', '三', '四'];

  DIMENSIONS.forEach(({ key, title, brief, points }, index) => {
    const card = document.createElement('article');
    card.className = 'dim-card';
    card.dataset.dim = key;

    const head = document.createElement('div');
    head.className = 'dim-card-head';
    const no = document.createElement('span');
    no.className = 'no';
    no.textContent = ordinals[index] || String(index + 1);
    const name = document.createElement('h4');
    name.textContent = title;
    head.append(no, name);

    const briefEl = document.createElement('p');
    briefEl.className = 'brief';
    briefEl.textContent = brief || '';

    const list = document.createElement('ul');
    list.className = 'points';
    (points || []).forEach((point) => {
      const li = document.createElement('li');
      li.textContent = point;
      list.appendChild(li);
    });

    card.append(head, briefEl, list);
    host.appendChild(card);
  });
}

// ---------------------------------------------------------------- 历史记录
/* 每次生成都会由后端自动落盘（results_dir，默认项目目录下的 .local/logs）。
   初始页把这些已保存的报告按「代码 / 名称 / 时间」列出来：点开可重新查看，右侧可删除。 */
async function loadHistory() {
  try {
    state.history = await api('/api/history');
    renderHistory();
  } catch (err) {
    toast(`历史记录读取失败：${err.message}`, 'err');
  }
}

/* 时间用后端给的保存时间（saved_at），基准日另标一格：
   两者可能不同——同一份基准日的报告再跑一次，文件名不变而保存时间会刷新。 */
function renderHistory() {
  const list = $('history-list');
  const data = state.history || {};
  const items = data.reports || [];

  $('history-dir').textContent = data.dir ? `保存目录：${data.dir}` : '';
  $('history-empty').hidden = items.length > 0;
  list.hidden = items.length === 0;
  list.innerHTML = '';

  items.forEach((item) => {
    const row = document.createElement('li');
    row.className = 'history-item';

    const open = document.createElement('button');
    open.type = 'button';
    open.className = 'history-open';
    open.title = `点开查看这份报告（保存于 ${item.saved_at}）`;

    const code = document.createElement('span');
    code.className = 'code mono';
    code.textContent = item.ticker;

    const name = document.createElement('span');
    name.className = 'name';
    name.textContent = item.name || item.ticker;

    const date = document.createElement('span');
    date.className = 'date mono';
    date.textContent = `基准日 ${item.report_date}`;

    const time = document.createElement('span');
    time.className = 'time mono';
    time.textContent = `保存于 ${item.saved_at}`;

    open.append(code, name, date, time);
    open.addEventListener('click', () => openHistoryItem(item));

    const del = document.createElement('button');
    del.type = 'button';
    del.className = 'history-del';
    del.textContent = '删除';
    del.title = `删除 ${item.ticker} 基准日 ${item.report_date} 的已保存报告（磁盘文件一并删除）`;
    del.addEventListener('click', () => deleteHistoryItem(item));

    row.append(open, del);
    list.appendChild(row);
  });
}

/* 读回落盘原文并显示。后端 GET /api/reports 回的是文件里那份结构
   （company + reports + markdown …），这里整理成与「生成」同形的字段，
   好让中栏复用同一套渲染与「保存到本地」逻辑。 */
async function openHistoryItem(item) {
  const url = `/api/reports/${encodeURIComponent(item.ticker)}/${encodeURIComponent(item.report_date)}`;
  try {
    const saved = await api(url);
    const company = saved.company || {};
    renderResult({
      ticker: company.ticker || item.ticker,
      company_name: company.name || item.name,
      report_date: company.report_date || item.report_date,
      market: company.market || item.market || '',
      provider: '已保存',
      model: '',
      reports: saved.reports || {},
      conclusion: saved.conclusion || '',
      analysis_document: saved.analysis_document || '',
      markdown: saved.markdown || '',
      disclaimer: saved.disclaimer || '',
      guardrail: saved.guardrail || {},
      capital: saved.capital || {},
      valuation: saved.valuation || {},
      trace: saved.trace || [],
      result_path: item.path || '',
    });
    toast(`已打开已保存报告：${item.ticker}（基准日 ${item.report_date}）`, 'ok');
  } catch (err) {
    toast(`打开失败：${err.message}`, 'err');
    loadHistory();      // 可能已被别处删掉，刷新列表
  }
}

async function deleteHistoryItem(item) {
  const label = `${item.ticker}（${item.name || item.ticker}）基准日 ${item.report_date}`;
  if (!confirm(`删除已保存报告 ${label}？磁盘上的文件会一并删除，且不可撤销。`)) return;
  const url = `/api/history/${encodeURIComponent(item.ticker)}/${encodeURIComponent(item.report_date)}`;
  try {
    await api(url, { method: 'DELETE' });
    toast(`已删除：${label}`, 'ok');
    await loadHistory();
  } catch (err) {
    toast(`删除失败：${err.message}`, 'err');
  }
}

/* 标题栏的「初始页 / 返回结果」开关：没有结果时它没有意义，直接收起 */
function syncStartToggle() {
  const btn = $('start-toggle');
  if (!btn) return;
  const result = state.lastResult;
  btn.hidden = !result;
  if (!result) return;
  const atStart = !!state.startView;
  btn.textContent = atStart ? '返回结果' : '初始页';
  btn.title = atStart ? '回到刚打开的那份报告' : '回到初始页：已保存分析 + 维度说明';
}

// ---------------------------------------------------------------- 绑定
function bindEvents() {
  $('llm_provider').addEventListener('change', (e) => applyProviderDefaults(e.target.value));
  $('backend_url').addEventListener('input', () => updateUrlHint($('llm_provider').value));
  $('save-config').addEventListener('click', saveConfig);
  $('test-config').addEventListener('click', testConfig);
  $('clear-key').addEventListener('click', clearKey);
  $('reset-config').addEventListener('click', resetConfig);
  $('generate').addEventListener('click', generateReport);
  $('save-report').addEventListener('click', saveReport);
  // 标题栏的「初始页 ↔ 返回结果」：只切视图，不动 state.lastResult
  $('start-toggle').addEventListener('click', () => {
    state.startView = !state.startView;
    renderPanes();
  });
  $('history-refresh').addEventListener('click', loadHistory);
  $('ticker').addEventListener('input', updateTickerHint);
  $('toggle-key').addEventListener('click', () => {
    const input = $('api_key');
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    $('toggle-key').textContent = show ? '隐藏' : '显示';
  });
}

// ---------------------------------------------------------------- 分隔条拖动
/* 两根分隔条：左栏↔中栏、中栏↔豆包栏。都用 pointer 事件，
   鼠标 / 触摸屏 / 手写笔一套代码都能拖。

   记忆的是「占应用宽度的比例」而不是像素：窗口变大变小后按比例重算，
   否则存下来的固定像素宽度会在小窗口里把中栏挤爆（这是很容易踩的坑）。 */
const MIN_SIDEBAR_W = 180;
const MIN_STAGE_W = 340;
const MIN_DOUBAO_W = 220;
const SIDEBAR_RATIO_KEY = 'ba_sidebar_ratio';
const DOUBAO_RATIO_KEY = 'ba_doubao_ratio';
const FALLBACK_SPLITTER_W = 6;

function splitterVisible() {
  const splitter = $('splitter');
  return !!splitter && getComputedStyle(splitter).display !== 'none';
}

/* 当前可见的分隔条总宽度（堆叠模式下 display:none，offsetParent 为 null） */
function splitterWidth() {
  return [...document.querySelectorAll('.splitter')]
    .filter((el) => el.offsetParent !== null)
    .reduce((sum, el) => sum + (el.getBoundingClientRect().width || FALLBACK_SPLITTER_W), 0);
}

/* 一次量齐当前布局，夹取上下限时要用到相邻两栏的实时宽度 */
function layoutWidths() {
  const widthOf = (sel) => {
    const el = document.querySelector(sel);
    return el ? el.getBoundingClientRect().width : 0;
  };
  return {
    app: widthOf('#app'),
    sidebar: widthOf('.sidebar'),
    stage: widthOf('.stage'),
    doubao: widthOf('.doubao-col'),
    splitter: splitterWidth(),
  };
}

function clampSidebarWidth(width) {
  const L = layoutWidths();
  if (!L.app) return width;
  // 右边界：给中栏和豆包栏留够最低宽度
  const max = Math.max(MIN_SIDEBAR_W, L.app - L.splitter - L.doubao - MIN_STAGE_W);
  return Math.min(Math.max(width, MIN_SIDEBAR_W), max);
}

function clampDoubaoWidth(width) {
  const L = layoutWidths();
  if (!L.app) return width;
  const max = Math.max(MIN_DOUBAO_W, L.app - L.splitter - L.sidebar - MIN_STAGE_W);
  return Math.min(Math.max(width, MIN_DOUBAO_W), max);
}

function setVarWidth(name, width) {
  const app = $('app');
  if (app) app.style.setProperty(name, `${Math.round(width)}px`);
}

function savedRatio(key) {
  try {
    const r = parseFloat(localStorage.getItem(key));
    return r > 0 && r < 1 ? r : 0;
  } catch { return 0; }
}

/* 清掉内联覆盖，回到 CSS 里 clamp() 定好的默认比例 */
function resetSide(side) {
  const app = $('app');
  const varName = side === 'left' ? '--sidebar-w' : '--doubao-w';
  const key = side === 'left' ? SIDEBAR_RATIO_KEY : DOUBAO_RATIO_KEY;
  app.style.removeProperty(varName);
  try {
    localStorage.removeItem(key);
    localStorage.removeItem('ba_doubao_w');   // 旧版本留下的键，顺手清掉
  } catch { /* 忽略 */ }
}

/* 绑定一根分隔条：side='left' 改左栏宽，side='right' 改豆包栏宽。
   中栏是 flex:1，自动吸收剩余宽度。 */
function bindSplitter(splitter, side) {
  if (!splitter) return;

  let dragging = false;
  let dragX = 0;

  const apply = () => {
    const appRect = $('app').getBoundingClientRect();
    const offset = dragX - appRect.left;                  // 分隔条左边缘距应用左边
    const sw = splitter.getBoundingClientRect().width || FALLBACK_SPLITTER_W;
    if (side === 'left') {
      setVarWidth('--sidebar-w', clampSidebarWidth(offset));
    } else {
      setVarWidth('--doubao-w', clampDoubaoWidth(appRect.width - offset - sw));
    }
  };

  splitter.addEventListener('pointerdown', (e) => {
    if (!splitterVisible()) return;
    e.preventDefault();
    dragging = true;
    dragX = e.clientX;
    splitter.classList.add('active');
    document.body.classList.add('dragging');
    // 捕获指针：鼠标划过豆包 iframe 也不会丢事件（触摸拖动同样受益）
    splitter.setPointerCapture?.(e.pointerId);
  });

  window.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    dragX = e.clientX;
    apply();
  });

  const stop = () => {
    if (!dragging) return;
    dragging = false;
    splitter.classList.remove('active');
    document.body.classList.remove('dragging');
    const L = layoutWidths();
    if (L.app > 0) {
      const key = side === 'left' ? SIDEBAR_RATIO_KEY : DOUBAO_RATIO_KEY;
      const value = side === 'left' ? L.sidebar : L.doubao;
      try { localStorage.setItem(key, String(value / L.app)); } catch { /* 忽略 */ }
    }
  };
  window.addEventListener('pointerup', stop);
  window.addEventListener('pointercancel', stop);
  window.addEventListener('blur', stop);   // 拖到窗口外松手时收不到 pointerup，兜底

  // 双击分隔条 = 恢复该侧默认比例
  splitter.addEventListener('dblclick', () => resetSide(side));
}

/* 按保存的比例重算两栏像素宽（窗口尺寸变了要重来一次，避免固定像素溢出） */
function restoreSplitterSizes() {
  if (!splitterVisible()) return;
  const app = $('app');
  if (!app) return;
  const appW = app.getBoundingClientRect().width;
  if (!appW) return;
  const sidebarRatio = savedRatio(SIDEBAR_RATIO_KEY);
  if (sidebarRatio) setVarWidth('--sidebar-w', clampSidebarWidth(appW * sidebarRatio));
  const doubaoRatio = savedRatio(DOUBAO_RATIO_KEY);
  if (doubaoRatio) setVarWidth('--doubao-w', clampDoubaoWidth(appW * doubaoRatio));
}

function setupSplitters() {
  if (!$('app')) return;
  bindSplitter($('splitter-left'), 'left');
  bindSplitter($('splitter'), 'right');

  window.addEventListener('resize', restoreSplitterSizes);
  restoreSplitterSizes();
}

// ---------------------------------------------------------------- 视口读数
/* 显示 CSS 像素宽度，用来解释「为什么变成上下堆叠了」。
   浏览器窗口的物理宽度会被 Windows 显示缩放（125%/150%）和浏览器缩放除掉：
   1920 的屏幕 @150% 只有 1280 CSS px，@200% 只剩 960。 */
const STACK_BREAKPOINT = 600;   // 与 CSS 的 @media (max-width: 600px) 保持一致

function showViewportInfo() {
  const el = $('viewport-info');
  if (!el) return;
  const wide = window.innerWidth > STACK_BREAKPOINT;
  el.textContent = `视口 ${window.innerWidth}×${window.innerHeight}`;
  el.title = wide
    ? 'CSS 像素宽度。已按三栏并排显示。'
    : `CSS 像素宽度。≤ ${STACK_BREAKPOINT}px 时自动改为上下堆叠；`
      + '窗口拉宽，或在浏览器里按 Ctrl+0 复位缩放即可回到三栏。';
}

// ---------------------------------------------------------------- 启动
(async function init() {
  $('report_date').value = new Date().toISOString().slice(0, 10);
  buildDimensionPicker();
  buildDimsIntro();
  syncSaveAction(null);        // 打开页面时没有结果，保存区保持收起
  updateTickerHint();
  setupSplitters();
  bindRowPan();
  showViewportInfo();
  window.addEventListener('resize', showViewportInfo);
  bindEvents();
  syncStartToggle();
  try {
    // 初始页要列出历史记录，必须拉一次；失败只提示，不挡住其它初始化
    await loadHistory();
    await loadProviders();
    const cfg = await loadConfig();
    if (!cfg.api_key_set && cfg.llm_provider !== 'mock') {
      toast('提示：尚未保存 API Key，可先填 Key 再点「测试连通性」', '');
    }
  } catch (err) {
    toast(`初始化失败：${err.message}`, 'err');
  }
})();

