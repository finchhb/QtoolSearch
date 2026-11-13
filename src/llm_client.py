"""
src/llm_client.py - клиент любого OpenAI-совместимого API (стандартная библиотека). Используется ТОЛЬКО как проверяющий
(src/reviewer.py): ответ клиенту всегда формирует внутренний парсер.

OpenRouter с 27.06.2026 не принимает запросы из РФ — по умолчанию провайдер НЕ задан. Рабочие варианты (см. README):
  Yandex AI Studio   LLM_BASE_URL=https://ai.api.cloud.yandex.net/v1
                     LLM_MODELS=gpt://<folder_id>/gpt-oss-120b   LLM_EXTRA_HEADERS={"OpenAI-Project":"<folder_id>"}
                     LLM_EXTRA_PARAMS={"reasoning_effort":"low"}
  Cloud.ru           LLM_BASE_URL=https://foundation-models.api.cloud.ru/v1   LLM_MODELS=<id модели из каталога>
  MWS GPT Model Hub  LLM_BASE_URL=<адрес из личного кабинета>   LLM_MODELS=gpt-oss-120b
  Своя модель        Ollama: LLM_BASE_URL=http://localhost:11434/v1  LLM_API_KEY=none  LLM_MODELS=qwen2.5:14b-instruct
Переменные окружения или .env:
  LLM_BASE_URL, LLM_API_KEY, LLM_MODELS (через запятую, по приоритету; при 429/5xx/404 берётся следующая),
  LLM_EXTRA_HEADERS и LLM_EXTRA_PARAMS (JSON-объекты), LLM_MAX_TOKENS (по умолчанию 250),
  LLM_TIMEOUT (общий дедлайн одной проверки, по умолчанию 90 с; для CPU-инференса можно увеличить).
Прокси: urllib сам использует HTTPS_PROXY / HTTP_PROXY. В режиме ADVISOR_MODE=public ключ берётся только из окружения.
"""
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

CONFIG_PATH = os.path.join("data", "llm_config.json")
DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"
DEFAULT_MODELS = "qwen2.5:3b"


