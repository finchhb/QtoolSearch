"""src/ui.py - HTML публичного чата (/) и админки (/admin). Всё в одном файле, без внешних скриптов и шрифтов."""

BASE_CSS = r"""
:root{--bg:#f6f7f9;--card:#fff;--text:#1d2430;--muted:#6b7686;--line:#dfe3ea;--accent:#c8102e;--accent2:#1d4ed8;--ok:#15803d;--warn:#b45309;--bad:#b91c1c;--bubble:#eef1f6}
@media (prefers-color-scheme:dark){:root{--bg:#0f141b;--card:#18202b;--text:#e7ecf3;--muted:#93a0b2;--line:#2a3544;--bubble:#202a37}}
*{box-sizing:border-box}html,body{height:100%;margin:0}
body{font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--text);display:flex;flex-direction:column}
a{color:var(--accent2)}code{background:var(--bubble);padding:1px 5px;border-radius:4px;font-size:.92em}
button{font:inherit;cursor:pointer}
"""

CHAT_HTML = r"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Подбор инструмента qtool.ru</title>
<style>__BASE_CSS__
header{padding:12px 16px;background:var(--card);border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center;gap:8px}
header b{font-size:17px}header small{color:var(--muted)}
#adm{display:none;gap:6px;flex-wrap:wrap}#adm a{border:1px solid var(--line);border-radius:8px;padding:5px 10px;color:var(--text);text-decoration:none;font-size:14px}#adm a:hover{border-color:var(--accent2);color:var(--accent2)}
#msgs{flex:1;overflow-y:auto;padding:14px 12px;display:flex;flex-direction:column;gap:12px}
.msg{max-width:860px;width:100%;margin:0 auto;padding:12px 14px;border-radius:12px;background:var(--card);border:1px solid var(--line);overflow-wrap:anywhere}
.msg.user{background:var(--bubble);border-color:transparent;width:auto;margin-left:auto;margin-right:0;max-width:min(560px,92%)}
.msg h3{margin:.6em 0 .3em;font-size:16px}.msg p{margin:.35em 0}.msg ul,.msg ol{margin:.3em 0;padding-left:1.3em}
.msg blockquote{margin:.4em 0;padding:6px 10px;border-left:3px solid var(--warn);background:var(--bubble);border-radius:6px}
.badge.warn{background:#fff3cd;color:#7a4b00}.badge.ok{background:#e3f4e8;color:#14532d}.badge{display:inline-block;font-size:12px;padding:2px 8px;border-radius:99px;background:var(--bubble);color:var(--muted);margin-bottom:6px}
.fb{margin-top:10px;display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.fb button{border:1px solid var(--line);background:transparent;color:var(--text);padding:4px 10px;border-radius:8px}
.fb button.on{border-color:var(--accent2);color:var(--accent2)}
.fb input{flex:1;min-width:160px;border:1px solid var(--line);border-radius:8px;padding:5px 8px;background:var(--card);color:var(--text)}
#chips{max-width:860px;margin:0 auto;display:flex;flex-wrap:wrap;gap:8px}
#chips button{border:1px solid var(--line);background:var(--card);color:var(--text);padding:7px 11px;border-radius:10px;text-align:left}
form{display:flex;gap:8px;padding:10px 12px;background:var(--card);border-top:1px solid var(--line)}
form input{flex:1;font-size:16px;padding:12px 14px;border:1px solid var(--line);border-radius:10px;background:var(--bg);color:var(--text)}
form button{background:var(--accent);color:#fff;border:0;border-radius:10px;padding:0 18px;font-weight:600}
form button.sec{background:transparent;color:var(--muted);border:1px solid var(--line);font-weight:400}
.train{margin-top:10px;border-top:1px dashed var(--line);padding-top:8px;font-size:14px}
.train summary{cursor:pointer;color:var(--accent2)}.train .grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:8px 0}
.train select,.train input,.train textarea{width:100%;padding:6px 8px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--text);font:inherit}
.train textarea{min-height:48px}.train button{background:var(--accent2);color:#fff;border:0;border-radius:8px;padding:7px 14px;margin-top:6px}
.train .hint{color:var(--muted);font-size:13px}.train .ok{color:var(--ok)}.train .sug label{display:inline-block;margin:4px 10px 0 0}
.note{color:var(--muted);font-size:12.5px;max-width:860px;margin:0 auto;padding:0 2px}
</style></head><body>
<header><div><b>Подбор инструмента qtool.ru</b><br><small id="src">загрузка…</small></div><nav id="adm"><a href="/admin#sec-source">📚 Источник</a><a href="/admin#sec-train">🎓 Обучение</a><a href="/admin#sec-rules">📝 Правила</a><a href="/admin#sec-llm" id="llmlink">🤖 LLM</a></nav></header>
<div id="msgs">
  <div class="msg"><p>Опишите задачу или артикул: пластины, сверла, фрезы, метчики, державки, развертки — подберу из каталога qtool.ru.</p></div>
  <div id="chips"></div>
  <div class="note">Подбор справочный. Перед заказом сверьте характеристики и цену в карточке товара.</div>
</div>
<form id="f" autocomplete="off">
  <textarea id="q" rows="2" maxlength="4000" style="resize:vertical;font:inherit" placeholder="Например: CNMG 120408 10 шт; сверло 8,5 мм; фреза концевая 10 мм 3 зуба; метчик М10. Можно несколько позиций — каждая с новой строки (Shift+Enter — перенос)" required></textarea>
  <button type="button" class="sec" id="reset" title="Начать новый подбор">Сброс</button>
  <button type="submit" id="go">Найти</button>
</form>
<script>
const API = (window.ADVISOR_API_BASE || "");
const sid = (() => { try { let s = sessionStorage.getItem("sid"); if (!s) { s = (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2) + Date.now()); sessionStorage.setItem("sid", s); } return s; } catch (e) { return "anon" + Date.now(); } })();
const $ = id => document.getElementById(id);
const esc = s => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const SAFE_URL = /^https:\/\/(www\.)?(qtool\.ru|rinscom\.com)\//;

function inline(t) {
  t = esc(t);
  t = t.replace(/\[([^\]]+)\]\((https:[^)\s]+)\)/g, (m, txt, url) => {
    const u = url.replace(/&amp;/g, "&");
    return SAFE_URL.test(u) ? '<a href="' + esc(u) + '" target="_blank" rel="noopener noreferrer">' + txt + '</a>' : txt;
  });
  return t.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*([^*\n]+)\*/g, "<i>$1</i>");
}
function md(text) {
  const out = []; let list = null;
  const close = () => { if (list) { out.push("</" + list + ">"); list = null; } };
  for (const raw of text.split("\n")) {
    const line = raw.replace(/\s+$/, "");
    let m;
    if (!line.trim()) { close(); continue; }
    if ((m = line.match(/^#{1,4}\s+(.*)/))) { close(); out.push("<h3>" + inline(m[1]) + "</h3>"); continue; }
    if ((m = line.match(/^>\s?(.*)/))) { close(); out.push("<blockquote>" + inline(m[1]) + "</blockquote>"); continue; }
    if ((m = line.match(/^\s*(\d+)\.\s+(.*)/))) { if (list !== "ol") { close(); out.push("<ol>"); list = "ol"; } out.push("<li>" + inline(m[2]) + "</li>"); continue; }
    if ((m = line.match(/^\s*[*-]\s+(.*)/))) { if (list !== "ul") { close(); out.push("<ul>"); list = "ul"; } out.push("<li>" + inline(m[1]) + "</li>"); continue; }
    close(); out.push("<p>" + inline(line) + "</p>");
  }
  close(); return out.join("");
}
function add(cls, html) { const d = document.createElement("div"); d.className = "msg " + cls; d.innerHTML = html; $("msgs").appendChild(d); d.scrollIntoView({ block: "end", behavior: "smooth" }); return d; }

function badge(d) {
  if (d.decision === "site_search" || d.decision === "multi_position") return '<span class="badge">⚡ Детерминированный поиск по каталогу qtool.ru</span>';
  if (d.llm_status === "checked") return '<span class="badge ok">🔍 Проверено LLM-верификатором</span>';
  if (d.llm_status === "unavailable") return '<span class="badge">⚡ Внутренний парсер ISO 1832</span> <span class="badge warn">⚠️ Проверка LLM сейчас недоступна — проверьте параметры вручную</span><br>';
  return '<span class="badge">⚡ Внутренний парсер ISO 1832</span>';
}
let LOCAL_ADMIN = false;
const ISO_OPT = '<option value="">— не менять —</option><option value="P">P — сталь</option><option value="M">M — нержавеющая</option><option value="K">K — чугун</option><option value="N">N — цветные</option><option value="S">S — титан/жаропрочные</option><option value="H">H — закалённые</option>';
const OP_OPT = '<option value="">— не менять —</option><option value="finishing">чистовая</option><option value="semi_finishing">получистовая</option><option value="roughing">черновая</option>';
const SHAPE_OPT = '<option value="">— не менять —</option><option value="C">C — ромб 80°</option><option value="D">D — ромб 55°</option><option value="V">V — ромб 35°</option><option value="E">E — ромб 75°</option><option value="M">M — ромб 86°</option><option value="T">T — треугольник 60°</option><option value="W">W — тригон 80°</option><option value="S">S — квадрат 90°</option><option value="R">R — круглая</option><option value="H">H — шестигранник 120°</option><option value="O">O — восьмигранник</option><option value="P">P — пятигранник</option><option value="L">L — прямоугольная</option><option value="A">A — параллелограмм 85°</option><option value="B">B — параллелограмм 82°</option><option value="K">K — параллелограмм 55°</option>';
const RAD_OPT = '<option value="">— не менять —</option><option>0.2</option><option>0.4</option><option>0.8</option><option>1.2</option><option>1.6</option><option>2.4</option>';
function trainBox(card, query, parsed) {
  const p = parsed || {};
  const det = document.createElement("details"); det.className = "train";
  det.innerHTML = '<summary>🎓 Обучить парсер: указать правильный ответ</summary>' +
    '<div class="hint">Парсер понял: ISO ' + (p.iso || "не определено") + ', обработка ' + (p.operation || "не указана") + (p.shape ? ", форма " + p.shape : "") + (p.size ? ", размер " + p.size : "") + (p.radius != null ? ", радиус " + p.radius : "") + (p.code ? ", код " + p.code : "") + '.</div>' +
    '<div class="grid"><div>Правильная группа ISO<select class="ti">' + ISO_OPT + '</select></div><div>Правильный вид обработки<select class="to">' + OP_OPT + '</select></div></div>' +
    '<div class="grid"><div>Геометрия (форма)<select class="tsh">' + SHAPE_OPT + '</select></div><div>Размер (код кромки)<input class="tz" maxlength="2" placeholder="напр. 12 (из CNMG12…)"></div><div>Радиус вершины, мм<select class="tr">' + RAD_OPT + '</select></div></div>' +
    'Правильные артикулы (через запятую или с новой строки)<textarea class="ts" placeholder="CNMG 120408 DM YBC252"></textarea>' +
    'Комментарий<input class="tc" maxlength="600" placeholder="Что не так / почему так правильно"><button type="button" class="tsave">Сохранить в таблицу</button> <span class="tmsg"></span><div class="sug"></div>';
  card.appendChild(det);
  const g = sel => det.querySelector(sel);
  g(".tsave").onclick = async () => {
    const body = { query, correct_iso: g(".ti").value, correct_operation: g(".to").value, correct_shape: g(".tsh").value, correct_size: g(".tz").value, correct_radius: g(".tr").value, correct_skus: g(".ts").value, comment: g(".tc").value, parsed: p };
    try {
      const r = await fetch(API + "/api/admin/train_add", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const d = await r.json(); g(".tmsg").className = "tmsg" + (d.ok ? " ok" : ""); g(".tmsg").textContent = d.message || d.error || "";
      if (d.ok && d.suggested && d.suggested.length) {
        const box = g(".sug"); box.innerHTML = '<div class="hint">Сделать правилом материала → ISO ' + d.iso + '? Отметьте марки из запроса:</div>' + d.suggested.map(t => '<label><input type="checkbox" value="' + t.replace(/"/g, "") + '"> ' + t.replace(/</g, "&lt;") + '</label>').join("") + '<br><button type="button" class="trule">Добавить правила</button>';
        box.querySelector(".trule").onclick = async () => {
          const toks = [...box.querySelectorAll("input:checked")].map(x => x.value); if (!toks.length) return;
          const rr = await fetch(API + "/api/admin/train_rules", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tokens: toks, iso: d.iso }) }); const dd = await rr.json(); box.innerHTML = '<span class="ok">' + (dd.message || "") + '</span>';
        };
      }
    } catch (e) { g(".tmsg").textContent = "Не удалось сохранить"; }
  };
}
let n = 0;
function feedbackBox(card, query, answer, meta) {
  const id = "fb" + (++n);
  const box = document.createElement("div"); box.className = "fb"; box.id = id;
  box.innerHTML = '<button data-r="like">👍 Точно</button><button data-r="warn">⚠️ Неполно</button><button data-r="dislike">👎 Ошибка</button><input placeholder="Комментарий (необязательно)" maxlength="400">';
  const input = box.querySelector("input");
  box.querySelectorAll("button").forEach(b => b.onclick = async () => {
    box.querySelectorAll("button").forEach(x => x.classList.remove("on")); b.classList.add("on");
    try { await fetch(API + "/api/feedback", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sid, rating: b.dataset.r, comment: input.value, query, answer: answer.slice(0, 3000), meta }) }); } catch (e) {}
  });
  input.onchange = () => { const on = box.querySelector("button.on"); if (on) on.click(); };
  card.appendChild(box);
}

