"""
src/engine.py - Центральный движок ИИ-консультанта:
1. Внутренний парсер ISO 1832 + проверка параметров внешней LLM (src/reviewer.py).
2. Мгновенное переключение (< 1 мс) между кэшированными каталогами двух источников:
   - Rinscom.com: https://www.rinscom.com/downloads/price_sale.xlsx (data/catalog_rinscom.csv)
   - qtool.ru:    https://qtool.ru/upload/V/smennie_plastini_ISO_tochenie_03.11.26.xlsx (data/catalog_qtool.csv)
   - Оба источника вместе (data/catalog_both.csv)
3. Автоматическое прикрепление ссылок на страницы магазинов (rinscom.com / qtool.ru, либо ДВЕ ссылки, если пластина есть и там, и там).
4. Гарантированное добавление наводящих уточняющих вопросов (по заднему углу пластины, радиусу при вершине, виду обработки), если они не были указаны в запросе.
"""
import json
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from build_catalog import (
    CATALOG_BOTH_CSV,
    CATALOG_QTOOL_CSV,
    CATALOG_RINSCOM_CSV,
    QTOOL_DEFAULT_XLSX,
    QTOOL_PRICE_URL,
    RINSCOM_DEFAULT_XLSX,
    RINSCOM_PRICE_URL,
    build_catalog,
    build_combined_catalog,
    download_price_sale,
    download_qtool_price,
)
from src import iso1832, rates, training
from src.analogs_engine import AnalogsEngine
from src.catalog_search import CatalogSearchEngine
from src.clarification_advisor import ClarificationAdvisor
from src.hybrid_search import HybridSearchEngine
from src.llm_client import LLMClient
from src.materials_mapping import (
    BRAND_SYNONYMS,
    detect_clearance_angle,
    detect_corner_radius,
    detect_explicit_operation,
    detect_insert_shape,
    detect_iso_group,
    detect_material_note,
    find_unknown_marks,
)
from src.reviewer import Reviewer
from src.site_catalog import SITE_CSV, load_site_catalog

HOLDER_TO_INSERT_MAP = {
    "PCLN": ("CNMG", "C", "12"),
    "MCLN": ("CNMG", "C", "12"),
    "PWLN": ("WNMG", "W", "08"),
    "MWLN": ("WNMG", "W", "08"),
    "PTGN": ("TNMG", "T", "16"),
    "MTGN": ("TNMG", "T", "16"),
    "PDJN": ("DNMG", "D", "15"),
    "MDJN": ("DNMG", "D", "15"),
    "MVJN": ("VNMG", "V", "16"),
    "PVJN": ("VNMG", "V", "16"),
    "PSSN": ("SNMG", "S", "12"),
    "MSSN": ("SNMG", "S", "12"),
    "SCLC": ("CCMT", "C", "09"),
    "SDJC": ("DCMT", "D", "11"),
    "STGC": ("TCMT", "T", "16"),
    "SVJB": ("VBMT", "V", "16"),
    "SVJC": ("VCMT", "V", "16"),
}

INSERT_TO_HOLDERS_INFO = {
    "CNMG": "Наружные державки: PCLNR/L 2525M12, MCLNR/L 2525M12 (или 2020K12); расточные оправки: S25S-PCLNR12, S32T-PCLNR12",
    "WNMG": "Наружные державки: PWLNR/L 2525M08, MWLNR/L 2525M08 (или 2020K08); расточные оправки: S25S-PWLNR08",
    "TNMG": "Наружные державки: PTGNR/L 2525M16, MTGNR/L 2525M16 (или 2020K16); расточные оправки: S25S-PTGNR16",
    "TNMA": "Наружные державки: PTGNR/L 2525M16, MTGNR/L 2525M16; расточные оправки: S25S-PTGNR16",
    "DNMG": "Наружные державки: PDJNR/L 2525M15, MDJNR/L 2525M15 (под DNMG1504/1506); расточные: S25S-PDJNR15",
    "VNMG": "Наружные контурные державки: MVJNR/L 2525M16, PVJNR/L 2525M16",
    "SNMG": "Наружные державки: PSSNR/L 2525M12, MSSNR/L 2525M12, PSDNN 2525M12",
    "CCMT": "Наружные державки: SCLCR/L 2020K09, SCLCR/L 2525M12; расточные оправки: S12M-SCLCR06, S16Q-SCLCR09, S20S-SCLCR09",
    "CCGT": "Наружные державки: SCLCR/L 2020K09, SCLCR/L 1616H09; расточные оправки: S12M-SCLCR06, S16Q-SCLCR09",
    "DCMT": "Наружные державки: SDJCR/L 2020K11, SDJCR/L 2525M11; расточные оправки: S12M-SDJCR07, S16Q-SDJCR11, S20S-SDJCR11",
    "DCGT": "Наружные державки: SDJCR/L 2020K11, SDJCR/L 1616H07; расточные оправки: S12M-SDJCR07, S16Q-SDJCR11",
    "TCMT": "Наружные державки: STGCR/L 2020K16, STGCR/L 2525M16; расточные оправки: S16Q-STGCR11, S20S-STGCR16",
    "TCGT": "Наружные державки: STGCR/L 2020K16; расточные оправки: S16Q-STGCR11, S20S-STGCR16",
    "VBMT": "Наружные державки: SVJBR/L 2020K16, SVJBR/L 2525M16; расточные оправки: S20S-SVJBR16",
}


