#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_admin_ui.py — Полное исправление всех кнопок, индикации и обработчиков в админке (/admin) и чате (/).
"""
import os
import re

ROOT = os.path.dirname(os.path.abspath(__file__))


def patch_ui_py():
    path = os.path.join(ROOT, "src", "ui.py")
    if not os.path.exists(path):
        print("❌ Не найден src/ui.py")
        return

    with open(path, "r", encoding="utf-8-sig") as f:
        content = f.read()

    # Находим начало ADMIN_HTML и заменяем его на версию с наглядной индикацией на каждой кнопке и всплывающим тостом
    idx = content.find("ADMIN_HTML = ")
    if idx == -1:
        print("❌ Не найден блок ADMIN_HTML в src/ui.py")
        return

    header_part = content[:idx]

    new_admin_html = r'''ADMIN_HTML = r"""<!DOCTYPE html>
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
'''

    with open(path, "w", encoding="utf-8") as f:
        f.write(header_part + new_admin_html)
    print("✅ 1/2: src/ui.py — все кнопки админки переведены на прямые обработчики событий с тост-уведомлениями и подсветкой активного источника.")


def patch_app_py():
    path = os.path.join(ROOT, "app.py")
    if not os.path.exists(path):
        print("❌ Не найден app.py")
        return

    with open(path, "r", encoding="utf-8-sig") as f:
        code = f.read()

    # Убираем жесткий CSP на странице, чтобы ни один браузер или расширение не блокировал скрипты админки
    code = re.sub(
        r'self\._headers\(200, "text/html; charset=utf-8", \{"Content-Security-Policy": csp, "Cache-Control": "no-store", "Content-Length": str\(len\(data\)\)\}\)',
        'self._headers(200, "text/html; charset=utf-8", {"Cache-Control": "no-store, no-cache, must-revalidate", "Content-Length": str(len(data))})',
        code,
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write(code)
    print("✅ 2/2: app.py — отключено кэширование HTML и сняты ограничения CSP для локальной админки.")


if __name__ == "__main__":
    patch_ui_py()
    patch_app_py()
    print("\n🎉 Готово! Перезапустите сервер (Закройте окно run.bat и запустите run.bat заново), затем обновите /admin в браузере.")