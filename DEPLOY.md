# DEPLOY — запуск и обслуживание QtoolSearch

QtoolSearch — микросервис подбора твёрдосплавного инструмента по каталогу qtool.ru.
Три точки входа работают от **одного ядра** (индекс в памяти держит только `api`):

| Сервис | Что это | Порт |
|---|---|---|
| `api` | Backend API (FastAPI): `/search/single`, `/search/batch`, `/admin/reload` | 8000 |
| `streamlit` | Веб-виджет (быстрый поиск + пакетный подбор + выгрузка Excel) | 8501 |
| `max-bot` | Бот мессенджера MAX (текст, список, файл, заявка на счёт) | — |

Всё запускается одной командой через Docker Compose — не нужно ставить Python и библиотеки вручную.

---

## 1. Что подготовить заранее

1. **Токен бота MAX.** Создайте бота на `business.max.ru` (Чат-боты → ⋮ → Настройки) и
   скопируйте токен. Никому его не показывайте.
2. **Сервер (VPS/VDS).** Ubuntu 22.04/24.04, минимум 2 ГБ RAM, 1–2 ядра, 15–20 ГБ диска.
3. **Домен (для виджета на сайте).** Технический поддомен, например `search.qtool.ru`,
   A-запись на IP сервера. Нужен, чтобы отдавать виджет по HTTPS (иначе браузер
   заблокирует `<iframe>` на https-сайте).

---

## 2. Первый запуск

```bash
# 1. Установить Docker (один раз)
apt update && apt install -y git docker.io docker-compose-v2

# 2. Скачать проект
git clone https://github.com/finchhb/QtoolSearch.git
cd QtoolSearch

# 3. Создать .env и заполнить токен бота
cp .env.example .env
nano .env            # впишите MAX_BOT_TOKEN, ADMIN_SECRET, MANAGER_CHAT_ID; Ctrl+O, Enter, Ctrl+X

# 4. Собрать и запустить всё в фоне
docker compose up -d --build
```

Проверка:

```bash
docker compose ps                 # все три сервиса должны быть "running"/"healthy"
curl -s http://localhost:8000/health
docker compose logs -n 50 max-bot # бот должен написать «запущен (long polling)»
```

- Виджет: `http://<IP_СЕРВЕРА>:8501`
- API: `http://<IP_СЕРВЕРА>:8000/docs` (Swagger)

---

## 3. Виджет на сайте (iframe, HTTPS)

Разместите за Caddy/Nginx с бесплатным сертификатом. Пример Caddyfile:

```
search.qtool.ru {
    reverse_proxy 127.0.0.1:8501
}
```

`caddy` сам выпустит сертификат Let's Encrypt. После этого на страницу сайта вставляется:

```html
<iframe src="https://search.qtool.ru/?embed=true" width="100%" height="700" frameborder="0"></iframe>
```

Параметр `?embed=true` скрывает шапку/футер/меню Streamlit — виджет выглядит как часть сайта.
Добавьте домен сайта в `ALLOWED_ORIGINS` в `.env`.

---

## 4. Обслуживание

| Задача | Команда |
|---|---|
| Перезапустить после изменения `.env` | `docker compose restart` |
| Обновить код из GitHub | `git pull && docker compose up -d --build` |
| Смотреть логи | `docker compose logs -n 50 <api\|streamlit\|max-bot>` |
| Остановить всё | `docker compose down` |

После перезагрузки сервера контейнеры поднимаются сами (`restart: always`).

### Обновление каталога / прайсов

Два способа:

1. **Автоматически по расписанию** — задайте `ADVISOR_SYNC_HOURS=24` в `.env` (движок
   сам перекачивает выгрузки qtool.ru).
2. **Вручную через API** (защищено `ADMIN_SECRET`):

```bash
curl -X POST "http://localhost:8000/admin/reload" \
     -H "X-Admin-Token: <ADMIN_SECRET>"
# Скачать свежие выгрузки: (по умолчанию download=1)
# Пересобрать из уже скачанных data/uploads: ...?download=0
```

Перезапуск контейнеров при этом не нужен — `api` перечитает каталог по новому mtime.

---

## 5. Проверка приёмки

| Требование | Как проверить |
|---|---|
| Одиночный поиск < 300 мс | `time curl -s -X POST localhost:8000/search/single -H 'Content-Type: application/json' -d '{"query":"CNMG 120408 PM 4325"}'` |
| Пакет на 100 строк < 5 с + .xlsx | виджет → вкладка «Пакетный подбор» → скачать Excel |
| Виджет в iframe | открыть `https://search.qtool.ru/?embed=true` на стороннем домене |
| Бот отвечает на текст/список/файл | написать боту в MAX артикул, список и `.xlsx` |

---

## 6. Переменные окружения

Полный список — в `.env.example`. Ключевые:

| Переменная | Назначение |
|---|---|
| `MAX_BOT_TOKEN` | токен бота MAX |
| `ADMIN_SECRET` | защита `/admin/reload` |
| `BOT_MODE` | `polling` (по умолчанию) или `webhook` |
| `MANAGER_CHAT_ID` | рабочий чат менеджеров для заявок на счёт |
| `MANAGER_EMAIL` | email отдела продаж (при настроенном SMTP) |
| `ALLOWED_ORIGINS` | домены для CORS/iframe |
| `API_BASE_URL` | куда ходят streamlit и бот (имя сервиса `api`) |