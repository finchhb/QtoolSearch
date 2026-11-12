@echo off
chcp 65001 >nul
cd /d "%~dp0"
python patch_sources2.py
echo.
pause