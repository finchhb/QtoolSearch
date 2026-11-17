/**
 * Виджет подбора для qtool.ru: отправляет запрос в ai.php и рендерит ответ в контейнер.
 *
 * <script src="/assets/ai-widget.js" defer></script>
 * <form data-qtool-ai="/ai.php" data-out="#qtool-ai-results">
 *   <input type="search" name="q" placeholder="CNMG 120408 для стали">
 *   <button type="submit">Подобрать</button>
 * </form>
 * <div id="qtool-ai-results"></div>
 *
 * data-qtool-ai — путь к ai.php, data-out — селектор контейнера для ответов.
 */
(function () {
  "use strict";

  const SAFE_URL = /^https:\/\/(www\.)?(qtool\.ru|rinscom\.com)\//;
  const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

  function inline(t) {
    t = esc(t);
    t = t.replace(/\[([^\]]+)\]\((https:[^)\s]+)\)/g, (m, txt, url) => {
      const u = url.replace(/&amp;/g, "&");
      return SAFE_URL.test(u) ? '<a href="' + esc(u) + '" target="_blank" rel="noopener noreferrer">' + txt + "</a>" : txt;
    });
    return t.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*([^*\n]+)\*/g, "<i>$1</i>");
  }

  function md(text) {
    const out = [];
    let list = null;
    const close = () => {
      if (list) {
        out.push("</" + list + ">");
        list = null;
      }
    };
    for (const raw of text.split("\n")) {
      const line = raw.replace(/\s+$/, "");
      let m;
      if (!line.trim()) {
        close();
        continue;
      }
      if ((m = line.match(/^#{1,4}\s+(.*)/))) {
        close();
        out.push("<h3>" + inline(m[1]) + "</h3>");
        continue;
      }
      if ((m = line.match(/^>\s?(.*)/))) {
        close();
        out.push("<blockquote>" + inline(m[1]) + "</blockquote>");
        continue;
      }
      if ((m = line.match(/^\s*(\d+)\.\s+(.*)/))) {
        if (list !== "ol") {
          close();
          out.push("<ol>");
          list = "ol";
        }
        out.push("<li>" + inline(m[2]) + "</li>");
        continue;
      }
      if ((m = line.match(/^\s*[*-]\s+(.*)/))) {
        if (list !== "ul") {
          close();
          out.push("<ul>");
          list = "ul";
        }
        out.push("<li>" + inline(m[1]) + "</li>");
        continue;
      }
      close();
      out.push("<p>" + inline(line) + "</p>");
    }
    close();
    return out.join("");
  }

  function injectCss() {
    if (document.getElementById("qai-css")) return;
    const st = document.createElement("style");
    st.id = "qai-css";
    st.textContent = [
      ".qai-block{margin:18px 0;padding:16px;border:1px solid #e2e5ea;border-radius:10px;background:#fff}",
      ".qai-q{font-weight:600;margin-bottom:8px}",
      ".qai-note{color:#6b7280;font-size:14px}",
      ".qai-err{color:#b91c1c}",
      ".qai-answer{font-size:15px;line-height:1.55}",
      ".qai-answer h3{margin:0 0 8px;font-size:16px}",
      ".qai-answer p{margin:6px 0}",
      ".qai-answer ol,.qai-answer ul{margin:8px 0;padding-left:22px}",
      ".qai-answer li{margin:8px 0}",
      ".qai-answer blockquote{margin:8px 0;padding:6px 12px;border-left:3px solid #d1d5db;color:#4b5563}",
      ".qai-answer code{background:#f3f4f6;padding:1px 4px;border-radius:4px;font-size:13px}",
      ".qai-answer a{color:#c8102e}",
    ].join("");
    document.head.appendChild(st);
  }

  function mount(form) {
    const endpoint = form.getAttribute("data-qtool-ai") || "/ai.php";
    const input = form.querySelector('input[type="search"], input[name="q"], input[name="query"]');
    const outSel = form.getAttribute("data-out");
    const out = outSel ? document.querySelector(outSel) : document.getElementById("qtool-ai-results");
    if (!input || !out) return;
    const submit = form.querySelector('button[type="submit"], button:not([type])');
    let busy = false;

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const q = input.value.trim();
      if (!q || busy) return;
      busy = true;
      if (submit) submit.disabled = true;

      const block = document.createElement("div");
      block.className = "qai-block";
      block.innerHTML = '<div class="qai-q"></div><div class="qai-note">Ищу по каталогу…</div>';
      block.querySelector(".qai-q").textContent = q;
      out.appendChild(block);
      block.scrollIntoView({ block: "end", behavior: "smooth" });

      try {
        const r = await fetch(endpoint, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({ q }),
        });
        let d = null;
        try {
          d = await r.json();
        } catch (err) {
          d = null;
        }
        if (!r.ok || !d) throw new Error((d && d.error) || "Сервис подбора недоступен");
        if (d.error) throw new Error(d.error);
        block.innerHTML = '<div class="qai-q"></div><div class="qai-answer"></div>';
        block.querySelector(".qai-q").textContent = q;
        block.querySelector(".qai-answer").innerHTML = md(d.response_text || "");
      } catch (err) {
        block.innerHTML = '<div class="qai-q"></div><div class="qai-note qai-err"></div>';
        block.querySelector(".qai-q").textContent = q;
        block.querySelector(".qai-err").textContent = err && err.message ? err.message : "Ошибка подбора";
      } finally {
        busy = false;
        if (submit) submit.disabled = false;
        input.focus();
      }
    });
  }

  function boot() {
    const forms = document.querySelectorAll("form[data-qtool-ai]");
    if (!forms.length) return;
    injectCss();
    forms.forEach(mount);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
