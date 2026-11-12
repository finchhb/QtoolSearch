"""
src/hybrid_search.py - Сверхбыстрый гибридный поиск СТРОГО по таблице остатков (Rinscom.com / qtool.ru).
Оптимизации скорости и ссылок:
- Кэширование распарсенных каталогов в памяти (_memory_cache): переключение между Rinscom.com, qtool.ru и объединённой базой занимает < 1 мс.
- Предвычисление поисковых полей при загрузке: фильтрация 18 500+ строк занимает < 3 мс.
- Автоматическое формирование ссылок на магазины (rinscom_url, qtool_url, shop_links_markdown):
  если пластина есть в выбранном источнике — даётся ссылка на него, а если пластина есть и в Rinscom.com, и в qtool.ru — даются ДВЕ ссылки!
"""
import csv
import math
import os
import re
from typing import Any, Dict, List, Optional, Tuple
from src import rates
from src.materials_mapping import BRAND_SYNONYMS, CLEARANCE_ANGLE_DESCRIPTIONS

EXCLUDE_INACTIVE = os.environ.get("ADVISOR_EXCLUDE_INACTIVE", "0") == "1"


SHAPE_EXAMPLES = {
    "T": ("TNMG", "TCMT / TCGT", "PTGNR/L, MTGNR/L", "STGCR/L"),
    "C": ("CNMG", "CCMT / CCGT", "PCLNR/L, MCLNR/L", "SCLCR/L"),
    "D": ("DNMG", "DCMT / DCGT", "PDJNR/L, MDJNR/L", "SDJCR/L"),
    "V": ("VNMG", "VBMT / VCMT", "MVJNR/L, PVJNR/L", "SVJBR/L, SVJCR/L"),
    "W": ("WNMG", "WCMT", "PWLNR/L, MWLNR/L", "SWLCR/L"),
    "S": ("SNMG", "SCMT / SCGT", "PSSNR/L, MSSNR/L", "SSSCR/L"),
    "R": ("RNMG", "RCMT / RPMT", "PRGNR/L", "SRGCR/L"),
}


