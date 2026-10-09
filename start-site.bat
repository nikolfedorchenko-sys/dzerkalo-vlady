@echo off
chcp 65001 >nul
cd /d "%~dp0site"
echo Сайт відкривається на http://localhost:8080
echo Щоб зупинити – закрийте це вікно.
start "" http://localhost:8080
python -m http.server 8080
