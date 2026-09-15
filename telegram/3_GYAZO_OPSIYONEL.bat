@echo off
title Gyazo gorselleri - OPSIYONEL (sadece hala acilan linkler)
cd /d "%~dp0"
if not exist "%~dp0bot_log.txt" (
  echo.
  echo HATA: bot_log.txt bu klasorde yok. Dosyalari BOT KLASORUNE cikarin.
  echo.
  pause
  exit /b 1
)
echo.
echo  Gyazo'da HALA acilan linkleri indirir (Telegram'a dokunmaz). Bot kapali olmasi gerekmez.
echo  Sonuc: ekran_goruntuleri\ + indeks.csv  (Durum: gyazo_silinmis = Gyazo'da artik yok)
echo.
pause
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Export-GyazoGorselleri.ps1" -Ay 2 -Format png
echo.
pause
