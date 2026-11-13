"""
src/reviewer.py - «второе мнение» от LLM (любой OpenAI-совместимый API: Yandex AI Studio, Cloud.ru, MWS или своя модель) поверх внутреннего парсера.

Парсер всегда отвечает сам (текст ответа формирует он). LLM подключается только:
  - в сложных/неясных случаях (нет результатов, ослаблены фильтры, не распознан материал,
    слишком много наводящих вопросов, длинный запрос) и
  - выборочно (AUDIT_SAMPLE_RATE, по умолчанию 15% остальных запросов) — для контроля качества парсера.

LLM возвращает только JSON с поправками параметров и короткими вопросами. Его текст клиенту не показывается.
Поправки применяются лишь к тем параметрам, которые парсер НЕ смог извлечь из запроса; если LLM не согласна
с уже найденным значением, это уходит в примечание и в лог, но результат не меняется (приоритет у парсера).
Если LLM была нужна, но недоступна (ошибка API, лимит, пауза), результат помечается status=unavailable — интерфейс честно
предупреждает об этом, а клиент получает ответ парсера. Все проверки пишутся в data/review_log.jsonl.
"""
import json
import os
import random
import re
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional

LOG_PATH = os.path.join("data", "review_log.jsonl")


def review_enabled() -> bool:
    """Единый признак включения проверки LLM для движка, статуса в UI и самого Reviewer.
    Выключается любой из переменных: ADVISOR_DISABLE_LLM=1 или REVIEW_ENABLED=0."""
    return os.environ.get("ADVISOR_DISABLE_LLM", "0") != "1" and os.environ.get("REVIEW_ENABLED", "1") != "0"

ENUMS = {
    "iso_group": {"P", "M", "K", "N", "S", "H"},
    "operation": {"finishing", "medium", "roughing"},
    "insert_shape": {"C", "W", "T", "D", "S", "V", "R"},
    "clearance_angle": {"N", "C", "P", "B", "D", "E", "F", "G"},
    "category": {"turning_insert", "thread_insert", "groove_insert"},
}
SIZE_CODES = {"06", "09", "11", "12", "15", "16", "19", "22", "25"}

SYSTEM_PROMPT = """Ты — технолог-проверяющий для каталога сменных токарных пластин. Тебе дают запрос клиента, параметры, которые извлёк автоматический парсер, и его лучшие находки. Твоя задача — проверить параметры и вернуть ТОЛЬКО JSON без пояснений и без markdown:
{"verdict":"ok"|"fix","corrections":{"iso_group":null,"operation":null,"insert_shape":null,"clearance_angle":null,"size_code":null,"corner_radius_mm":null,"category":null},"questions":[],"reason":""}
Правила:
- iso_group: P сталь, M нержавеющая (в т.ч. 20Х13, 12Х18Н10Т, AISI 304/316), K чугун, N цветные и неметаллы, S титан и жаропрочные сплавы, H закалённые >45 HRC.
- operation: finishing (чистовая), medium (получистовая), roughing (черновая, удар, корка).
- insert_shape: C ромб 80°, W тригон, T треугольник, D ромб 55°, S квадрат, V ромб 35°, R круг.
- clearance_angle: N 0° (негативная), C 7°, P 11°, B 5°, D 15°, E 20°.
- В corrections пиши значение только если оно прямо следует из запроса клиента; иначе null. Ничего не придумывай.
- questions: не более 3 коротких вопросов клиенту на русском, только действительно нужных для выбора пластины (материал, обработка, форма/размер, внутренняя или наружная). Если запрос понятен — пустой список.
- reason: не более 20 слов."""


