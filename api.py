"""
api.py - единый REST API QtoolSearch (FastAPI).

Один процесс держит поисковый индекс в памяти (src.service.SearchService, singleton),
и обслуживает три точки входа: Streamlit-виджет, MAX-бота и (в будущем) сайт.

Эндпоинты:
  GET  /health              — проверка работоспособности + объём каталога.
  POST /search/single       — поиск по одному запросу.
  POST /search/batch        — пакетный поиск (до 500 строк).
  POST /admin/reload        — пересборка каталога (по токену ADMIN_SECRET).
  GET  /                    — краткая справка.

Переменные окружения (см. .env.example): API_HOST, API_PORT, ADMIN_SECRET,
ALLOWED_ORIGINS, RATE_LIMIT_PER_MIN, TRUST_PROXY, SKIP_NETWORK_SYNC, SKIP_RINSCOM_SYNC.
"""
from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.llm_client import load_env_file

load_env_file()  # .env читаем до инициализации сервиса

from src.service import MAX_BATCH, SearchService  # noqa: E402

ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "")
ALLOWED_ORIGINS = [o.strip().rstrip("/") for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
RATE_LIMIT = int(os.environ.get("RATE_LIMIT_PER_MIN", "60"))
TRUST_PROXY = os.environ.get("TRUST_PROXY", "0") == "1"

service: Optional[SearchService] = None
_started = 0.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    global service, _started
    service = SearchService.instance()  # инициализация индекса один раз при старте
    _started = time.time()
    yield


app = FastAPI(title="QtoolSearch API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS or ["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


# --------------------------------------------------------------------------------------------------
# Модели
# --------------------------------------------------------------------------------------------------
class SingleRequest(BaseModel):
    query: str = Field(..., description="Текст запроса, например 'CNMG 120408 PM 4325'")
    limit: int = Field(5, ge=1, le=50)


class BatchRequest(BaseModel):
    queries: List[Any] = Field(..., description="Список строк или объектов {text, qty}")
    limit: int = Field(3, ge=1, le=20)


# --------------------------------------------------------------------------------------------------
# Лимит запросов по IP (простой in-memory, как в app.py)
# --------------------------------------------------------------------------------------------------
_hits: Dict[str, List[float]] = {}
_HITS_LOCK = __import__("threading").Lock()


def _client_ip(request: Request) -> str:
    if TRUST_PROXY:
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            return xff.split(",")[-1].strip()[:64]
    return (request.client.host if request.client else "unknown") or "unknown"


def _allow(ip: str) -> bool:
    if RATE_LIMIT <= 0:
        return True
    now = time.time()
    with _HITS_LOCK:
        q = _hits.setdefault(ip, [])
        q[:] = [t for t in q if now - t < 60]
        if len(q) >= RATE_LIMIT:
            return False
        q.append(now)
        return True


def _guard(request: Request) -> None:
    ip = _client_ip(request)
    if not _allow(ip):
        raise HTTPException(status_code=429, detail="Слишком много запросов. Подождите минуту.")


def _require_admin(authorization: Optional[str], x_admin_token: Optional[str]) -> None:
    if not ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="ADMIN_SECRET не задан на сервере")
    token = x_admin_token or ""
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if token != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Неверный админ-токен")


# --------------------------------------------------------------------------------------------------
# Эндпоинты
# --------------------------------------------------------------------------------------------------
@app.get("/")
def root() -> Dict[str, Any]:
    return {
        "service": "QtoolSearch API",
        "version": "1.0.0",
        "endpoints": ["/health", "/search/single", "/search/batch", "/admin/reload"],
    }


@app.get("/health")
def health() -> JSONResponse:
    st = service.stats() if service else {}
    return JSONResponse({
        "ok": True,
        "uptime_s": round(time.time() - _started, 1) if _started else 0,
        "catalog": {
            "total": st.get("total", 0),
            "in_stock": st.get("in_stock", 0),
            "source": st.get("source_label", ""),
        },
    })


@app.post("/search/single")
def search_single(body: SingleRequest, request: Request) -> Dict[str, Any]:
    _guard(request)
    if not service:
        raise HTTPException(status_code=503, detail="Сервис ещё не готов")
    return service.search_single(body.query, body.limit)


@app.post("/search/batch")
def search_batch(body: BatchRequest, request: Request) -> Dict[str, Any]:
    _guard(request)
    if not service:
        raise HTTPException(status_code=503, detail="Сервис ещё не готов")
    if len(body.queries) > MAX_BATCH:
        raise HTTPException(status_code=413, detail=f"Не более {MAX_BATCH} строк за один запрос")
    results = service.search_batch(body.queries, body.limit)
    found = sum(1 for r in results if r.get("status") == "ok")
    return {"count": len(results), "found": found, "results": results}


@app.post("/admin/reload")
def admin_reload(request: Request, authorization: Optional[str] = Header(default=None),
                 x_admin_token: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    _require_admin(authorization, x_admin_token)
    if not service:
        raise HTTPException(status_code=503, detail="Сервис ещё не готов")
    download = (request.query_params.get("download", "1") != "0")
    return service.reload(download=download)


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("API_HOST", "0.0.0.0")
    port = int(os.environ.get("API_PORT", "8000"))
    uvicorn.run(app, host=host, port=port, workers=1)