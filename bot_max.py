"""
bot_max.py - чат-бот QtoolSearch для мессенджера MAX (https://dev.max.ru).

Режимы работы (переменная BOT_MODE):
  polling (по умолчанию) — Long Polling, не требует домена и SSL; для теста и небольшого продакшена.
  webhook — приём обновлений через POST /webhook (нужен публичный HTTPS-адрес); для production.

Сценарии:
  /start           — приветствие, инструкция, кнопки-примеры и ссылка на пакетный подбор.
  Текст (1 строка) — карточка с 1–3 аналогами, ценой, наличием и inline-кнопками.
  Текст (список)   — пакетный режим: до 10 позиций — сводка, больше — готовый .xlsx.
  Документ .xlsx/.csv — скачиваем, прогоняем через /search/batch, отдаём .xlsx с аналогами.
  «Запросить счёт»  — берём контакт/username и пересылаем заявку менеджеру (MANAGER_CHAT_ID).

Переменные: MAX_BOT_TOKEN, BOT_MODE, API_BASE_URL, PUBLIC_BASE_URL, WEBHOOK_SECRET,
MANAGER_CHAT_ID, MANAGER_EMAIL, SITE_URL, MAX_API_BASE.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any, Dict, List, Optional

import aiohttp

from src.llm_client import load_env_file

load_env_file()

MAX_BOT_TOKEN = os.environ.get("MAX_BOT_TOKEN", "")
MAX_API_BASE = os.environ.get("MAX_API_BASE", "https://platform-api2.max.ru").rstrip("/")
BOT_MODE = os.environ.get("BOT_MODE", "polling").lower()
API_BASE_URL = os.environ.get("API_BASE_URL", "http://api:8000").rstrip("/")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
MANAGER_CHAT_ID = os.environ.get("MANAGER_CHAT_ID", "")
MANAGER_EMAIL = os.environ.get("MANAGER_EMAIL", "")
SITE_URL = os.environ.get("SITE_URL", "https://qtool.ru")
BATCH_SUMMARY_LIMIT = 10  # до N позиций — текстом, больше — файлом

_HEADERS = {"Authorization": MAX_BOT_TOKEN}

# Чаты, ожидающие контакт для заявки на счёт (in-memory, переживает только один процесс).
_PENDING_LEADS: set[int] = set()
_LEAD_RE = re.compile(r"@?\b[\w.+-]+@[\w.-]+\b|\+?\d[\d\s\-()]{6,}|@[A-Za-z0-9_]{3,}")


# --------------------------------------------------------------------------------------------------
# Низкоуровневые вызовы MAX API
# --------------------------------------------------------------------------------------------------
async def _api(session: aiohttp.ClientSession, method: str, path: str, **kw) -> Dict[str, Any]:
    url = MAX_API_BASE + path
    async with session.request(method, url, headers=_HEADERS, **kw) as resp:
        text = await resp.text()
        try:
            data = json.loads(text) if text else {}
        except json.JSONDecodeError:
            data = {"raw": text}
        if resp.status >= 400:
            raise RuntimeError(f"MAX API {method} {path} -> {resp.status}: {text[:300]}")
        return data


async def send_message(session: aiohttp.ClientSession, chat_id: int, text: str,
                       attachments: Optional[List[Dict[str, Any]]] = None,
                       user_id: Optional[int] = None) -> Dict[str, Any]:
    params = {"user_id": user_id} if user_id else {"chat_id": chat_id}
    body: Dict[str, Any] = {"text": text}
    if attachments:
        body["attachments"] = attachments
    return await _api(session, "POST", "/messages", params=params, json=body)


async def upload_file(session: aiohttp.ClientSession, filename: str, raw: bytes) -> str:
    """Загружает файл и возвращает токен вложения для отправки."""
    up = await _api(session, "POST", "/uploads", params={"type": "file"})
    upload_url = up.get("url") or (up.get("payload") or {}).get("url")
    if not upload_url:
        raise RuntimeError(f"Не получен URL загрузки: {up}")
    form = aiohttp.FormData()
    form.add_field("data", raw, filename=filename,
                   content_type="application/octet-stream")
    async with session.post(upload_url, data=form) as resp:
        if resp.status >= 400:
            raise RuntimeError(f"Загрузка файла не удалась: {resp.status}")
    # Токен приходит в ответе POST /uploads (поле token) — переиспользуем его.
    token = up.get("token") or (up.get("payload") or {}).get("token")
    if not token:
        raise RuntimeError(f"Не получен токен файла: {up}")
    return token


async def send_file(session: aiohttp.ClientSession, chat_id: int, filename: str, raw: bytes,
                    caption: str = "") -> None:
    token = await upload_file(session, filename, raw)
    await send_message(session, chat_id, caption or "Готово",
                       attachments=[{"type": "file", "payload": {"token": token}}])


async def download_attachment(session: aiohttp.ClientSession, url: str) -> bytes:
    async with session.get(url) as resp:
        resp.raise_for_status()
        return await resp.read()


# --------------------------------------------------------------------------------------------------
# Взаимодействие с Backend API (единый индекс)
# --------------------------------------------------------------------------------------------------
async def api_single(session: aiohttp.ClientSession, query: str, limit: int = 3) -> Dict[str, Any]:
    async with session.post(API_BASE_URL + "/search/single", json={"query": query, "limit": limit}) as r:
        r.raise_for_status()
        return await r.json()


async def api_batch(session: aiohttp.ClientSession, queries: List[Any], limit: int = 3) -> Dict[str, Any]:
    async with session.post(API_BASE_URL + "/search/batch", json={"queries": queries, "limit": limit}) as r:
        r.raise_for_status()
        return await r.json()


# --------------------------------------------------------------------------------------------------
# Форматирование ответов
# --------------------------------------------------------------------------------------------------
def _card_text(query: str, data: Dict[str, Any]) -> str:
    results = data.get("results") or []
    if not results:
        return (f"🔎 «{query}» — ничего не найдено.\n"
                "Уточните группу и параметры, например: `CNMG 120408 PM 4325`.")
    lines = [f"🔎 «{query}» — {data.get('corrected') or ''}".rstrip()]
    for i, p in enumerate(results, 1):
        stock = int(p.get("stock") or 0)
        avail = f"✅ {stock} шт." if stock > 0 else "⏳ под заказ"
        lines.append(f"\n{i}. {p.get('name') or p.get('sku')}")
        lines.append(f"   Артикул: {p.get('sku')} · {p.get('match_type')} · {avail}")
        lines.append(f"   Цена: {p.get('price_display') or 'по запросу'}")
    return "\n".join(lines)


def _card_keyboard(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    buttons: List[List[Dict[str, Any]]] = []
    top = results[0] if results else {}
    if top.get("url"):
        buttons.append([{"type": "link", "text": "Открыть на сайте", "url": top["url"]}])
    buttons.append([{"type": "callback", "text": "Запросить счёт", "payload": "lead"}])
    return [{"type": "inline_keyboard", "payload": {"buttons": buttons}}]


def _summary_text(data: Dict[str, Any]) -> str:
    results = data.get("results") or []
    lines = [f"📋 Подбор по {data.get('count', len(results))} позициям:"]
    for i, r in enumerate(results, 1):
        res = r.get("results") or []
        top = res[0] if res else {}
        if top:
            lines.append(f"{i}. {r.get('query')} → {top.get('sku')} · {top.get('price_display') or 'по запросу'}")
        else:
            lines.append(f"{i}. {r.get('query')} → не найдено")
    lines.append("\nГотовлю Excel-файл со всеми аналогами…")
    return "\n".join(lines)


# --------------------------------------------------------------------------------------------------
# Обработка входящих событий
# --------------------------------------------------------------------------------------------------
async def handle_message(session: aiohttp.ClientSession, chat_id: int, sender: Dict[str, Any],
                         body: Dict[str, Any]) -> None:
    text = (body.get("text") or "").strip()
    attachments = body.get("attachments") or []

    # Документ .xlsx/.csv — пакетный подбор по файлу.
    file_att = next((a for a in attachments if a.get("type") == "file"), None)
    if file_att:
        await _handle_file(session, chat_id, file_att)
        return

    if not text:
        await send_message(session, chat_id, "Пришлите артикул, список артикулов или файл .xlsx/.csv.")
        return

    # Если клиент прислал контакт после запроса счёта — пересылаем менеджеру.
    if chat_id in _PENDING_LEADS:
        _PENDING_LEADS.discard(chat_id)
        if _LEAD_RE.search(text):
            await forward_lead_contact(session, chat_id, text, sender)
            return
        await send_message(session, chat_id, "Не вижу контакта. Пришлите телефон или email, либо артикул для подбора.")

    low = text.lower()
    if low in ("/start", "/help", "start", "помощь"):
        await _send_start(session, chat_id)
        return

    lines = [ln.strip() for ln in re.split(r"[\n\r]+", text) if ln.strip()]
    if len(lines) > 1:
        await _handle_list(session, chat_id, lines)
        return

    # Одиночный запрос.
    try:
        data = await api_single(session, text, limit=3)
    except Exception as e:
        await send_message(session, chat_id, f"Не удалось выполнить поиск: {e}")
        return
    results = data.get("results") or []
    await send_message(session, chat_id, _card_text(text, data),
                       attachments=_card_keyboard(results) if results else None)


async def _send_start(session: aiohttp.ClientSession, chat_id: int) -> None:
    text = (
        "👋 **Qtool Подбор аналогов**\n\n"
        "Пришлите артикул или запрос — подберу точный инструмент и аналоги с ценой и наличием.\n\n"
        "• Один артикул: `CNMG 120408 PM 4325`\n"
        "• Список (по одному в строке) — отвечу сводкой или Excel-файлом\n"
        "• Файл `.xlsx` / `.csv` — верну Excel с подобранными аналогами\n\n"
        f"Весь каталог и пакетный подбор: {SITE_URL}"
    )
    kb = [{"type": "inline_keyboard", "payload": {"buttons": [
        [{"type": "callback", "text": "Пример: CNMG 120408", "payload": "ex1"}],
        [{"type": "callback", "text": "Запросить счёт", "payload": "lead"}],
        [{"type": "link", "text": "Пакетный подбор на сайте", "url": SITE_URL}],
    ]}}]
    await send_message(session, chat_id, text, attachments=kb)


async def _handle_list(session: aiohttp.ClientSession, chat_id: int, lines: List[str]) -> None:
    try:
        data = await api_batch(session, lines, limit=3)
    except Exception as e:
        await send_message(session, chat_id, f"Не удалось обработать список: {e}")
        return
    results = data.get("results") or []
    if len(results) <= BATCH_SUMMARY_LIMIT:
        await send_message(session, chat_id, _summary_text(data))
        # Всё равно приложим Excel — удобно переслать менеджеру.
    else:
        await send_message(session, chat_id, f"📋 Обрабатываю {len(results)} позиций, собираю Excel…")
    await _send_batch_xlsx(session, chat_id, results)


async def _handle_file(session: aiohttp.ClientSession, chat_id: int, file_att: Dict[str, Any]) -> None:
    payload = file_att.get("payload") or {}
    url = payload.get("url")
    name = payload.get("filename") or "file.xlsx"
    if not url:
        await send_message(session, chat_id, "Не удалось скачать файл.")
        return
    try:
        raw = await download_attachment(session, url)
    except Exception as e:
        await send_message(session, chat_id, f"Не удалось скачать файл: {e}")
        return

    from src.service import read_table_bytes
    try:
        headers, rows, col = read_table_bytes(name, raw)
    except Exception as e:
        await send_message(session, chat_id, f"Не удалось прочитать файл: {e}")
        return
    if not rows or col is None:
        await send_message(session, chat_id, "В файле не найдена колонка с артикулом.")
        return
    queries = [row[col] if col < len(row) else "" for row in rows]
    queries = [q for q in queries if q and q.strip()][:500]
    if not queries:
        await send_message(session, chat_id, "В файле нет данных для обработки.")
        return

    await send_message(session, chat_id, f"📄 Получил «{name}», обрабатываю {len(queries)} строк…")
    try:
        data = await api_batch(session, queries, limit=3)
    except Exception as e:
        await send_message(session, chat_id, f"Не удалось обработать файл: {e}")
        return
    results = data.get("results") or []

    from src.service import build_batch_xlsx
    xlsx = build_batch_xlsx(results, headers, rows)
    await send_file(session, chat_id, "qtool_search_result.xlsx", xlsx,
                    caption=f"✅ Готово: найдено {data.get('found', 0)} из {data.get('count', len(results))}")


async def _send_batch_xlsx(session: aiohttp.ClientSession, chat_id: int, results: List[Dict[str, Any]]) -> None:
    try:
        from src.service import build_batch_xlsx
        xlsx = build_batch_xlsx(results)
        await send_file(session, chat_id, "qtool_search_result.xlsx", xlsx,
                        caption="✅ Excel с аналогами готов")
    except Exception as e:
        await send_message(session, chat_id, f"Не удалось собрать Excel: {e}")


async def handle_callback(session: aiohttp.ClientSession, chat_id: int, sender: Dict[str, Any],
                          callback: Dict[str, Any]) -> None:
    # MAX: callback.payload — строка с токеном нажатой кнопки.
    raw = callback.get("payload")
    token = raw if isinstance(raw, str) else (raw or {}).get("payload", "") if isinstance(raw, dict) else ""
    user = sender or {}
    if token == "lead":
        await _request_lead(session, chat_id, user)
    elif token == "ex1":
        data = await api_single(session, "CNMG 120408", limit=3)
        await send_message(session, chat_id, _card_text("CNMG 120408", data),
                           attachments=_card_keyboard(data.get("results") or []))


async def _request_lead(session: aiohttp.ClientSession, chat_id: int, user: Dict[str, Any]) -> None:
    name = (user.get("first_name") or "") + (" " + user.get("last_name") if user.get("last_name") else "")
    username = user.get("username") or ""
    contact_line = f"@{username}" if username else f"user_id={user.get('user_id')}"
    _PENDING_LEADS.add(chat_id)
    await send_message(
        session, chat_id,
        "📞 Чтобы менеджер выставил счёт, оставьте контакт: пришлите телефон или email одним сообщением.",
    )
    # Заявку с уже известными данными дублируем менеджеру.
    if MANAGER_CHAT_ID:
        try:
            await send_message(session, int(MANAGER_CHAT_ID),
                               f"🔔 Заявка на счёт от {name.strip() or 'клиента'} ({contact_line}), чат {chat_id}.")
        except Exception:
            pass


async def forward_lead_contact(session: aiohttp.ClientSession, chat_id: int, contact_text: str,
                               user: Dict[str, Any]) -> None:
    """Пересылка присланного клиентом контакта менеджеру."""
    name = (user.get("first_name") or "").strip()
    if MANAGER_CHAT_ID:
        try:
            await send_message(session, int(MANAGER_CHAT_ID),
                               f"🔔 Контакт для счёта: {contact_text} (от {name or 'клиента'}, чат {chat_id}).")
        except Exception:
            pass
    if MANAGER_EMAIL:
        await _email_lead(contact_text, user, chat_id)
    await send_message(session, chat_id, "✅ Спасибо! Передал контакт менеджеру — он скоро свяжется с вами.")


async def _email_lead(contact_text: str, user: Dict[str, Any], chat_id: int) -> None:
    """Отправка заявки на почту (через локальный SMTP, если настроен)."""
    host = os.environ.get("SMTP_HOST")
    if not host:
        return
    import smtplib
    from email.message import EmailMessage
    msg = EmailMessage()
    msg["Subject"] = "QtoolSearch: заявка на счёт"
    msg["From"] = os.environ.get("SMTP_FROM", "noreply@qtool.ru")
    msg["To"] = MANAGER_EMAIL
    msg.set_content(f"Контакт клиента: {contact_text}\nПользователь: {user}\nЧат: {chat_id}")
    try:
        with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587"))) as s:
            s.starttls()
            user_pw = os.environ.get("SMTP_USER")
            if user_pw:
                s.login(user_pw, os.environ.get("SMTP_PASS", ""))
            s.send_message(msg)
    except Exception as e:
        print(f"[email lead] {e}")


# --------------------------------------------------------------------------------------------------
# Long Polling
# --------------------------------------------------------------------------------------------------
async def run_polling() -> None:
    if not MAX_BOT_TOKEN:
        raise SystemExit("Не задан MAX_BOT_TOKEN")
    marker: Optional[int] = None
    async with aiohttp.ClientSession() as session:
        me = await _api(session, "GET", "/me")
        print(f"[MAX] бот @{me.get('username')} запущен (long polling)")
        while True:
            try:
                params: Dict[str, Any] = {"timeout": 60, "limit": 100}
                if marker is not None:
                    params["marker"] = marker
                resp = await _api(session, "GET", "/updates", params=params)
            except Exception as e:
                print(f"[MAX] ошибка long polling: {e}")
                await asyncio.sleep(3)
                continue
            marker = resp.get("marker", marker)
            for upd in resp.get("updates") or []:
                await _dispatch(session, upd)


async def _dispatch(session: aiohttp.ClientSession, upd: Dict[str, Any]) -> None:
    utype = upd.get("update_type")
    try:
        if utype == "message_created":
            msg = upd.get("message") or {}
            body = msg.get("body") or {}
            sender = msg.get("sender") or {}
            recipient = msg.get("recipient") or {}
            chat_id = recipient.get("chat_id") or upd.get("chat_id")
            # Игнорируем сообщения самого бота.
            if sender.get("is_bot"):
                return
            await handle_message(session, int(chat_id), sender, body)
        elif utype == "message_callback":
            cb = upd.get("callback") or {}
            sender = cb.get("user") or {}
            chat_id = upd.get("chat_id") or (cb.get("message") or {}).get("recipient", {}).get("chat_id")
            await handle_callback(session, int(chat_id), sender, cb)
        elif utype == "bot_started":
            user = upd.get("user") or {}
            chat_id = upd.get("chat_id") or user.get("user_id")
            await _send_start(session, int(chat_id))
    except Exception as e:
        print(f"[MAX] ошибка обработки события {utype}: {e}")


# --------------------------------------------------------------------------------------------------
# Webhook (опционально)
# --------------------------------------------------------------------------------------------------
def build_webhook_app():
    from aiohttp import web

    async def webhook(request: web.Request) -> web.Response:
        if WEBHOOK_SECRET and request.headers.get("X-Max-Webhook-Secret") != WEBHOOK_SECRET:
            return web.Response(status=403, text="forbidden")
        upd = await request.json()
        async with aiohttp.ClientSession() as session:
            await _dispatch(session, upd)
        return web.Response(text="ok")

    app = web.Application()
    app.router.add_post("/webhook", webhook)
    return app


async def run_webhook() -> None:
    from aiohttp import web
    if not MAX_BOT_TOKEN:
        raise SystemExit("Не задан MAX_BOT_TOKEN")
    app = build_webhook_app()
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("BOT_WEBHOOK_PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"[MAX] бот запущен (webhook на :{port}/webhook)")
    while True:
        await asyncio.sleep(3600)


# --------------------------------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------------------------------
def main() -> None:
    if BOT_MODE == "webhook":
        asyncio.run(run_webhook())
    else:
        asyncio.run(run_polling())


if __name__ == "__main__":
    main()