class Reviewer:
    def __init__(self, client: Any, sample_rate: Optional[float] = None, max_per_hour: Optional[int] = None, max_per_day: Optional[int] = None, log_path: str = LOG_PATH):
        self.client = client
        env_rate = os.environ.get("AUDIT_SAMPLE_RATE", os.environ.get("REVIEW_SAMPLE_RATE", "0.15"))
        self.sample_rate = float(env_rate) if sample_rate is None else sample_rate
        self.max_per_hour = int(os.environ.get("REVIEW_MAX_PER_HOUR", "60")) if max_per_hour is None else max_per_hour
        # Суточный потолок вызовов LLM: для платного провайдера это ещё и предел расходов
        self.max_per_day = int(os.environ.get("REVIEW_MAX_PER_DAY", "300")) if max_per_day is None else max_per_day
        self.enabled = review_enabled()
        self.log_path = log_path
        self.extra_rules = ""
        self._calls = deque()
        self._down_until = 0.0
        self._lock = threading.Lock()
        self.stats = {"reviewed": 0, "fixed": 0, "disagreed": 0, "unavailable": 0, "skipped_budget": 0}

    # --- когда подключать LLM ------------------------------------------------------------------
    def decide(self, query: str, args: Dict[str, Any], result: Dict[str, Any], completeness: Dict[str, Any], is_analog: bool) -> List[str]:
        """Возвращает список причин проверки (пустой — LLM не нужна)."""
        reasons: List[str] = []
        products = result.get("products") or result.get("available_catalog_matches") or []
        if not products:
            reasons.append("no_results")
        if result.get("relaxation_applied"):
            reasons.append("filters_relaxed")
        has_code = bool(args.get("insert_iso_code"))
        words = len(re.findall(r"\w+", query))
        # Материал не распознан, хотя запрос описательный (в нём может быть марка, которой нет в таблице)
        if not is_analog and not args.get("iso_group") and not has_code and not args.get("insert_shape") and words >= 4:
            reasons.append("material_unknown")
        # Размытый запрос: материал неизвестен и не хватает ещё ≥2 из (форма, размер, вид обработки) — понадобится много вопросов
        missing_key = sum(1 for k in ("insert_shape", "size_code", "operation") if not args.get(k))
        if not has_code and not is_analog and not args.get("iso_group") and missing_key >= 2:
            reasons.append("many_questions")
        if len(re.findall(r"\w+", query)) > 25:
            reasons.append("long_query")
        if not reasons and random.random() < self.sample_rate:
            reasons.append("sample")
        return reasons

    def _budget_ok(self, sample_only: bool) -> bool:
        """Лимиты в час и в сутки. Контрольная выборка не должна съедать больше половины суточного лимита —
        остальное бережём для сложных запросов."""
        now = time.time()
        with self._lock:
            while self._calls and now - self._calls[0] > 86400:
                self._calls.popleft()
            hour = sum(1 for t in self._calls if now - t <= 3600)
            day = len(self._calls)
            if hour >= self.max_per_hour or day >= self.max_per_day or (sample_only and day >= self.max_per_day * 0.5):
                self.stats["skipped_budget"] += 1
                return False
            self._calls.append(now)
            return True

    def usage_today(self) -> int:
        now = time.time()
        with self._lock:
            return sum(1 for t in self._calls if now - t <= 86400)

    # --- вызов LLM -----------------------------------------------------------------------------
    @staticmethod
    def _brief(products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        keys = ("sku", "brand", "grade", "iso_group", "clearance_angle", "corner_radius_mm", "chipbreaker")
        return [{k: p.get(k) for k in keys if p.get(k) not in (None, "")} for p in products[:3]]

    @staticmethod
    def parse_json(text: str) -> Optional[Dict[str, Any]]:
        text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except Exception:
            return None

    @staticmethod
    def sanitize(raw: Dict[str, Any]) -> Dict[str, Any]:
        """Принимаем только значения из белых списков — свободный текст LLM в поиск не попадает."""
        corr_in = raw.get("corrections") if isinstance(raw.get("corrections"), dict) else {}
        corr: Dict[str, Any] = {}
        for k, allowed in ENUMS.items():
            v = corr_in.get(k)
            if isinstance(v, str) and v.strip():
                v = v.strip().upper() if k != "operation" and k != "category" else v.strip().lower()
                if v in allowed:
                    corr[k] = v
        sc = corr_in.get("size_code")
        if sc is not None and str(sc).strip().zfill(2) in SIZE_CODES:
            corr["size_code"] = str(sc).strip().zfill(2)
        rad = corr_in.get("corner_radius_mm")
        try:
            if rad is not None and 0.1 <= float(rad) <= 6.4:
                corr["corner_radius_mm"] = float(rad)
        except (TypeError, ValueError):
            pass
        qs = [str(q).strip() for q in (raw.get("questions") or []) if isinstance(q, (str, int, float)) and str(q).strip()][:3]
        qs = [q[:160] for q in qs]
        reason = str(raw.get("reason") or "")[:200]
        return {"verdict": "fix" if corr else "ok", "corrections": corr, "questions": qs, "reason": reason}

    def ask(self, query: str, args: Dict[str, Any], products: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        shown_args = {k: v for k, v in args.items() if v not in (None, "", []) and k not in ("text_query", "limit", "in_stock_only")}
        user_msg = json.dumps({"запрос": query, "параметры_парсера": shown_args, "находки_парсера": self._brief(products)}, ensure_ascii=False)
        text = self.client.chat([{"role": "system", "content": SYSTEM_PROMPT + (("\nДополнительные правила технолога:\n" + self.extra_rules) if self.extra_rules else "")}, {"role": "user", "content": user_msg}], temperature=0.0, max_tokens=250)
        parsed = self.parse_json(text)
        return self.sanitize(parsed) if parsed else None

    # --- основной вход -------------------------------------------------------------------------
    def _unavailable(self, query: str, reasons: List[str], why: str) -> Dict[str, Any]:
        self.stats["unavailable"] += 1
        out = {"reasons": reasons, "status": "unavailable", "verdict": "none", "applied": {}, "disagreements": {}, "notes": [], "questions": [], "llm_reason": why[:200]}
        self._log({"query": query, **out})
        return out

    def review(self, query: str, args: Dict[str, Any], result: Dict[str, Any], completeness: Dict[str, Any], is_analog: bool = False) -> Optional[Dict[str, Any]]:
        """None — проверка не требовалась (или функция выключена/не настроена).
        Иначе dict со status: "checked" (LLM ответила) или "unavailable" (была нужна, но API не ответил / лимит / пауза)."""
        if not self.enabled or not self.client or not self.client.is_configured():
            return None
        reasons = self.decide(query, args, result, completeness, is_analog)
        if not reasons:
            return None
        sample_only = reasons == ["sample"]
        if time.time() < self._down_until:
            return None if sample_only else self._unavailable(query, reasons, "пауза после ошибки API")
        if not self._budget_ok(sample_only):
            return None if sample_only else self._unavailable(query, reasons, "исчерпан лимит запросов к LLM")
        products = result.get("products") or result.get("available_catalog_matches") or []
        try:
            verdict = self.ask(query, args, products)
        except Exception as e:
            self._down_until = time.time() + 60  # не заставляем каждого клиента ждать таймаут: минута паузы
            return None if sample_only else self._unavailable(query, reasons, str(e))
        if verdict is None:
            return None if sample_only else self._unavailable(query, reasons, "LLM вернула не JSON")

        applied, disagreements = {}, {}
        for k, v in verdict["corrections"].items():
            if args.get(k) in (None, "", 0):
                applied[k] = v
            elif str(args.get(k)).upper() != str(v).upper():
                disagreements[k] = {"parser": args.get(k), "llm": v}
        notes = []
        if "iso_group" in disagreements:
            d = disagreements["iso_group"]
            notes.append(f"Проверка LLM: материал может относиться к группе ISO {d['llm']} (парсер определил {d['parser']}). Уточните материал.")

        self.stats["reviewed"] += 1
        self.stats["fixed"] += 1 if applied else 0
        self.stats["disagreed"] += 1 if disagreements else 0
        out = {"reasons": reasons, "status": "checked", "verdict": verdict["verdict"], "applied": applied, "disagreements": disagreements,
               "notes": notes, "questions": verdict["questions"], "llm_reason": verdict["reason"],
               "model": getattr(self.client, "last_model", "")}
        self._log({"query": query, "parser_args": {k: v for k, v in args.items() if v not in (None, "")}, **out})
        return out

    def _log(self, rec: Dict[str, Any]) -> None:
        try:
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
            rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), **rec}
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass
