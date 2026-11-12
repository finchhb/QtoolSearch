#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_ollama.py - Автоматический патчер проекта Tool Advisor v8.4 под локальную модель Ollama.
Выполняет:
  1. Проверку запущенного сервера Ollama (127.0.0.1:11434) и автоопределение скачанной модели (qwen2.5:3b / 1.5b).
  2. Создание резервных копий (.bak) перед изменением файлов.
  3. Создание/обновление .env и data/llm_config.json с оптимизацией под CPU (Pentium G6400, 8 ГБ ОЗУ).
  4. Патч src/llm_client.py (приоритет .env, авто-ключ для локальной Ollama, полный таймаут для одиночной модели, лимит контекста).
  5. Патч app.py (увеличение таймаута HTTP-сокета с 30 до 120 сек для CPU-генерации).
  6. Патч src/reviewer.py (ограничение max_tokens=250 для быстрой генерации JSON-ответа).
  7. Контрольный пинг модели через обновленный LLMClient.
"""
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
OLLAMA_HOST = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5:3b"


def step(msg: str) -> None:
    print(f"\n>>> {msg}")


def ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def warn(msg: str) -> None:
    print(f"  [!] {msg}")


def backup_file(path: str) -> None:
    if os.path.exists(path):
        bak_path = path + ".ollama.bak"
        if not os.path.exists(bak_path):
            shutil.copy2(path, bak_path)
            ok(f"Создана резервная копия: {os.path.relpath(bak_path, ROOT_DIR)}")


def detect_ollama_model() -> str:
    step("Проверка локального сервера Ollama и установленных моделей...")
    url = f"{OLLAMA_HOST}/api/tags"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        models = [m.get("name", "") for m in (data.get("models") or []) if m.get("name")]
        if not models:
            warn(f"Сервер Ollama запущен, но список моделей пуст. Будет прописана {DEFAULT_MODEL}.")
            return DEFAULT_MODEL
        ok(f"Найдены модели в Ollama: {', '.join(models)}")
        for pref in ("qwen2.5:3b", "qwen2.5:1.5b", "qwen2.5:7b", "llama3.2:3b"):
            if pref in models:
                ok(f"Выбрана оптимальная модель: {pref}")
                return pref
        for m in models:
            if m.startswith("qwen"):
                ok(f"Выбрана модель семейства Qwen: {m}")
                return m
        ok(f"Выбрана первая доступная модель: {models[0]}")
        return models[0]
    except Exception as e:
        warn(f"Не удалось опросить {url} ({e}). Убедитесь, что Ollama запущена. В настройки будет прописана {DEFAULT_MODEL}.")
        return DEFAULT_MODEL


def write_env_and_config(model_name: str) -> None:
    step("Настройка файлов конфигурации (.env и data/llm_config.json)...")
    env_path = os.path.join(ROOT_DIR, ".env")
    backup_file(env_path)

    desired_env = {
        "ADVISOR_MODE": "local",
        "LLM_BASE_URL": f"{OLLAMA_HOST}/v1",
        "LLM_API_KEY": "ollama",
        "LLM_MODELS": model_name,
        "LLM_TIMEOUT": "90",
        "LLM_MAX_TOKENS": "250",
        "LLM_EXTRA_PARAMS": '{"options":{"num_ctx":2048,"num_thread":4}}',
        "REVIEW_ENABLED": "1",
        "AUDIT_SAMPLE_RATE": "1.0",
        "REVIEW_MAX_PER_HOUR": "500",
        "REVIEW_MAX_PER_DAY": "5000",
    }

    existing_lines = []
    seen_keys = set()
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8-sig") as f:
            for line in f:
                raw = line.rstrip("\r\n")
                stripped = raw.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    k, _ = stripped.split("=", 1)
                    k = k.strip()
                    if k in desired_env:
                        existing_lines.append(f"{k}={desired_env[k]}")
                        seen_keys.add(k)
                        continue
                existing_lines.append(raw)

    for k, v in desired_env.items():
        if k not in seen_keys:
            existing_lines.append(f"{k}={v}")

    with open(env_path, "w", encoding="utf-8") as f:
        f.write("\n".join(existing_lines).strip() + "\n")
    ok(f"Файл .env обновлен (модель: {model_name}, таймаут: 90с, контекст: 2048 токенов)")

    data_dir = os.path.join(ROOT_DIR, "data")
    os.makedirs(data_dir, exist_ok=True)
    cfg_path = os.path.join(data_dir, "llm_config.json")
    backup_file(cfg_path)
    cfg_data = {
        "api_key": "ollama",
        "base_url": f"{OLLAMA_HOST}/v1",
        "models": [model_name],
    }
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg_data, f, ensure_ascii=False, indent=2)
    ok("Файл data/llm_config.json синхронизирован")


def patch_llm_client(model_name: str) -> None:
    step("Проверка и патч src/llm_client.py...")
    path = os.path.join(ROOT_DIR, "src", "llm_client.py")
    if not os.path.exists(path):
        warn(f"Файл {path} не найден, пропуск.")
        return

    with open(path, "r", encoding="utf-8-sig") as f:
        content = f.read()

    orig = content

    # 1. Задаем дефолтные значения для локальной Ollama
    content = re.sub(
        r'^DEFAULT_BASE_URL\s*=\s*".*"' ,
        f'DEFAULT_BASE_URL = "{OLLAMA_HOST}/v1"',
        content,
        flags=re.M,
    )
    content = re.sub(
        r'^DEFAULT_MODELS\s*=\s*".*"' ,
        f'DEFAULT_MODELS = "{model_name}"',
        content,
        flags=re.M,
    )

    # 2. Увеличиваем дефолтный таймаут с 18 до 90 секунд для CPU
    content = content.replace(
        'os.environ.get("LLM_TIMEOUT", "18")',
        'os.environ.get("LLM_TIMEOUT", "90")',
    )
    content = content.replace(
        'os.environ.get("LLM_MAX_TOKENS", "1200")',
        'os.environ.get("LLM_MAX_TOKENS", "250")',
    )

    # 3. Исправляем перезапись base_url из llm_config.json, если задан LLM_BASE_URL в .env,
    #    и добавляем авто-ключ "ollama" для локального сервера
    old_cfg_block = "\n".join([
        '        env_key = os.environ.get("LLM_API_KEY", "").strip()',
        '        if env_key:',
        '            self.api_key = env_key',
    ])

    new_cfg_block = "\n".join([
        '        env_url = os.environ.get("LLM_BASE_URL", "").strip().rstrip("/")',
        '        if env_url:',
        '            self.base_url = env_url',
        '        env_key = os.environ.get("LLM_API_KEY", "").strip()',
        '        if env_key:',
        '            self.api_key = env_key',
        '        if not self.api_key and ("127.0.0.1" in self.base_url or "localhost" in self.base_url):',
        '            self.api_key = "ollama"',
    ])

    if "if env_url:" not in content and old_cfg_block in content:
        content = content.replace(old_cfg_block, new_cfg_block)

    # 4. Отдаем весь доступный таймаут, если используется одна локальная модель
    old_timeout_calc = "timeout=min(left, max(12.0, self.deadline * 0.7))"
    new_timeout_calc = "timeout=(left if len(self.models) == 1 else min(left, max(12.0, self.deadline * 0.7)))"
    if old_timeout_calc in content:
        content = content.replace(old_timeout_calc, new_timeout_calc)

    if content != orig:
        backup_file(path)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        ok("src/llm_client.py успешно обновлен")
    else:
        ok("src/llm_client.py уже содержит нужные изменения")


def patch_app_py() -> None:
    step("Проверка и патч app.py...")
    path = os.path.join(ROOT_DIR, "app.py")
    if not os.path.exists(path):
        warn(f"Файл {path} не найден, пропуск.")
        return

    with open(path, "r", encoding="utf-8-sig") as f:
        content = f.read()

    orig = content

    # Увеличиваем таймаут HTTP-обработчика с 30 до 120 секунд, чтобы браузер не рвал соединение при работе CPU
    content = re.sub(
        r"(class\s+AdvisorHTTPHandler\([^)]+\):\s*\n\s*)timeout\s*=\s*30\b",
        r"\1timeout = 120",
        content,
    )

    if content != orig:
        backup_file(path)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        ok("app.py обновлен (таймаут HTTP-соединения увеличен до 120 сек)")
    else:
        ok("app.py уже содержит нужные изменения")


def patch_reviewer_py() -> None:
    step("Проверка и патч src/reviewer.py...")
    path = os.path.join(ROOT_DIR, "src", "reviewer.py")
    if not os.path.exists(path):
        warn(f"Файл {path} не найден, пропуск.")
        return

    with open(path, "r", encoding="utf-8-sig") as f:
        content = f.read()

    orig = content

    # Включаем 100% проверку по умолчанию в режиме обучения и ограничиваем max_tokens=250 в Reviewer.ask()
    content = content.replace(
        'os.environ.get("REVIEW_SAMPLE_RATE", "0.15")',
        'os.environ.get("REVIEW_SAMPLE_RATE", "1.0")',
    )
    content = content.replace(
        '{"role": "user", "content": user_msg}], temperature=0.0)',
        '{"role": "user", "content": user_msg}], temperature=0.0, max_tokens=250)',
    )

    if content != orig:
        backup_file(path)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        ok("src/reviewer.py обновлен (AUDIT_SAMPLE_RATE=1.0, max_tokens=250)")
    else:
        ok("src/reviewer.py уже содержит нужные изменения")


def verify_integration() -> None:
    step("Тестирование связки проекта с Ollama...")
    sys.path.insert(0, ROOT_DIR)
    try:
        from src.llm_client import LLMClient
        with open(os.path.join(ROOT_DIR, ".env"), "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")

        client = LLMClient()
        print(f"  Конфигурация клиента: URL={client.base_url}, Модели={client.models}, Таймаут={client.deadline}с")
        is_ok, msg = client.ping()
        if is_ok:
            ok(f"Тест пройден! {msg}")
        else:
            warn(f"Тест вернул предупреждение: {msg}")
    except Exception as e:
        warn(f"Ошибка при тестовом вызове LLMClient: {e}")


def main() -> None:
    print("=" * 68)
    print("  ПАТЧЕР TOOL ADVISOR v8.4 -> OLLAMA (LOCAL CPU EDITION)")
    print("=" * 68)

    if not os.path.exists(os.path.join(ROOT_DIR, "app.py")) or not os.path.exists(os.path.join(ROOT_DIR, "src")):
        print("[ОШИБКА] Запустите этот файл из корневой папки проекта (где лежат app.py и папка src)!")
        input("\nНажмите Enter для выхода...")
        sys.exit(1)

    model_name = detect_ollama_model()
    write_env_and_config(model_name)
    patch_llm_client(model_name)
    patch_app_py()
    patch_reviewer_py()
    verify_integration()

    print("\n" + "=" * 68)
    print("  ГОТОВО! Теперь можно запускать проект через run.bat")
    print("=" * 68)
    try:
        input("\nНажмите Enter для закрытия окна...")
    except EOFError:
        pass


if __name__ == "__main__":
    main()
