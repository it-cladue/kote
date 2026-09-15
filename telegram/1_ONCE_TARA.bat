@echo off
title Telegram gorselleri - TARAMA (indirme yok)
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
echo  Once BOT'u kapatin (calisiyorsa). Bu adim sadece TARAR, indirmez.
echo  Sonuc: telegram_gorseller\indeks.csv
echo.
pause
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Recover-TelegramGorselleri.ps1" -SadeceTara -SonAy 2 -Format png
echo.
pause
