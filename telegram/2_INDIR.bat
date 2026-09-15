@echo off
title Telegram gorselleri - INDIR (son 2 ay, PNG)
cd /d "%~dp0"
if not exist "%~dp0telegram_cache.txt" (
  echo.
  echo HATA: telegram_cache.txt bu klasorde yok.
  echo Bu dosyalari BOT KLASORUNE cikarin: bot_log.txt, telegram_cache.txt ve config.json'un oldugu klasor.
  echo.
  pause
  exit /b 1
)
echo.
echo  Once BOT'u kapatin (calisiyorsa). Son 2 ayin gorselleri PNG olarak inecek:
echo    telegram_gorseller\OF, GA, HI, PP, VI, PA  +  indeks.csv
echo  Kesilirse tekrar calistirin; inmis olanlar atlanir.
echo.
pause
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Recover-TelegramGorselleri.ps1" -SonAy 2 -Format png
echo.
pause
