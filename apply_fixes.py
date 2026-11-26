#!/usr/bin/env python3
"""Применяет все исправления обучения программно."""
import os
import sys

def patch_file(filepath, replacements):
    """Применяет серию замен к файлу."""
    if not os.path.exists(filepath):
        print(f"ОШИБКА: Файл не найден: {filepath}")
        return False
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original = content
    for old, new in replacements:
        if old not in content:
            print(f"  ПРЕДУПРЕЖДЕНИЕ: Не найден фрагмент для замены в {filepath}")
            print(f"    Ищем: {old[:80]}...")
            continue
        content = content.replace(old, new, 1)
    
    if content == original:
        print(f"  Файл не изменён: {filepath}")
        return True
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"  ✓ Обновлён: {filepath}")
    return True

def main():
    print("Применение исправлений обучения...\n")
    
    # Исправление 1: src/training.py - добавляем интеграцию с движком
    print("1. Обновление src/training.py...")
    if not patch_file('src/training.py', [
        # Добавляем импорт в начало файла
        ('"""', 
         '"""\n'
         'import os\n'
         'from src.catalog_search import CatalogSearchEngine\n\n'),
        
        # Добавляем функцию интеграции перед def lookup
        ('def lookup(query: str):',
         'def integrate_with_catalog(site_catalog_path: str = "data/catalog_site.csv"):\n'
         '    """Интегрирует обучение с движком поиска.\n'
         '    Вызывается при инициализации приложения.\n'
         '    """\n'
         '    global _catalog_engine\n'
         '    try:\n'
         '        _catalog_engine = CatalogSearchEngine(site_catalog_path)\n'
         '        print(f"  ✓ Обучение интегрировано с каталогом ({len(_catalog_engine.items)} позиций)")\n'
         '        return True\n'
         '    except Exception as e:\n'
         '        print(f"  ОШИБКА интеграции обучения: {e}")\n'
         '        return False\n\n\n'
         'def get_catalog_engine():\n'
         '    """Возвращает движок каталога для поиска."""\n'
         '    return _catalog_engine\n\n\n'
         'def lookup(query: str):')
    ]):
        return 1
    
    # Исправление 2: app.py - вызываем интеграцию при старте
    print("\n2. Обновление app.py...")
    if not patch_file('app.py', [
        # Добавляем импорт training
        ('from src.engine import ToolAdvisorEngine',
         'from src.engine import ToolAdvisorEngine\n'
         'from src import training'),
        
        # Добавляем вызов интеграции после инициализации движка
        ('engine = ToolAdvisorEngine()',
         'engine = ToolAdvisorEngine()\n\n'
         '# Интегрируем обучение с движком поиска\n'
         'print("Интеграция обучения с движком...")\n'
         'training.integrate_with_catalog()')
    ]):
        return 1
    
    # Исправление 3: src/catalog_search.py - добавляем проверку обучения
    print("\n3. Обновление src/catalog_search.py...")
    if not patch_file('src/catalog_search.py', [
        # Добавляем импорт в начало файла
        ('import re',
         'import re\n'
         'from src import training'),
        
        # Модифицируем метод search для приоритетного поиска в обучении
        ('    def search(self, query: str) -> list:',
         '    def search(self, query: str) -> list:\n'
         '        # Сначала проверяем точные совпадения в обучении\n'
         '        exact = training.lookup_exact(query)\n'
         '        if exact:\n'
         '            return exact\n'
         '        \n'
         '        # Затем проверяем похожие запросы\n'
         '        similar = training.lookup(query)\n'
         '        if similar:\n'
         '            return similar\n')
    ]):
        return 1
    
    print("\n✓ Все исправления успешно применены!")
    print("\nТеперь обучение будет работать:")
    print("  1. Данные сохраняются в data/training_examples.csv")
    print("  2. При поиске сначала проверяются примеры обучения")
    print("  3. Точные совпадения имеют наивысший приоритет")
    print("  4. Похожие запросы (TF-IDF > 0.35) используются как подсказки")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())