@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==== Kanit Paneli kurulum ====
where py >nul 2>nul
if errorlevel 1 (
  echo Python bulunamadi. https://www.python.org/downloads/windows/ adresinden Python 3.11 veya 3.12 kurun.
  echo Kurulumda "Add python.exe to PATH" kutusunu isaretleyin, sonra bu dosyayi tekrar calistirin.
  pause
  exit /b 1
)
if not exist venv (
  echo Sanal ortam olusturuluyor...
  py -3 -m venv venv || (echo venv olusturulamadi & pause & exit /b 1)
)
call venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt || (echo Paketler kurulamadi. Internet baglantisini kontrol edin. & pause & exit /b 1)
if not exist panel_ayar.json (
  copy panel_ayar.ornek.json panel_ayar.json >nul
  echo.
  echo panel_ayar.json olusturuldu. ICINDEKI BOT_KLASOR SATIRINI bot klasorunuze gore duzeltin:
  echo    "BOT_KLASOR": "C:\\...\\telegramkant"
  echo    (ters bolu isaretleri cift yazilir: \\ )
  echo.
)
echo.
echo Ilk super admin kullanicisini acalim.
set /p KADI=Kullanici adi (ornek: admin): 
if "%KADI%"=="" set KADI=admin
python -m app.panel kullanici-ekle %KADI% admin
echo.
echo Kurulum tamam. BASLAT.bat ile paneli acin; tarayicida http://127.0.0.1:8080
pause
