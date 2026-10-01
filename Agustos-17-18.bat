@echo off
title 17-18 Agustos gorselleri (Gyazo)
cd /d "%~dp0"
if not exist "%~dp0Gyazo-Cek.ps1" (
  echo HATA: Gyazo-Cek.ps1 bu klasorde yok. Bu .bat dosyasini Gyazo-Cek.ps1 ile ayni klasore koyun.
  pause
  exit /b 1
)
echo.
echo  17-18 Agustos 2026 kayitlarinin gorselleri Gyazo'dan PNG olarak inecek:
echo    Masaustu\Agustos-17-18\  (proje klasorleri + indeks.csv; linkler GyazoLinki sutununda)
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Gyazo-Cek.ps1" -Baslangic 2026-08-17 -Bitis 2026-08-18 -CiktiKlasoru "%USERPROFILE%\Desktop\Agustos-17-18" -Format png
echo.
pause
