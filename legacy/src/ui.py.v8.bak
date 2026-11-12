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
<title>Подбор токарных пластин</title>
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
<header><div><b>Подбор токарных пластин</b><br><small id="src">загрузка…</small></div><nav id="adm"><a href="/admin#sec-source">📚 Источник</a><a href="/admin#sec-train">🎓 Обучение</a><a href="/admin#sec-rules">📝 Правила</a><a href="/admin#sec-llm" id="llmlink">🤖 LLM</a></nav></header>
<div id="msgs">
  <div class="msg"><p>Опишите задачу: материал, вид обработки, форму или артикул пластины — подберу варианты из наличия.</p></div>
  <div id="chips"></div>
  <div class="note">Подбор справочный. Перед заказом сверьте характеристики и цену в карточке товара.</div>
</div>
<form id="f" autocomplete="off">
  <input id="q" maxlength="500" placeholder="Например: чистовое точение нержавейки 12Х18Н10Т, CNMG 120408" required>
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
  if (d.llm_status === "checked") return '<span class="badge ok">🔍 Проверено LLM-верификатором</span>';
  if (d.llm_status === "unavailable") return '<span class="badge">⚡ Внутренний парсер ISO 1832</span> <span class="badge warn">⚠️ Проверка LLM сейчас недоступна — проверьте параметры вручную</span><br>';
  return '<span class="badge">⚡ Внутренний парсер ISO 1832</span>';
}
let LOCAL_ADMIN = false;
const ISO_OPT = '<option value="">— не менять —</option><option value="P">P — сталь</option><option value="M">M — нержавеющая</option><option value="K">K — чугун</option><option value="N">N — цветные</option><option value="S">S — титан/жаропрочные</option><option value="H">H — закалённые</option>';
const OP_OPT = '<option value="">— не менять —</option><option value="finishing">чистовая</option><option value="semi_finishing">получистовая</option><option value="roughing">черновая</option>';
function trainBox(card, query, parsed) {
  const p = parsed || {};
  const det = document.createElement("details"); det.className = "train";
  det.innerHTML = '<summary>🎓 Обучить парсер: указать правильный ответ</summary>' +
    '<div class="hint">Парсер понял: ISO ' + (p.iso || "не определено") + ', обработка ' + (p.operation || "не указана") + (p.shape ? ", форма " + p.shape : "") + (p.size ? ", размер " + p.size : "") + (p.code ? ", код " + p.code : "") + '.</div>' +
    '<div class="grid"><div>Правильная группа ISO<select class="ti">' + ISO_OPT + '</select></div><div>Правильный вид обработки<select class="to">' + OP_OPT + '</select></div></div>' +
    'Правильные артикулы (через запятую или с новой строки)<textarea class="ts" placeholder="CNMG 120408 DM YBC252"></textarea>' +
    'Комментарий<input class="tc" maxlength="600" placeholder="Что не так / почему так правильно"><button type="button" class="tsave">Сохранить в таблицу</button> <span class="tmsg"></span><div class="sug"></div>';
  card.appendChild(det);
  const g = sel => det.querySelector(sel);
  g(".tsave").onclick = async () => {
    const body = { query, correct_iso: g(".ti").value, correct_operation: g(".to").value, correct_skus: g(".ts").value, comment: g(".tc").value, parsed: p };
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
$("reset").onclick = async () => { try { await fetch(API + "/api/clear_chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sid }) }); } catch (e) {} document.querySelectorAll("#msgs .msg:not(:first-child)").forEach(x => x.remove()); };
["Чистовое точение нержавейки 12Х18Н10Т", "Черновая обработка чугуна СЧ20 с коркой", "CNMG 120408 для стали 40Х", "Аналог SNMG 120408 Sandvik GC4325"].forEach(t => { const b = document.createElement("button"); b.type = "button"; b.textContent = t; b.onclick = () => ask(t); $("chips").appendChild(b); });
fetch(API + "/api/status").then(r => r.json()).then(s => { $("src").textContent = "В наличии: " + s.in_stock + " поз. • обновлено " + (s.catalog_updated || "—"); if (s.local_admin) { LOCAL_ADMIN = true; $("adm").style.display = "flex"; $("llmlink").textContent = "🤖 LLM: " + (s.llm_on ? "вкл" : "выкл"); } }).catch(() => { $("src").textContent = ""; });
</script></body></html>
""".replace("__BASE_CSS__", BASE_CSS)

ADMIN_HTML = r"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Админка подбора пластин</title>
<style>__BASE_CSS__
body{overflow:auto;display:block;padding:14px;max-width:900px;margin:0 auto}
section{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;margin-bottom:12px}
h2{margin:0 0 8px;font-size:16px}label{display:block;color:var(--muted);font-size:13px;margin:8px 0 3px}
input,textarea,select{width:100%;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--text);font:inherit}
textarea{min-height:90px}.row{display:flex;gap:8px;flex-wrap:wrap}.row>*{flex:1;min-width:140px}
button{background:var(--accent2);color:#fff;border:0;border-radius:8px;padding:8px 14px;margin:6px 6px 0 0}button.sec{background:transparent;color:var(--text);border:1px solid var(--line)}
pre{background:var(--bubble);padding:10px;border-radius:8px;overflow:auto;font-size:12.5px;max-height:260px}#out{color:var(--muted);font-size:13px;min-height:18px}
</style></head><body>
<h2 style="font-size:20px"><a href="/" style="text-decoration:none">← К чату</a> &nbsp; Админка</h2>
<section><label>Админ-токен (ADMIN_TOKEN на сервере; на локальном ПК можно пусто)</label><input id="tok" type="password" autocomplete="off"><button onclick="saveTok()">Войти</button><span id="out"></span></section>
<section><h2>Состояние</h2><pre id="status">—</pre><button class="sec" onclick="load()">Обновить</button></section>
<section id="sec-source"><h2>Источник данных (каталог)</h2>
<div><button class="sec" onclick="post('source',{source:'qtool'})">qtool.ru</button><button class="sec" onclick="post('source',{source:'rinscom'})">Rinscom.com</button><button class="sec" onclick="post('source',{source:'both'})">Оба</button></div>
<div><button onclick="post('sync_all',{})">Обновить обе таблицы (qtool + Rinscom)</button><button class="sec" onclick="post('sync_qtool',{})">Только qtool.ru</button><button class="sec" onclick="post('sync_rinscom',{})">Только Rinscom</button></div>
<label>Загрузить свой .xlsx (формат qtool-выгрузки или прайс Rinscom)</label><input type="file" id="xl" accept=".xlsx"><button onclick="upload()">Загрузить</button></section>
<section id="sec-llm"><h2>LLM-верификатор (любой OpenAI-совместимый API)</h2>
<div class="row"><div><label>Ключ API</label><input id="lkey" type="password" autocomplete="off" placeholder="только в локальном режиме"></div><div><label>Адрес API</label><input id="lurl" placeholder="https://ai.api.cloud.yandex.net/v1"></div></div>
<label>Модели по приоритету (через запятую)</label><input id="lmodels" placeholder="gpt://&lt;folder_id&gt;/gpt-oss-120b">
<button onclick="post('llm',{api_key:v('lkey'),base_url:v('lurl'),models:v('lmodels')})">Сохранить и проверить связь</button></section>
<section id="sec-train"><h2>🎓 Обучение парсера на примерах</h2>
<div class="hint">Введите запрос, посмотрите, как его понял парсер, и укажите правильный ответ. Пример сохраняется в таблицу и применяется к такому же запросу; марки можно превратить в правила материалов.</div>
<label>Запрос</label><input id="tq" placeholder="например: нужно обдирать вязкую нержу по корке с ударом"><button class="sec" onclick="trainTest()">Как понял парсер</button>
<pre id="tparsed">—</pre>
<div class="row"><div><label>Правильная группа ISO</label><select id="tiso"><option value="">— не менять —</option><option value="P">P — сталь</option><option value="M">M — нержавеющая</option><option value="K">K — чугун</option><option value="N">N — цветные</option><option value="S">S — титан/жаропрочные</option><option value="H">H — закалённые</option></select></div>
<div><label>Правильный вид обработки</label><select id="top"><option value="">— не менять —</option><option value="finishing">чистовая</option><option value="semi_finishing">получистовая</option><option value="roughing">черновая</option></select></div></div>
<label>Правильные артикулы (через запятую)</label><textarea id="tsk" style="min-height:50px"></textarea>
<label>Комментарий</label><input id="tcm" maxlength="600"><button onclick="trainSave()">Сохранить в таблицу</button><button class="sec" onclick="trainDownload()">⬇ Скачать таблицу (CSV для Excel)</button>
<div id="tsug"></div><label>Последние примеры</label><div style="overflow-x:auto"><table id="ttab" style="width:100%;border-collapse:collapse;font-size:13px"></table></div></section>
<section id="sec-rules"><h2>Правила технолога (промпт проверяющей модели) (для проверяющей модели и подсказки бренда)</h2><textarea id="rules"></textarea><button onclick="post('prompt',{custom_instructions:v('rules')})">Сохранить</button></section>
<section><h2>Проверки ИИ и оценки</h2><pre id="rev">—</pre><button class="sec" onclick="load()">Обновить</button></section>
<script>
const $=id=>document.getElementById(id), v=id=>$(id).value;
let TOK=sessionStorage.getItem("adm")||""; $("tok").value=TOK;
function saveTok(){TOK=v("tok");sessionStorage.setItem("adm",TOK);load();}
function say(t){$("out").textContent=t;}
async function api(path,opt={}){const r=await fetch("/api/admin/"+path,{...opt,headers:{"Content-Type":"application/json","X-Admin-Token":TOK}});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.error||("HTTP "+r.status));return d;}
async function post(path,body){say("…");try{const d=await api(path,{method:"POST",body:JSON.stringify(body)});say(d.message||"Готово");load(true);}catch(e){say("Ошибка: "+e.message);}}
async function load(keep){try{const d=await api("status");$("status").textContent=JSON.stringify(d.status,null,2);$("rules").value=d.status.custom_instructions||"";$("lurl").value=d.status.llm.base_url||"";$("lmodels").value=(d.status.llm.models||[]).join(",");$("rev").textContent=JSON.stringify(d.review,null,2);if(!keep)say("");}catch(e){say("Ошибка: "+e.message);}}
function upload(){const f=$("xl").files[0];if(!f)return say("Выберите файл");const fr=new FileReader();fr.onload=()=>post("upload_xlsx",{filename:f.name,content_base64:fr.result.split(",")[1]});fr.readAsDataURL(f);}
let LASTP={};
async function trainTest(){const q=v("tq");if(!q)return;try{const d=await api("train_test",{method:"POST",body:JSON.stringify({query:q})});LASTP=d.parsed||{};$("tparsed").textContent=JSON.stringify(d.parsed,null,1)+"\n\n"+(d.response_text||"").slice(0,600);}catch(e){say("Ошибка: "+e.message);}}
async function trainSave(){const q=v("tq");if(!q)return say("Введите запрос");try{const d=await api("train_add",{method:"POST",body:JSON.stringify({query:q,correct_iso:v("tiso"),correct_operation:v("top"),correct_skus:v("tsk"),comment:v("tcm"),parsed:LASTP})});say(d.message);const box=$("tsug");box.innerHTML="";if(d.ok&&d.suggested&&d.suggested.length){box.innerHTML='<div class="hint">Сделать правилом материала → ISO '+d.iso+'? Отметьте марки:</div>'+d.suggested.map(t=>'<label style="display:inline-block;margin-right:10px"><input type="checkbox" style="width:auto" value="'+t.replace(/"/g,"")+'"> '+t.replace(/</g,"&lt;")+'</label>').join("")+'<br><button onclick="trainRules(\''+d.iso+'\')">Добавить правила</button>';}loadTrain();}catch(e){say("Ошибка: "+e.message);}}
async function trainRules(iso){const toks=[...document.querySelectorAll("#tsug input:checked")].map(x=>x.value);if(!toks.length)return;const d=await api("train_rules",{method:"POST",body:JSON.stringify({tokens:toks,iso})});say(d.message);$("tsug").innerHTML="";}
async function loadTrain(){try{const d=await api("training");const rows=d.examples||[];$("ttab").innerHTML='<tr style="text-align:left"><th>№</th><th>Запрос</th><th>ISO</th><th>Обработка</th><th>Артикулы</th><th>Комментарий</th><th></th></tr>'+rows.slice(0,50).map(r=>'<tr style="border-top:1px solid var(--line)"><td>'+r.id+'</td><td>'+esc(r.query)+'</td><td>'+(r.correct_iso||"")+'</td><td>'+(r.correct_operation||"")+'</td><td>'+esc(r.correct_skus)+'</td><td>'+esc(r.comment)+'</td><td><button class="sec" onclick="trainDel(\''+r.id+'\')">✕</button></td></tr>').join("");}catch(e){}}
async function trainDel(id){await api("train_delete",{method:"POST",body:JSON.stringify({id})});loadTrain();}
async function trainDownload(){const r=await fetch("/api/admin/training.csv",{headers:{"X-Admin-Token":TOK}});if(!r.ok)return say("Ошибка загрузки");const b=await r.blob();const a=document.createElement("a");a.href=URL.createObjectURL(b);a.download="training_examples.csv";a.click();}
function esc(t){return String(t||"").replace(/&/g,"&amp;").replace(/</g,"&lt;");}
load();loadTrain();
</script></body></html>
""".replace("__BASE_CSS__", BASE_CSS)
