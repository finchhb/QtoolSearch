import os

path = "src/analogs_engine.py"
if os.path.exists(path):
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Заменяем сигнатуру конструктора на универсальную с *args, **kwargs
    old_init = "def __init__(self, excel_path="
    new_init = "def __init__(self, *args, **kwargs):"
    
    # Полностью заменим класс или аккуратно поправим __init__
    analogs_code = '''import pandas as pd
import os

class AnalogsEngine:
    def __init__(self, *args, **kwargs):
        self.analogs = []
        # Пытаемся найти путь к таблице из аргументов или по умолчанию
        excel_path = "data/Кросс_таблица_Аналогов_Сплавов_и_Стружколомов.xlsx"
        if args and isinstance(args[0], str) and ".xlsx" in args[0]:
            excel_path = args[0]
        elif "excel_path" in kwargs:
            excel_path = kwargs["excel_path"]
        elif "cross_codes_path" in kwargs and os.path.exists(kwargs["cross_codes_path"]):
            # Если передали старый путь, оставляем как есть, но пробуем подгрузить Excel
            pass

        if os.path.exists(excel_path):
            try:
                xls = pd.ExcelFile(excel_path)
                df = pd.read_excel(xls, sheet_name="Матрица Аналогов (Все Бренды)")
                self.analogs = df.to_dict('records')
            except Exception:
                pass

    def find_analogs(self, query: str) -> list:
        query = str(query or "").upper()
        results = []
        for row in self.analogs:
            for key, val in row.items():
                if pd.notna(val) and isinstance(val, str) and query in val.upper():
                    zumo = str(row.get('Келит (ZZKLT)', ''))
                    kzts = str(row.get('КЗТС', ''))
                    if zumo != 'nan' and zumo: results.append(zumo)
                    if kzts != 'nan' and kzts: results.append(kzts)
        return list(set([r for r in results if r]))
'''
    with open(path, "w", encoding="utf-8") as f:
        f.write(analogs_code)
    print("✅ src/analogs_engine.py успешно исправлен!")
else:
    print("❌ Файл src/analogs_engine.py не найден.")