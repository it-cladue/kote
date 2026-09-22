# Gelistirilmis Telegram Kampanya Botu - Windows baslatici
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location $PSScriptRoot

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "  Gelistirilmis Telegram Kampanya Botu" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""

if (Get-Command py -ErrorAction SilentlyContinue) {
    $python = "py"
    $pythonArgs = @("-3")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $python = "python"
    $pythonArgs = @()
} elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
    $python = "python3"
    $pythonArgs = @()
} else {
    Write-Host "HATA: Python 3 bulunamadi. https://www.python.org/downloads/ adresinden kurun." -ForegroundColor Red
    Read-Host "Cikmak icin Enter"
    exit 1
}

if (-not (Test-Path "config.txt")) {
    Write-Host "HATA: config.txt bulunamadi." -ForegroundColor Red
    Read-Host "Cikmak icin Enter"
    exit 1
}

$configText = Get-Content "config.txt" -Raw
if ($configText -match "BURAYA_BOT_TOKEN" -or $configText -match "BURAYA_GUCLU_ADMIN_SIFRESI") {
    Write-Host "UYARI: Once config.txt icindeki TOKEN ve PASSWORD alanlarini doldurun." -ForegroundColor Yellow
    Read-Host "Cikmak icin Enter"
    exit 1
}

New-Item -ItemType Directory -Force -Path "images", "backups", "complaints", "complaints\images" | Out-Null

Write-Host "[*] Python paketleri kontrol ediliyor..." -ForegroundColor Yellow
& $python @pythonArgs -m pip install --quiet -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "HATA: Gerekli Python paketleri kurulamadi." -ForegroundColor Red
    Read-Host "Cikmak icin Enter"
    exit 1
}

Write-Host "[OK] Bot baslatiliyor..." -ForegroundColor Green
& $python @pythonArgs "bot.py"

if ($LASTEXITCODE -ne 0) {
    Write-Host "Bot hata ile kapandi. Ayrintilar icin logs klasorunu kontrol edin." -ForegroundColor Red
}
Read-Host "Cikmak icin Enter"
