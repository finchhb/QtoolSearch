@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Tool Advisor v8.4
echo ====================================================================
echo   Подбор токарных пластин v8.4 (внутренний парсер ISO 1832 + LLM-верификатор)
echo   Откроется http://localhost:8000  (админка: /admin)
echo ====================================================================
if exist "%~dp0python_embed\python.exe" (
    "%~dp0python_embed\python.exe" app.py
    goto :end
)
where python >nul 2>nul
if not errorlevel 1 (
    python app.py
    goto :end
)
where py >nul 2>nul
if not errorlevel 1 (
    py app.py
    goto :end
)
echo Python не найден. Скачиваю портативный Python 3.11 (права администратора не нужны)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip -OutFile py_embed.zip; Expand-Archive -Path py_embed.zip -DestinationPath python_embed -Force; Remove-Item py_embed.zip -Force; Set-Content -Path python_embed\python311._pth -Value python311.zip`r`n.`r`n..`r`nimport site"
if exist "%~dp0python_embed\python.exe" (
    "%~dp0python_embed\python.exe" app.py
) else (
    echo [ОШИБКА] Не удалось запустить Python. Установите Python 3 с https://www.python.org
)
:end
pause
