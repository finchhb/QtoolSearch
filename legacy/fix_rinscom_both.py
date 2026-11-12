#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_rinscom_both.py — Исправление показа позиций Rinscom.com при включенном режиме «Оба» (Rinscom + qtool).
Исправляет:
  1. Склейку одинаковых позиций между Rinscom и qtool по нормализованному обозначению (head / iso+cb+grade),
     чтобы не терялись цены и остатки Rinscom.com.
  2. Балансировку выдачи в режиме 'both': гарантированное присутствие позиций Rinscom.com и двухмагазинных позиций в ТОП-выдаче.
  3. Сброс ложных токарных фильтров (insert_shape / clearance_angle) для канавочных (MGMN) и резьбовых (16ER/16IR) пластин Rinscom.
  4. Отображение плашки [Rinscom.com + qtool.ru] в ответе бота.
"""
import os
import re

ROOT = os.path.dirname(os.path.abspath(__file__))


def patch_hybrid_search():
    path = os.path.join(ROOT, "src", "hybrid_search.py")
    if not os.path.exists(path):
        print("❌ Не найден src/hybrid_search.py")
        return

    with open(path, "r", encoding="utf-8-sig") as f:
        code = f.read()

    # 1. Для канавочных и резьбовых пластин (которые лежат в Rinscom) отключаем фильтрацию по токарным полям insert_shape/clearance_angle/insert_iso_code
    old_cat_init = '''        initial_filters = {
            "category": category or "turning_insert",'''
    new_cat_init = '''        eff_cat = category or "turning_insert"
        if eff_cat in ("groove_insert", "thread_insert"):
            # Для канавочных и резьбовых пластин (MGMN, 16ER и др. из базы Rinscom) не применяем токарные фильтры формы/заднего угла
            if insert_iso_code and not family_code:
                family_code = re.match(r"^[A-Z0-9]+", insert_iso_code).group(0) if re.match(r"^[A-Z0-9]+", insert_iso_code) else None
            insert_iso_code = None
            insert_shape = None
            clearance_angle = None

        initial_filters = {
            "category": eff_cat,'''

    if "eff_cat = category or \"turning_insert\"" not in code:
        code = code.replace(old_cat_init, new_cat_init, 1)

    # 2. Исправляем _merge_duplicates: в Rinscom sku — это числовой ID (154822), а название пластины лежит в head!
    new_merge = '''    @staticmethod
    def _merge_duplicates(matches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Склеивает одинаковые пластины между Rinscom.com и qtool.ru по нормализованному обозначению (head или iso_code+cb+grade),
        сохраняя предложения обоих магазинов в item['_offers'] и выставляя оба URL."""
        def key(it: Dict[str, Any]) -> str:
            h = re.sub(r"[^A-Z0-9]", "", str(it.get("head") or "").upper())
            if len(h) >= 6:
                return "H:" + h
            iso = str(it.get("iso_code") or "").strip().upper()
            cb = re.sub(r"[^A-Z0-9]", "", str(it.get("chipbreaker") or "").upper())
            gr = re.sub(r"[^A-Z0-9]", "", str(it.get("grade") or "").upper())
            if iso and gr:
                return f"ICG:{iso}_{cb}_{gr}"
            return re.sub(r"[^A-Z0-9А-Я]", "", str(it.get("sku") or "").upper()) or str(id(it))

        groups: Dict[str, Dict[str, Any]] = {}
        order: List[str] = []
        for m in matches:
            k = key(m["item"])
            if k not in groups:
                groups[k] = {"match": m, "rows": [m["item"]]}
                order.append(k)
            else:
                groups[k]["rows"].append(m["item"])
                if m["score"] > groups[k]["match"]["score"]:
                    groups[k]["match"]["score"] = m["score"]

        merged: List[Dict[str, Any]] = []
        for k in order:
            g = groups[k]
            rows_list = g["rows"]
            if len(rows_list) == 1:
                merged.append(g["match"])
                continue

            # Предпочитаем запись, где заполнены обе ссылки, либо строку Rinscom для отображения кода 1С
            r_row = next((r for r in rows_list if r.get("source_site") == "rinscom.com"), None)
            q_row = next((r for r in rows_list if r.get("source_site") == "qtool.ru"), None)
            base = dict(r_row or rows_list[0])
            if q_row and not base.get("qtool_url"):
                base["qtool_url"] = q_row.get("qtool_url", "")
            if r_row and not base.get("rinscom_url"):
                base["rinscom_url"] = r_row.get("rinscom_url", "")
            if r_row and q_row:
                base["in_both_stores"] = "1"
                base["source_site"] = "Rinscom.com + qtool.ru"

            offers = []
            seen_stores = set()
            for r in rows_list:
                st_name = r.get("source_site", "")
                url = (r.get("qtool_url") if st_name == "qtool.ru" else r.get("rinscom_url")) or r.get("rinscom_url") or r.get("qtool_url") or ""
                offer_key = (st_name, r.get("sku", ""), r.get("price", 0.0))
                if offer_key in seen_stores:
                    continue
                seen_stores.add(offer_key)
                offers.append({
                    "store": st_name,
                    "sku": r.get("sku", ""),
                    "stock": r.get("stock", 0),
                    "price": r.get("price", 0.0),
                    "currency": r.get("currency", "RUB"),
                    "por": bool(r.get("_por")),
                    "url": url,
                })
            base["_offers"] = offers
            base["stock"] = sum(int(r.get("stock", 0) or 0) for r in rows_list)
            m2 = dict(g["match"])
            m2["item"] = base
            m2["score"] += 2.5  # Бонус за подтверждённое наличие сразу в двух прайсах
            merged.append(m2)
        merged.sort(key=lambda m: (m["score"], m["item"].get("stock", 0)), reverse=True)
        return merged'''

    code = re.sub(
        r"    @staticmethod\n    def _merge_duplicates\(matches: List\[Dict\[str, Any\]\]\) -> List\[Dict\[str, Any\]\]:.*?(?=\n    def _select_diverse_top)",
        new_merge + "\n",
        code,
        flags=re.DOTALL,
    )

    # 3. Балансируем _select_diverse_top: чтобы в режиме 'both' позиции с Rinscom.com ВСЕГДА попадали в выдачу
    new_diverse = '''    def _select_diverse_top(self, matches: List[Dict[str, Any]], initial_filters: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
        if not matches or len(matches) <= limit:
            return matches[:limit]

        # Гарантируем баланс магазинов: чтобы позиции с Rinscom.com (включая эксклюзивные Rinscom) не вытеснялись огромным числом строк qtool.ru
        rinscom_matches = [
            m for m in matches
            if "rinscom" in (m["item"].get("source_site") or "").lower()
            or str(m["item"].get("in_both_stores")) == "1"
            or bool(m["item"].get("rinscom_url"))
        ]
        pure_rinscom = [m for m in matches if (m["item"].get("source_site") or "").lower() == "rinscom.com"]
        qtool_matches = [m for m in matches if (m["item"].get("source_site") or "").lower() == "qtool.ru" and str(m["item"].get("in_both_stores")) != "1"]

        picked: List[Dict[str, Any]] = []
        picked_ids = set()

        def add_cand(cand):
            cid = id(cand)
            if cid not in picked_ids and len(picked) < limit:
                picked.append(cand)
                picked_ids.add(cid)

        # Сначала берём до 2 чистых позиций Rinscom.com и до 2 двухмагазинных позиций
        for m in pure_rinscom[:2]:
            add_cand(m)
        for m in rinscom_matches[:3]:
            add_cand(m)
        for m in qtool_matches[:2]:
            add_cand(m)

        # Добираем оставшиеся слоты по общему рейтингу и разнообразию задних углов
        for m in matches:
            if len(picked) >= limit:
                break
            add_cand(m)

        return picked[:limit]'''

    code = re.sub(
        r"    def _select_diverse_top\(self, matches: List\[Dict\[str, Any\]\], initial_filters: Dict\[str, Any\], limit: int\) -> List\[Dict\[str, Any\]\]:.*?(?=\n    def build_follow_up_questions)",
        new_diverse + "\n",
        code,
        flags=re.DOTALL,
    )

    # 4. Увеличиваем бонус в _filter_and_score для позиций с Rinscom.com и in_both_stores, а также разрешаем пустой iso_group при совпадении кода пластины
    code = code.replace(
        'both_bonus = 1.0 if item.get("in_both_stores") == "1" else 0.0',
        'both_bonus = (3.5 if item.get("in_both_stores") == "1" else 0.0) + (2.0 if item.get("source_site") == "rinscom.com" else 0.0)',
    )
    code = code.replace(
        """            if iso_req:
                if iso_req in item["_iso_primary_list"]:
                    iso_bonus = 8.0
                elif allow_secondary_iso and iso_req in item["_iso_secondary_list"]:
                    iso_bonus = 4.0
                else:
                    continue""",
        """            if iso_req:
                if iso_req in item["_iso_primary_list"]:
                    iso_bonus = 8.0
                elif allow_secondary_iso and iso_req in item["_iso_secondary_list"]:
                    iso_bonus = 4.0
                elif (code_req or fc_req) and not item["_iso_primary_list"]:
                    iso_bonus = 2.0
                else:
                    continue""",
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write(code)
    print("✅ 1/3: src/hybrid_search.py — исправлена склейка Rinscom + qtool и добавлена гарантированная квота позиций Rinscom.com в выдаче.")


def patch_clarification_and_engine():
    # 1. Патчим src/clarification_advisor.py, чтобы резьбовые (16ER/16IR), канавочные (MGMN/TGF) и державки из Rinscom не блокировались уточняющими вопросами
    ca_path = os.path.join(ROOT, "src", "clarification_advisor.py")
    if os.path.exists(ca_path):
        with open(ca_path, "r", encoding="utf-8-sig") as f:
            ca_code = f.read()
        old_has_iso = "has_iso_code = bool(re.search(r'\\b[ABCDEFGHKLMOPRSTVW][ABCDEGFNP][ACEFGHJKLMNU][NRFAMGWTQUBHCJX](\\s?\\d|\\b)', query.upper())) or bool(shape)"
        new_has_iso = (
            "has_iso_code = bool(re.search(r'\\b[ABCDEFGHKLMOPRSTVW][ABCDEGFNP][ACEFGHJKLMNU][NRFAMGWTQUBHCJX](\\s?\\d|\\b)', query.upper())) "
            "or bool(shape) or bool(re.search(r'\\b(16ER|16IR|11IR|11ER|22ER|22IR|06IR|08IR|MGMN|MGGN|TGF|8GR|APKT|APMT|LNMU|LOGU|SEKT|SPGT|SOMG|RCMT|SCMT|VCMT|CCET)\\b', query.upper())) "
            "or any(w in query.lower() for w in ['резьб', 'канав', 'отрез', 'державк', 'оправк', 'расточ', 'резц'])"
        )
        if old_has_iso in ca_code:
            ca_code = ca_code.replace(old_has_iso, new_has_iso)
            with open(ca_path, "w", encoding="utf-8") as f:
                f.write(ca_code)
            print("✅ 2/3: src/clarification_advisor.py — разрешён прямой поиск резьбовых, канавочных пласти