class HybridSearchEngine:
    def __init__(self, catalog_path: str = "data/catalog_qtool.csv", cross_codes_path: str = "data/cross_codes.csv", grades_path: str = "data/grades.csv"):
        self.catalog_path = catalog_path
        self.cross_codes_path = cross_codes_path
        self.grades_path = grades_path
        self.catalog: List[Dict[str, Any]] = []
        self.doc_tokens: List[set] = []
        self.df: Dict[str, int] = {}
        self.total_docs: int = 0
        self._memory_cache: Dict[str, Tuple[float, List[Dict[str, Any]], List[set], Dict[str, int]]] = {}
        self.reload_catalog(catalog_path)

    def reload_catalog(self, catalog_path: Optional[str] = None, force: bool = False):
        """
        Перезагружает каталог из указанного CSV (или берет из RAM-кэша за 0.001 сек, если файл не менялся).
        """
        if catalog_path:
            self.catalog_path = catalog_path

        if not os.path.exists(self.catalog_path):
            self.catalog = []
            self.doc_tokens = []
            self.df = {}
            self.total_docs = 0
            return

        mtime = os.path.getmtime(self.catalog_path)
        cache_entry = self._memory_cache.get(self.catalog_path)
        if not force and cache_entry and cache_entry[0] == mtime:
            _, self.catalog, self.doc_tokens, self.df = cache_entry
            self.total_docs = len(self.catalog)
            return

        new_catalog: List[Dict[str, Any]] = []
        with open(self.catalog_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                def parse_float_opt(val):
                    if val is None or str(val).strip() == "":
                        return None
                    try:
                        return float(str(val).replace(",", "."))
                    except ValueError:
                        return None

                def parse_int_opt(val, default=0):
                    if val is None or str(val).strip() == "":
                        return default
                    try:
                        return int(round(float(str(val).replace(",", "."))))
                    except ValueError:
                        return default

                row["corner_radius_mm"] = parse_float_opt(row.get("corner_radius_mm"))
                row["pitch_value"] = parse_float_opt(row.get("pitch_value"))
                row["groove_width_mm"] = parse_float_opt(row.get("groove_width_mm"))
                row["price"] = parse_float_opt(row.get("price")) or 0.0
                row["_por"] = str(row.get("price_on_request") or "0").strip() == "1" or row["price"] <= 0
                row["_inactive"] = (row.get("active") or "Y").strip().upper() == "N"
                row["currency"] = (row.get("currency") or "RUB").strip().upper()
                row["source_site"] = (row.get("source_site") or "rinscom.com").strip()
                row["rinscom_url"] = (row.get("rinscom_url") or "").strip()
                row["qtool_url"] = (row.get("qtool_url") or "").strip()
                row["in_both_stores"] = (row.get("in_both_stores") or "0").strip()
                row["stock"] = parse_int_opt(row.get("stock"), 0)
                row["stock_qty"] = row["stock"]

                ca = (row.get("clearance_angle") or "").strip().upper()
                iso_c = (row.get("iso_code") or "").strip().upper()
                if not ca and len(iso_c) >= 2 and iso_c[1].isalpha():
                    ca = iso_c[1]
                row["clearance_angle"] = ca

                # Предвычисленные поля для мгновенной фильтрации без лишних аллокаций
                row["_iso_primary_list"] = [x.strip().upper() for x in (row.get("iso_group") or "").split(",") if x.strip()]
                row["_iso_secondary_list"] = [x.strip().upper() for x in (row.get("secondary_iso") or "").split(",") if x.strip()]
                row["_code_up"] = iso_c
                row["_head_up"] = (row.get("head") or "").upper().replace(" ", "")
                row["_shape_up"] = (row.get("insert_shape") or "").upper()
                row["_ca_up"] = ca
                row["_size_str"] = str(row.get("size_code") or "")
                row["_cb_up"] = (row.get("chipbreaker") or "").upper()
                row["_cb_parts"] = row["_cb_up"].split("-") if row["_cb_up"] else []
                row["_op_list"] = [x.strip() for x in (row.get("operation") or "").lower().split(",") if x.strip()]
                row["_grade_up"] = (row.get("grade") or "").upper()
                row["_coat_up"] = (row.get("coating") or "").upper()
                row["_brand_low"] = (row.get("brand") or "").lower()
                row["_tp_up"] = (row.get("thread_profile") or "").upper()
                row["_side_low"] = (row.get("side") or "").lower()
                row["_hand_up"] = (row.get("hand") or "").upper()
                row["_fc_up"] = (row.get("family_code") or "").upper()
                new_catalog.append(row)

        self.catalog = new_catalog
        self._build_inverted_index()
        self._memory_cache[self.catalog_path] = (mtime, self.catalog, self.doc_tokens, self.df)

    def _build_inverted_index(self):
        self.doc_tokens = []
        self.df = {}
        self.total_docs = len(self.catalog)
        for item in self.catalog:
            text = (
                f"{item.get('sku', '')} {item.get('code_1c', '')} {item.get('name', '')} "
                f"{item.get('brand', '')} {item.get('grade', '')} {item.get('chipbreaker', '')} "
                f"{item.get('iso_code', '')} {item.get('family_code', '')}"
            ).lower()
            tokens = set(re.findall(r"[a-zа-я0-9.]+", text))
            self.doc_tokens.append(tokens)
            for tok in tokens:
                self.df[tok] = self.df.get(tok, 0) + 1

    def _compute_text_score(self, query_tokens: List[str], doc_id: int) -> float:
        if not query_tokens or doc_id >= len(self.doc_tokens):
            return 0.0
        doc_toks = self.doc_tokens[doc_id]
        score = 0.0
        for q_tok in query_tokens:
            if q_tok in doc_toks:
                doc_freq = self.df.get(q_tok, 1)
                idf = math.log((self.total_docs - doc_freq + 0.5) / (doc_freq + 0.5) + 1.0)
                score += idf
            else:
                if len(q_tok) >= 4 and any(q_tok in dt for dt in doc_toks):
                    score += 1.5
        return score

    def _normalize_operation(self, op: Optional[str]) -> Optional[str]:
        if not op:
            return None
        op_low = op.strip().lower()
        if op_low in ("medium", "semi_finishing", "получистовая", "универсальная"):
            return "semi_finishing"
        if op_low in ("finishing", "чистовая"):
            return "finishing"
        if op_low in ("roughing", "черновая"):
            return "roughing"
        return op_low

    def search(
        self,
        category: Optional[str] = None,
        iso_group: Optional[str] = None,
        operation: Optional[str] = None,
        application_type: Optional[str] = None,
        insert_iso_code: Optional[str] = None,
        insert_shape: Optional[str] = None,
        clearance_angle: Optional[str] = None,
        size_code: Optional[str] = None,
        corner_radius_mm: Optional[float] = None,
        chipbreaker: Optional[str] = None,
        grade: Optional[str] = None,
        coating: Optional[str] = None,
        brand: Optional[str] = None,
        pitch_value: Optional[float] = None,
        thread_profile: Optional[str] = None,
        side: Optional[str] = None,
        hand: Optional[str] = None,
        groove_width_mm: Optional[float] = None,
        family_code: Optional[str] = None,
        text_query: Optional[str] = None,
        in_stock_only: bool = True,
        limit: int = 5,
        active_source: str = "rinscom",
    ) -> Dict[str, Any]:
        if brand and brand.lower() in BRAND_SYNONYMS:
            brand = BRAND_SYNONYMS[brand.lower()]

        eff_operation = self._normalize_operation(operation or application_type)

        if insert_iso_code:
            from src.iso1832 import norm_code
            insert_iso_code = re.sub(r"\s+", "", norm_code(insert_iso_code))
            if "-" in insert_iso_code:
                code_part, _, cb_part = insert_iso_code.partition("-")
                insert_iso_code = code_part
                if not chipbreaker and cb_part:
                    chipbreaker = cb_part.split()[0]

        if size_code is not None and str(size_code).strip() != "":
            sz_s = str(size_code).strip()
            if sz_s.isdigit() and len(sz_s) == 1:
                size_code = f"0{sz_s}"
            else:
                size_code = sz_s

        query_tokens = []
        if text_query:
            q_clean = text_query.strip().lower()
            stop_words = {
                "пластина", "пластины", "токарная", "токарные", "для", "под", "точения", "обработки",
                "резьбовая", "канавочная", "нужна", "подбери", "посоветуй", "по", "размер", "размером"
            }
            query_tokens = [t for t in re.findall(r"[a-zа-я0-9.]+", q_clean) if t not in stop_words]
            # Тот же токен кириллицей/латиницей: «25x25» и «25х25», «PCLNR» и «РСLNR» в каталоге встречаются в обоих видах
            homoglyphs = str.maketrans("abcehkmoptxygd", "авсенкмортхугд")
            extra = [alt for t in query_tokens if (alt := t.translate(homoglyphs)) != t]
            query_tokens.extend(t for t in extra if t not in query_tokens)

        initial_filters = {
            "category": category or "turning_insert",
            "iso_group": iso_group.upper() if iso_group else None,
            "operation": eff_operation,
            "insert_iso_code": insert_iso_code,
            "insert_shape": insert_shape.upper() if insert_shape else None,
            "clearance_angle": clearance_angle.upper() if clearance_angle else None,
            "size_code": str(size_code) if size_code else None,
            "corner_radius_mm": float(corner_radius_mm) if corner_radius_mm is not None else None,
            "chipbreaker": chipbreaker.upper() if chipbreaker else None,
            "grade": grade.upper() if grade else None,
            "coating": coating.upper() if coating else None,
            "brand": brand,
            "pitch_value": float(pitch_value) if pitch_value is not None else None,
            "thread_profile": thread_profile.upper() if thread_profile else None,
            "side": side.lower() if side else None,
            "hand": hand.upper() if hand else None,
            "groove_width_mm": float(groove_width_mm) if groove_width_mm is not None else None,
            "family_code": family_code.upper() if family_code else None,
            "in_stock_only": in_stock_only,
        }
        filters = dict(initial_filters)

        matches = self._filter_and_score(filters, query_tokens, allow_secondary_iso=False)
        strict_matches = list(matches)

        relaxation_info = {"relaxed": False, "steps": [], "hints": {}}

        if len(matches) < 3 and filters["iso_group"]:
            sec_matches = self._filter_and_score(filters, query_tokens, allow_secondary_iso=True)
            if len(sec_matches) > len(matches):
                matches = sec_matches
                relaxation_info["relaxed"] = True
                relaxation_info["steps"].append(f"Включены сплавы со смежным допуском по группе ISO {filters['iso_group']}")

        if len(matches) == 0:
            for drop_key, drop_desc in [
                ("chipbreaker", "стружколом"),
                ("operation", "тип операции (по стружколому)"),
                ("grade", "конкретная марка сплава"),
                ("coating", "тип покрытия"),
                ("brand", "бренд"),
                ("corner_radius_mm", "радиус при вершине"),
                ("clearance_angle", "задний угол пластины"),
                ("size_code", "размер пластины"),
            ]:
                if filters.get(drop_key) is not None:
                    filters[drop_key] = None
                    relaxation_info["relaxed"] = True
                    relaxation_info["steps"].append(f"Ослаблен фильтр: {drop_desc}")
                    matches = self._filter_and_score(filters, query_tokens, allow_secondary_iso=True)
                    if len(matches) > 0:
                        break

        did_you_mean: List[str] = []
        if not matches and filters.get("insert_iso_code"):
            did_you_mean = [c for c, _ in self._fuzzy_codes(filters["insert_iso_code"])]

        matches.sort(key=lambda m: (m["score"], m["item"].get("stock", 0)), reverse=True)
        matches = self._merge_duplicates(matches)
        # Точных совпадений считаем после склейки дублей — иначе счётчик расходится с total_found
        exact_found = len(matches) if not relaxation_info["relaxed"] else len(self._merge_duplicates(strict_matches))

        selected_matches = self._select_diverse_top(matches, initial_filters, limit, active_source=active_source)
        top_items = [self._clean_item_for_output(m["item"], active_source=active_source) for m in selected_matches]

        missing_params, follow_up_questions = self.build_follow_up_questions(initial_filters, matches)

        return {
            "source": "таблица остатков (Rinscom.com / qtool.ru)",
            "query_category": category or "turning_insert",
            "total_found": len(matches),
            "exact_found": exact_found,
            "returned_count": len(top_items),
            "relaxation_applied": relaxation_info["relaxed"],
            "relaxation_notes": "; ".join(relaxation_info["steps"]) if relaxation_info["steps"] else "Точное совпадение по фильтрам таблицы остатков",
            "applied_filters": {k: v for k, v in filters.items() if v is not None},
            "missing_parameters_in_query": missing_params,
            "follow_up_questions_for_user": follow_up_questions,
            "products": top_items,
            "did_you_mean": did_you_mean,
        }

    @staticmethod
    def _merge_duplicates(matches):
        """PATCH_SOURCES_V2: при склейке артикула ссылки и признак «в обоих» берём со всех строк."""
        def key(it):
            return re.sub(r"[^A-Z0-9А-Я]", "", str(it.get("sku") or "").upper()) or str(id(it))

        groups = {}
        order = []
        for m in matches:
            k = key(m["item"])
            if k not in groups:
                groups[k] = {"match": m, "rows": [m["item"]]}
                order.append(k)
            else:
                groups[k]["rows"].append(m["item"])

        merged = []
        for k in order:
            g = groups[k]
            if len(g["rows"]) == 1:
                merged.append(g["match"])
                continue
            rows = g["rows"]
            item = dict(rows[0])
            r_url = next((r.get("rinscom_url") for r in rows if r.get("rinscom_url")), "")
            q_url = next((r.get("qtool_url") for r in rows if r.get("qtool_url")), "")
            if r_url:
                item["rinscom_url"] = r_url
            if q_url:
                item["qtool_url"] = q_url
            stores = {r.get("source_site", "") for r in rows if r.get("source_site")}
            if (r_url and q_url) or len(stores) > 1:
                item["in_both_stores"] = "1"
            item["_offers"] = [
                {"store": r.get("source_site", ""), "stock": r.get("stock", 0),
                 "price": r.get("price", 0.0), "currency": r.get("currency", "RUB"),
                 "por": bool(r.get("_por")),
                 "url": (r.get("qtool_url") if r.get("source_site") == "qtool.ru" else r.get("rinscom_url"))
                        or r.get("qtool_url") or r.get("rinscom_url") or ""}
                for r in rows
            ]
            item["stock"] = sum(int(r.get("stock", 0) or 0) for r in rows)
            priced = [r for r in rows if (r.get("price") or 0) > 0 and not r.get("_por")]
            if priced:
                best = min(priced, key=lambda r: r.get("price", 0.0))
                item["price"] = best.get("price", 0.0)
                item["currency"] = best.get("currency", "RUB")
                item["_por"] = False
            m2 = dict(g["match"])
            m2["item"] = item
            merged.append(m2)
        return merged

    def _select_diverse_top(self, matches, initial_filters, limit, active_source="rinscom"):
        """PATCH_SOURCES_V2: в режиме both каждый магазин, у которого есть совпадения, попадает в выдачу."""
        def stores_of(m):
            it = m["item"]
            s = set()
            ss = (it.get("source_site") or "").lower()
            if ss:
                s.add("qtool" if "qtool" in ss else "rinscom")
            for o in (it.get("_offers") or []):
                st = (o.get("store") or "").lower()
                if st:
                    s.add("qtool" if "qtool" in st else "rinscom")
            if it.get("rinscom_url"):
                s.add("rinscom")
            if it.get("qtool_url"):
                s.add("qtool")
            return s

        def balance(picked):
            picked = list(picked)
            if active_source != "both" or not picked or limit <= 0:
                return picked[:limit]
            ids = {id(x) for x in picked}
            have = set()
            for m in picked:
                have |= stores_of(m)
            for store in ("rinscom", "qtool"):
                if store in have:
                    continue
                cand = next((m for m in matches
                             if store in stores_of(m) and id(m) not in ids), None)
                if cand is None:
                    continue
                if len(picked) < limit:
                    picked.append(cand)
                else:
                    idx = None
                    for j in range(len(picked) - 1, -1, -1):
                        rest = set()
                        for t, mm in enumerate(picked):
                            if t != j:
                                rest |= stores_of(mm)
                        if stores_of(picked[j]) <= rest:
                            idx = j
                            break
                    if idx is None:
                        idx = len(picked) - 1
                    ids.discard(id(picked[idx]))
                    picked[idx] = cand
                ids.add(id(cand))
                have |= stores_of(cand)
            return picked[:limit]

        if not matches or len(matches) <= limit:
            return balance(matches[:limit])
        if initial_filters.get("clearance_angle") or initial_filters.get("insert_iso_code"):
            return balance(matches[:limit])
        by_ca = {}
        for m in matches:
            by_ca.setdefault(m["item"].get("_ca_up", ""), []).append(m)
        if len(by_ca) <= 1:
            return balance(matches[:limit])
        picked = []
        picked_ids = set()
        for ca_key in ("N", "C", "P", "B"):
            if ca_key in by_ca:
                for cand in by_ca[ca_key][:2]:
                    cid = id(cand)
                    if cid not in picked_ids and len(picked) < limit:
                        picked.append(cand)
                        picked_ids.add(cid)
        for m in matches:
            if len(picked) >= limit:
                break
            cid = id(m)
            if cid not in picked_ids:
                picked.append(m)
                picked_ids.add(cid)
        return balance(picked)

    def build_follow_up_questions(self, initial_filters: Dict[str, Any], matches: List[Dict[str, Any]]) -> Tuple[List[str], List[str]]:
        cat = initial_filters.get("category") or "turning_insert"
        missing_params: List[str] = []
        questions: List[str] = []

        if cat == "turning_insert":
            has_exact_iso = bool(initial_filters.get("insert_iso_code") and len(str(initial_filters["insert_iso_code"])) >= 4)
            shape = (initial_filters.get("insert_shape") or "").upper()
            neg_ex, pos_ex, neg_hold, pos_hold = SHAPE_EXAMPLES.get(
                shape, ("CNMG / TNMG", "CCMT / TCMT", "PCLNR/L, PTGNR/L", "SCLCR/L, STGCR/L")
            )

            if not initial_filters.get("clearance_angle") and not has_exact_iso:
                avail_ca = sorted({m["item"].get("_ca_up", "") for m in matches if m["item"].get("_ca_up")})
                ca_note = f" (в наличии есть варианты с кодами заднего угла: {', '.join(avail_ca)})" if avail_ca else ""
                missing_params.append("clearance_angle (задний угол пластины)")
                questions.append(
                    f"**Задний угол пластины и тип державки:** вам нужна **негативная двухсторонняя пластина с задним углом 0° (буква `N` — например, `{neg_ex}`)** "
                    f"под жёсткие державки `{neg_hold}` или **позитивная односторонняя пластина с задним углом 7° (буква `C` — например, `{pos_ex}`)** "
                    f"с меньшим усилием резания под державки `{pos_hold}`{ca_note}?"
                )

            has_iso_radius = bool(initial_filters.get("insert_iso_code") and len(str(initial_filters["insert_iso_code"])) >= 10)
            if initial_filters.get("corner_radius_mm") is None and not has_iso_radius:
                avail_rads = sorted({m["item"].get("corner_radius_mm") for m in matches if m["item"].get("corner_radius_mm") is not None})
                rad_str = ", ".join(f"R{r}" for r in avail_rads[:5]) if avail_rads else "R0.4, R0.8, R1.2"
                missing_params.append("corner_radius_mm (радиус при вершине R)")
                questions.append(
                    f"**Радиус при вершине (`R`):** какой радиус скругления требуется по чертежу и жёсткости детали "
                    f"(в остатках по вашему запросу доступны `{rad_str}` мм: `R0.4` — для чистовой обработки, `R0.8` — универсальный, `R1.2` — для чернового съёма)?"
                )

            if not initial_filters.get("operation") and not initial_filters.get("chipbreaker"):
                missing_params.append("operation (вид обработки: черновая / получистовая / чистовая)")
                questions.append(
                    "**Характер обработки и состояние заготовки:** планируется **черновая обдирка** (в т.ч. по литейной корке или с прерывистым резанием), "
                    "**получистовое** или **чистовое (финишное)** точение?"
                )

            if not initial_filters.get("size_code") and not has_exact_iso:
                avail_sz = sorted({str(m["item"].get("size_code")) for m in matches if m["item"].get("size_code")})
                sz_str = ", ".join(avail_sz[:6]) if avail_sz else "09, 12, 16"
                missing_params.append("size_code (размер режущей кромки пластины)")
                questions.append(
                    f"**Размер пластины (габарит гнезда державки):** какой размер режущей кромки нужен под вашу державку (в наличии: `{sz_str}`)?"
                )

            if not initial_filters.get("insert_shape") and not has_exact_iso:
                missing_params.append("insert_shape (форма пластины по ISO)")
                questions.append(
                    "**Форма пластины:** какая геометрия предпочтительна (ромб 80° `C`, треугольник 60° `T`, тригон `W`, ромб 55° `D`, ромб 35° `V`, квадрат `S`)?"
                )

        elif cat == "thread_insert":
            if initial_filters.get("pitch_value") is None:
                missing_params.append("pitch_value (шаг резьбы)")
                questions.append("**Шаг и профиль резьбы:** какой точный шаг резьбы (мм или ниток на дюйм) и стандарт профиля (`ISO`, `W 55°`, `TR`, `BSPT`, `NPT`) требуется нарезать?")
            if not initial_filters.get("side"):
                missing_params.append("side (наружная или внутренняя резьба)")
                questions.append("**Тип резьбы и размер пластины:** резьба **наружная (`ER/EL`)** или **внутренняя (`IR/IL`)**, и какой размер пластины под державку (`11`, `16`, `22`)?")

        elif cat == "groove_insert":
            if initial_filters.get("groove_width_mm") is None:
                missing_params.append("groove_width_mm (ширина канавки/отрезки)")
                questions.append("**Ширина пластины и серия державки:** какая ширина паза/отрезки в мм (например, `2.0`, `2.5`, `3.0`, `4.0` мм) и под какую державку (`MGMN`, `TGF`, `8GR`, `SP`) нужна пластина?")

        return missing_params, questions

    @staticmethod
    def format_store_links(item, active_source="rinscom"):
        """PATCH_SOURCES_V2: ссылки по всем предложениям, оба магазина не теряются."""
        links = []
        seen = set()

        def add(store, url, primary=False):
            url = (url or "").strip()
            if not url or url in seen:
                return
            seen.add(url)
            is_q = "qtool" in (store or "")
            label = ("Открыть на qtool.ru" if primary and is_q else
                     "Открыть на Rinscom.com" if primary else
                     "Также есть на qtool.ru" if is_q else "Также есть на Rinscom.com")
            links.append(f"[{label}]({url})")

        offers = item.get("_offers") or []

        def rank(o):
            s = (o.get("store") or "").lower()
            if active_source == "qtool":
                return 0 if "qtool" in s else 1
            if active_source == "rinscom":
                return 0 if "rinscom" in s else 1
            return 0

        first = True
        for o in sorted(offers, key=rank):
            add(o.get("store", ""), o.get("url", ""), primary=first)
            first = False
        r_url = (item.get("rinscom_url") or "").strip()
        q_url = (item.get("qtool_url") or "").strip()
        if active_source == "qtool":
            add("qtool.ru", q_url, primary=first); first = False
            add("rinscom.com", r_url)
        else:
            add("rinscom.com", r_url, primary=first); first = False
            add("qtool.ru", q_url)
        return " | ".join(links)

    def _clean_item_for_output(self, item: Dict[str, Any], active_source: str = "rinscom") -> Dict[str, Any]:
        """Формирует компактную карточку позиции со ссылками на магазины (1 или 2 ссылки)."""
        ca = item.get("_ca_up") or (item.get("clearance_angle") or "").upper()
        shop_links = self.format_store_links(item, active_source=active_source)
        out: Dict[str, Any] = {
            "sku": item.get("sku", ""),
            "code_1c": item.get("code_1c", ""),
            "name": item.get("name", ""),
            "brand": item.get("brand", ""),
            "grade": item.get("grade", ""),
            "iso_group": item.get("iso_group", ""),
            "stock": item.get("stock", 0),
            "price": item.get("price", 0.0),
            "currency": item.get("currency", "RUB"),
            "price_on_request": bool(item.get("_por")),
            "price_display": rates.price_display(item.get("price", 0.0), item.get("currency", "RUB"), bool(item.get("_por"))),
            "source_site": item.get("source_site", ""),
            "shop_links_markdown": shop_links,
        }
        if item.get("_inactive"):
            out["inactive_on_site"] = True
        if item.get("_offers"):
            out["offers"] = [{"store": o["store"], "stock": o["stock"], "url": o["url"],
                              "price_display": rates.price_display(o["price"], o["currency"], o["por"])} for o in item["_offers"]]
        if item.get("rinscom_url"):
            out["rinscom_url"] = item["rinscom_url"]
        if item.get("qtool_url"):
            out["qtool_url"] = item["qtool_url"]
        if str(item.get("in_both_stores")) == "1":
            out["in_both_stores"] = True
        if ca:
            out["clearance_angle"] = ca
            out["clearance_angle_desc"] = CLEARANCE_ANGLE_DESCRIPTIONS.get(ca, ca)
        for opt_key in ("coating", "iso_code", "insert_shape", "size_code", "corner_radius_mm", "chipbreaker", "operation", "pitch_value", "thread_profile", "side", "hand", "groove_width_mm", "family_code"):
            val = item.get(opt_key)
            if val is not None and val != "":
                out[opt_key] = val
        return out

    @staticmethod
    def _grams(s: str, n: int = 3):
        from collections import Counter
        s = f"  {s.lower()}  "
        return Counter(s[i:i + n] for i in range(len(s) - n + 1))

    def _fuzzy_codes(self, code: str, k: int = 5):
        """Векторный поиск похожих кодов: символьные 3-граммы + косинусная близость (без LLM)."""
        from src.iso1832 import norm_code
        if getattr(self, "_cg_src", None) is not self.catalog:
            self._cg_src = self.catalog
            self._code_grams = {}
            for it in self.catalog:
                c = it.get("_code_up") or ""
                if c and c not in self._code_grams:
                    self._code_grams[c] = self._grams(c)
        qg = self._grams(norm_code(code))
        qn = math.sqrt(sum(v * v for v in qg.values())) or 1.0
        out = []
        for c, g in self._code_grams.items():
            num = sum(v * qg.get(t, 0) for t, v in g.items())
            den = (math.sqrt(sum(v * v for v in g.values())) or 1.0) * qn
            sim = num / den
            if sim >= 0.6:
                out.append((c, sim))
        return sorted(out, key=lambda x: -x[1])[:k]

    def _filter_and_score(self, f: Dict[str, Any], query_tokens: List[str], allow_secondary_iso: bool = False) -> List[Dict[str, Any]]:
        results = []
        in_stock_only = f.get("in_stock_only")
        cat_req = f.get("category")
        iso_req = f.get("iso_group")
        code_req = f.get("insert_iso_code")
        shape_req = f.get("insert_shape")
        ca_req = f.get("clearance_angle")
        size_req = f.get("size_code")
        rad_req = f.get("corner_radius_mm")
        cb_req = f.get("chipbreaker")
        op_req = f.get("operation")
        grade_req = f.get("grade")
        coat_req = f.get("coating")
        brand_req = f["brand"].lower() if f.get("brand") else None
        pitch_req = f.get("pitch_value")
        tp_req = f.get("thread_profile")
        side_req = f.get("side")
        hand_req = f.get("hand")
        gw_req = f.get("groove_width_mm")
        fc_req = f.get("family_code")

        for doc_id, item in enumerate(self.catalog):
            if in_stock_only and item["stock"] <= 0:
                continue
            if EXCLUDE_INACTIVE and item.get("_inactive"):
                continue
            if cat_req and item["category"] != cat_req:
                continue

            iso_bonus = 0.0
            if iso_req:
                if iso_req in item["_iso_primary_list"]:
                    iso_bonus = 8.0
                elif allow_secondary_iso and iso_req in item["_iso_secondary_list"]:
                    iso_bonus = 4.0
                else:
                    continue

            if code_req and not (item["_code_up"].startswith(code_req) or item["_head_up"].startswith(code_req)):
                continue
            if shape_req and item["_shape_up"] != shape_req:
                continue
            if ca_req and item["_ca_up"] != ca_req:
                continue
            if size_req and item["_size_str"] != size_req:
                continue
            if rad_req is not None:
                r_item = item["corner_radius_mm"]
                if r_item is None or abs(r_item - rad_req) > 0.05:
                    continue
            if cb_req and cb_req != item["_cb_up"] and cb_req not in item["_cb_parts"]:
                continue
            if op_req and item["_op_list"] and op_req not in item["_op_list"]:
                continue
            if grade_req and grade_req != item["_grade_up"] and grade_req not in item["_grade_up"]:
                continue
            if coat_req and coat_req != item["_coat_up"]:
                continue
            if brand_req and brand_req not in item["_brand_low"]:
                continue
            if pitch_req is not None:
                p_item = item["pitch_value"]
                if p_item is None or abs(p_item - pitch_req) > 0.02:
                    continue
            if tp_req and tp_req not in item["_tp_up"]:
                continue
            if side_req and item["_side_low"] != side_req:
                continue
            if hand_req and item["_hand_up"] != hand_req:
                continue
            if gw_req is not None:
                gw_item = item["groove_width_mm"]
                if gw_item is None or abs(gw_item - gw_req) > 0.05:
                    continue
            if fc_req and not item["_fc_up"].startswith(fc_req):
                continue

            text_score = self._compute_text_score(query_tokens, doc_id) if query_tokens else 1.0
            both_bonus = 1.0 if item.get("in_both_stores") == "1" else 0.0
            total_score = iso_bonus + text_score + both_bonus + (2.0 if item["stock"] > 0 else 0.0)
            results.append({"item": item, "score": total_score})

        return results
