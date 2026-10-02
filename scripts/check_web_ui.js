/* 前端改动验证：用极简 DOM 桩在 Node 里跑真实的 app.js，检查
   ① 左栏保存区随结果出现/收起 ② 保存到本地生成的文件名与内容
   ③ 初始页四个框常驻（无信息框入口） ④ 四个框按维度表渲染 4 张卡片
   ⑤ 历史记录渲染 / 打开 / 删除  ⑥ 初始页 ↔ 结果 双向切换

   用法：node scripts/check_web_ui.js
   路径按本文件位置推导（scripts/ 的上一级是项目根），换机器/换盘符都能跑。 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const WEB = path.join(__dirname, '..', 'banalyse', 'web', 'static');
const appJs = fs.readFileSync(path.join(WEB, 'app.js'), 'utf8');
const html = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8');
const css = fs.readFileSync(path.join(WEB, 'style.css'), 'utf8');

// ---------------------------------------------------------------- DOM 桩
const blobs = [];
let createdAnchors = 0;

function makeEl(tag = 'div') {
  const el = {
    tagName: tag.toUpperCase(),
    children: [],
    textContent: '',
    innerHTML: '',
    className: '',
    hidden: false,
    value: '',
    type: '',
    title: '',
    href: '',
    download: '',
    dataset: {},
    style: { setProperty() {}, removeProperty() {} },
    offsetParent: null,
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    appendChild(child) { this.children.push(child); return child; },
    append(...nodes) { this.children.push(...nodes); },
    remove() {},
    addEventListener() {},
    setPointerCapture() {},
    querySelector() { return makeEl(); },
    querySelectorAll() { return []; },
    getBoundingClientRect: () => ({ width: 0, height: 0, left: 0, top: 0 }),
    focus() {},
    click() { if (tag === 'a') createdAnchors += 1; },
  };
  return el;
}

const byId = new Map();
const getEl = (id) => {
  if (!byId.has(id)) {
    const el = makeEl('div');
    el.id = id;
    if (['llm_provider', 'output_language'].includes(id)) el.value = 'mock';
    if (id === 'ticker') el.value = '600519';
    byId.set(id, el);
  }
  return byId.get(id);
};

global.document = {
  getElementById: getEl,
  createElement: (tag) => makeEl(tag),
  querySelector: () => makeEl(),
  querySelectorAll: () => [],
  body: makeEl('body'),
};
global.window = { addEventListener() {}, removeEventListener() {}, innerWidth: 1400, innerHeight: 900 };
global.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
global.getComputedStyle = () => ({ display: 'flex' });
global.setTimeout = setTimeout;
// /api/reports 故意返回失败，用来验证「生成失败」分支的界面状态
global.fetch = (url) => {
  if (String(url).includes('/api/reports')) {
    return Promise.resolve({ ok: false, status: 500, json: async () => ({ detail: '模拟失败' }) });
  }
  return Promise.resolve({ ok: true, json: async () => ({ providers: [] }) });
};
global.URL = { createObjectURL: () => 'blob:stub', revokeObjectURL() {} };
global.Blob = class {
  constructor(parts, opts) { this.parts = parts; this.type = (opts || {}).type; blobs.push(this); }
};

// ---------------------------------------------------------------- 载入真实的 app.js
vm.runInThisContext(appJs, { filename: 'app.js' });
const run = (expr) => vm.runInThisContext(expr);

const checks = [];
const ok = (name, cond, extra = '') => checks.push({ name, pass: !!cond, extra });

// ① 文件名与正文
ok('文件名（A 股）', run("reportFileName({ticker:'600519', report_date:'2026-09-30'})") === '600519_2026-09-30_分析报告.md',
  run("reportFileName({ticker:'600519', report_date:'2026-09-30'})"));
ok('文件名过滤非法字符', run("reportFileName({ticker:'BRK/B', report_date:'2026-09-30'})") === 'BRK_B_2026-09-30_分析报告.md',
  run("reportFileName({ticker:'BRK/B', report_date:'2026-09-30'})"));
ok('优先用后端 markdown', run("reportMarkdown({markdown:'# 全文'})") === '# 全文');
ok('markdown 为空时用结论+维度拼',
  /## 综合结论/.test(run("reportMarkdown({conclusion:'提纲', reports:{business_model:'正文A'}})"))
  && /## 商业模式/.test(run("reportMarkdown({conclusion:'提纲', reports:{business_model:'正文A'}})")));

// ② 保存区显隐
run('syncSaveAction(null)');
ok('无结果 → 保存区收起', getEl('save-action').hidden === true);
run("syncSaveAction({ticker:'600519', report_date:'2026-09-30', markdown:'# 正文'})");
ok('有结果 → 保存区出现', getEl('save-action').hidden === false);
ok('保存提示写明文件名', String(getEl('save-hint').textContent).includes('600519_2026-09-30_分析报告.md'),
  getEl('save-hint').textContent);
run("syncSaveAction({ticker:'600519', markdown:'   '})");
ok('空正文 → 保存区仍收起', getEl('save-action').hidden === true);

// ③ 点击保存 → 真的产出 Blob + <a download>
run("state.lastResult = {ticker:'600519', report_date:'2026-09-30', markdown:'# 报告正文'}; saveReport()");
ok('保存生成了 Blob', blobs.length === 1 && blobs[0].parts[0] === '# 报告正文');
ok('Blob 类型为 markdown', String(blobs[0].type).startsWith('text/markdown'));
ok('触发了下载（<a> 被点击）', createdAnchors === 1);
ok('保存后有 toast 提示', String(getEl('toast').textContent).includes('已保存到本地'),
  getEl('toast').textContent);

// ④ 四个框常驻初始页（不再有「信息框 → 四个框」的点击切换）
run('applyEmptyView()');
ok('引导文字常驻', getEl('placeholder').hidden === false);
ok('四个框常驻、无需点开', getEl('dims-intro').hidden === false);
ok('页面里已无信息框入口', !html.includes('id="open-dims"') && !html.includes('id="close-dims"'));
ok('app.js 里不再有 showDimsIntro', !appJs.includes('showDimsIntro'));

// ⑤ 四个框渲染：4 张卡片，标题来自维度表
const grid = getEl('dims-grid');
ok('四个框渲染出 4 张卡片', grid.children.length === 4, `children=${grid.children.length}`);
// 卡片结构：card > [head(no+h4), brief(p), points(ul)]，标题在 head 里
const titles = grid.children.map((card) => {
  const head = card.children.find((x) => x.tagName === 'DIV') || { children: [] };
  const h4 = head.children.find((x) => x.tagName === 'H4') || {};
  return h4.textContent;
});
ok('卡片标题正确', JSON.stringify(titles) === JSON.stringify(['商业模式', '管理层', '财务状况', '安全边际']),
  JSON.stringify(titles));
const pointCounts = grid.children.map((card) => {
  const ul = card.children.find((x) => x.tagName === 'UL') || { children: [] };
  return ul.children.length;
});
ok('每张卡片都有要点清单', pointCounts.every((n) => n >= 3), JSON.stringify(pointCounts));
run("state.lastResult = {ticker:'600519', report_date:'2026-09-30', markdown:'# x'}; renderPanes()");
ok('生成后空状态两个视图都隐藏',
  getEl('placeholder').hidden === true && getEl('dims-intro').hidden === true);
run('state.lastResult = null; renderPanes()');
ok('回到初始页后四个框自动回来',
  getEl('dims-intro').hidden === false && getEl('placeholder').hidden === false);

// ⑥ 静态资源确实带上了新标记
ok('index.html 含四个框与保存按钮（且无信息框）',
  ['id="dims-intro"', 'id="dims-grid"', 'id="save-report"', 'id="save-action"']
    .every((needle) => html.includes(needle)));
ok('style.css 含新样式类',
  ['.dims-grid', '.dim-card', '.btn-sm', '.history-item'].every((needle) => css.includes(needle))
  && !css.includes('.intro-card'));

// ---------------------------------------------------------------- 结果
(async () => {
  // ⑦ 生成失败：错误面板出现，初始页（含四个框、历史列表）与保存区都必须收起
  run("state.lastResult = {ticker:'600519', markdown:'# 旧报告'}; syncSaveAction(state.lastResult)");
  await run("generateReport()");                    // 内部会走 catch 分支
  ok('失败后四个框收起', getEl('dims-intro').hidden === true);
  ok('失败后信息框不出现', getEl('placeholder').hidden === true);
  ok('失败后保存区收起（不会存到旧报告）', getEl('save-action').hidden === true);
  ok('失败后 state.lastResult 清空', run('state.lastResult') === null);
  const errPane = getEl('result-panels');
  ok('失败后中栏显示错误面板', errPane.hidden === false && String(errPane.innerHTML).includes('生成失败'));
  ok('失败后初始页整块收起（含历史列表）', getEl('stage-intro').hidden === true);

  // ⑧ 历史记录：按「代码 / 名称 / 时间」渲染，可打开、可删除
  const hist = {
    dir: 'D:/proj/.local/logs',
    reports: [
      { ticker: '600519', name: '贵州茅台', report_date: '2026-09-30', saved_at: '2026-09-30 10:12:00', path: 'a.json' },
      { ticker: 'BRK_B', report_date: '2026-09-30', saved_at: '2026-09-30 11:20:00', path: 'b.json' },
    ],
  };
  run(`state.history = ${JSON.stringify(hist)}; renderHistory()`);
  const hList = getEl('history-list');
  ok('历史列表渲染出 2 条', hList.children.length === 2, `children=${hList.children.length}`);
  ok('历史列表不再显示空提示', getEl('history-empty').hidden === true);
  ok('显示保存目录', String(getEl('history-dir').textContent).includes('.local/logs'));
  const firstRow = hList.children[0];
  const openBtn = firstRow.children[0];
  const texts = openBtn.children.map((c) => String(c.textContent));
  ok('每行含代码/名称/基准日/保存时间',
    texts[0] === '600519' && texts[1] === '贵州茅台'
    && texts[2].includes('2026-09-30') && texts[3].includes('2026-09-30 10:12:00'),
    JSON.stringify(texts));
  ok('每行带删除按钮', !!firstRow.children[1]);
  // 缺名称时回落成代码，不留空白格
  const secondTexts = hList.children[1].children[0].children.map((c) => String(c.textContent));
  ok('缺名称回落为代码', secondTexts[1] === 'BRK_B', JSON.stringify(secondTexts));
  run('state.history = {dir:"",reports:[]}; renderHistory()');
  ok('无记录时列表隐藏、提示出现',
    getEl('history-list').hidden === true && getEl('history-empty').hidden === false);

  // ⑨ 初始页 ↔ 返回结果 开关
  run("state.lastResult = {ticker:'600519', report_date:'2026-09-30', markdown:'# 正文', reports:{business_model:'A'}}; state.startView=false; renderPanes(); syncSaveAction(state.lastResult)");
  ok('有结果后初始页收起', getEl('stage-intro').hidden === true);
  ok('有结果后开关出现且写「初始页」',
    getEl('start-toggle').hidden === false && getEl('start-toggle').textContent === '初始页');
  // 选一个维度，否则 specs 为空 → result-panels 本就该是空的
  run("state.selected = new Set(['business_model']); state.startView = true; renderPanes()");
  ok('切到初始页：容器回来、报告收走',
    getEl('stage-intro').hidden === false && getEl('result-panels').hidden === true);
  ok('切到初始页：按钮变「返回结果」', getEl('start-toggle').textContent === '返回结果');
  run('state.startView = false; renderPanes()');
  ok('切回结果：报告回来、初始页收起',
    getEl('result-panels').hidden === false && getEl('stage-intro').hidden === true);
  run('state.lastResult = null; renderPanes()');
  ok('无结果时开关自动隐藏', getEl('start-toggle').hidden === true);

  let failed = 0;
  checks.forEach(({ name, pass, extra }) => {
    if (!pass) failed += 1;
    console.log(`${pass ? 'PASS' : 'FAIL'}  ${name}${extra ? `  -> ${extra}` : ''}`);
  });
  console.log(`\n${checks.length - failed}/${checks.length} passed`);
  process.exit(failed ? 1 : 0);
})();
