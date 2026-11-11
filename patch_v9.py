

import os
import re
import pandas as pd

print("🚀 Запуск исправления и обновления до версии 9...")

# 1. Патчим ISO 1832 для распознавания русских терминов
path_iso = "src/iso1832.py"
if os.path.exists(path_iso):
    with open(path_iso, "r", encoding="utf-8") as f:
        content = f.read()
    
    rus_shapes = '''
RUS_SHAPES = {
    "ромб": "C", "треугольник": "T", "квадрат": "S", "круг": "R", "круглая": "R",
    "тригон": "W", "ломаный треугольник": "W", "шестигранник": "H", 
    "восьмигранник": "O", "пятигранник": "P", "параллелограмм": "A"
}
'''
    if "RUS_SHAPES" not in content:
        content = content.replace("SHAPES = {", rus_shapes + "SHAPES = {")
        
    if "for rus, iso in RUS_SHAPES.items():" not in content:
        parse_patch = '''def parse(text: str) -> Dict[str, Any]:
    text = text.lower()
    for rus, iso in RUS_SHAPES.items():
        if rus in text:
            text = text.replace(rus, iso)
    text = text.upper()'''
        content = re.sub(r'def parse\(text: str\) -> Dict\[str, Any\]:\s+text = text\.upper\(\)', parse_patch, content)
        
    with open(path_iso, "w", encoding="utf-8") as f:
        f.write(content)
    print("✅ iso1832.py: Добавлено распознавание русских форм (ромб, треугольник и т.д.)")

# 2. Создаем движок поиска аналогов по Excel
path_analogs = "src/analogs_engine.py"
analogs_code = '''import pandas as pd
import os

class AnalogsEngine:
    def __init__(self, excel_path="data/Кросс_таблица_Аналогов_Сплавов_и_Стружколомов.xlsx"):
        self.analogs = []
        if os.path.exists(excel_path):
            try:
                xls = pd.ExcelFile(excel_path)
                df = pd.read_excel(xls, sheet_name="Матрица Аналогов (Все Бренды)")
                self.analogs = df.to_dict('records')
            except:
                pass

    def find_analogs(self, query: str) -> list:
        query = query.upper()
        results = []
        for row in self.analogs:
            for key, val in row.items():
                if pd.notna(val) and isinstance(val, str) and query in val.upper():
                    zumo = str(row.get('Келит (ZZKLT)', ''))
                    kzts = str(row.get('КЗТС', ''))
                    if zumo != 'nan': results.append(zumo)
                    if kzts != 'nan': results.append(kzts)
        return list(set([r for r in results if r]))
'''
with open(path_analogs, "w", encoding="utf-8") as f:
    f.write(analogs_code)
print("✅ analogs_engine.py: Создан движок поиска аналогов по Excel таблице.")

# 3. Обновляем engine.py для многострочного поиска
path_engine = "src/engine.py"
if os.path.exists(path_engine):
    with open(path_engine, "r", encoding="utf-8") as f:
        content = f.read()
        
    if "from src.analogs_engine import AnalogsEngine" not in content:
        content = "from src.analogs_engine import AnalogsEngine\n" + content
        
    if "queries = [q.strip() for q in query.split('\\n') if q.strip()]" not in content:
        multi_patch = '''def process_query(self, query: str) -> dict:
        queries = [q.strip() for q in query.split('\\n') if q.strip()]
        if len(queries) > 1:
            results = [self._process_single(q) for q in queries]
            return {"multi": True, "results": results}
        return self._process_single(query)
        
    def _process_single(self, query: str) -> dict:'''
        content = content.replace("def process_query(self, query: str) -> dict:", multi_patch)
        
    with open(path_engine, "w", encoding="utf-8") as f:
        f.write(content)
    print("✅ engine.py: Поддержан многострочный ввод запросов.")

print("🎉 Все патчи успешно применены! Перезапустите run.bat.")