def load_env_file(env_path: str = ".env") -> None:
    if not os.path.exists(env_path):
        return
    try:
        with open(env_path, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and v and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass


class LLMError(RuntimeError):
    """Ошибка внешнего API; .code — HTTP-статус (0 — сеть/таймаут)."""

    def __init__(self, msg: str, code: int = 0):
        super().__init__(msg)
        self.code = code


class LLMClient:
    def __init__(self) -> None:
        load_env_file()
        self.public_mode = os.environ.get("ADVISOR_MODE", "local").lower() == "public"
        self.base_url = os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
        self.api_key = ""
        self.models: List[str] = [m.strip() for m in os.environ.get("LLM_MODELS", DEFAULT_MODELS).split(",") if m.strip()]
        self.deadline = float(os.environ.get("LLM_TIMEOUT", "90"))
        self.max_tokens = int(os.environ.get("LLM_MAX_TOKENS", "250"))
        self.extra_headers = self._json_env("LLM_EXTRA_HEADERS")
        self.extra_params = self._json_env("LLM_EXTRA_PARAMS")
        self.last_model = ""
        self.last_error = ""
        self.last_usage: Dict[str, Any] = {}
        self._lock = threading.Lock()
        if not self.public_mode and os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                self.api_key = (cfg.get("api_key") or "").strip()
                self.base_url = (cfg.get("base_url") or self.base_url).rstrip("/")
                if cfg.get("models") and not os.environ.get("LLM_MODELS"):
                    self.models = [m.strip() for m in cfg["models"] if m.strip()]
            except Exception:
                pass
        env_url = os.environ.get("LLM_BASE_URL", "").strip().rstrip("/")
        if env_url:
            self.base_url = env_url
        env_key = os.environ.get("LLM_API_KEY", "").strip()
        if env_key:
            self.api_key = env_key
        if not self.api_key and ("127.0.0.1" in self.base_url or "localhost" in self.base_url):
            self.api_key = "ollama"

    @staticmethod
    def _json_env(name: str) -> Dict[str, Any]:
        try:
            v = json.loads(os.environ.get(name, "") or "{}")
            return v if isinstance(v, dict) else {}
        except ValueError:
            return {}

    @property
    def model(self) -> str:
        return ", ".join(self.models)

    def is_configured(self) -> bool:
        if not (self.api_key and self.models and self.base_url):
            return False
        if "ваш_ключ" in self.api_key.lower() or "your-" in self.base_url:
            return False  # заглушка из data/llm_config.json — не считаем настроенным
        return True

    def save_config(self, api_key: str = "", base_url: str = "", models: str = "") -> None:
        if self.public_mode:
            raise PermissionError("В публичном режиме ключ задаётся только переменной окружения LLM_API_KEY.")
        if api_key.strip():
            self.api_key = api_key.strip()
        if base_url.strip():
            self.base_url = base_url.strip().rstrip("/")
        if models.strip():
            self.models = [m.strip() for m in models.split(",") if m.strip()]
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump({"api_key": self.api_key, "base_url": self.base_url, "models": self.models}, f, ensure_ascii=False, indent=2)

    # --- запросы -----------------------------------------------------------------------------------
    def _call(self, model: str, messages: List[Dict[str, str]], temperature: float, max_tokens: int, timeout: float) -> str:
        headers = {"Content-Type": "application/json", "Accept": "application/json", "Authorization": f"Bearer {self.api_key}"}
        if os.environ.get("LLM_REFERER"):
            headers["HTTP-Referer"] = os.environ["LLM_REFERER"]
        if os.environ.get("LLM_TITLE"):
            headers["X-Title"] = os.environ["LLM_TITLE"]
        headers.update({str(k): str(v) for k, v in self.extra_headers.items()})
        # HTTP-заголовки кодируются в latin-1: кириллица в ключе или доп. заголовке раньше роняла запрос
        # с "'latin-1' codec can't encode characters". Ключ проверяем явно, остальные такие заголовки отбрасываем.
        for name in list(headers):
            try:
                str(headers[name]).encode("latin-1")
            except UnicodeEncodeError as exc:
                if name.lower() == "authorization":
                    raise LLMError(f"{model}: ключ LLM содержит не-ASCII символы — проверьте LLM_API_KEY", 401) from exc
                headers.pop(name, None)
        payload = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        payload.update(self.extra_params)
        req = urllib.request.Request(self.base_url + "/chat/completions", data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise LLMError(f"{model}: HTTP {e.code} {e.read().decode('utf-8', errors='ignore')[:200]}", e.code) from e
        except Exception as e:
            raise LLMError(f"{model}: {e}", 0) from e
        if body.get("error"):
            err = body["error"]
            code = int(err.get("code") or 0) if isinstance(err, dict) and str(err.get("code") or "0").isdigit() else 0
            raise LLMError(f"{model}: {str(err)[:200]}", code)
        text = ((body.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()  # Qwen3/DeepSeek-R1 добавляют блок рассуждений
        self.last_usage = body.get("usage") or {}
        if not text.strip():
            raise LLMError(f"{model}: пустой ответ", 0)
        return text

    def chat(self, messages: List[Dict[str, str]], temperature: float = 0.0, max_tokens: Optional[int] = None) -> str:
        """Пробует модели по очереди в пределах общего дедлайна. Бросает LLMError, если ни одна не ответила."""
        if not self.is_configured():
            raise LLMError("LLM не настроена (нет LLM_API_KEY)")
        t0 = time.time()
        errors = []
        for model in self.models:
            left = self.deadline - (time.time() - t0)
            if left < 2:
                break
            try:
                out = self._call(model, messages, temperature, max_tokens or self.max_tokens, timeout=(left if len(self.models) == 1 else min(left, max(12.0, self.deadline * 0.7))))
                with self._lock:
                    self.last_model, self.last_error = model, ""
                return out
            except LLMError as e:
                errors.append(str(e))
                if e.code in (401, 403):  # неверный ключ — перебирать модели бессмысленно
                    break
        msg = "; ".join(errors) or "превышен дедлайн"
        with self._lock:
            self.last_error = msg[:400]
        raise LLMError(msg, 0)

    def ping(self) -> Tuple[bool, str]:
        if not self.is_configured():
            return False, "Не заданы адрес API, ключ или модель (LLM_BASE_URL / LLM_API_KEY / LLM_MODELS)."
        try:
            self.chat([{"role": "user", "content": "Ответь одним словом: ок"}], max_tokens=300)
            return True, f"Связь есть, ответила модель {self.last_model}."
        except LLMError as e:
            return False, f"Нет связи с LLM: {e}"
