"""Оформление страницы дашборда.

Это содержимое страницы, а не логика её сборки: до выноса ~330 строк CSS лежали
в том же файле, что и рендеринг, и держали его выше любого разумного лимита.
Правка стиля не должна требовать открытия модуля с логикой — и наоборот.
"""

CSS = """\
:root {
  color-scheme: dark;
  --bg: #0b0d10;
  --panel: #15181c;
  --panel-2: #1d2228;
  --panel-3: #252b33;
  --line: #36404a;
  --line-soft: #252b33;
  --text: #e9edf1;
  --muted: #9aa3ad;
  --muted-2: #737d88;
  --green-bg: #123322;
  --green-fg: #8ee0b2;
  --amber-bg: #3b2f10;
  --amber-fg: #f2c766;
  --red-bg: #3b161b;
  --red-fg: #ff9aa8;
  --cyan-bg: #102f35;
  --cyan-fg: #8bdde8;
  --blue-bg: #132437;
  --blue-fg: #9bc8ff;
  /* Базовый кегль тянется за шириной окна: 16px на узком экране, 20px на
     широком (там вид прежний), между ними — плавно. Выбор «20 или 16» был
     ложной дилеммой: 20 удобен для чтения на большом мониторе и слишком крупен
     для дата-плотной страницы в половину экрана. Границы заданы явно и
     проверяются кейсом, поэтому это не «поедет само», а заданный диапазон.
     Опора на rem намеренная: если человек увеличил шрифт в браузере, вырастет
     и наш кегль. На чистых px+vw эта настройка игнорируется — ровно поэтому
     visual-check и запрещал кегль, зависящий от окна. */
  --fs-base: clamp(1rem, 0.875rem + 0.35vw, 1.25rem);
  /* Мелкий текст — доля базы, иначе на узком экране он сравнялся бы с ней. */
  --fs-small: calc(var(--fs-base) * 0.78);
  --fs-h1: 2.0rem;
  --fs-h2: 1.45rem;
  --fs-h3: 1.15rem;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: var(--fs-base);
  line-height: 1.6;
  color: var(--text);
  background: radial-gradient(circle at 15% -10%, rgba(50, 96, 118, .18), transparent 28rem), var(--bg);
  padding: 1rem 2rem;
  max-width: 1680px;
  margin: 0 auto;
}
body.compact section { padding: .7rem .85rem; margin-bottom: .6rem; }
body.compact table { font-size: var(--fs-small); }
body.compact td, body.compact th { padding: 3px 6px; }
body.hide-diagnostics .diagnostic { display: none; }
h1 { font-size: var(--fs-h1); margin-bottom: .2rem; font-weight: 650; letter-spacing: 0; }
h2 {
  font-size: var(--fs-h2);
  margin: 1.25rem 0 .45rem;
  border-bottom: 1px solid var(--line);
  padding-bottom: .25rem;
  color: #f4f6f8;
  letter-spacing: 0;
}
h3 { font-size: var(--fs-h3); margin: .65rem 0 .35rem; color: #d6dbe0; letter-spacing: 0; }
section {
  background: var(--panel);
  border: 1px solid var(--line-soft);
  border-radius: 6px;
  padding: .95rem 1.1rem;
  margin-bottom: .9rem;
}
section:target { border-color: var(--cyan-fg); }
.primary-surface {
  border-color: rgba(139, 221, 232, .24);
  background: linear-gradient(180deg, rgba(31, 37, 43, .98), rgba(21, 24, 28, .98));
}
.topbar {
  position: sticky;
  top: 0;
  z-index: 10;
  background: rgba(14, 15, 17, .94);
  border-bottom: 1px solid var(--line);
  padding: .65rem 0 .55rem;
  margin-bottom: .75rem;
  backdrop-filter: blur(6px);
}
.quick-nav {
  display: flex;
  flex-wrap: wrap;
  gap: .35rem;
  margin-top: .45rem;
}
.quick-nav a {
  color: var(--text);
  text-decoration: none;
  background: var(--panel-2);
  border: 1px solid var(--line);
  border-radius: 4px;
  padding: 3px 8px;
  font-size: var(--fs-small);
}
.quick-nav a:hover { border-color: var(--cyan-fg); color: var(--cyan-fg); }
.command-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: .6rem;
  margin-bottom: .7rem;
}
.metric-card {
  background: var(--panel-2);
  border: 1px solid var(--muted-2);
  border-radius: 6px;
  padding: .6rem .7rem;
}
.metric-card.good { border-color: var(--green-fg); }
.metric-card.warn { border-color: var(--amber-fg); }
.metric-card.bad { border-color: var(--red-fg); }
.metric-card strong { display: block; font-size: 3.0rem; line-height: 1.05; font-weight: 700; color: #f7f9fb; }
.metric-card span { display: block; color: var(--muted); font-size: var(--fs-small); margin-top: .15rem; }
.command-actions {
  display: flex;
  flex-wrap: wrap;
  gap: .4rem;
  margin-top: .35rem;
}
.command-actions a {
  color: var(--cyan-fg);
  text-decoration: none;
  border: 1px solid var(--line);
  border-radius: 4px;
  padding: 3px 8px;
  font-size: var(--fs-small);
}
.command-actions a:hover { border-color: var(--cyan-fg); background: var(--cyan-bg); }
.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: .35rem;
  margin-left: auto;
}
.topbar-row { display: flex; gap: 1rem; align-items: flex-start; justify-content: space-between; }
.task-group { margin-top: .85rem; }
.task-group > h3 { display: flex; align-items: center; gap: .5rem; }
.task-list { display: grid; gap: .5rem; margin-top: .5rem; }
.task-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: .6rem;
  align-items: center;
  border: 1px solid var(--line-soft);
  border-radius: 6px;
  padding: .55rem .7rem;
  background: rgba(0,0,0,.12);
}
/* Приоритет кодируется значком, а не цветной полосой слева: полоса дублировала
   подпись «P1», которая и так стоит в заголовке, и попадала под правило
   side-tab — цветной боковой акцент читается как навигационная закладка,
   хотя никуда не ведёт. На значке цвет стоит рядом с текстом, поэтому работает
   и для тех, кто цвет не различает. */
.task-card.prio-P0 .badge-prio { color: var(--red-fg); border-color: var(--red-fg); }
.task-card.prio-P1 .badge-prio { color: var(--amber-fg); border-color: var(--amber-fg); }
.task-card.prio-P2 .badge-prio { color: var(--cyan-fg); border-color: var(--cyan-fg); }
.task-card.prio-cyclic .badge-prio { color: var(--blue-fg); border-color: var(--blue-fg); }
.badge-prio { border: 1px solid var(--line); font-weight: 650; }
.task-card-title { font-weight: 650; color: #f7f9fb; display: flex; flex-wrap: wrap; gap: .4rem; align-items: baseline; }
.task-card-meta { color: var(--muted); font-size: var(--fs-small); margin-top: .15rem; }
.task-card-meta .error { font-weight: 600; }
.task-card-actions { display: flex; flex-wrap: wrap; gap: .3rem; justify-content: flex-end; align-items: center; }
.task-card-actions select.task-client, .task-card-actions select.task-mode {
  background: #111316; color: var(--text); border: 1px solid var(--line);
  border-radius: 4px; padding: 2px 5px; font: inherit; font-size: var(--fs-small);
}
.task-fold { margin-top: .85rem; }
.task-fold > summary { cursor: pointer; font-size: var(--fs-h3); color: var(--muted); padding: .35rem 0; list-style: none; font-weight: 650; }
.task-fold > summary::-webkit-details-marker { display: none; }
.task-fold > summary:hover { color: var(--cyan-fg); }
.task-fold > summary::before { content: "\\25B8  "; }
.task-fold[open] > summary::before { content: "\\25BE  "; }
.subtle { color: var(--muted); }
.button-primary {
  border-color: rgba(139, 221, 232, .55);
  color: var(--cyan-fg);
  background: var(--cyan-bg);
}
.button-primary:hover { background: #153c44; }
table {
  border-collapse: collapse;
  width: 100%;
  margin-top: .45rem;
  font-size: var(--fs-small);
}
th {
  background: var(--panel-3);
  color: #f1f3f5;
  text-align: left;
  padding: 4px 8px;
  border: 1px solid var(--line);
  font-weight: 600;
}
td {
  padding: 4px 8px;
  border: 1px solid var(--line-soft);
  vertical-align: top;
  color: var(--text);
}
tr:nth-child(even) td { background: rgba(255, 255, 255, .045); }
tr.stale td { background: rgba(255, 80, 105, .12); }
tr.missing td { color: var(--muted-2); }
em { color: var(--muted); }
ul { margin: .35rem 0 0 1rem; color: var(--text); }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: var(--fs-small); }
.small { font-size: var(--fs-small); color: var(--muted); }
code {
  background: #111316;
  border: 1px solid var(--line-soft);
  color: var(--cyan-fg);
  padding: 0 4px;
  border-radius: 3px;
  font-size: var(--fs-small);
}
.badge {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: var(--fs-small);
  font-weight: 650;
  white-space: nowrap;
}
.state-open { background: var(--green-bg); color: var(--green-fg); }
.state-progress { background: var(--amber-bg); color: var(--amber-fg); }
.state-done { background: #163128; color: #a6e8c2; }
.state-blocked { background: var(--red-bg); color: var(--red-fg); }
.stale { background: var(--red-bg); color: var(--red-fg); }
.error { color: var(--red-fg); }
.summary-row { display: flex; flex-wrap: wrap; gap: .45rem; margin-bottom: .65rem; }
.filter-row {
  display: flex;
  flex-wrap: wrap;
  gap: .45rem;
  align-items: end;
  margin: .6rem 0 .75rem;
}
.filter-row label {
  display: grid;
  gap: .2rem;
  color: var(--muted);
  font-size: var(--fs-small);
}
.filter-row input, .filter-row select {
  background: #111316;
  color: var(--text);
  border: 1px solid var(--line);
  border-radius: 4px;
  min-height: 28px;
  padding: 3px 7px;
  font: inherit;
  font-size: var(--fs-small);
}
.secondary-group { margin-top: 1.4rem; border-top: 2px solid var(--line); }
#command-center { margin-bottom: 0; border-bottom-left-radius: 0; border-bottom-right-radius: 0; }
.manual-launch { margin-top: .6rem; }
.manual-launch > summary { cursor: pointer; font-size: var(--fs-h3); color: var(--muted); padding: .5rem 0; list-style: none; }
.manual-launch > summary::-webkit-details-marker { display: none; }
.manual-launch > summary:hover { color: var(--cyan-fg); }
.manual-launch > summary::before { content: "\\25B8  "; }
.manual-launch[open] > summary::before { content: "\\25BE  "; }
.kb-output { margin-top: 1rem; min-height: 2.4rem; padding: .85rem 1.1rem; border: 2px solid var(--cyan-fg); border-radius: 8px; background: #0e1418; color: var(--text); font-size: var(--fs-base); white-space: pre-wrap; line-height: 1.5; }
.kb-output:empty { display: none; }
.secondary-group > summary {
  cursor: pointer;
  font-size: var(--fs-h2);
  font-weight: 650;
  padding: .9rem 0;
  color: var(--muted);
  list-style: none;
}
.secondary-group > summary::-webkit-details-marker { display: none; }
.secondary-group > summary:hover { color: var(--cyan-fg); }
.secondary-group > summary::before { content: "\\25B8  "; }
.secondary-group[open] > summary::before { content: "\\25BE  "; }
.card {
  background: var(--panel-2);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: .5rem .7rem;
  min-width: 116px;
}
.card strong { display: block; font-size: 1.6rem; color: #f7f9fb; }
.provider-card .chain { margin-top: .4rem; font-size: var(--fs-small); color: var(--muted); }
.cards-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: .75rem; }
.actions { min-width: 218px; }
button {
  appearance: none;
  border: 1px solid var(--line);
  background: var(--panel-3);
  color: var(--text);
  border-radius: 4px;
  padding: 3px 7px;
  margin: 1px 2px 1px 0;
  font: inherit;
  font-size: var(--fs-small);
  cursor: pointer;
}
button:hover { border-color: var(--cyan-fg); color: var(--cyan-fg); }
button:disabled { opacity: .55; cursor: wait; }
table.mini { width: auto; font-size: var(--fs-small); margin-top: .25rem; }
table.mini th, table.mini td { padding: 2px 6px; }
.meta { font-size: var(--fs-small); color: var(--muted); margin-bottom: .65rem; }
.search-box { display: flex; gap: .5rem; margin-bottom: .8rem; }
.search-box input { flex: 1; background: #111316; color: var(--text); border: 1px solid var(--line); border-radius: 4px; padding: 4px 10px; font: inherit; }
.search-box select { background: #111316; color: var(--text); border: 1px solid var(--line); border-radius: 4px; padding: 4px; font: inherit; }
@media (max-width: 760px) {
  body { padding: .75rem; }
  section { padding: .8rem; }
  table { display: block; overflow-x: auto; }
  .card { min-width: 0; flex: 1 1 145px; }
  .topbar-row { display: block; }
  .toolbar { margin-top: .45rem; }
  .task-card { grid-template-columns: 1fr; }
  .task-card-actions { justify-content: flex-start; }
}"""


TAB_CSS = """
.tabbar{display:flex;gap:.25rem;flex-wrap:wrap;margin:.5rem 0 .9rem;border-bottom:1px solid var(--line);}
.tab-btn{background:var(--panel-2);color:var(--muted);border:1px solid var(--line);border-bottom:none;border-radius:6px 6px 0 0;padding:.4rem .85rem;cursor:pointer;font:inherit;line-height:1.4;}
.tab-btn:hover{color:#f7f9fb;}
.tab-btn.active{background:var(--panel-3);color:#f7f9fb;border-color:var(--cyan-fg);font-weight:600;box-shadow:inset 0 -2px 0 var(--cyan-fg);}
.tab-add{opacity:.7;}
.tab-panel{display:none;}
.tab-panel.active{display:block;}
.ws-warn{color:var(--amber-fg);margin:.3rem 0;padding-left:1.1rem;}
"""
