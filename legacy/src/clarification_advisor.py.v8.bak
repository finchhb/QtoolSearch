"""
src/clarification_advisor.py - Модуль анализа полноты параметров и генерации уточняющих вопросов
"""
from typing import Dict, List, Optional
import re
from src.materials_mapping import detect_iso_group, detect_application_type, detect_insert_shape, detect_corner_radius

class ClarificationAdvisor:
    def __init__(self):
        pass

    def analyze_query_completeness(self, query: str) -> Dict:
        """
        Анализирует текст запроса на наличие необходимых технологических параметров.
        Ветвление (ask_clarification) требуется ТОЛЬКО тогда, когда запрос принципиально размыт:
        нет ни обрабатываемого материала, ни формы/размера пластины, ни конкретного назначения.
        """
        iso_group = detect_iso_group(query)
        app_type = detect_application_type(query)
        shape = detect_insert_shape(query)
        radius = detect_corner_radius(query)

        # Проверка наличия конкретного артикула ISO (например, CNMG, WNMG, CCMT)
        has_iso_code = bool(re.search(r'\b[CWTDSVR][NCTB][MG]\b', query.upper())) or bool(shape)
        
        # Проверка запроса на аналог / замену
        is_analog = any(w in query.lower() for w in ["аналог", "замен", "кросс", "вместо", "эквивалент"])

        # Проверка запроса на совместимость оснастки
        is_tooling = any(w in query.lower() for w in ["державк", "оправк", "подходит", "ставятся в", "комплект"])

        missing = []
        if not iso_group:
            missing.append({
                "field": "material",
                "question": "Какой материал заготовки обрабатывается (марка стали по ГОСТ, нержавеющая сталь, чугун, цветмет)?",
                "hint": "Например: Сталь 40Х (ISO P), 12Х18Н10Т (ISO M), СЧ20 (ISO K), Д16Т (ISO N)."
            })

        if not has_iso_code and not is_tooling:
            missing.append({
                "field": "geometry_or_holder",
                "question": "Какая форма пластины или державка предпочтительна (например, ромб 80° CNMG, тригон WNMG)?",
                "hint": "Укажите форму или маркировку державки (например, PCLNR 2525)."
            })

        # Ветвление нужно ТОЛЬКО если неизвестен материал И неизвестна геометрия/код И это не запрос аналога/оснастки
        clarification_needed = False
        if not iso_group and not has_iso_code and not is_analog and not is_tooling:
            clarification_needed = True

        return {
            "is_complete": not clarification_needed,
            "detected_params": {
                "iso_group": iso_group or "P",  # По умолчанию конструкционная сталь (первый выбор)
                "application_type": app_type,
                "insert_shape": shape or "C",   # По умолчанию ромб 80°
                "corner_radius_mm": radius
            },
            "missing_fields": missing,
            "recommended_action": "ask_clarification" if clarification_needed else "direct_recommendation"
        }

    def generate_clarification_message(self, completeness: Dict) -> str:
        """Формирование вежливого профессионального ответа с уточняющими вопросами"""
        missing = completeness.get("missing_fields", [])
        lines = ["Для точного подбора инструмента и гарантии стойкости подскажите, пожалуйста, несколько деталей:\n"]
        for idx, item in enumerate(missing, 1):
            lines.append(f"{idx}. {item['question']}")
            if item.get('hint'):
                lines.append(f"   *(Подсказка: {item['hint']})*")

        lines.append("\n💡 *Если задача типовая для конструкционной стали (P), стандартный выбор — пластины CNMG 120408 с державкой PCLNR 2525.*")
        return "\n".join(lines)
