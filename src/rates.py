"""
src/rates.py - курсы ЦБ РФ для пересчёта цен из USD/EUR/GBP/CNY в рубли.
Только стандартная библиотека. Курсы кэшируются в data/rates.json и обновляются раз в 12 часов в фоне.
Если сети нет и кэша нет — конвертации нет, цена показывается в исходной валюте (ничего не выдумываем).
"""
import json
import os
import threading
import time
import urllib.request
from typing import Dict, Optional

RATES_URL = "https://www.cbr-xml-daily.ru/daily_json.js"
RATES_PATH = os.path.join("data", "rates.json")
MAX_AGE_SEC = 12 * 3600

_lock = threading.Lock()
_state: Dict = {"rates": {}, "date": "", "fetched_at": 0.0}


def parse_cbr_json(payload: dict) -> Dict[str, float]:
    """Формат cbr-xml-daily: Valute -> {USD: {Nominal, Value}}. Возвращает рублей за 1 единицу валюты."""
    out = {}
    for code, v in (payload.get("Valute") or {}).items():
        try:
            out[code.upper()] = float(v["Value"]) / float(v.get("Nominal") or 1)
        except (KeyError, ValueError, TypeError, ZeroDivisionError):
            continue
    return out


def _load_cache() -> None:
    try:
        with open(RATES_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        _state.update(rates=d.get("rates", {}), date=d.get("date", ""), fetched_at=float(d.get("fetched_at", 0)))
    except Exception:
        pass


def refresh(timeout: int = 10) -> bool:
    try:
        with urllib.request.urlopen(urllib.request.Request(RATES_URL, headers={"User-Agent": "tool-advisor"}), timeout=timeout) as r:
            payload = json.loads(r.read().decode("utf-8"))
        rates = parse_cbr_json(payload)
        if not rates.get("USD"):
            return False
        with _lock:
            _state.update(rates=rates, date=str(payload.get("Date", ""))[:10], fetched_at=time.time())
            os.makedirs(os.path.dirname(RATES_PATH), exist_ok=True)
            with open(RATES_PATH, "w", encoding="utf-8") as f:
                json.dump({"rates": rates, "date": _state["date"], "fetched_at": _state["fetched_at"]}, f)
        return True
    except Exception:
        return False


def init(background: bool = True) -> None:
    _load_cache()
    if time.time() - _state["fetched_at"] > MAX_AGE_SEC and os.environ.get("SKIP_NETWORK_SYNC") != "1":
        if background:
            threading.Thread(target=refresh, daemon=True).start()
        else:
            refresh()


def to_rub(amount: float, currency: str) -> Optional[float]:
    cur = (currency or "RUB").upper()
    if cur == "RUB":
        return amount
    rate = _state["rates"].get(cur)
    return round(amount * rate, 2) if rate else None


def rates_date() -> str:
    return _state.get("date", "")


def set_rates_for_tests(rates: Dict[str, float], date: str = "") -> None:
    _state.update(rates=rates, date=date, fetched_at=time.time())


def price_display(price: float, currency: str, on_request: bool) -> str:
    """Человекочитаемая цена: «цена по запросу», «2 496 ₽» или «≈ 10 240 ₽ (112.46 EUR, курс ЦБ 05.11)»."""
    if on_request or not price or price <= 0:
        return "цена по запросу"
    cur = (currency or "RUB").upper()

    def fmt(x: float) -> str:
        return f"{x:,.0f}".replace(",", " ")

    if cur == "RUB":
        return f"{fmt(price)} ₽"
    orig = f"{price:,.2f}".replace(",", " ") + f" {cur}"
    # Пересчёт по курсу выключен по умолчанию: у позиций qtool.ru с валютой USD/EUR/CNY числа сопоставимы с рублёвыми ценами Rinscom
    # (медиана отношения ≈1 при ожидаемых ≈0,01), то есть валюта в выгрузке, вероятно, указана ошибочно. Включить: ADVISOR_CONVERT_FX=1.
    if os.environ.get("ADVISOR_CONVERT_FX", "0") != "1":
        return f"цена уточняется на сайте (в выгрузке: {orig})"
    rub = to_rub(price, cur)
    if rub is None:
        return orig
    d = rates_date()
    d_txt = f", курс ЦБ {d[8:10]}.{d[5:7]}" if len(d) >= 10 else ", курс ЦБ"
    return f"≈ {fmt(rub)} ₽ ({orig}{d_txt})"
