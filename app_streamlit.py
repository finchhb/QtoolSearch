"""
app_streamlit.py - веб-виджет QtoolSearch на Streamlit.

Две вкладки:
  1. «Быстрый поиск» — мгновенные карточки товаров, расшифровка ISO, копирование артикула.
  2. «Пакетный подбор» — вставка столбца из Excel / загрузка .xlsx/.csv, выгрузка результата в .xlsx.

Режим виджета: открыть с ?embed=true — скрываются шапка/футер/меню Streamlit, чтобы
встраивать через <iframe> на сайт. Ходит в единый Backend API (API_BASE_URL), индекс
держится в одном процессе api.py, а не в трёх копиях.

Переменные: API_BASE_URL (по умолчанию http://api:8000), APP_TITLE.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List

import requests
import streamlit as st

API_BASE_URL = os.environ.get("API_BASE_URL", "http://api:8000").rstrip("/")
APP_TITLE = os.environ.get("APP_TITLE", "QtoolSearch — подбор аналогов")
REQUEST_TIMEOUT = 30


# --------------------------------------------------------------------------------------------------
# Запросы к Backend API
# --------------------------------------------------------------------------------------------------
def _api_post(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    resp = requests.post(API_BASE_URL + path, json=payload, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _api_get(path: str) -> Dict[str, Any]:
    resp = requests.get(API_BASE_URL + path, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


# --------------------------------------------------------------------------------------------------
# Кэш состояния
# --------------------------------------------------------------------------------------------------
def _init_state() -> None:
    if "embed" not in st.session_state:
        # ?embed=true — режим встраивания в iframe.
        params = st.query_params
        st.session_state.embed = str(params.get("embed", "")).lower() in ("1", "true", "yes")


def _embed_css() -> None:
    st.markdown(
        """
        <style>
        #MainMenu {visibility: hidden;}
        header {visibility: hidden;}
        footer {visibility: hidden;}
        .stApp {margin: 0;}
        block-container {padding-top: 1.2rem;}
        </style>
        """,
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------------------------------
# Карточка товара (быстрый поиск)
# --------------------------------------------------------------------------------------------------
_MATCH_COLORS = {
    "точное": "🟢 точное совпадение",
    "полный аналог": "🔵 полный аналог",
    "близкий аналог": "🟡 близкий аналог",
    "не найдено": "⚪ не найдено",
}


def _render_card(p: Dict[str, Any], idx: int) -> None:
    label = _MATCH_COLORS.get(p.get("match_type", ""), p.get("match_type", ""))
    with st.container(border=True):
        top = st.columns([3, 1])
        top[0].markdown(f"**{idx}. {p.get('name') or p.get('sku')}**")
        top[1].markdown(f"<span style='font-size:0.8rem'>{label}</span>", unsafe_allow_html=True)
        meta = []
        if p.get("sku"):
            meta.append(f"Артикул: `{p['sku']}`")
        if p.get("brand"):
            meta.append(f"Бренд: {p['brand']}")
        if meta:
            st.caption(" · ".join(meta))
        stock = int(p.get("stock") or 0)
        price = p.get("price_display") or "по запросу"
        st.markdown(f"**{price}** — " + (f"✅ в наличии {stock} шт." if stock > 0 else "⏳ под заказ"))
        btns = st.columns(2)
        if p.get("sku"):
            btns[0].code(p["sku"], language=None)
        if p.get("url"):
            btns[1].link_button("Открыть на сайте", p["url"])


# --------------------------------------------------------------------------------------------------
# Вкладка 1: быстрый поиск
# --------------------------------------------------------------------------------------------------
def tab_single() -> None:
    st.subheader("Быстрый поиск")
    q = st.text_input("Артикул или запрос", placeholder="Например: CNMG 120408 PM 4325", key="single_q")
    limit = st.slider("Сколько позиций показать", 1, 10, 5, key="single_limit")
    if st.button("Найти", type="primary", key="single_btn") or (q and st.session_state.get("auto_single")):
        if not q.strip():
            st.warning("Введите запрос.")
            return
        try:
            data = _api_post("/search/single", {"query": q, "limit": limit})
        except requests.RequestException as e:
            st.error(f"Ошибка связи с API: {e}")
            return
        chips = data.get("chips") or []
        if data.get("corrected"):
            st.info(f"Распознанный код: `{data['corrected']}`")
        if chips:
            st.caption("Понял запрос: " + " · ".join(chips))
        results = data.get("results") or []
        if not results:
            st.warning("Ничего не найдено. Уточните группу и параметры (например, пластина CNMG 120408).")
            return
        for i, p in enumerate(results, 1):
            _render_card(p, i)


# --------------------------------------------------------------------------------------------------
# Вкладка 2: пакетный подбор
# --------------------------------------------------------------------------------------------------
def _batch_to_dataframe(results: List[Dict[str, Any]]):
    import pandas as pd

    rows = []
    for r in results:
        res = r.get("results") or []
        t1 = res[0] if res else {}
        rows.append({
            "Запрос": r.get("query", ""),
            "Количество": r.get("qty"),
            "Статус": r.get("status", ""),
            "Артикул (топ-1)": t1.get("sku", ""),
            "Название": t1.get("name", ""),
            "Бренд": t1.get("brand", ""),
            "Тип совпадения": t1.get("match_type", ""),
            "Наличие": t1.get("stock", ""),
            "Цена": t1.get("price_display", ""),
            "Ссылка": t1.get("url", ""),
        })
    return pd.DataFrame(rows)


def tab_batch() -> None:
    st.subheader("Пакетный подбор (Excel / Список)")

    queries: List[Any] = []
    source_headers = None
    source_rows = None

    mode = st.radio("Источник", ["Вставить список", "Загрузить файл"], horizontal=True, key="batch_mode")

    if mode == "Вставить список":
        txt = st.text_area("Вставьте столбец артикулов (по одному в строке)", height=200, key="batch_text")
        queries = [ln.strip() for ln in (txt or "").splitlines() if ln.strip()]
    else:
        up = st.file_uploader("Загрузите .xlsx или .csv", type=["xlsx", "csv"], key="batch_file")
        if up is not None:
            raw = up.getvalue()
            try:
                from src.service import read_table_bytes
                source_headers, source_rows, col = read_table_bytes(up.name, raw)
            except Exception as e:
                st.error(f"Не удалось прочитать файл: {e}")
                source_headers, source_rows, col = [], [], None
            if source_rows and col is not None:
                # Даём выбрать колонку, если их несколько.
                options = list(range(len(source_headers))) if source_headers else [col]
                default = options.index(col) if col in options else 0
                chosen = st.selectbox("Колонка с артикулом", options, index=default, key="batch_col",
                                      format_func=lambda i: source_headers[i] if source_headers else f"Столбец {i + 1}")
                queries = [row[chosen] if chosen < len(row) else "" for row in source_rows]
                queries = [q for q in queries if q and q.strip()]
                st.caption(f"Строк для обработки: {len(queries)}")
            elif source_rows:
                queries = [row[0] if row else "" for row in source_rows]

    limit = st.slider("Альтернатив на позицию", 1, 5, 3, key="batch_limit")

    if st.button("Подобрать аналоги", type="primary", key="batch_btn"):
        if not queries:
            st.warning("Нет данных для обработки.")
            return
        if len(queries) > 500:
            st.error("Не более 500 строк за один раз.")
            return
        with st.spinner(f"Обрабатываю {len(queries)} строк…"):
            try:
                data = _api_post("/search/batch", {"queries": queries, "limit": limit})
            except requests.RequestException as e:
                st.error(f"Ошибка связи с API: {e}")
                return
        results = data.get("results") or []
        st.success(f"Готово: найдено {data.get('found', 0)} из {data.get('count', len(results))}")
        st.dataframe(_batch_to_dataframe(results), use_container_width=True)

        # Выгрузка в .xlsx через API-ядро (те же заголовки и ссылки).
        try:
            from src.service import build_batch_xlsx
            xlsx = build_batch_xlsx(results, source_headers, source_rows)
            st.download_button("Скачать результат в Excel", xlsx, file_name="qtool_search_result.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               key="batch_download")
        except Exception as e:
            st.warning(f"Не удалось собрать Excel: {e}")


# --------------------------------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------------------------------
def main() -> None:
    _init_state()
    st.set_page_config(page_title=APP_TITLE, page_icon="🔧", layout="wide", initial_sidebar_state="collapsed")
    if st.session_state.embed:
        _embed_css()

    if not st.session_state.embed:
        st.title(APP_TITLE)
    tab1, tab2 = st.tabs(["Быстрый поиск", "Пакетный подбор (Excel / Список)"])
    with tab1:
        tab_single()
    with tab2:
        tab_batch()


if __name__ == "__main__":
    main()