async function ask(text) {
  add("user", esc(text));
  const wait = add("", '<span class="badge">ищу в наличии…</span>');
  $("go").disabled = true;
  try {
    const r = await fetch(API + "/api/query", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sid, query: text }) });
    const d = await r.json();
    wait.remove();
    if (!r.ok) { add("", '<p>' + esc(d.error || "Ошибка сервера") + '</p>'); return; }
    const card = add("", badge(d) + md(d.response_text || ""));
    if (LOCAL_ADMIN) trainBox(card, text, d.parsed);
    feedbackBox(card, text, d.response_text || "", { decision: d.decision, llm_status: d.llm_status || 'not_needed', top: ((d.tool_result || {}).products || []).slice(0, 3).map(p => p.sku) });
  } catch (e) { wait.remove(); add("", "<p>Нет связи с сервером. Попробуйте ещё раз.</p>"); }
  finally { $("go").disabled = false; $("q").focus(); }
}
$("f").onsubmit = e => { e.preventDefault(); const t = $("q").value.trim(); if (!t) return; $("q").value = ""; ask(t); };
$("q").addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("f").requestSubmit(); } });
$("reset").onclick = async () => { try { await fetch(API + "/api/clear_chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sid }) }); } catch (e) {} document.querySelectorAll("#msgs .msg:not(:first-child)").forEach(x => x.remove()); };
["CNMG 120408 для стали 40Х", "Сверло 8,5 мм по нержавейке", "Фреза концевая 10 мм 3 зуба", "Метчик М10", "Державка PCLNR 2525M12", "Аналог SNMG 120408 Sandvik GC4325"].forEach(t => { const b = document.createElement("button"); b.type = "button"; b.textContent = t; b.onclick = () => ask(t); $("chips").appendChild(b); });
fetch(API + "/api/status").then(r => r.json()).then(s => { $("src").textContent = "В наличии: " + s.in_stock + " поз. • обновлено " + (s.catalog_updated || "—"); if (s.local_admin) { LOCAL_ADMIN = true; $("adm").style.display = "flex"; $("llmlink").textContent = "🤖 LLM: " + (s.llm_on ? "вкл" : "выкл"); } }).catch(() => { $("src").textContent = ""; });
</script></body></html>
""".replace("__BASE_CSS__", BASE_CSS)

ADMIN_HTML = r"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Админка подбора пластин</title>
<style>__BASE_CSS__
body{overflow:auto;display:block;padding:16px;max-width:940px;margin:0 auto}
section{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:14px}
h2{margin:0 0 10px;font-size:16px}label{display:block;color:var(--muted);font-size:13px;margin:8px 0 3px}
input,textarea,select{width:100%;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--text);font:inherit}
textarea{min-height:90px}.row{display:flex;gap:8px;flex-wrap:wrap}.row>*{flex:1;min-width:140px}
button{background:var(--accent2);color:#fff;border:1px solid transparent;border-radius:8px;padding:8px 14px;margin:6px 6px 0 0;transition:opacity .15s,background .15s}
button:hover{opacity:.92}button:disabled{opacity:.55;cursor:wait}
button.sec{background:transparent;color:var(--text);border:1px solid var(--line)}
button.sec.active{background:var(--accent2);color:#fff;border-color:var(--accent2);font-weight:600}
button.danger{background:transparent;color:var(--bad);border:1px solid var(--line);padding:4px 9px;margin:0}
pre{background:var(--bubble);padding:10px;border-radius:8px;overflow:auto;font-size:12.5px;max-height:260px;margin:8px 0}
.status-msg{display:inline-block;margin-left:8px;font-size:13px;font-weight:500}
.status-msg.ok{color:var(--ok)}.status-msg.err{color:var(--bad)}
#toast{position:fixed;right:20px;bottom:20px;background:#1e293b;color:#fff;padding:12px 18px;border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,.25);font-size:14px;z-index:9999;display:none;max-width:420px;border-left:4px solid var(--accent2)}
#toast.ok{border-left-color:#22c55e}#toast.err{border-left-color:#ef4444}
.hint{color:var(--muted);font-size:13px;margin-bottom:6px}
table th,table td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
</style></head><body>
<div id="toast"></div>
<h2 style="font-size:20px;display:flex;justify-content:space-between;align-items:center">
  <span><a href="/" style="text-decoration:none">← К чату</a> &nbsp; Панель администратора</span>
  <span id="out" class="status-msg"></span>
</h2>

<section>
  <label>Админ-токен (на локальном ПК оставьте пустым)</label>
  <div class="row" style="align-items:center">
    <input id="tok" type="password" autocomplete="off" placeholder="Не требуется для localhost">
    <button type="button" id="btn-tok" style="flex:0 0 auto;margin:0">Применить токен</button>
  </div>
</section>

<section>
  <h2>📊 Состояние системы</h2>
  <pre id="status">Загрузка состояния…</pre>
  <button type="button" class="sec" id="btn-refresh-1">🔄 Обновить состояние</button>
</section>

<section id="sec-source">
  <h2>📚 Источник данных (активный каталог: <span id="cur-src-label" style="color:var(--accent2)">—</span>)</h2>
  <div class="hint">Переключение между кэшированными таблицами занимает менее 1 мс:</div>
  <div>
    <button type="button" class="sec src-btn" data-src="qtool" id="btn-src-qtool">Только qtool.ru</button>
    <button type="button" class="sec src-btn" data-src="rinscom" id="btn-src-rinscom">Только Rinscom.com</button>
    <button type="button" class="sec src-btn" data-src="both" id="btn-src-both">Оба магазина (Rinscom + qtool)</button>
  </div>
  <div style="margin-top:8px">
    <button type="button" id="btn-sync-all">⬇️ Скачать и пересобрать обе таблицы (qtool + Rinscom)</button>
    <button type="button" class="sec" id="btn-sync-qtool">⬇️ Обновить прайс qtool.ru</button>
    <button type="button" class="sec" id="btn-sync-rinscom">⬇️ Обновить прайс Rinscom</button>
  </div>
  <label style="margin-top:12px">Загрузить свой файл прайса (.xlsx в формате qtool или Rinscom 1С)</label>
  <div class="row" style="align-items:center">
    <input type="file" id="xl" accept=".xlsx">
    <button type="button" id="btn-upload" style="flex:0 0 auto;margin:0">📤 Загрузить .xlsx</button>
  </div>
</section>

<section id="sec-llm">
  <h2>🤖 LLM-верификатор (опционально, любой OpenAI-совместимый API)</h2>
  <div class="row">
    <div><label>Ключ API</label><input id="lkey" type="password" autocomplete="off" placeholder="Оставьте пустым, если не меняете"></div>
    <div><label>Адрес API (Base URL)</label><input id="lurl" placeholder="http://127.0.0.1:11434/v1"></div>
  </div>
  <label>Модели по приоритету (через запятую)</label>
  <input id="lmodels" placeholder="qwen2.5:3b">
  <button type="button" id="btn-llm-save">💾 Сохранить и проверить связь</button>
</section>

<section id="sec-train">
  <h2>🎓 Обучение парсера на примерах</h2>
  <div class="hint">Введите запрос, нажмите «Проверить разбор парсером» или сразу укажите правильные параметры и артикулы. Парсер автоматически использует векторный поиск (TF-IDF) по сохранённым примерам.</div>
  <label>Текст запроса клиента</label>
  <div class="row" style="align-items:center">
    <input id="tq" placeholder="Например: ромб 80 размер 12 чистовая по нержавейке 12Х18Н10Т">
    <button type="button" class="sec" id="btn-train-test" style="flex:0 0 auto;margin:0">🔍 Проверить разбор парсером</button>
  </div>
  <pre id="tparsed">Нажмите «Проверить разбор парсером», чтобы увидеть, какие параметры извлёк движок…</pre>
  <div class="row">
    <div><label>Правильная группа ISO</label><select id="tiso"><option value="">— не менять —</option><option value="P">P — сталь</option><option value="M">M — нержавеющая</option><option value="K">K — чугун</option><option value="N">N — цветные</option><option value="S">S — титан/жаропрочные</option><option value="H">H — закалённые</option></select></div>
    <div><label>Правильный вид обработки</label><select id="top"><option value="">— не менять —</option><option value="finishing">чистовая</option><option value="semi_finishing">получистовая</option><option value="roughing">черновая</option></select></div>
  </div>
  <div class="row">
    <div><label>Геометрия (форма по ISO)</label><select id="tshape"><option value="">— не менять —</option><option value="C">C — ромб 80°</option><option value="D">D — ромб 55°</option><option value="V">V — ромб 35°</option><option value="E">E — ромб 75°</option><option value="M">M — ромб 86°</option><option value="T">T — треугольник 60°</option><option value="W">W — тригон 80°</option><option value="S">S — квадрат 90°</option><option value="R">R — круглая</option><option value="H">H — шестигранник 120°</option><option value="O">O — восьмигранник</option><option value="P">P — пятигранник</option><option value="L">L — прямоугольная</option><option value="A">A — параллелограмм 85°</option><option value="B">B — параллелограмм 82°</option><option value="K">K — параллелограмм 55°</option></select></div>
    <div><label>Размер (код кромки)</label><input id="tsize" maxlength="2" placeholder="напр. 12"></div>
    <div><label>Радиус вершины, мм</label><select id="trad"><option value="">— не менять —</option><option value="0.2">0.2</option><option value="0.4">0.4</option><option value="0.8">0.8</option><option value="1.2">1.2</option><option value="1.6">1.6</option><option value="2.4">2.4</option></select></div>
  </div>
  <label>Правильные артикулы (через запятую, точку с запятой или с новой строки)</label>
  <textarea id="tsk" style="min-height:54px" placeholder="CNMG120408-MM KT8206; CNMG 120408 LF6018"></textarea>
  <label>Комментарий технолога</label>
  <input id="tcm" maxlength="600" placeholder="Почему выбран этот сплав/стружколом">
  <div>
    <button type="button" id="btn-train-save">✅ Сохранить пример в базу обучения</button>
    <button type="button" class="sec" id="btn-train-dl">⬇ Скачать таблицу примеров (CSV для Excel)</button>
  </div>
  <div id="tsug" style="margin-top:8px"></div>
  <label style="margin-top:14px">Сохранённые примеры обучения (<span id="train-cnt">0</span>)</label>
  <div style="overflow-x:auto"><table id="ttab" style="width:100%;border-collapse:collapse;font-size:13px"></table></div>
</section>

<section id="sec-rules">
  <h2>📝 Дополнительные правила технолога</h2>
  <textarea id="rules" placeholder="Например: Приоритетный бренд для точения стали — ZZKLT и Deskar"></textarea>
  <button type="button" id="btn-rules-save">💾 Сохранить правила</button>
</section>

<section>
  <h2>📈 Лог проверок и статистика оценок</h2>
  <pre id="rev">—</pre>
  <button type="button" class="sec" id="btn-refresh-2">🔄 Обновить статистику</button>
</section>

<script>
const $ = id => document.getElementById(id);
const v = id => ($(id) ? $(id).value : "");
let TOK = "";
try { TOK = sessionStorage.getItem("adm") || ""; } catch(e) {}
$("tok").value = TOK;

let toastTimer = null;
function notify(msg, isErr = false) {
  const out = $("out");
  if (out) {
    out.textContent = msg;
    out.className = "status-msg " + (isErr ? "err" : "ok");
  }
  const t = $("toast");
  if (t && msg) {
    t.textContent = (isErr ? "⚠️ " : "✅ ") + msg;
    t.className = isErr ? "err" : "ok";
    t.style.display = "block";
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.style.display = "none"; }, 4500);
  }
}

async function api(path, opt = {}) {
  const r = await fetch("/api/admin/" + path, {
    ...opt,
    headers: { "Content-Type": "application/json", "X-Admin-Token": TOK }
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok || d.ok === false) {
    throw new Error(d.message || d.error || ("HTTP " + r.status));
  }
  return d;
}

async function runBtn(btn, fn) {
  const origText = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.textContent = "⏳ Выполняется…"; }
  try {
    await fn();
  } catch (e) {
    notify(e.message || String(e), true);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = origText; }
  }
}

async function post(path, body, btn) {
  await runBtn(btn, async () => {
    const d = await api(path, { method: "POST", body: JSON.stringify(body) });
    notify(d.message || "Успешно выполнено");
    await load(true);
  });
}

async function load(keepMsg = false) {
  try {
    const d = await api("status");
    $("status").textContent = JSON.stringify(d.status, null, 2);
    $("rules").value = d.status.custom_instructions || "";
    $("lurl").value = (d.status.llm && d.status.llm.base_url) || "";
    $("lmodels").value = ((d.status.llm && d.status.llm.models) || []).join(", ");
    $("rev").textContent = JSON.stringify(d.review, null, 2);

    const cat = (d.status && d.status.catalog) || {};
    const activeSrc = cat.active_source || "both";
    $("cur-src-label").textContent = (cat.source_label || activeSrc) + " (в наличии: " + (cat.in_stock || 0) + " из " + (cat.total || 0) + ")";
    document.querySelectorAll(".src-btn").forEach(b => {
      b.classList.toggle("active", b.dataset.src === activeSrc);
    });
    if (!keepMsg) $("out").textContent = "";
  } catch (e) {
    notify("Ошибка чтения статуса: " + e.message, true);
  }
}

function esc(t) {
  return String(t || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

let LASTP = {};

async function loadTrain() {
  try {
    const d = await api("training");
    const rows = d.examples || [];
    $("train-cnt").textContent = d.count != null ? d.count : rows.length;
    const head = '<tr><th>№</th><th>Запрос</th><th>ISO</th><th>Обработка</th><th>Форма/Разм./R</th><th>Артикулы</th><th>Комментарий</th><th></th></tr>';
    const body = rows.slice(0, 60).map(r => {
      const geom = [r.correct_shape ? "Форма " + r.correct_shape : "", r.correct_size ? "р-р " + r.correct_size : "", r.correct_radius ? "R" + r.correct_radius : ""].filter(Boolean).join(", ");
      return '<tr>' +
        '<td>' + esc(r.id) + '</td>' +
        '<td><b>' + esc(r.query) + '</b></td>' +
        '<td>' + esc(r.correct_iso || "—") + '</td>' +
        '<td>' + esc(r.correct_operation || "—") + '</td>' +
        '<td>' + esc(geom || "—") + '</td>' +
        '<td><code>' + esc(r.correct_skus || "—") + '</code></td>' +
        '<td>' + esc(r.comment || "") + '</td>' +
        '<td><button type="button" class="danger btn-del-ex" data-id="' + esc(r.id) + '" title="Удалить пример">✕</button></td>' +
      '</tr>';
    }).join("");
    $("ttab").innerHTML = head + (body || '<tr><td colspan="8" style="color:var(--muted)">Примеров пока нет</td></tr>');
    $("ttab").querySelectorAll(".btn-del-ex").forEach(b => {
      b.addEventListener("click", () => runBtn(b, async () => {
        await api("train_delete", { method: "POST", body: JSON.stringify({ id: b.dataset.id }) });
        notify("Пример №" + b.dataset.id + " удалён");
        await loadTrain();
      }));
    });
  } catch (e) {
    notify("Не удалось загрузить таблицу обучения: " + e.message, true);
  }
}

// Привязываем все кнопки через addEventListener
$("btn-tok").addEventListener("click", () => {
  TOK = v("tok").trim();
  try { sessionStorage.setItem("adm", TOK); } catch(e) {}
  notify("Токен сохранён, обновляю статус…");
  load(true);
  loadTrain();
});

$("btn-refresh-1").addEventListener("click", function() { runBtn(this, async () => { await load(true); notify("Состояние обновлено"); }); });
$("btn-refresh-2").addEventListener("click", function() { runBtn(this, async () => { await load(true); notify("Статистика обновлена"); }); });

document.querySelectorAll(".src-btn").forEach(btn => {
  btn.addEventListener("click", () => post("source", { source: btn.dataset.src }, btn));
});

$("btn-sync-all").addEventListener("click", function() { post("sync_all", {}, this); });
$("btn-sync-qtool").addEventListener("click", function() { post("sync_qtool", {}, this); });
$("btn-sync-rinscom").addEventListener("click", function() { post("sync_rinscom", {}, this); });

$("btn-upload").addEventListener("click", function() {
  const f = $("xl").files[0];
  if (!f) return notify("Сначала выберите файл .xlsx", true);
  const btn = this;
  const fr = new FileReader();
  fr.onload = () => post("upload_xlsx", { filename: f.name, content_base64: fr.result.split(",")[1] }, btn);
  fr.readAsDataURL(f);
});

$("btn-llm-save").addEventListener("click", function() {
  post("llm", { api_key: v("lkey"), base_url: v("lurl"), models: v("lmodels") }, this);
});

$("btn-rules-save").addEventListener("click", function() {
  post("prompt", { custom_instructions: v("rules") }, this);
});

$("btn-train-test").addEventListener("click", function() {
  const q = v("tq").trim();
  if (!q) return notify("Введите текст запроса в поле выше", true);
  runBtn(this, async () => {
    const d = await api("train_test", { method: "POST", body: JSON.stringify({ query: q }) });
    LASTP = d.parsed || {};
    $("tparsed").textContent = "Распознанные параметры:\n" + JSON.stringify(LASTP, null, 2) + "\n\nПервые строки ответа:\n" + (d.response_text || "").slice(0, 700);
    if (LASTP.iso && !$("tiso").value) $("tiso").value = LASTP.iso;
    if (LASTP.operation && !$("top").value) $("top").value = LASTP.operation;
    if (LASTP.shape && !$("tshape").value) $("tshape").value = LASTP.shape;
    if (LASTP.size && !$("tsize").value) $("tsize").value = LASTP.size;
    notify("Разбор запроса выполнен");
  });
});

$("btn-train-save").addEventListener("click", function() {
  const q = v("tq").trim();
  if (!q) return notify("Введите текст запроса для обучения", true);
  runBtn(this, async () => {
    const payload = {
      query: q,
      correct_iso: v("tiso"),
      correct_operation: v("top"),
      correct_shape: v("tshape"),
      correct_size: v("tsize"),
      correct_radius: v("trad"),
      correct_skus: v("tsk"),
      comment: v("tcm"),
      parsed: LASTP
    };
    const d = await api("train_add", { method: "POST", body: JSON.stringify(payload) });
    notify(d.message || "Пример сохранён");
    const box = $("tsug");
    box.innerHTML = "";
    if (d.ok && d.suggested && d.suggested.length) {
      const wrap = document.createElement("div");
      wrap.innerHTML = '<div class="hint">Сделать правилом материала → ISO ' + esc(d.iso) + '? Отметьте слова из запроса:</div>';
      d.suggested.forEach(tok => {
        const lbl = document.createElement("label");
        lbl.style.cssText = "display:inline-block;margin-right:12px;cursor:pointer";
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.style.width = "auto";
        cb.value = tok;
        cb.checked = true;
        lbl.appendChild(cb);
        lbl.appendChild(document.createTextNode(" " + tok));
        wrap.appendChild(lbl);
      });
      const bRule = document.createElement("button");
      bRule.type = "button";
      bRule.textContent = "➕ Добавить выбранные марки в правила материалов";
      bRule.addEventListener("click", () => runBtn(bRule, async () => {
        const toks = [...wrap.querySelectorAll("input:checked")].map(x => x.value);
        if (!toks.length) return notify("Отметьте хотя бы одно слово", true);
        const res = await api("train_rules", { method: "POST", body: JSON.stringify({ tokens: toks, iso: d.iso }) });
        notify(res.message || "Правила добавлены");
        box.innerHTML = "";
      }));
      wrap.appendChild(document.createElement("br"));
      wrap.appendChild(bRule);
      box.appendChild(wrap);
    }
    await loadTrain();
    await load(true);
  });
});

$("btn-train-dl").addEventListener("click", function() {
  runBtn(this, async () => {
    const r = await fetch("/api/admin/training.csv", { headers: { "X-Admin-Token": TOK } });
    if (!r.ok) throw new Error("Не удалось скачать CSV (HTTP " + r.status + ")");
    const b = await r.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(b);
    a.download = "training_examples.csv";
    a.click();
    notify("Файл training_examples.csv скачан");
  });
});

load();
loadTrain();
</script></body></html>
""".replace("__BASE_CSS__", BASE_CSS)
