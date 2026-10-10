@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist venv\Scripts\python.exe (echo Once KUR.bat calistirin. & pause & exit /b 1)
set /p KADI=Sifresi sifirlanacak kullanici adi: 
venv\Scripts\python.exe -m app.panel sifre-sifirla "%KADI%"
pause