class ToolAdvisorEngine:
    # Текст текущего запроса хранится отдельно для каждого потока (сервер многопоточный)
    @property
    def _current_user_query(self) -> str:
        return getattr(self._tls, "q", "")

    @_current_user_query.setter
    def _current_user_query(self, value: str) -> None:
        self._tls.q = value

    def __init__(
        self,
        catalog_path: str = CATALOG_QTOOL_CSV,
        price_xlsx_path: str = RINSCOM_DEFAULT_XLSX,
        qtool_xlsx_path: str = QTOOL_DEFAULT_XLSX,
        cross_codes_path: str = "data/cross_codes.csv",
        grades_path: str = "data/grades.csv",
        auto_sync_rinscom: bool = False,
    ):
        self.catalog_path = catalog_path
        self.price_xlsx_path = price_xlsx_path
        self.qtool_xlsx_path = qtool_xlsx_path
        self.cross_codes_path = cross_codes_path
        self.grades_path = grades_path
        self.active_source = "qtool"
        self.price_source_label = "qtool.ru (smennie_plastini_ISO_tochenie_03.11.26.xlsx)"
        self._tls = threading.local()
        self.site_catalog_path = SITE_CSV
        self._site_engine: Optional[CatalogSearchEngine] = None
        self._site_mtime = 0.0
        self._site_lock = threading.Lock()

        if os.path.exists("smennie_plastini_ISO_tochenie_03.11.26.xlsx"):
            self.qtool_xlsx_path = "smennie_plastini_ISO_tochenie_03.11.26.xlsx"
        if os.path.exists("price_sale.xlsx"):
            self.price_xlsx_path = "price_sale.xlsx"
        if not os.path.exists(self.catalog_path) and os.path.exists(self.qtool_xlsx_path):
            build_catalog(self.qtool_xlsx_path, self.catalog_path, self.grades_path)

        self.search_engine = HybridSearchEngine(self.catalog_path, cross_codes_path, grades_path)
        self.analogs_engine = AnalogsEngine(cross_codes_path, grades_path)
        self.clarification_advisor = ClarificationAdvisor()
        self.llm = LLMClient()

        rates.init(background=True)
        self.reviewer = Reviewer(self.llm)

        self.custom_instructions = ""
        # По умолчанию работаем сразу с двумя таблицами (Rinscom + qtool): ADVISOR_DEFAULT_SOURCE=qtool|rinscom меняет это
        if os.environ.get("ADVISOR_DEFAULT_SOURCE", "both").lower() == "both":
            try:
                self.switch_source("both")
            except Exception as e:
                print(f"[источник по умолчанию] не удалось включить обе таблицы: {e}")

    def rebuild_both(self) -> Tuple[bool, str, Dict]:
        """Пересобирает qtool.csv, rinscom.csv и объединённый каталог из xlsx (без устаревшего кэша) и включает режим «оба»."""
        backups = {}
        for path in (CATALOG_QTOOL_CSV, CATALOG_RINSCOM_CSV, CATALOG_BOTH_CSV):
            if os.path.exists(path):
                backups[path] = path + ".bak"
                os.replace(path, path + ".bak")
        try:
            paths = [p for p in (self.price_xlsx_path, self.qtool_xlsx_path) if os.path.exists(p)]
            if not paths:
                raise FileNotFoundError("не найдены xlsx-файлы прайсов")
            build_combined_catalog(paths, CATALOG_BOTH_CSV, self.grades_path)
            for bak in backups.values():
                if os.path.exists(bak):
                    os.remove(bak)
        except Exception as e:
            for path, bak in backups.items():  # откат на предыдущие каталоги
                if os.path.exists(bak):
                    os.replace(bak, path)
            return False, f"Не удалось пересобрать каталоги: {e}", self.get_catalog_stats()
        self.search_engine.reload_catalog(CATALOG_BOTH_CSV, force=True)
        self.active_source = "both"
        self.price_source_label = "Оба источника: Rinscom.com + qtool.ru"
        st = self.get_catalog_stats()
        return True, f"Оба магазина пересобраны: {st['total']} поз., в наличии {st['in_stock']}", st

    def sync_all(self) -> Tuple[bool, str, Dict]:
        """Обновляет ОБЕ таблицы (qtool.ru и Rinscom.com): скачивает прайсы и пересобирает объединённый каталог."""
        msgs = []
        ok_q, m_q = download_qtool_price(QTOOL_DEFAULT_XLSX, url=QTOOL_PRICE_URL)
        msgs.append("qtool.ru: " + ("скачан" if ok_q else "не скачан, использую локальный файл") + f" ({m_q})")
        ok_r, m_r = download_price_sale(RINSCOM_DEFAULT_XLSX, url=RINSCOM_PRICE_URL)
        msgs.append("Rinscom.com: " + ("скачан" if ok_r else "не скачан, использую локальный файл") + f" ({m_r})")
        if not (ok_q or ok_r):  # ничего нового — каталог не трогаем, но обе таблицы должны быть активны
            ok, msg, st = self.switch_source("both")
            return ok, " | ".join(msgs) + f" → {msg}", st
        if ok_q:
            self.qtool_xlsx_path = QTOOL_DEFAULT_XLSX
        if ok_r:
            self.price_xlsx_path = RINSCOM_DEFAULT_XLSX
        ok, msg, st = self.rebuild_both()
        return ok, " | ".join(msgs) + f" → {msg}", st

    def sync_price_from_rinscom(self, url: str = RINSCOM_PRICE_URL) -> Tuple[bool, str, Dict]:
        """Скачивает свежий прайс с https://www.rinscom.com/downloads/price_sale.xlsx и активирует базу Rinscom.com."""
        dest = RINSCOM_DEFAULT_XLSX
        ok, msg = download_price_sale(dest, url=url)
        if ok:
            self.price_xlsx_path = dest
            self.active_source = "rinscom"
            self.price_source_label = f"Rinscom.com ({url})"
            stats = build_catalog(dest, CATALOG_RINSCOM_CSV, self.grades_path)
            if hasattr(self, "search_engine"):
                self.search_engine.reload_catalog(CATALOG_RINSCOM_CSV, force=True)
            return True, f"✅ Rinscom.com: {msg} — в базе {stats['total']} поз. (в наличии: {stats['in_stock']})", self.get_catalog_stats()
        elif os.path.exists(CATALOG_RINSCOM_CSV) or os.path.exists(dest):
            self.active_source = "rinscom"
            self.price_source_label = "Rinscom.com (локальная база price_sale.xlsx)"
            if not os.path.exists(CATALOG_RINSCOM_CSV):
                build_catalog(dest, CATALOG_RINSCOM_CSV, self.grades_path)
            if hasattr(self, "search_engine"):
                self.search_engine.reload_catalog(CATALOG_RINSCOM_CSV)
            st = self.get_catalog_stats()
            return True, f"ℹ️ Загружена локальная база Rinscom.com ({st['total']} поз., в наличии: {st['in_stock']})", st
        else:
            return False, msg, self.get_catalog_stats()

    def sync_price_from_qtool(self, url: str = QTOOL_PRICE_URL) -> Tuple[bool, str, Dict]:
        """Скачивает свежий прайс с https://qtool.ru/upload/V/smennie_plastini_ISO_tochenie_03.11.26.xlsx и активирует базу qtool.ru."""
        dest = QTOOL_DEFAULT_XLSX
        ok, msg = download_qtool_price(dest, url=url)
        if ok:
            self.qtool_xlsx_path = dest
            self.active_source = "qtool"
            self.price_source_label = f"qtool.ru ({url})"
            stats = build_catalog(dest, CATALOG_QTOOL_CSV, self.grades_path)
            if hasattr(self, "search_engine"):
                self.search_engine.reload_catalog(CATALOG_QTOOL_CSV, force=True)
            return True, f"✅ qtool.ru: {msg} — в базе {stats['total']} поз. (в наличии: {stats['in_stock']})", self.get_catalog_stats()
        elif os.path.exists(CATALOG_QTOOL_CSV) or os.path.exists(dest):
            self.active_source = "qtool"
            self.price_source_label = "qtool.ru (локальная база smennie_plastini_ISO_tochenie_03.11.26.xlsx)"
            if not os.path.exists(CATALOG_QTOOL_CSV):
                build_catalog(dest, CATALOG_QTOOL_CSV, self.grades_path)
            if hasattr(self, "search_engine"):
                self.search_engine.reload_catalog(CATALOG_QTOOL_CSV)
            st = self.get_catalog_stats()
            return True, f"ℹ️ Включена локальная база qtool.ru ({st['total']} поз., в наличии: {st['in_stock']})", st
        else:
            return False, msg, self.get_catalog_stats()

    def switch_source(self, source_key: str) -> Tuple[bool, str, Dict]:
        """Мгновенное переключение между кэшированными каталогами (< 1 мс из RAM-кэша)."""
        source_key = (source_key or "rinscom").strip().lower()
        if source_key == "qtool":
            if not os.path.exists(CATALOG_QTOOL_CSV) and os.path.exists(self.qtool_xlsx_path):
                build_catalog(self.qtool_xlsx_path, CATALOG_QTOOL_CSV, self.grades_path)
            if os.path.exists(CATALOG_QTOOL_CSV):
                self.active_source = "qtool"
                self.price_source_label = f"qtool.ru ({os.path.basename(self.qtool_xlsx_path)})"
                self.search_engine.reload_catalog(CATALOG_QTOOL_CSV)
                st = self.get_catalog_stats()
                return True, f"Активный источник: qtool.ru ({st['total']} поз., в наличии: {st['in_stock']})", st
            return self.sync_price_from_qtool()

        elif source_key == "both":
            if not os.path.exists(CATALOG_BOTH_CSV):
                paths = [p for p in (self.price_xlsx_path, self.qtool_xlsx_path) if os.path.exists(p)]
                if paths:
                    build_combined_catalog(paths, CATALOG_BOTH_CSV, self.grades_path)
            if os.path.exists(CATALOG_BOTH_CSV):
                self.active_source = "both"
                self.price_source_label = "Оба источника: Rinscom.com + qtool.ru"
                self.search_engine.reload_catalog(CATALOG_BOTH_CSV)
                st = self.get_catalog_stats()
                return True, f"Активный источник: Оба магазина (Rinscom.com + qtool.ru) — {st['total']} поз. (в наличии: {st['in_stock']})", st
            return False, "Локальные файлы источников не найдены.", self.get_catalog_stats()

        else:
            if not os.path.exists(CATALOG_RINSCOM_CSV) and os.path.exists(self.price_xlsx_path):
                build_catalog(self.price_xlsx_path, CATALOG_RINSCOM_CSV, self.grades_path)
            if os.path.exists(CATALOG_RINSCOM_CSV):
                self.active_source = "rinscom"
                self.price_source_label = f"Rinscom.com ({os.path.basename(self.price_xlsx_path)})"
                self.search_engine.reload_catalog(CATALOG_RINSCOM_CSV)
                st = self.get_catalog_stats()
                return True, f"Активный источник: Rinscom.com ({st['total']} поз., в наличии: {st['in_stock']})", st
            return self.sync_price_from_rinscom()

    def load_custom_xlsx_bytes(self, file_bytes: bytes, filename: str = "custom_price.xlsx") -> Tuple[bool, str, Dict]:
        dest = os.path.join("data", os.path.basename(filename) or "custom_price.xlsx")
        custom_csv = "data/catalog_custom.csv"
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        try:
            with open(dest, "wb") as f:
                f.write(file_bytes)
            stats = build_catalog(dest, custom_csv, self.grades_path)
            fmt_label = "qtool.ru" if stats.get("detected_format") == "qtool" else "Rinscom 1C"
            self.active_source = "qtool" if stats.get("detected_format") == "qtool" else "rinscom"
            self.price_source_label = f"{filename} (формат {fmt_label})"
            self.search_engine.reload_catalog(custom_csv, force=True)
            return True, f"Файл '{filename}' ({fmt_label}) успешно загружен: {stats['total']} поз. (в наличии: {stats['in_stock']})", self.get_catalog_stats()
        except Exception as e:
            return False, f"Ошибка разбора файла '{filename}': {e}", self.get_catalog_stats()

    def get_site_engine(self) -> Optional[CatalogSearchEngine]:
        """Поиск по выгрузке qtool.ru (/upload/*.xlsx). Перезагружается при обновлении CSV без перезапуска сервера."""
        try:
            mtime = os.path.getmtime(self.site_catalog_path)
        except OSError:
            return None
        if self._site_engine is not None and mtime == self._site_mtime:
            return self._site_engine
        with self._site_lock:
            if self._site_engine is not None and mtime == self._site_mtime:
                return self._site_engine
            try:
                items = load_site_catalog(self.site_catalog_path)
            except Exception as e:
                print(f"[каталог сайта] не удалось загрузить {self.site_catalog_path}: {e}")
                items = []
            self._site_engine = CatalogSearchEngine(items) if items else None
            self._site_mtime = mtime
        return self._site_engine

    def get_catalog_stats(self) -> Dict[str, Any]:
        site = self.get_site_engine()
        if site and site.items:
            by_family: Dict[str, int] = {}
            for it in site.items:
                fam = it.get("family") or "other"
                by_family[fam] = by_family.get(fam, 0) + 1
            return {
                "total": len(site.items),
                "in_stock": sum(1 for x in site.items if int(x.get("stock") or 0) > 0),
                "in_both_stores": 0,
                "by_family": by_family,
                "active_source": "site",
                "source_label": "qtool.ru (/upload, все группы)",
                "site_catalog": True,
            }
        cat = self.search_engine.catalog if hasattr(self, "search_engine") else []
        return {
            "total": len(cat),
            "turning_insert": sum(1 for x in cat if x.get("category") == "turning_insert"),
            "thread_insert": sum(1 for x in cat if x.get("category") == "thread_insert"),
            "groove_insert": sum(1 for x in cat if x.get("category") == "groove_insert"),
            "in_stock": sum(1 for x in cat if int(x.get("stock") or 0) > 0),
            "in_both_stores": sum(1 for x in cat if str(x.get("in_both_stores")) == "1"),
            "active_source": getattr(self, "active_source", "rinscom"),
            "source_label": self.price_source_label,
        }

    def set_custom_instructions(self, instructions: str):
        self.reviewer.extra_rules = (instructions or "").strip()
        self.custom_instructions = instructions.strip()

    def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name == "search_products":
            return self._tool_search_products(arguments)
        elif tool_name == "get_analogs":
            return self._tool_get_analogs(arguments)
        elif tool_name == "get_stock_price":
            return self._tool_get_stock_price(arguments)
        elif tool_name == "find_compatible":
            return self._tool_find_compatible(arguments)
        elif tool_name == "ask_clarification":
            return self._tool_ask_clarification(arguments)
        elif tool_name == "handoff_to_manager":
            return {
                "status": "handed_off",
                "reason": arguments.get("reason", "Нестандартный запрос передан технологу"),
                "summary": arguments.get("summary", ""),
                "message": "Запрос зафиксирован для ведущего инженера-технолога.",
            }
        else:
            return {"error": f"Неизвестная функция: {tool_name}"}

    def _tool_search_products(self, args: Dict[str, Any]) -> Dict[str, Any]:
        mat = args.get("workpiece_material")
        iso_group = args.get("iso_group")
        if mat and not iso_group:
            iso_group = detect_iso_group(mat)

        category = args.get("category")
        if not category:
            if args.get("pitch_value") or args.get("thread_profile") or args.get("operation") == "threading":
                category = "thread_insert"
            elif args.get("groove_width_mm") or args.get("family_code") or args.get("operation") == "grooving":
                category = "groove_insert"
            else:
                category = "turning_insert"

        raw_q = self._current_user_query or ""
        clearance_angle = args.get("clearance_angle")
        if raw_q and category == "turning_insert":
            explicit_ca = detect_clearance_angle(raw_q)
            if not explicit_ca and clearance_angle:
                clearance_angle = None
            elif explicit_ca and not clearance_angle:
                clearance_angle = explicit_ca

        operation = args.get("operation") or args.get("application_type")
        if raw_q and category == "turning_insert":
            explicit_op = detect_explicit_operation(raw_q)
            if not explicit_op and operation in ("finishing", "semi_finishing", "medium", "roughing"):
                operation = None

        req_limit = min(int(args.get("limit") or 5), 6)

        req_grade = args.get("grade")
        req_cb = args.get("chipbreaker")
        res = self.search_engine.search(
            category=category,
            iso_group=iso_group,
            operation=operation,
            insert_iso_code=args.get("insert_iso_code"),
            insert_shape=args.get("insert_shape"),
            clearance_angle=clearance_angle,
            size_code=args.get("size_code"),
            corner_radius_mm=args.get("corner_radius_mm"),
            chipbreaker=args.get("chipbreaker"),
            grade=args.get("grade"),
            coating=args.get("coating"),
            brand=args.get("brand"),
            pitch_value=args.get("pitch_value"),
            thread_profile=args.get("thread_profile"),
            side=args.get("side"),
            hand=args.get("hand"),
            groove_width_mm=args.get("groove_width_mm"),
            family_code=args.get("family_code"),
            text_query=args.get("text_query"),
            in_stock_only=args.get("in_stock_only", True),
            limit=req_limit,
            active_source=self.active_source,
        )
        res["source"] = self.price_source_label

        # Если в запросе был указан сплав (например, IS7015) или стружколом, прикрепляем кросс-таблицу аналогов
        if req_grade or req_cb:
            cross_list = self.analogs_engine.find_grade_cross(req_grade or "", fallback_iso=iso_group, fallback_op=operation)
            cb_analogs = self.analogs_engine.get_chipbreaker_analogs(req_cb, iso_group=iso_group, operation=operation)
            if cross_list:
                res["analog_cross_info"] = cross_list[0]
            if cb_analogs:
                res["chipbreaker_analogs"] = cb_analogs

            # Проверяем, есть ли в выдаче точный запрошенный сплав; если нет — приоритизируем аналоги из кросс-таблицы!
            prods_now = res.get("products") or []
            has_exact_grade = bool(req_grade and any((p.get("grade") or "").upper() == req_grade.upper() for p in prods_now))
            if req_grade and not has_exact_grade and cross_list:
                c_info = cross_list[0]
                analog_grade_tokens = set()
                for g_str in c_info.get("analogs", {}).values():
                    for g_tok in re.split(r"[,/]+", g_str):
                        g_clean = re.sub(r"\(.*?\)", "", g_tok).strip().upper()
                        if g_clean:
                            analog_grade_tokens.add(g_clean)
                # Ищем в каталоге позиции той же геометрии и группы ISO с марками-аналогами из таблицы
                analog_matches = []
                seen_skus = set()
                for ag in sorted(analog_grade_tokens):
                    sub = self.search_engine.search(
                        category=category,
                        iso_group=iso_group or c_info.get("iso_group"),
                        insert_iso_code=args.get("insert_iso_code"),
                        insert_shape=args.get("insert_shape"),
                        clearance_angle=clearance_angle,
                        size_code=args.get("size_code"),
                        corner_radius_mm=args.get("corner_radius_mm"),
                        grade=ag,
                        in_stock_only=args.get("in_stock_only", True),
                        limit=3,
                        active_source=self.active_source,
                    )
                    for sp in sub.get("products") or []:
                        if sp["sku"] not in seen_skus:
                            seen_skus.add(sp["sku"])
                            analog_matches.append(sp)
                for p in prods_now:
                    if p["sku"] not in seen_skus:
                        seen_skus.add(p["sku"])
                        analog_matches.append(p)
                if analog_matches:
                    res["products"] = analog_matches[:req_limit]
                    res["relaxation_applied"] = True
                    res["relaxation_notes"] = (
                        f"Точного сплава `{req_grade}` нет в остатках — подобраны прямые аналоги для группы **ISO {iso_group or c_info.get('iso_group')}** "
                        f"({c_info.get('operation_desc', '')})"
                    )

        # Сразу добавляем информацию о подходящих державках в ответ search_products, чтобы не нужен был 2-й вызов функции
        prods = res.get("products") or []
        if prods and category == "turning_insert":
            ins_prefix = (prods[0].get("iso_code") or "")[:4]
            if ins_prefix in INSERT_TO_HOLDERS_INFO:
                res["compatible_holders_info"] = INSERT_TO_HOLDERS_INFO[ins_prefix]

        if self.custom_instructions:
            res["TECHNOLOGIST_CUSTOM_PROMPT_RULES"] = self.custom_instructions
        return res

    def _tool_get_analogs(self, args: Dict[str, Any]) -> Dict[str, Any]:
        ref_code = args.get("reference_code", "").strip()
        ref_brand = args.get("reference_brand")
        target_brands = args.get("target_brands", [])
        in_stock_only = args.get("in_stock_only", True)

        extracted = self.analogs_engine.extract_grade_and_sku(ref_code)
        grade_candidate = extracted["grade"]

        if not grade_candidate:
            parsed = self.analogs_engine.parse_sku_elements(ref_code)
            grade_candidate = parsed["grade"] or ref_code

        cross_res = self.analogs_engine.find_grade_cross(grade_candidate)
        matched_analogs = []
        iso_group = ""

        if cross_res:
            first_match = cross_res[0]
            iso_group = first_match["iso_group"]
            for brand_name, grade_val in first_match["analogs"].items():
                if target_brands and not any(tb.lower() in brand_name.lower() for tb in target_brands):
                    continue
                matched_analogs.append({"brand": brand_name, "grade": grade_val})
        else:
            g_info = self.analogs_engine.grades.get(grade_candidate.upper(), {})
            iso_raw = g_info.get("iso_groups") or g_info.get("iso_p") or ""
            if iso_raw and iso_raw[0] in "PMKNSH":
                iso_group = iso_raw[0]

        if not iso_group:
            iso_group = detect_iso_group(ref_code) or "P"

        shape_detected = detect_insert_shape(ref_code)
        ca_detected = detect_clearance_angle(ref_code)
        radius_detected = detect_corner_radius(ref_code)
        iso_code_match = re.search(r"\b([CWTDSVR][NCTBPEFG][MGU][A-Z]\d{6})\b", ref_code.upper().replace(" ", ""))
        insert_iso_code = iso_code_match.group(1) if iso_code_match else None

        recommended_products = []
        seen_skus = set()

        for a in matched_analogs:
            found = self.search_engine.search(
                category="turning_insert",
                insert_iso_code=insert_iso_code,
                insert_shape=shape_detected or None,
                clearance_angle=ca_detected or None,
                corner_radius_mm=radius_detected,
                grade=a["grade"],
                in_stock_only=in_stock_only,
                limit=4,
                active_source=self.active_source,
            )
            for p in found["products"]:
                if p["sku"] not in seen_skus:
                    seen_skus.add(p["sku"])
                    recommended_products.append(p)

        if len(recommended_products) < 5:
            fallback = self.search_engine.search(
                category="turning_insert",
                iso_group=iso_group,
                insert_iso_code=insert_iso_code,
                insert_shape=shape_detected or None,
                clearance_angle=ca_detected or None,
                corner_radius_mm=radius_detected,
                in_stock_only=in_stock_only,
                limit=5,
                active_source=self.active_source,
            )
            for p in fallback["products"]:
                if p["sku"] not in seen_skus:
                    seen_skus.add(p["sku"])
                    recommended_products.append(p)

        return {
            "source": self.price_source_label,
            "source_reference": ref_code,
            "detected_grade": grade_candidate,
            "detected_brand": ref_brand or (cross_res[0]["detected_brand"] if cross_res else "Внешний бренд"),
            "iso_group": iso_group,
            "grade_equivalents": matched_analogs,
            "available_catalog_matches": recommended_products[:6],
        }

    def _tool_get_stock_price(self, args: Dict[str, Any]) -> Dict[str, Any]:
        skus = [s.strip().upper() for s in args.get("skus", []) if s]
        results = []
        for item in self.search_engine.catalog:
            sku_up = (item.get("sku") or "").upper()
            c1c_up = (item.get("code_1c") or "").upper()
            if sku_up in skus or c1c_up in skus or any(q in sku_up for q in skus):
                results.append({
                    "sku": item["sku"],
                    "code_1c": item.get("code_1c", ""),
                    "name": item["name"],
                    "brand": item.get("brand", ""),
                    "price": item["price"],
                    "currency": item.get("currency", "RUB"),
                    "stock": item["stock"],
                    "source_site": item.get("source_site", ""),
                    "shop_links_markdown": self.search_engine.format_store_links(item, active_source=self.active_source),
                    "status": f"В наличии на складе ({item['stock']} шт.)" if item["stock"] > 0 else "Нет в остатках",
                })
        return {"source": self.price_source_label, "items": results[:15]}

    def _tool_find_compatible(self, args: Dict[str, Any]) -> Dict[str, Any]:
        sku_raw = args.get("sku", "").strip().upper()
        sku_clean = re.sub(r"[\s_-]+", "", sku_raw)

        insert_prefix = None
        shape = None
        size_code = None

        for h_pref, (ins_pref, sh, def_sz) in HOLDER_TO_INSERT_MAP.items():
            if h_pref in sku_clean:
                insert_prefix = ins_pref
                shape = sh
                m_sz = re.search(r"[A-Z](\d{2})$", sku_clean)
                size_code = m_sz.group(1) if m_sz else def_sz
                break

        if insert_prefix:
            found = self.search_engine.search(
                category="turning_insert",
                insert_shape=shape,
                clearance_angle=insert_prefix[1],
                size_code=size_code,
                in_stock_only=True,
                limit=6,
                active_source=self.active_source,
            )
            return {
                "source": self.price_source_label,
                "query_type": "inserts_for_holder",
                "holder_code": sku_raw,
                "compatible_insert_standard": f"{insert_prefix} {size_code}..",
                "compatible_items": found["products"],
            }

        m_ins = re.search(r"\b([CWTDSVR][NCTBPEFG][MGU][A-Z])(\d{2})?", sku_clean)
        ins_type = m_ins.group(1) if m_ins else "CNMG"
        holder_rec = INSERT_TO_HOLDERS_INFO.get(ins_type, "Стандартные державки ISO по форме, заднему углу и размеру пластины")
        found_ins = self.search_engine.search(
            category="turning_insert",
            insert_iso_code=sku_clean[:10] if m_ins else None,
            insert_shape=ins_type[0] if m_ins else None,
            clearance_angle=ins_type[1] if m_ins else None,
            in_stock_only=True,
            limit=5,
            active_source=self.active_source,
        )
        return {
            "source": self.price_source_label,
            "query_type": "holders_and_matching_inserts",
            "insert_code": sku_raw,
            "recommended_holder_standards": holder_rec,
            "matching_inserts_in_stock": found_ins["products"],
        }

    def _tool_ask_clarification(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "action": "clarification_requested",
            "missing_parameters": args.get("missing_parameters", []),
            "message": args.get("clarification_message", ""),
        }

    # ------------------------------------------------------------------------------------------
    # Основной вход: внутренний парсер отвечает всегда; LLM лишь проверяет параметры (src/reviewer.py)
    # ------------------------------------------------------------------------------------------
    def _process_multi(self, positions: List[Dict[str, Any]], allow_review: bool) -> Dict[str, Any]:
        """Несколько позиций в одном запросе: каждая ищется отдельно, ответ объединяется."""
        texts, all_prods, steps, first = [], [], [], None
        seen = set()
        for i, pos in enumerate(positions, 1):
            r = self.process_query_autonomous(pos["text"], allow_review=allow_review)
            if first is None:
                first = r
            qty = f" — {pos['qty']} шт" if pos.get("qty") else ""
            texts.append(f"## Позиция {i}: {pos['text']}{qty}\n\n{r.get('response_text', '')}")
            for pr in (r.get("tool_result") or {}).get("products") or []:
                if pr.get("sku") not in seen:
                    seen.add(pr.get("sku"))
                    all_prods.append(pr)
            steps.extend(r.get("tool_steps") or [])
        merged = dict(first)
        merged.update({"decision": "multi_position", "response_text": "\n\n---\n\n".join(texts),
                       "tool_result": {**(first.get("tool_result") or {}), "products": all_prods[:30]},
                       "tool_steps": steps, "positions": positions})
        return merged

    def process_query(self, user_query: str, chat_history: Optional[List[Dict[str, Any]]] = None, force_local: bool = False) -> Dict[str, Any]:
        # LLM не используется: подбор полностью детерминированный (парсер + каталог сайта).
        allow_review = False
        positions = iso1832.split_positions(user_query)
        if len(positions) > 1:
            return self._process_multi(positions, allow_review)
        res = self.process_query_autonomous(user_query, allow_review=allow_review)
        res["provider"] = "site_catalog"
        res["model"] = "deterministic-catalog"
        res.setdefault("llm_status", "not_needed")
        return res

    def _detect_search_args(self, user_query: str) -> Dict[str, Any]:
        lower = user_query.lower()
        category = "turning_insert"
        if any(w in lower for w in ["резьб", "16er", "16ir", "11ir", "22er", "ag60", "a60"]):
            category = "thread_insert"
        elif any(w in lower for w in ["канав", "отрез", "mgmn", "mggn", "tgf", "8gr"]):
            category = "groove_insert"

        detected_op = detect_explicit_operation(user_query)
        det = iso1832.detect_all(user_query)

        # Извлекаем сплав, стружколом и его ISO-группу через AnalogsEngine
        ext = self.analogs_engine.extract_grade_and_sku(user_query)
        detected_grade = ext.get("grade") or None
        detected_cb = ext.get("chipbreaker") or None
        iso_from_grade = ext.get("iso_group") or None
        op_from_grade = ext.get("operation") or None

        iso_final = detect_iso_group(user_query) or iso_from_grade or None
        op_final = detected_op if (category == "turning_insert" and detected_op) else (op_from_grade if category == "turning_insert" else None)

        detected_brand = None
        for syn, b_norm in BRAND_SYNONYMS.items():
            if re.search(rf"(?<![a-zа-я0-9]){re.escape(syn)}(?![a-zа-я0-9])", lower):
                detected_brand = b_norm
                break
        if not detected_brand and self.custom_instructions:
            ci_low = self.custom_instructions.lower()
            for syn, b_norm in BRAND_SYNONYMS.items():
                if syn in ci_low:
                    detected_brand = b_norm
                    break

        return {
            "category": category,
            "iso_group": iso_final,
            "operation": op_final,
            "insert_iso_code": det["code"] or None,
            "insert_shape": det["shape"] or None,
            "clearance_angle": det["clearance"] or None,
            "size_code": det["size_code"] or None,
            "corner_radius_mm": det["radius"],
            "chipbreaker": detected_cb,
            "grade": detected_grade,
            "brand": detected_brand,
            "text_query": user_query,
            "in_stock_only": True,
            "limit": 6,
        }

    _unrec_lock = threading.Lock()
    _CLASS_RANGE = {"finishing": (5, 20), "semi_finishing": (15, 30), "medium": (15, 30), "roughing": (25, 40)}
    _ISO_NAMES = {"P": "сталь", "M": "нержавеющая сталь", "K": "чугун"}
    _OP_NAMES = {"finishing": "чистовая", "semi_finishing": "получистовая", "medium": "получистовая", "roughing": "черновая"}

    _SITE_FAMILY_TITLES = {
        "insert": "Пластины", "drill": "Сверла", "mill": "Фрезы", "tap": "Метчики",
        "die": "Плашки", "reamer": "Развертки", "countersink": "Зенковки и фаскосниматели",
        "holder": "Державки и резцы", "accessory": "Оснастка и крепеж",
        "measuring": "Измерительный инструмент", "saw": "Пилы и диски",
    }
    _SITE_ATTR_FMT = (
        ("diameter_mm", "Ø {} мм"), ("bore_mm", "посадочное Ø {} мм"),
        ("shank_section", "сечение {} мм"), ("shank_mm", "хвостовик {} мм"),
        ("length_mm", "длина {} мм"), ("cutting_length_mm", "раб. длина {} мм"),
        ("thickness_mm", "толщина {} мм"), ("width_mm", "ширина {} мм"),
        ("teeth", "зубьев {}"), ("thread", "резьба {}"), ("pitch_mm", "шаг {} мм"),
        ("iso_code", "код {}"), ("insert_code", "пластина {}"), ("size_code", "размер {}"),
        ("insert_shape", "форма {}"), ("corner_radius_mm", "R {} мм"), ("radius_mm", "радиус {} мм"),
        ("angle_deg", "угол {}°"), ("clearance_angle", "задний угол {}"),
        ("chipbreaker", "стружколом {}"), ("operation", "обработка {}"),
        ("holder_code", "код державки {}"), ("insert_size_code", "пластина {}"),
        ("compatible_inserts", "под пластины {}"),
        ("collet_series", "серия {}"), ("clamp_range", "зажим {} мм"), ("clamp_mm", "под Ø {} мм"),
        ("standard", "стандарт {}"), ("coating", "покрытие {}"), ("material", "материал {}"),
        ("tolerance", "допуск {}"), ("hrc", "{} HRC"), ("ld_ratio", "{}-D"),
        ("secondary_iso", "также ISO {}"),
    )

    def _load_docs_classes(self) -> Dict[str, Dict[str, Any]]:
        """Классы применяемости сплавов (P05…K40) из справочника компании: data/grades_docs.csv (создаёт import_docs.py)."""
        if getattr(self, "_docs_classes", None) is None:
            self._docs_classes = {}
            try:
                import csv
                with open(os.path.join("data", "grades_docs.csv"), "r", encoding="utf-8-sig", newline="") as f:
                    for row in csv.DictReader(f):
                        cls = [c for c in (row.get("classes") or "").split() if c]
                        if cls:
                            self._docs_classes[row["grade"].upper()] = {"brand": row.get("brand", ""), "classes": cls}
            except Exception:
                pass
        return self._docs_classes

    def _docs_grade_hint(self, iso: Optional[str], operation: Optional[str]) -> str:
        """Подсказка по методичке (таблица аналогов сплавов): какие сплавы Deskar/INTOOL/ZCC-CT рекомендованы для группы ISO и вида обработки, и сколько позиций есть в наличии."""
        if iso not in self._ISO_NAMES:
            return ""
        docs = self._load_docs_classes()
        if not docs:
            return ""
        lo, hi = self._CLASS_RANGE.get(operation or "", (0, 99))
        stock = {}
        for it in self.search_engine.catalog:
            if it.get("stock", 0) > 0:
                g = (it.get("grade") or "").upper()
                stock[g] = stock.get(g, 0) + 1
        in_stock: Dict[str, List[str]] = {}
        missing: List[str] = []
        for g, d in sorted(docs.items()):
            nums = [int(c[1:]) for c in d["classes"] if c[0] == iso and c[1:].isdigit()]
            if not nums or not any(lo <= n <= hi for n in nums):
                continue
            if stock.get(g):
                in_stock.setdefault(d["brand"], []).append(f"{g} ({stock[g]} поз.)")
            else:
                missing.append(g)
        by_brand = in_stock
        if not by_brand and not missing:
            return ""
        op_txt = f", {self._OP_NAMES[operation]}" if operation in self._OP_NAMES else ""
        parts = "; ".join(f"{b}: {', '.join(v)}" for b, v in by_brand.items()) or "в наличии подходящих сплавов из таблицы нет"
        tail = f" Нет в наличии: {', '.join(missing[:4])}{'…' if len(missing) > 4 else ''}." if missing else ""
        return f"📘 По методичке (аналоги сплавов), {self._ISO_NAMES[iso]} (ISO {iso}){op_txt} — {parts}.{tail}"


    def _log_unrecognized(self, query: str) -> None:
        """Запросы, где парсер не нашёл ни материал, ни код пластины: технолог добавляет строки в data/materials.csv."""
        try:
            path = os.path.join("data", "unrecognized_queries.jsonl")
            with self._unrec_lock:
                if os.path.exists(path) and os.path.getsize(path) > 2_000_000:
                    return
                with open(path, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "query": query[:300]}, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _llm_meta(self, rv: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """llm_status: not_needed | checked | unavailable. Плашка в интерфейсе строится по нему."""
        if not rv:
            return {"llm_checked": False, "llm_status": "not_needed"}
        return {"llm_checked": rv["status"] == "checked", "llm_status": rv["status"], "llm_reasons": rv["reasons"],
                "llm_verdict": rv["verdict"], "llm_applied": rv["applied"], "llm_disagreements": rv["disagreements"]}

    # ------------------------------------------------------------------------------------------
    # Каталог сайта qtool.ru: ответ по всем группам (без LLM)
    # ------------------------------------------------------------------------------------------
    def _site_answer(self, user_query: str, site: CatalogSearchEngine) -> Dict[str, Any]:
        res = site.search(user_query, limit=8, in_stock_only=True)
        if not res.get("products"):
            self._log_unrecognized(user_query)
        attrs = res.get("parsed") or {}
        parsed = {
            "iso": attrs.get("iso_group") or "", "operation": attrs.get("operation") or "",
            "shape": attrs.get("insert_shape") or "", "size": attrs.get("size_code") or "",
            "code": res.get("insert_code") or attrs.get("iso_code") or "",
            "radius": attrs.get("corner_radius_mm"),
        }
        return {
            "mode": "site_catalog", "decision": "site_search", "tool_called": "catalog_search",
            "tool_result": res,
            "tool_steps": [{"step": 1, "function": "catalog_search", "arguments": {"query": user_query}, "result": res}],
            "response_text": self._format_site_response(res), "parsed": parsed,
            "llm_checked": False, "llm_status": "not_needed",
        }

    @staticmethod
    def _fmt_num(value: Any) -> str:
        if isinstance(value, float):
            return f"{value:g}".replace(".", ",")
        return str(value)

    @staticmethod
    def _plural(n: int, one: str, few: str, many: str) -> str:
        n = abs(int(n))
        if n % 100 in (11, 12, 13, 14):
            return many
        if n % 10 == 1:
            return one
        if n % 10 in (2, 3, 4):
            return few
        return many

    def _site_attr_parts(self, product: Dict[str, Any]) -> List[str]:
        attrs = product.get("attrs") or {}
        parts = []
        for key, fmt in self._SITE_ATTR_FMT:
            value = attrs.get(key)
            if value in (None, "", []):
                continue
            if key == "shank_mm" and attrs.get("shank_section"):
                continue
            if key == "operation":
                value = self._OP_NAMES.get(value, value)
            parts.append(fmt.format(self._fmt_num(value)))
        return parts

    def _render_site_product(self, idx: int, p: Dict[str, Any]) -> List[str]:
        name = (p.get("name") or p.get("sku") or "").replace("*", "\\*")
        lines = [f"{idx}. **{name}**"]
        sku = p.get("sku", "")
        art = ""
        if sku and sku != name:
            art = f"   * **Артикул:** `{sku}`"
        elif p.get("code_1c"):
            art = f"   * **ID на сайте:** `{p['code_1c']}`"
        if art and p.get("brand"):
            art += f" | **Бренд:** {p['brand']}"
        elif not art and p.get("brand"):
            art = f"   * **Бренд:** {p['brand']}"
        if art:
            lines.append(art)
        details = []
        if p.get("grade"):
            details.append(f"сплав `{p['grade']}`")
        if p.get("iso_group"):
            details.append(f"ISO `{p['iso_group']}`")
        details.extend(self._site_attr_parts(p))
        if details:
            lines.append("   * **Характеристики:** " + ", ".join(details))
        stock = int(p.get("stock") or 0)
        avail = f"✅ В наличии: **{stock} шт.**" if stock > 0 else "⏳ под заказ"
        lines.append(f"   * **Цена и остаток:** **{p.get('price_display') or 'по запросу'}** | {avail}")
        if p.get("shop_links_markdown"):
            lines.append(f"   * **Магазин:** {p['shop_links_markdown']}")
        lines.append("")
        return lines

    def _format_site_response(self, res: Dict[str, Any]) -> str:
        lines = ["### Поиск по каталогу qtool.ru"]
        chips = res.get("chips") or []
        if chips:
            lines.append("**Понял запрос:** " + " · ".join(chips) + "\n")
        total = int(res.get("total_found") or 0)
        level = res.get("level") or ""
        if res.get("family") is None:
            word = self._plural(total, "позиция", "позиции", "позиций")
            if res.get("compatible_insert"):
                lines.append(f"Найдено совместимого инструмента: **{total}** {word}.\n")
            else:
                lines.append(f"Найдено в разных группах: **{total}** {word} — уточните группу, чтобы сузить выбор.\n")
        else:
            if level == "уточните пластину":
                lines.append("Чтобы подобрать совместимый инструмент, укажите код пластины — например CNMG 120408 или APMT1604.\n")
            elif level == "уточните державку":
                lines.append("Чтобы подобрать пластину, укажите код державки — например MCLNR2525M12.\n")
            else:
                note = {"точное": "точное совпадение", "частичное": "частичное совпадение", "аналог": "ближайшие аналоги"}.get(level, level)
                word = self._plural(total, "позиция", "позиции", "позиций")
                lines.append(f"Найдено: **{total}** {word}" + (f" ({note})" if note else "") + "\n")
        if res.get("availability"):
            lines.append(f"> ⚠️ {res['availability']}\n")
        if res.get("relaxations"):
            lines.append("> ℹ️ " + "; ".join(res["relaxations"]) + "\n")
        td = res.get("tap_drill")
        if td:
            lines.append(f"**Сверло под резьбу {td['thread']}:** Ø {self._fmt_num(td['drill_mm'])} мм.\n")
        if res.get("fits_insert"):
            lines.append(f"**Подходящая пластина:** {res['fits_insert']}.\n")
        if res.get("fits_holder"):
            lines.append(f"**Подбор под державку {res['fits_holder']}:** показаны пластины, которые в неё устанавливаются.\n")
        if res.get("compatible_insert"):
            fam = res.get("family")
            if fam:
                what = {"holder": "державки", "mill": "корпуса фрез"}.get(fam, "инструмент")
                lines.append(f"**Подбор под пластину {res['compatible_insert']}:** показаны {what}, которые с ней совместимы.\n")
            else:
                titles = [self._SITE_FAMILY_TITLES.get(g.get("family")) for g in (res.get("groups") or []) if g.get("products")]
                titles = [t for t in titles if t]
                lines.append(f"**Подбор под пластину {res['compatible_insert']}:** совместимый инструмент"
                             + (": " + ", ".join(titles) if titles else "") + ".\n")
        products = res.get("products") or []
        if not products and not res.get("follow_ups"):
            lines.append("⚠️ По этому запросу в каталоге ничего не найдено — уточните группу, код или размер.\n")
        groups = res.get("groups") or []
        if groups:
            for g in groups:
                title = self._SITE_FAMILY_TITLES.get(g.get("family"), g.get("title") or g.get("family"))
                lines.append(f"**{title}** — найдено {g.get('total_found', 0)}")
                for i, p in enumerate(g.get("products") or [], 1):
                    lines.extend(self._render_site_product(i, p))
        else:
            for i, p in enumerate(products, 1):
                lines.extend(self._render_site_product(i, p))
        follow = res.get("follow_ups") or []
        if follow and level not in ("уточните пластину", "уточните державку"):
            lines.append("### 💡 Уточните запрос")
            for i, tip in enumerate(follow[:3], 1):
                lines.append(f"{i}. {tip}")
        return "\n".join(lines).strip()

    def process_query_autonomous(self, user_query: str, allow_review: bool = False) -> Dict[str, Any]:
        self._current_user_query = user_query
        lower = user_query.lower()
        completeness = self.clarification_advisor.analyze_query_completeness(user_query)
        example = training.lookup(user_query)  # пример технолога для этого запроса (точное совпадение), если есть
        is_analog_request = any(w in lower for w in ["аналог", "замен", "кросс", "вместо", "эквивалент"])

        if is_analog_request:
            args = {"reference_code": user_query}
            tool_res = self.execute_tool("get_analogs", args)
            return {
                "mode": "local_stock_table", "decision": "get_analogs", "tool_called": "get_analogs",
                "tool_result": tool_res, "llm_checked": False,
                "tool_steps": [{"step": 1, "function": "get_analogs", "arguments": args, "result": tool_res}],
                "response_text": self._format_analog_response(user_query, tool_res), "llm_status": "not_needed",
            }

        # 2. Каталог сайта qtool.ru (/upload): все группы одним детерминированным поиском,
        # включая подбор совместимого инструмента («державка под пластину CNMG»).
        site = self.get_site_engine()
        if site is not None:
            return self._site_answer(user_query, site)

        search_args = self._detect_search_args(user_query)
        parsed_orig = {"iso": search_args["iso_group"] or "", "operation": search_args["operation"] or ""}  # что определил парсер сам
        rv = None
        if not search_args["iso_group"] and not search_args["insert_iso_code"] and not example:
            self._log_unrecognized(user_query)
        if example:
            if example["correct_iso"]:
                search_args["iso_group"] = example["correct_iso"]
            if example["correct_operation"]:
                search_args["operation"] = example["correct_operation"]
            if example.get("correct_shape"):
                search_args["insert_shape"] = example["correct_shape"]
            if example.get("correct_size"):
                search_args["size_code"] = example["correct_size"]
            if example.get("correct_radius"):
                try:
                    search_args["corner_radius_mm"] = float(example["correct_radius"])
                except ValueError:
                    pass

        # 1. Запрос слишком размытый: парсер просит уточнения (LLM может распознать материал или написать точные вопросы)
        if completeness["recommended_action"] == "ask_clarification" and not (example and (example["correct_iso"] or example["correct_skus"])):
            if allow_review:
                rv = self.reviewer.review(user_query, search_args, {}, completeness, False)
            if rv and any(k in rv["applied"] for k in ("iso_group", "insert_shape")):
                search_args.update(rv["applied"])
            else:
                if rv and rv["questions"]:
                    completeness = dict(completeness)
                    completeness["missing_fields"] = [{"field": "llm", "question": q, "hint": ""} for q in rv["questions"]]
                msg = self.clarification_advisor.generate_clarification_message(completeness)
                return {
                    "mode": "local_stock_table", "decision": "clarification_branch", "tool_called": "ask_clarification",
                    "tool_result": completeness, "tool_steps": [{"step": 1, "function": "ask_clarification", "arguments": {"query": user_query}, "result": completeness}],
                    "response_text": msg, "parsed": self._parsed_view(search_args, {}, parsed_orig), **self._llm_meta(rv),
                }

        # 2. Запрос про державки/оправки
        is_holder_query = any(w in lower for w in ["державк", "оправк", "pcln", "mcln", "pwln", "ptgn", "pdjn", "mvjn", "pssn", "sclc", "sdjc", "stgc"])
        if is_holder_query and not re.search(r"\b(сталь|нержав|чугун|алюмин|титан|40х|12х18)\b", lower):
            # Конкретную державку (сечение 25x25 или код PCLNR…) ищем в каталоге оснастки;
            # «державка под пластину CNMG» — это запрос про совместимость, его обрабатывает find_compatible.
            holder_geometry = re.search(r"\b\d{2}\s*[xх×]\s*\d{2}\b", lower) or re.search(r"\b(pcln|mcln|pwln|ptgn|pdjn|mvjn|pssn|sclc|sdjc|stgc)[a-z]*\s*\d", lower)
            if holder_geometry:
                holder_res = self.search_engine.search(category="turning_holder", text_query=user_query, in_stock_only=True, limit=1000, active_source=self.active_source)
                prods = holder_res.get("products") or []
                size_m = re.search(r"\b(\d{2})\s*[xх×]\s*(\d{2})\b", lower)
                if size_m:
                    w, h = size_m.groups()
                    rx_size = re.compile(rf"{w}\s*[xх×]\s*{h}")
                    prods = [p for p in prods if rx_size.search((p.get("name") or "").lower()) or rx_size.search((p.get("sku") or "").lower())]
                holder_res["products"] = prods[:6]
                holder_res["total_found"] = len(prods)
                if holder_res["products"]:
                    holder_res["source"] = self.price_source_label
                    holder_res["follow_up_questions_for_user"] = []
                    return {
                        "mode": "local_stock_table", "decision": "direct_recommendation", "tool_called": "search_products",
                        "tool_result": holder_res, "llm_checked": False, "llm_status": "not_needed",
                        "tool_steps": [{"step": 1, "function": "search_products", "arguments": {"category": "turning_holder", "text_query": user_query}, "result": holder_res}],
                        "response_text": self._format_recommendation_response(user_query, holder_res, {}),
                    }
            comp_res = self.execute_tool("find_compatible", {"sku": user_query})
            prods = comp_res.get("compatible_items") or comp_res.get("matching_inserts_in_stock") or []
            fake = {"source": self.price_source_label, "total_found": len(prods), "relaxation_applied": False, "relaxation_notes": "", "products": prods}
            return {
                "mode": "local_stock_table", "decision": "direct_recommendation", "tool_called": "find_compatible",
                "tool_result": fake, "llm_checked": False, "llm_status": "not_needed",
                "tool_steps": [{"step": 1, "function": "find_compatible", "arguments": {"sku": user_query}, "result": comp_res}],
                "response_text": self._format_recommendation_response(user_query, fake, comp_res),
            }

        # 3. Обычный подбор
        tool_res = self.execute_tool("search_products", search_args)
        if allow_review and rv is None:
            rv = self.reviewer.review(user_query, search_args, tool_res, completeness, False)
        if rv and rv["applied"]:
            search_args.update(rv["applied"])
            tool_res = self.execute_tool("search_products", search_args)
        if rv and rv["questions"] and len(tool_res.get("follow_up_questions_for_user") or []) >= 4:
            tool_res["follow_up_questions_for_user"] = rv["questions"]  # 3 точных вопроса вместо длинного списка

        holder_res = {}
        if tool_res.get("products") and search_args["category"] == "turning_insert":
            first = tool_res["products"][0]
            holder_res = self.execute_tool("find_compatible", {"sku": first.get("iso_code") or first["sku"]})

        pinned_note = self._pin_example_products(tool_res, example)
        tool_res["iso_requested"] = search_args.get("iso_group") or ""
        text = self._format_recommendation_response(user_query, tool_res, holder_res)
        if tool_res.get("did_you_mean") and not tool_res.get("products"):
            text += "\n\n> 💡 Возможно, вы имели в виду: " + ", ".join(f"`{c}`" for c in tool_res["did_you_mean"][:5])
        pre_notes = []
        if example:
            bits = [x for x in (f"ISO {example['correct_iso']}" if example["correct_iso"] else "",
                                {"finishing": "чистовая", "semi_finishing": "получистовая", "roughing": "черновая"}.get(example["correct_operation"], "")) if x]
            pre_notes.append(f"📚 Применён пример технолога №{example['id']} ({example['ts'][:10]})" + (": " + ", ".join(bits) if bits else "")
                             + (f". Комментарий: {example['comment']}" if example["comment"] else ""))
            if pinned_note:
                pre_notes.append(pinned_note)
        if search_args.get("iso_group"):
            note = detect_material_note(user_query)
            if note:
                pre_notes.append(note)
        else:
            marks = find_unknown_marks(user_query)
            if marks and not (rv and rv["applied"].get("iso_group")):
                pre_notes.append(f"Марка «{marks[0].upper()}» не найдена в таблице материалов, поэтому группа ISO не определена и подбор идёт без фильтра по материалу. "
                                 "Укажите группу (P, M, K, N, S, H) или добавьте марку в data/materials.csv.")
        hint = self._docs_grade_hint(search_args.get("iso_group"), search_args.get("operation"))
        if hint:
            pre_notes.append(hint)
        if pre_notes:
            text = "\n".join(f"> ℹ️ {n}" for n in pre_notes) + "\n\n" + text
        if rv and rv["applied"].get("iso_group"):
            rv["notes"].append(f"Группа ISO {rv['applied']['iso_group']} определена LLM-верификатором по вашему описанию. Если это не так — уточните материал.")
        if rv and rv["notes"]:
            text = "\n".join(f"> ⚠️ {n}" for n in rv["notes"]) + "\n\n" + text
        return {
            "mode": "local_stock_table", "decision": "direct_recommendation", "tool_called": "search_products",
            "tool_result": tool_res, "tool_steps": [{"step": 1, "function": "search_products", "arguments": search_args, "result": tool_res}],
            "response_text": text, "parsed": self._parsed_view(search_args, tool_res, parsed_orig), **self._llm_meta(rv),
        }

    def _parsed_view(self, args: Dict[str, Any], tool_res: Dict[str, Any], parsed_orig: Dict[str, str]) -> Dict[str, Any]:
        """Как парсер понял запрос — для формы обучения (показывается только при локальном запуске/в админке)."""
        return {"iso": parsed_orig.get("iso", ""), "operation": parsed_orig.get("operation", ""),
                "shape": args.get("insert_shape") or "", "size": args.get("size_code") or "", "code": args.get("insert_iso_code") or "",
                "radius": args.get("corner_radius_mm"),
                "brand": args.get("brand") or "", "category": args.get("category") or "",
                "top_skus": [p.get("sku", "") for p in (tool_res.get("products") or [])[:5]]}

    def _pin_example_products(self, tool_res: Dict[str, Any], example: Optional[Dict[str, str]]) -> str:
        """Артикулы, рекомендованные технологом, ставятся первыми, если они есть в наличии."""
        if not example or not example["correct_skus"]:
            return ""
        norm = lambda x: re.sub(r"[^A-Z0-9А-Я]", "", str(x).upper())  # noqa: E731
        want = [w.strip() for w in example["correct_skus"].split(";") if w.strip()]
        found, missing = [], []
        for w in want:
            wn = norm(w)
            hit = next((it for it in self.search_engine.catalog if it.get("stock", 0) > 0 and (norm(it.get("sku", "")) == wn or norm(it.get("sku", "")).startswith(wn))), None)
            if hit:
                found.append(self.search_engine._clean_item_for_output(hit, active_source=self.active_source))
            else:
                missing.append(w)
        if found:
            have = {norm(p["sku"]) for p in found}
            rest = [p for p in (tool_res.get("products") or []) if norm(p.get("sku", "")) not in have]
            tool_res["products"] = (found + rest)[:max(5, len(found))]
            tool_res["total_found"] = max(tool_res.get("total_found", 0), len(tool_res["products"]))
        note = ""
        if found:
            note = "⭐ Рекомендовано технологом (первыми в списке): " + ", ".join(p["sku"] for p in found) + "."
        if missing:
            note += (" " if note else "") + "Нет в наличии из рекомендованных технологом: " + ", ".join(missing) + "."
        return note

    @staticmethod
    def _fmt_price(p: Dict[str, Any]) -> str:
        return p.get("price_display") or f"{p.get('price', 0)} {(p.get('currency') or 'RUB').upper()}"

    def _format_analog_response(self, query: str, analog_res: Dict[str, Any]) -> str:
        lines = []
        ref = analog_res.get("detected_grade") or analog_res.get("source_reference")
        lines.append(f"### Подбор аналогов из таблицы остатков (`{self.price_source_label}`) для `{ref}`\n")
        lines.append(
            f"**Исходный бренд:** {analog_res.get('detected_brand')} | "
            f"**Группа обрабатываемых материалов:** ISO {analog_res.get('iso_group') or 'P'}\n"
        )

        equivs = analog_res.get("grade_equivalents", [])
        if equivs:
            lines.append("**Соответствие марок сплавов по кросс-таблице:**")
            for eq in equivs:
                lines.append(f"* **{eq['brand']}:** сплав `{eq['grade']}`")
            lines.append("")

        matches = analog_res.get("available_catalog_matches", [])
        if matches:
            lines.append(f"**Позиции в наличии из активной базы (`{self.price_source_label}`):**")
            for idx, p in enumerate(matches[:5], 1):
                c1c = f" (Код/ID: `{p['code_1c']}`)" if p.get("code_1c") else ""
                src_tag = f" `[{p['source_site']}]`" if p.get("source_site") else ""
                ca_str = f", задний угол `{p.get('clearance_angle_desc') or p.get('clearance_angle')}`" if p.get("clearance_angle") else ""
                lines.append(f"{idx}. **{p['name']}**{src_tag}")
                lines.append(f"   * **Артикул:** `{p['sku']}`{c1c}")
                lines.append(
                    f"   * **Параметры:** Бренд `{p.get('brand') or '-'}`, сплав `{p.get('grade') or '-'}` "
                    f"(ISO `{p.get('iso_group') or '-'}`, покрытие `{p.get('coating') or '-'}`){ca_str}, "
                    f"стружколом `{p.get('chipbreaker') or '-'}`, радиус R={p.get('corner_radius_mm') or '-'} мм"
                )
                lines.append(f"   * **Остаток и цена:** **{self._fmt_price(p)}** | ✅ В наличии: **{p['stock']} шт.**")
                if p.get("shop_links_markdown"):
                    dual_note = " *(позиция есть в обоих магазинах)*" if p.get("in_both_stores") else ""
                    lines.append(f"   * **Ссылки на магазин:** {p['shop_links_markdown']}{dual_note}\n")
                else:
                    lines.append("")
        else:
            lines.append(f"⚠️ В текущей базе (`{self.price_source_label}`) прямых складских позиций по этой геометрии не найдено.")

        return "\n".join(lines)

    def _format_recommendation_response(self, query: str, search_res: Dict[str, Any], holder_res: Dict[str, Any]) -> str:
        products = search_res.get("products", [])
        if not products:
            return (
                f"По заданным фильтрам в активной таблице остатков (`{self.price_source_label}`) позиций не найдено. "
                "Попробуйте переключить источник (Rinscom.com / qtool.ru) на боковой панели или ослабить фильтр по радиусу/стружколому."
            )

        lines = []
        first = products[0]
        req_iso = search_res.get("iso_requested", "__unset__")
        if search_res.get("query_category") == "turning_holder":
            iso_label = "оснастка: державки"
        else:
            iso_label = (f"Группа ISO: **{req_iso}**" if req_iso else "группа ISO материала не указана") if req_iso != "__unset__" else f"Группа ISO: **{first.get('iso_group') or 'P'}**"
        lines.append(f"### Подбор по таблице складских остатков (`{self.price_source_label}`)\n")
        total = search_res.get("total_found", len(products))
        exact = search_res.get("exact_found", total)
        if exact != total:
            lines.append(f"Найдено в наличии: **{exact}** точных совпадений, после ослабления фильтров — **{total}** ({iso_label})\n")
        else:
            lines.append(f"Найдено подходящих позиций в наличии: **{total} шт.** ({iso_label})\n")

        if search_res.get("relaxation_applied"):
            lines.append(f"> ℹ️ *Примечание фильтрации: {search_res.get('relaxation_notes')}*\n")

        cross_info = search_res.get("analog_cross_info")
        if cross_info:
            src_g = cross_info.get("source_grade") or ""
            lines.append(f"🔄 **Распознан сплав `{src_g}` ({cross_info.get('detected_brand', '')}) → Группа ISO `{cross_info.get('iso_group')}` ({cross_info.get('iso_range')})**")
            lines.append(f"* **Назначение:** {cross_info.get('operation_desc', '')}")
            eq_parts = [f"**{b}**: `{g}`" for b, g in list(cross_info.get("analogs", {}).items())[:8]]
            if eq_parts:
                lines.append("* **Аналоги сплава по кросс-таблице:** " + " | ".join(eq_parts))
            cb_list = search_res.get("chipbreaker_analogs") or cross_info.get("chipbreakers") or []
            if cb_list:
                lines.append("* **Рекомендуемые стружколомы-аналоги:** `" + "`, `".join(cb_list[:10]) + "`")
            lines.append("")

        for idx, p in enumerate(products[:5], 1):
            c1c = f" | **Код/ID:** `{p['code_1c']}`" if p.get("code_1c") else ""
            src_tag = f" `[{p['source_site']}]`" if p.get("source_site") else ""
            lines.append(f"{idx}. **{p['name']}**{src_tag}")
            lines.append(f"   * **Артикул:** `{p['sku']}`{c1c}")
            details = []
            if p.get("brand"):
                details.append(f"Бренд: **{p['brand']}**")
            if p.get("grade"):
                details.append(f"Сплав: `{p['grade']}` ({p.get('coating') or 'твердый сплав'})")
            if p.get("iso_group"):
                details.append(f"ISO: `{p['iso_group']}`")
            if p.get("clearance_angle_desc") or p.get("clearance_angle"):
                details.append(f"Задний угол: `{p.get('clearance_angle_desc') or p.get('clearance_angle')}`")
            if p.get("chipbreaker"):
                details.append(f"Стружколом: `{p['chipbreaker']}`")
            if p.get("corner_radius_mm") is not None and p.get("corner_radius_mm") != "":
                details.append(f"R={p['corner_radius_mm']} мм")
            if p.get("pitch_value") is not None and p.get("pitch_value") != "":
                details.append(f"Шаг: {p['pitch_value']} ({p.get('thread_profile') or ''})")
            if p.get("groove_width_mm") is not None and p.get("groove_width_mm") != "":
                details.append(f"Ширина канавки: {p['groove_width_mm']} мм")
            lines.append("   * **Характеристики:** " + ", ".join(details))
            if p.get("offers"):
                lines.append(f"   * **Предложения** (всего на складах: **{p['stock']} шт.**):")
                for o in p["offers"]:
                    store = {"qtool.ru": "qtool.ru", "rinscom.com": "Rinscom.com"}.get(o["store"], o["store"] or "склад")
                    link = f" — [открыть]({o['url']})" if o.get("url") else ""
                    lines.append(f"     - {store}: **{o['price_display']}**, {o['stock']} шт.{link}")
            else:
                lines.append(f"   * **Цена и остаток:** **{self._fmt_price(p)}** | ✅ На складе: **{p['stock']} шт.**")
            if p.get("shop_links_markdown"):
                dual_note = " *(есть в обоих магазинах)*" if p.get("in_both_stores") else ""
                lines.append(f"   * **Магазин:** {p['shop_links_markdown']}{dual_note}\n")
            else:
                lines.append("")

        if holder_res and holder_res.get("recommended_holder_standards"):
            lines.append("**Рекомендуемая оснастка (державки по ISO):**")
            lines.append(f"* {holder_res['recommended_holder_standards']}\n")

        follow_ups = search_res.get("follow_up_questions_for_user") or []
        if follow_ups:
            lines.append("### 💡 Уточняющие (наводящие) вопросы для максимального уточнения запроса")
            lines.append("В вашем запросе не были указаны некоторые конструктивные параметры пластины. Чтобы сузить выбор до одной точной позиции, уточните, пожалуйста:")
            for q_idx, q_text in enumerate(follow_ups, 1):
                lines.append(f"{q_idx}. {q_text}")

        return "\n".join(lines)
