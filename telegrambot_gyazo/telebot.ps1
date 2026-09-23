# ===================== AYARLAR =====================
# ==================== CONFIG / AYAR ====================
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $SCRIPT_DIR) { $SCRIPT_DIR = (Get-Location).Path }
$CONFIG_DOSYA = Join-Path $SCRIPT_DIR "config.json"

$global:Config = $null
if (Test-Path $CONFIG_DOSYA) {
    try { $global:Config = Get-Content $CONFIG_DOSYA -Encoding UTF8 -Raw | ConvertFrom-Json }
    catch { Write-Host "config.json okunamadi: $_" }
}

function Get-ConfigValue($name, $defaultValue) {
    $envName = "TELEBOT_$name"
    $envValue = [Environment]::GetEnvironmentVariable($envName, "User")
    if (-not $envValue) { $envValue = [Environment]::GetEnvironmentVariable($envName, "Machine") }
    if (-not $envValue) { $envValue = [Environment]::GetEnvironmentVariable($envName, "Process") }
    if ($envValue) { return $envValue }

    if ($global:Config) {
        $prop = $global:Config.PSObject.Properties[$name]
        if ($prop -and $null -ne $prop.Value -and [string]$prop.Value -ne "") { return $prop.Value }
    }
    return $defaultValue
}

function Join-Base($fileName) { return (Join-Path $SCRIPT_DIR $fileName) }

$TELEGRAM_TOKEN   = [string](Get-ConfigValue "TELEGRAM_TOKEN" "BURAYA_TELEGRAM_BOT_TOKEN")
$GYAZO_TOKEN      = [string](Get-ConfigValue "GYAZO_TOKEN" "BURAYA_GYAZO_TOKEN")
$SIFRE            = [string](Get-ConfigValue "BOT_PASSWORD" "BURAYA_GUVENLI_SIFRE")
$ADMIN_SIFRE      = [string](Get-ConfigValue "ADMIN_PASSWORD" "telecc123")
$ADMIN_IDS        = @(Get-ConfigValue "ADMIN_IDS" @())
$MAX_DENEME       = [int](Get-ConfigValue "MAX_DENEME" 3)
$EXCEL_DOSYA      = [string](Get-ConfigValue "EXCEL_DOSYA" (Join-Base "telegrambot_gyazo.xlsx"))
$OFFSET_DOSYA     = [string](Get-ConfigValue "OFFSET_DOSYA" (Join-Base "telegram_offset.txt"))
$CACHE_DOSYA      = [string](Get-ConfigValue "CACHE_DOSYA" (Join-Base "telegram_cache.txt"))
$LOG_DOSYA        = [string](Get-ConfigValue "LOG_DOSYA" (Join-Base "bot_log.txt"))
$ONAYLILAR_DOSYA  = [string](Get-ConfigValue "ONAYLILAR_DOSYA" (Join-Base "onaylilar.txt"))
$ENGELLENEN_DOSYA = [string](Get-ConfigValue "ENGELLENEN_DOSYA" (Join-Base "engellenenler.txt"))
$DENEME_DOSYA     = [string](Get-ConfigValue "DENEME_DOSYA" (Join-Base "denemeler.txt"))
$OTURUM_DOSYA     = [string](Get-ConfigValue "OTURUM_DOSYA" (Join-Base "oturumlar.json"))
$KULLANICI_DOSYA  = [string](Get-ConfigValue "KULLANICI_DOSYA" (Join-Base "kullanicilar.json"))
$BAKIM_DOSYA      = [string](Get-ConfigValue "BAKIM_DOSYA" (Join-Base "bakim_modu.txt"))
$BACKUP_KLASOR    = [string](Get-ConfigValue "BACKUP_KLASOR" (Join-Base "backups"))
$KATEGORI_DOSYA   = [string](Get-ConfigValue "KATEGORI_DOSYA" (Join-Base "kategoriler.json"))
$EXCEL_MOD_DOSYA  = [string](Get-ConfigValue "EXCEL_MOD_DOSYA" (Join-Base "excel_yazma_modu.txt"))
# GORSEL KAYIT: Gyazo yerine gorseli dogrudan diske kaydetme secenegi.
# Dosya adi = kategori + gonderim tarihi + kullanicinin girdigi bilgiler (personel, uye id, ana id, tur).
$GORSEL_KLASOR    = [string](Get-ConfigValue "GORSEL_KLASOR" (Join-Base "gorseller"))
# Gyazo bakim modu: 1 = Gyazo secenegi "sunucu bakimda" der (varsayilan; Gyazo'da sorun var).
# Admin komutlariyla degistirilir: /gyazo_bakim_ac ve /gyazo_bakim_kapat (dosya: gyazo_bakim.txt)
$GYAZO_BAKIM_VARSAYILAN = [string](Get-ConfigValue "GYAZO_BAKIM" "1")
$GYAZO_BAKIM_DOSYA = [string](Get-ConfigValue "GYAZO_BAKIM_DOSYA" (Join-Base "gyazo_bakim.txt"))
# ONEDRIVE / SHAREPOINT WEB LINKI: bot klasoru OneDrive icindeyse Excel'e yerel yol yerine
# tiklaninca tarayicida acilan web linki yazilir. Ornek:
#   GORSEL_ONEDRIVE_SITE = https://pipomail-my.sharepoint.com
#   GORSEL_ONEDRIVE_KOK  = /personal/ozgur_itspark_net/Documents/telegramkant/gorseller
# Bos birakilirsa Excel'e dosyanin yerel yolu yazilir.
$GORSEL_ONEDRIVE_SITE = ([string](Get-ConfigValue "GORSEL_ONEDRIVE_SITE" "")).Trim().TrimEnd('/')
$GORSEL_ONEDRIVE_KOK  = ([string](Get-ConfigValue "GORSEL_ONEDRIVE_KOK" "")).Trim().TrimEnd('/')

$global:AdminSessions = @{}
$global:AdminLoginPending = @{}
$global:PendingAdminConfirm = @{}
$global:StopRequested = $false
$global:LastErrorText = ""
# ===================================================

$PROJELER = @("pp","pa","of","hi","vi","ga")

# ==================== PERFORMANS ====================
# Long polling: Telegram yeni mesaj gelene kadar istegi acik tutar, mesaj gelince hemen doner.
# Bu nedenle dongu sonunda 10 saniye uyumak yerine cok kisa bekleme kullanilir.
$POLL_TIMEOUT_SECONDS = 25
$HTTP_TIMEOUT_SECONDS = 35
$NORMAL_SLEEP_MS      = 200
$ERROR_SLEEP_SECONDS  = 5

$PROJE_RENK = @{
    "pp" = 0xA6A6A6
    "pa" = 0x4472C4
    "of" = 0xFFFF00
    "hi" = 0xFF0000
    "vi" = 0x7030A0
    "ga" = 0x00B050
}

$HEADERS = @("Personel Kodu","Uye ID","Ana Uye ID","Sessiz / Telesekreter","Gyazo Linki","Kategori","Tarih / Saat")
$SUTUN_GENISLIKLERI = @(15, 20, 20, 22, 45, 12, 20)

$global:xlApp = $null
$global:xlWb  = $null

# ==================== LOG ====================
function Write-Log($mesaj) {
    $satir = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $mesaj"
    Write-Host $satir
    Add-Content -Path $LOG_DOSYA -Value $satir -Encoding UTF8
}

# ==================== CACHE ====================


# ==================== GUVENLI YAZMA / EMOJI ====================
function Set-TextFileAtomic($path, $content) {
    $dir = Split-Path -Parent $path
    if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $tmp = "$path.tmp"

    # Iceriği guvenli bicimde stringe cevir (bos dizi / null durumlarini ele al)
    if ($null -eq $content) {
        $text = ""
    } elseif ($content -is [array]) {
        $text = ($content -join "`r`n")
    } else {
        $text = [string]$content
    }

    # .NET ile yazinca dosya HER ZAMAN olusur (icerik bos olsa bile)
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($tmp, $text, $utf8NoBom)

    Move-Item -Path $tmp -Destination $path -Force
}

function E($hex) {
    try { return [System.Char]::ConvertFromUtf32([Convert]::ToInt32($hex, 16)) }
    catch { return "" }
}

function Get-DisplayName($userObj) {
    if ($userObj.username) { return "@$($userObj.username)" }
    if ($userObj.first_name) { return [string]$userObj.first_name }
    return "Bilinmeyen"
}

function Normalize-IdText($value) {
    return ([string]$value).Trim().Trim([char]0xFEFF)
}

function Normalize-KategoriCode($value) {
    return (([string]$value).Trim().ToLower() -replace "[^a-z0-9_]", "")
}

function Is-AdminId($userId) {
    # GUVENLIK: ADMIN_IDS bos ise HICKIMSE admin olamaz (eskiden herkese izin veriyordu).
    # Admin olmak icin config.json icindeki "ADMIN_IDS" listesine kendi Telegram ID'nizi ekleyin.
    # ID'nizi ogrenmek icin bota /kimim yazin.
    if (-not $ADMIN_IDS -or $ADMIN_IDS.Count -eq 0) { return $false }
    foreach ($id in $ADMIN_IDS) { if ([string]$id -eq [string]$userId) { return $true } }
    return $false
}

function Is-AdminLoggedIn($userId) {
    return ($global:AdminSessions.ContainsKey([string]$userId))
}

# ==================== CACHE ====================
function Get-Cache {
    if (Test-Path $CACHE_DOSYA) { return @(Get-Content $CACHE_DOSYA -Encoding UTF8) }
    return @()
}
function Add-Cache($messageId) { Add-Content -Path $CACHE_DOSYA -Value $messageId -Encoding UTF8 }
function Is-Cached($messageId) { return (Get-Cache) -contains [string]$messageId }

# ==================== OFFSET ====================
function Get-Offset {
    if (Test-Path $OFFSET_DOSYA) { return [int](Get-Content $OFFSET_DOSYA -Encoding UTF8) }
    return 0
}
function Save-Offset($o) { Set-TextFileAtomic $OFFSET_DOSYA ([string]$o) }

# ==================== OTURUM ====================
function Get-Oturumlar {
    if (Test-Path $OTURUM_DOSYA) {
        $icerik = Get-Content $OTURUM_DOSYA -Encoding UTF8 -Raw
        if ($icerik) {
            try {
                $json = $icerik | ConvertFrom-Json
                $hashtable = @{}
                $json.PSObject.Properties | ForEach-Object {
                    $oturum = @{}
                    $_.Value.PSObject.Properties | ForEach-Object { $oturum[$_.Name] = $_.Value }
                    $hashtable[$_.Name] = $oturum
                }
                return $hashtable
            } catch { return @{} }
        }
    }
    return @{}
}

function Save-Oturumlar($oturumlar) {
    Set-TextFileAtomic $OTURUM_DOSYA ($oturumlar | ConvertTo-Json -Depth 8)
}

function Get-Oturum($userId) {
    $oturumlar = Get-Oturumlar
    if ($oturumlar.ContainsKey([string]$userId)) { return $oturumlar[[string]$userId] }
    return $null
}

function Set-Oturum($userId, $oturum) {
    $oturumlar = Get-Oturumlar
    $oturumlar[[string]$userId] = $oturum
    Save-Oturumlar $oturumlar
}

function Remove-Oturum($userId) {
    $oturumlar = Get-Oturumlar
    $oturumlar.Remove([string]$userId)
    Save-Oturumlar $oturumlar
}

# ==================== ONAYLILAR ====================
function Get-Onaylilar {
    if (Test-Path $ONAYLILAR_DOSYA) { return @(Get-Content $ONAYLILAR_DOSYA -Encoding UTF8) }
    return @()
}

function Is-Onayli($userId) {
    $liste = Get-Onaylilar
    foreach ($satir in $liste) {
        $parcalar = $satir -split "\|"
        if ((Normalize-IdText $parcalar[0]) -eq [string]$userId) { return $true }
    }
    return $false
}

function Add-Onayli($userId, $userName) {
    $tarih = Get-Date -Format "yyyy-MM-dd HH:mm"
    Add-Content -Path $ONAYLILAR_DOSYA -Value "$userId|$userName|$tarih" -Encoding UTF8
    Add-ExcelRow "ONAYLILAR" @([string]$userId, [string]$userName, [string]$tarih) $null
    Write-Log "  Onayli eklendi: $userName ($userId)"
}

# ==================== ENGELLENENLER ====================
function Get-Engellenenler {
    if (Test-Path $ENGELLENEN_DOSYA) { return @(Get-Content $ENGELLENEN_DOSYA -Encoding UTF8) }
    return @()
}

function Is-Engellenen($userId) {
    $liste = Get-Engellenenler
    foreach ($satir in $liste) {
        $parcalar = $satir -split "\|"
        if ((Normalize-IdText $parcalar[0]) -eq [string]$userId) { return $true }
    }
    return $false
}

function Add-Engellenen($userId, $userName, $sebep) {
    $id = [string]$userId
    $tarih = Get-Date -Format "yyyy-MM-dd HH:mm"
    # Ayni ID icin tekrar tekrar satir olusmasin.
    Remove-Engellenen $id | Out-Null
    Add-Content -Path $ENGELLENEN_DOSYA -Value "$id|$userName|$tarih|$sebep" -Encoding UTF8
    Remove-Oturum $id
    Write-Log "  Engellendi: $userName ($id) - $sebep"
}

# ==================== DENEME ====================
function Get-Deneme($userId) {
    if (-not (Test-Path $DENEME_DOSYA)) { return 0 }
    $satirlar = Get-Content $DENEME_DOSYA -Encoding UTF8
    foreach ($satir in $satirlar) {
        $parcalar = $satir -split "\|"
        if ((Normalize-IdText $parcalar[0]) -eq [string]$userId) { return [int]$parcalar[1] }
    }
    return 0
}

function Set-Deneme($userId, $sayi) {
    $yeniSatirlar = @()
    $bulundu = $false
    if (Test-Path $DENEME_DOSYA) {
        $satirlar = Get-Content $DENEME_DOSYA -Encoding UTF8
        foreach ($satir in $satirlar) {
            $parcalar = $satir -split "\|"
            if ((Normalize-IdText $parcalar[0]) -eq [string]$userId) {
                $yeniSatirlar += "$userId|$sayi"
                $bulundu = $true
            } else {
                $yeniSatirlar += $satir
            }
        }
    }
    if (-not $bulundu) { $yeniSatirlar += "$userId|$sayi" }
    Set-TextFileAtomic $DENEME_DOSYA $yeniSatirlar
}

function Reset-Deneme($userId) {
    if (-not (Test-Path $DENEME_DOSYA)) { return }
    $id = [string]$userId
    $yeniSatirlar = @()
    foreach ($satir in @(Get-Content $DENEME_DOSYA -Encoding UTF8)) {
        if ([string]::IsNullOrWhiteSpace($satir)) { continue }
        $parcalar = $satir -split "\|"
        if ((Normalize-IdText $parcalar[0]) -ne $id) { $yeniSatirlar += $satir }
    }
    Set-TextFileAtomic $DENEME_DOSYA $yeniSatirlar
}


# ==================== YEDEKLEME ====================
function Invoke-Backup($manual = $false) {
    $dateName = Get-Date -Format "yyyy-MM-dd"
    $target = Join-Path $BACKUP_KLASOR $dateName
    if ((Test-Path $target) -and -not $manual) {
        Write-Log "  Gunluk yedek zaten var: $target"
        return $target
    }
    if ($manual) { $target = Join-Path $BACKUP_KLASOR (Get-Date -Format "yyyy-MM-dd_HH-mm-ss") }
    New-Item -ItemType Directory -Path $target -Force | Out-Null
    $files = @($EXCEL_DOSYA,$OFFSET_DOSYA,$CACHE_DOSYA,$LOG_DOSYA,$ONAYLILAR_DOSYA,$ENGELLENEN_DOSYA,$DENEME_DOSYA,$OTURUM_DOSYA,$KULLANICI_DOSYA,$BAKIM_DOSYA,$CONFIG_DOSYA)
    foreach ($f in $files) {
        try { if ($f -and (Test-Path $f)) { Copy-Item $f -Destination (Join-Path $target (Split-Path $f -Leaf)) -Force } }
        catch { Write-Log "! Yedek kopyalama hatasi ($f): $_" }
    }
    Write-Log "  Yedek alindi: $target"
    return $target
}

# ==================== KULLANICI KAYIT DEFTERI ====================
function Get-Kullanicilar {
    if (Test-Path $KULLANICI_DOSYA) {
        try {
            $raw = Get-Content $KULLANICI_DOSYA -Encoding UTF8 -Raw
            if ($raw) {
                $json = $raw | ConvertFrom-Json
                $h = @{}
                $json.PSObject.Properties | ForEach-Object {
                    $u = @{}
                    $_.Value.PSObject.Properties | ForEach-Object { $u[$_.Name] = $_.Value }
                    $h[$_.Name] = $u
                }
                return $h
            }
        } catch { Write-Log "! Kullanici defteri okunamadi: $_" }
    }
    return @{}
}

function Save-Kullanicilar($data) { Set-TextFileAtomic $KULLANICI_DOSYA ($data | ConvertTo-Json -Depth 8) }

function Update-Kullanici($userId, $userName, $firstName, $status) {
    try {
        $data = Get-Kullanicilar
        $key = [string]$userId
        if (-not $data.ContainsKey($key)) { $data[$key] = @{} }
        $data[$key].id = [string]$userId
        $data[$key].username = [string]$userName
        $data[$key].first_name = [string]$firstName
        $data[$key].last_seen = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
        $data[$key].status = [string]$status
        Save-Kullanicilar $data
    } catch { Write-Log "! Kullanici defteri yazilamadi: $_" }
}

function Format-KullaniciListesi($items, $title, $limit = 20) {
    $msg = "<b>$title</b>`n--------------------`n"
    $i = 0
    foreach ($u in $items) {
        if ($i -ge $limit) { break }
        $name = Escape-Html (($u.username, $u.first_name | Where-Object { $_ }) -join " / ")
        $msg += "<b>ID:</b> $($u.id)`n<b>Ad:</b> $name`n<b>Durum:</b> $(Escape-Html $u.status)`n<b>Son:</b> $(Escape-Html $u.last_seen)`n`n"
        $i++
    }
    if ($i -eq 0) { $msg += "Kayit bulunamadi." }
    return $msg
}

function Parse-SonKullanicilarArgs($argText) {
    $result = @{ limit = 20; since = $null; label = "son 20 kisi"; error = $null }
    $parts = @($argText.Trim() -split "\s+" | Where-Object { $_ })
    foreach ($part in $parts) {
        $p = $part.Trim().ToLower()
        if ($p -match '^\d+$') {
            $n = [int]$p
            if ($n -lt 1) { $n = 1 }
            if ($n -gt 50) { $n = 50 }
            $result.limit = $n
            continue
        }
        if ($p -match '^(\d+)(dk|dakika)$') {
            $n = [int]$Matches[1]
            if ($n -lt 1 -or $n -gt 60) { $result.error = "Dakika filtresi 1-60 dk arasinda olmali."; return $result }
            $result.since = (Get-Date).AddMinutes(-1 * $n)
            $result.label = "son $n dk"
            continue
        }
        if ($p -match '^(\d+)(saat|sa)$') {
            $n = [int]$Matches[1]
            if ($n -lt 1 -or $n -gt 24) { $result.error = "Saat filtresi 1-24 saat arasinda olmali."; return $result }
            $result.since = (Get-Date).AddHours(-1 * $n)
            $result.label = "son $n saat"
            continue
        }
        if ($p -match '^(\d+)(gun|g)$') {
            $n = [int]$Matches[1]
            if ($n -lt 1 -or $n -gt 2) { $result.error = "Gun filtresi 1-2 gun arasinda olmali."; return $result }
            $result.since = (Get-Date).AddDays(-1 * $n)
            $result.label = "son $n gun"
            continue
        }
        $result.error = "Kullanim: /son_kullanicilar [adet] [60dk|24saat|2gun]. Ornek: /son_kullanicilar 30 2saat"
        return $result
    }
    if ($null -eq $result.since) { $result.label = "son $($result.limit) kisi" }
    else { $result.label = "$($result.label), max $($result.limit) kisi" }
    return $result
}

# ==================== BAKIM / ADMIN ====================
function Is-MaintenanceMode { return (Test-Path $BAKIM_DOSYA) }

# ==================== GYAZO BAKIM / GORSEL DOSYA KAYDI ====================
# gyazo_bakim.txt icerigi: "1" = bakimda, "0" = acik. Dosya yoksa config GYAZO_BAKIM gecerli.
function Is-GyazoBakim {
    if (Test-Path $GYAZO_BAKIM_DOSYA) {
        try { $v = ([string](Get-Content $GYAZO_BAKIM_DOSYA -Raw -ErrorAction SilentlyContinue)).Trim() } catch { $v = "1" }
        return ($v -ne "0")
    }
    $d = ([string]$GYAZO_BAKIM_VARSAYILAN).Trim().ToLower()
    return ($d -ne "0" -and $d -ne "false" -and $d -ne "kapali")
}
function Set-GyazoBakim($enabled) {
    Set-TextFileAtomic $GYAZO_BAKIM_DOSYA ($(if ($enabled) { "1" } else { "0" }))
}

# Dosya adina girecek parcayi guvenli hale getirir: Turkce harfler cevrilir,
# izinli olmayan karakterler '-' olur, yol karakterleri ve '..' asla olusmaz.
function Get-DosyaParcasi($deger, [int]$limit = 40) {
    if ($null -eq $deger) { return "" }
    $s = [string]$deger
    # Hashtable anahtarlari buyuk/kucuk harf duyarsiz oldugu icin cift liste kullanilir.
    $trFrom = @('ç','Ç','ğ','Ğ','ı','İ','ö','Ö','ş','Ş','ü','Ü')
    $trTo   = @('c','C','g','G','i','I','o','O','s','S','u','U')
    for ($i = 0; $i -lt $trFrom.Count; $i++) { $s = $s.Replace([string]$trFrom[$i], [string]$trTo[$i]) }
    $s = [regex]::Replace($s, '[^A-Za-z0-9._-]+', '-')
    $s = [regex]::Replace($s, '\.{2,}', '.')
    $s = [regex]::Replace($s, '-{2,}', '-')
    $s = $s.Trim('-', '.', '_')
    if ($s.Length -gt $limit) { $s = $s.Substring(0, $limit).Trim('-', '.', '_') }
    return $s
}

# Dosya adi: KATEGORI_yyyy-MM-dd_HH-mm-ss_<girilen bilgiler...>  (bos alanlar atlanir)
function Get-GorselDosyaAdi($oturum, [datetime]$tarih) {
    $parcalar = @()
    $kat = Get-DosyaParcasi ((Get-KategoriLabel $oturum.kategori).ToUpper())
    if (-not $kat) { $kat = "KAYIT" }
    $parcalar += $kat
    $parcalar += $tarih.ToString("yyyy-MM-dd_HH-mm-ss")
    foreach ($alan in @($oturum.personel, $oturum.uyeid, $oturum.anaid, $oturum.tip)) {
        $pc = Get-DosyaParcasi $alan
        if ($pc) { $parcalar += $pc }
    }
    $ad = ($parcalar -join "_")
    if ($ad.Length -gt 180) { $ad = $ad.Substring(0, 180).Trim('-', '.', '_') }
    return $ad
}

# Kaydedilen gorsel icin OneDrive/SharePoint web linki (onedrive.aspx?id=...&parent=...).
# Ayar bos ise $null doner ve Excel'e yerel yol yazilir.
function Get-GorselWebLink($projeKlasorAdi, $dosyaAdi) {
    if (-not $GORSEL_ONEDRIVE_SITE -or -not $GORSEL_ONEDRIVE_KOK) { return $null }
    $klasor = "$GORSEL_ONEDRIVE_KOK/$projeKlasorAdi"
    $yol = "$klasor/$dosyaAdi"
    $id = [System.Uri]::EscapeDataString($yol)
    $parent = [System.Uri]::EscapeDataString($klasor)
    # /personal/<kullanici>/ kismindan site-relative "_layouts" adresi turetilir.
    $m = [regex]::Match($GORSEL_ONEDRIVE_KOK, '^(/personal/[^/]+)')
    $kisisel = if ($m.Success) { $m.Groups[1].Value } else { "" }
    return "$GORSEL_ONEDRIVE_SITE$kisisel/_layouts/15/onedrive.aspx?id=$id&parent=$parent"
}

# Telegram'daki fotoyu indirir, gorseller\<PROJE>\ altina girilen bilgilerle adlandirip kaydeder.
# Basarili olursa tam dosya yolunu, olmazsa $null dondurur.
function Save-GorselToDisk($fileId, $oturum, $tarih) {
    try {
        $fileInfo = Invoke-RestMethod -Uri "https://api.telegram.org/bot$TELEGRAM_TOKEN/getFile?file_id=$fileId" -TimeoutSec 15
        $maxBytes = 8 * 1024 * 1024
        if ($fileInfo.result.file_size -and [int64]$fileInfo.result.file_size -gt $maxBytes) {
            Write-Log "! Dosya cok buyuk, reddedildi: $([int64]$fileInfo.result.file_size) byte"
            return $null
        }
        $uzanti = [System.IO.Path]::GetExtension([string]$fileInfo.result.file_path)
        if (-not $uzanti -or $uzanti.Length -gt 5) { $uzanti = ".jpg" }
        $projeKlasor = Join-Path $GORSEL_KLASOR (Get-DosyaParcasi ($oturum.proje.ToUpper()) 10)
        if (-not (Test-Path $projeKlasor)) { New-Item -ItemType Directory -Path $projeKlasor -Force | Out-Null }
        $ad = Get-GorselDosyaAdi $oturum $tarih
        $hedef = Join-Path $projeKlasor ($ad + $uzanti)
        $n = 2
        while (Test-Path $hedef) { $hedef = Join-Path $projeKlasor ("{0}_{1}{2}" -f $ad, $n, $uzanti); $n++ }
        $tempFile = Join-Path $env:TEMP ("tg_" + [System.Guid]::NewGuid().ToString() + $uzanti)
        Invoke-WebRequest -Uri "https://api.telegram.org/file/bot$TELEGRAM_TOKEN/$($fileInfo.result.file_path)" `
            -OutFile $tempFile -TimeoutSec 30
        Move-Item -Path $tempFile -Destination $hedef -Force
        Write-Log "  Gorsel diske kaydedildi -> $hedef"
        return (Resolve-Path $hedef).Path
    } catch { Write-Log "! Gorsel kaydetme hatasi: $_"; return $null }
}
function Set-MaintenanceMode($enabled) {
    if ($enabled) { Set-TextFileAtomic $BAKIM_DOSYA (Get-Date -Format "yyyy-MM-dd HH:mm:ss") }
    else { Remove-Item $BAKIM_DOSYA -ErrorAction SilentlyContinue }
}

function Remove-Engellenen($userId) {
    if (-not (Test-Path $ENGELLENEN_DOSYA)) { return $false }
    $id = [string]$userId
    $bulundu = $false
    $lines = @()
    foreach ($satir in @(Get-Content $ENGELLENEN_DOSYA -Encoding UTF8)) {
        if ([string]::IsNullOrWhiteSpace($satir)) { continue }
        $parcalar = $satir -split "\|"
        if ((Normalize-IdText $parcalar[0]) -eq $id) { $bulundu = $true; continue }
        $lines += $satir
    }
    Set-TextFileAtomic $ENGELLENEN_DOSYA $lines
    return $bulundu
}

function Clear-KullaniciDurumu($userId) {
    $id = [string]$userId
    $engelSilindi = Remove-Engellenen $id
    Reset-Deneme $id
    Remove-Oturum $id
    return $engelSilindi
}

function Remove-Onayli($userId) {
    if (-not (Test-Path $ONAYLILAR_DOSYA)) { return $false }
    $id = [string]$userId
    $bulundu = $false
    $lines = @()
    foreach ($satir in @(Get-Content $ONAYLILAR_DOSYA -Encoding UTF8)) {
        if ([string]::IsNullOrWhiteSpace($satir)) { continue }
        $parcalar = $satir -split "\|"
        if ((Normalize-IdText $parcalar[0]) -eq $id) { $bulundu = $true; continue }
        $lines += $satir
    }
    Set-TextFileAtomic $ONAYLILAR_DOSYA $lines
    return $bulundu
}

function Clear-KullaniciTamSifirla($userId) {
    $id = [string]$userId
    $engelSilindi = Remove-Engellenen $id
    $onaySilindi = Remove-Onayli $id
    Reset-Deneme $id
    Remove-Oturum $id
    return [pscustomobject]@{ EngelSilindi=$engelSilindi; OnaySilindi=$onaySilindi }
}

function Send-EngelKaldirildiBildirim($userId) {
    $id = [string]$userId
    $mesaj = "$(E '2705') <b>Engeliniz kaldırıldı.</b>`n`nŞifreyi tekrar yazarak sisteme giriş yapabilirsiniz."
    $sonuc = Send-Message $id $mesaj $null
    if ($sonuc) {
        Write-Log "  Engel kaldirma bildirimi gonderildi: $id"
        return $true
    }
    Write-Log "! Engel kaldirma bildirimi gonderilemedi: $id"
    return $false
}

function ConvertTo-PlainHashtable($obj) {
    $h = @{}
    if (-not $obj) { return $h }
    if ($obj -is [hashtable]) {
        foreach ($k in $obj.Keys) { $h[[string]$k] = $obj[$k] }
        return $h
    }
    try {
        $obj.PSObject.Properties | ForEach-Object { $h[[string]$_.Name] = $_.Value }
    } catch {}
    return $h
}

function Format-CountMap($obj) {
    $h = ConvertTo-PlainHashtable $obj
    if ($h.Count -eq 0) { return "YOK" }
    $parts = @()
    foreach ($k in ($h.Keys | Sort-Object)) { $parts += ("{0}: {1}" -f $k, $h[$k]) }
    return ($parts -join ", ")
}

function Register-KullaniciKayit($userId, $userName, $firstName, $proje, $kategoriCode, $kategoriLabel) {
    try {
        $data = Get-Kullanicilar
        $key = [string]$userId
        if (-not $data.ContainsKey($key)) { $data[$key] = @{} }
        $u = $data[$key]
        $u.id = [string]$userId
        $u.username = [string]$userName
        $u.first_name = [string]$firstName
        $u.last_seen = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
        $u.status = "kayit_eklendi"

        $mevcut = 0
        try { if ($u.kayit_sayisi) { $mevcut = [int]$u.kayit_sayisi } } catch { $mevcut = 0 }
        $u.kayit_sayisi = ($mevcut + 1)
        $u.son_kayit_tarihi = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
        $u.son_kayit_proje = [string]$proje
        $u.son_kayit_kategori = [string]$kategoriLabel

        $pmap = ConvertTo-PlainHashtable $u.proje_sayilari
        $pkey = ([string]$proje).ToUpper()
        if (-not $pmap.ContainsKey($pkey)) { $pmap[$pkey] = 0 }
        $pmap[$pkey] = [int]$pmap[$pkey] + 1
        $u.proje_sayilari = $pmap

        $kmap = ConvertTo-PlainHashtable $u.kategori_sayilari
        $kkey = ([string]$kategoriCode).ToUpper()
        if (-not $kmap.ContainsKey($kkey)) { $kmap[$kkey] = 0 }
        $kmap[$kkey] = [int]$kmap[$kkey] + 1
        $u.kategori_sayilari = $kmap

        Save-Kullanicilar $data
    } catch { Write-Log "! Kullanici kayit sayaci yazilamadi: $_" }
}

function Get-KullaniciDurumMesaji($userId) {
    $id = [string]$userId
    $users = Get-Kullanicilar
    $u = $null
    if ($users.ContainsKey($id)) { $u = $users[$id] }
    $onay = if (Is-Onayli $id) { "EVET" } else { "HAYIR" }
    $engel = if (Is-Engellenen $id) { "EVET" } else { "HAYIR" }
    $deneme = Get-Deneme $id
    $ot = Get-Oturum $id
    $otText = if ($ot) { "Adim=$($ot.adim), Proje=$($ot.proje), Kategori=$($ot.kategori)" } else { "YOK" }
    $ad = if ($u) { Escape-Html ([string]$u.username) } else { "-" }
    $first = if ($u) { Escape-Html ([string]$u.first_name) } else { "-" }
    $last = if ($u) { Escape-Html ([string]$u.last_seen) } else { "-" }
    $kayit = if ($u -and $u.kayit_sayisi) { [string]$u.kayit_sayisi } else { "0" }
    $sonKayit = if ($u -and $u.son_kayit_tarihi) { "$(Escape-Html ([string]$u.son_kayit_tarihi)) / $(Escape-Html ([string]$u.son_kayit_proje)) / $(Escape-Html ([string]$u.son_kayit_kategori))" } else { "YOK" }
    $projeler = if ($u) { Escape-Html (Format-CountMap $u.proje_sayilari) } else { "YOK" }
    $kategoriler = if ($u) { Escape-Html (Format-CountMap $u.kategori_sayilari) } else { "YOK" }
    $msg = "<b>KULLANICI DURUMU</b>`n--------------------`n"
    $msg += "<b>ID:</b> $id`n<b>Username:</b> $ad`n<b>Ad:</b> $first`n<b>Son gorulme:</b> $last`n"
    $msg += "<b>Onayli:</b> $onay`n<b>Engelli:</b> $engel`n<b>Deneme:</b> $deneme`n<b>Oturum:</b> $(Escape-Html $otText)`n"
    $msg += "<b>Ekledigi kayit:</b> $kayit`n<b>Son kayit:</b> $sonKayit`n<b>Proje dagilimi:</b> $projeler`n<b>Kategori dagilimi:</b> $kategoriler"
    return $msg
}

function Format-KayitRaporu($limit = 10) {
    $users = (Get-Kullanicilar).Values | Where-Object { $_.kayit_sayisi } | Sort-Object {[int]$_.kayit_sayisi} -Descending
    $msg = "<b>KAYIT RAPORU</b>`n--------------------`n"
    $i = 0
    foreach ($u in $users) {
        if ($i -ge $limit) { break }
        $name = Escape-Html (($u.username, $u.first_name | Where-Object { $_ }) -join " / ")
        $msg += "<b>$($i+1).</b> ID: $($u.id) | $name | Kayit: $($u.kayit_sayisi)`n"
        $i++
    }
    if ($i -eq 0) { $msg += "Henuz Son sonrasi kayit sayaci olusmadi." }
    return $msg
}

# ==================== DINAMIK KATEGORI YONETIMI ====================
function Get-DefaultKategoriler {
    return @(
        [pscustomobject]@{ code="ark";   label="ARK";   mode="ark_ana" },
        [pscustomobject]@{ code="dds";   label="DDS";   mode="sessiz_tip" },
        [pscustomobject]@{ code="ddt";   label="DDT";   mode="sessiz_tip" },
        [pscustomobject]@{ code="hgst";  label="HGST";  mode="tek_uye" },
        [pscustomobject]@{ code="prcst"; label="PRCST"; mode="tek_uye" },
        [pscustomobject]@{ code="lpst";  label="LPST";  mode="ana_only" }
    )
}

function Save-Kategoriler($items) {
    Set-TextFileAtomic $KATEGORI_DOSYA ($items | ConvertTo-Json -Depth 8)
}

function Get-Kategoriler {
    if (Test-Path $KATEGORI_DOSYA) {
        try {
            $raw = Get-Content $KATEGORI_DOSYA -Encoding UTF8 -Raw
            if ($raw) {
                $json = $raw | ConvertFrom-Json
                $arr = @($json)
                $valid = @()
                foreach ($k in $arr) {
                    $code = Normalize-KategoriCode $k.code
                    $label = if ($k.label) { [string]$k.label } else { $code.ToUpper() }
                    $mode = if ($k.mode) { [string]$k.mode } else { "tek_uye" }
                    if ($code -and @("tek_uye","ark_ana","ana_only","sessiz_tip") -contains $mode) {
                        $valid += [pscustomobject]@{ code=$code; label=$label; mode=$mode }
                    }
                }
                if ($valid.Count -gt 0) { return $valid }
            }
        } catch { Write-Log "! Kategori dosyasi okunamadi, varsayilanlar kullaniliyor: $_" }
    }
    $defaults = Get-DefaultKategoriler
    try { Save-Kategoriler $defaults } catch {}
    return $defaults
}

function Get-Kategori($code) {
    $c = Normalize-KategoriCode $code
    foreach ($k in Get-Kategoriler) { if ($k.code -eq $c) { return $k } }
    return $null
}

function Get-KategoriMode($code) {
    $k = Get-Kategori $code
    if ($k) { return [string]$k.mode }
    return "tek_uye"
}

function Get-KategoriLabel($code) {
    $k = Get-Kategori $code
    if ($k) { return [string]$k.label }
    return ([string]$code).ToUpper()
}

function Add-OrUpdate-Kategori($code, $label, $mode) {
    $c = Normalize-KategoriCode $code
    if (-not $c) { return "Kategori kodu bos veya gecersiz." }
    if (-not (@("tek_uye","ark_ana","ana_only","sessiz_tip") -contains $mode)) { return "Akis tipi gecersiz. Gecerli: tek_uye, ark_ana, ana_only, sessiz_tip" }
    $items = @()
    foreach ($k in Get-Kategoriler) { if ($k.code -ne $c) { $items += $k } }
    $items += [pscustomobject]@{ code=$c; label=([string]$label).Trim(); mode=$mode }
    Save-Kategoriler $items
    return $null
}

function Remove-Kategori($code) {
    $c = Normalize-KategoriCode $code
    $items = @()
    $found = $false
    foreach ($k in Get-Kategoriler) {
        if ($k.code -eq $c) { $found = $true; continue }
        $items += $k
    }
    if ($found) { Save-Kategoriler $items }
    return $found
}

function Format-KategoriListesi {
    $msg = "<b>KATEGORILER</b>`n--------------------`n"
    foreach ($k in Get-Kategoriler) { $msg += "<b>$($k.label)</b> | kod: $($k.code) | akis: $($k.mode)`n" }
    $msg += "`n<b>Akis tipleri:</b>`ntek_uye: Personel + Uye ID`nark_ana: Personel + Arkadas ID + Ana ID`nana_only: Personel + Ana ID`nsessiz_tip: Personel + Uye ID + Sessiz/Telesekreter"
    return $msg
}

function Get-KategoriAlanMetni($mode) {
    switch ($mode) {
        "ark_ana"    { return "Personel Kodu, Arkadas Uye ID, Ana Uye ID" }
        "ana_only"   { return "Personel Kodu, Ana Uye ID" }
        "sessiz_tip" { return "Personel Kodu, Uye ID, Sessiz/Telesekreter secimi" }
        default      { return "Personel Kodu, Uye ID" }
    }
}

function Format-KategoriBilgi($code) {
    $k = Get-Kategori $code
    if (-not $k) { return "$(E '26A0') Kategori bulunamadi: $(Escape-Html $code)" }
    $msg = "<b>KATEGORI BILGISI</b>`n--------------------`n"
    $msg += "<b>Kod:</b> $($k.code)`n<b>Baslik:</b> $(Escape-Html ([string]$k.label))`n<b>Akis:</b> $($k.mode)`n<b>Sorulacak alanlar:</b> $(Escape-Html (Get-KategoriAlanMetni $k.mode))"
    return $msg
}

function Get-AdminHelp {
    $m  = "<b>ADMIN KOMUTLARI</b>`n--------------------`n"
    $m += "/durum - Bot ve dosya durumu`n"
    $m += "/istatistik - Kayit ve kullanici ozeti`n"
    $m += "/son_kullanicilar [adet] [sure] - Son kullanicilar; ornek: /son_kullanicilar 30 2saat`n"
    $m += "/kullanici_ara kelime - Kullanici ara`n"
    $m += "/engelle ID sebep - Kullanici engelle`n"
    $m += "/engel_kaldir ID - Engeli kaldir, deneme ve oturumu sifirla`n"
    $m += "/engel_kaldir_sifirla ID - Engel + onay + deneme + oturumu temizle`n"
    $m += "/engelliler - Engelli listesi`n"
    $m += "/oturumlar - Aktif oturumlar`n"
    $m += "/oturum_temizle ID - Oturumu sil`n"
    $m += "/kullanici_durum ID - Kullanici onay/engel/deneme/oturum durumu`n"
    $m += "/onayli_sil ID - Kullanici onayini kaldir, yeniden sifreye dusur`n"
    $m += "/kategori_liste - Kategorileri goster`n"
    $m += "/kategori_bilgi KOD - Kategorinin soracagi alanlari goster`n"
    $m += "/kategori_akislari - Kategori akis tiplerini goster`n"
    $m += "/kategori_ekle KOD|Baslik|akis - Kategori ekle/guncelle`n"
    $m += "/kategori_sil KOD - Kategoriyi kaldir`n"
    $m += "/kategori_yayinla - Kategori listesini yeni ekranlarda aktif et`n"
    $m += "/excel_son_satir SAYFA - Botun hangi satira yazacagini gosterir`n"
    $m += "/kayit_raporu [adet] - En cok kayit ekleyenleri goster`n"
    $m += "/excel_mod [son_dolunun_altina|ilk_bos_satir] - Excel yazma modunu gosterir/degistirir`n"
    $m += "/yedekle - Manuel yedek al`n"
    $m += "/bakim_ac - Bakim modunu ac`n"
    $m += "/bakim_kapat - Bakim modunu kapat`n"
    $m += "/gyazo_bakim_ac - Gyazo secenegi 'sunucu bakimda' desin (gorsel dosyaya kaydedilir)`n"
    $m += "/gyazo_bakim_kapat - Gyazo secenegini yeniden ac`n"
    $m += "/son_hatalar - Son log satirlari`n"
    $m += "/kapat - Botu guvenli durdur`n"
    $m += "/admin_cikis - Admin oturumunu kapat`n"
    return $m
}

function Process-AdminMessage($chatId, $userId, $userName, $firstName, $text) {
    if (-not $text) { return $false }
    $t = $text.Trim()

    if ($t -eq "/kimim") {
        Send-Message $chatId "<b>Telegram ID:</b> $userId`n<b>Ad:</b> $(Escape-Html $userName)" $null | Out-Null
        return $true
    }

    if ($global:AdminLoginPending.ContainsKey([string]$userId)) {
        if ($t -eq $ADMIN_SIFRE -and (Is-AdminId $userId)) {
            $global:AdminLoginPending.Remove([string]$userId)
            $global:AdminSessions[[string]$userId] = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
            Send-Message $chatId "$(E '2705') <b>Admin girisi basarili.</b>`n`n/yardim_admin komutuyla listeyi gorebilirsiniz." $null | Out-Null
        } else {
            $global:AdminLoginPending.Remove([string]$userId)
            Send-Message $chatId "$(E '26D4') <b>Admin girisi basarisiz.</b>" $null | Out-Null
        }
        return $true
    }

    if ($t -eq "/admin") {
        if (-not (Is-AdminId $userId)) { Send-Message $chatId "$(E '26D4') Bu ID admin listesinde degil. /kimim ile ID'nizi ogrenip config.json'a ekleyin." $null | Out-Null; return $true }
        $global:AdminLoginPending[[string]$userId] = $true
        Send-Message $chatId "$(E '1F510') <b>Admin sifresini yazin.</b>" $null | Out-Null
        return $true
    }

    $adminCommands = @('/admin_cikis','/yardim_admin','/durum','/istatistik','/son_kullanicilar','/kullanici_ara','/engelle','/engel_kaldir','/engel_kaldir_sifirla','/engelliler','/oturumlar','/kategori_liste','/kategori_bilgi','/kategori_akislari','/kategori_ekle','/kategori_sil','/kategori_yayinla','/oturum_temizle','/kullanici_durum','/onayli_sil','/excel_son_satir','/excel_mod','/kayit_raporu','/yedekle','/bakim_ac','/bakim_kapat','/gyazo_bakim_ac','/gyazo_bakim_kapat','/son_hatalar','/kapat','/onayla','/vazgec')
    $isAdminCommand = $false
    foreach ($cmd in $adminCommands) { if ($t -eq $cmd -or $t.StartsWith($cmd + ' ')) { $isAdminCommand = $true; break } }
    if (-not $isAdminCommand) { return $false }

    if (-not (Is-AdminLoggedIn $userId)) {
        Send-Message $chatId "$(E '1F510') Bu komut icin once /admin ile giris yapin." $null | Out-Null
        return $true
    }

    if ($t -eq "/admin_cikis") { $global:AdminSessions.Remove([string]$userId); Send-Message $chatId "Admin oturumu kapatildi." $null | Out-Null; return $true }
    if ($t -eq "/yardim_admin") { Send-Message $chatId (Get-AdminHelp) $null | Out-Null; return $true }

    if ($t -eq "/onayla" -or $t -eq "/vazgec") {
        if (-not $global:PendingAdminConfirm.ContainsKey([string]$userId)) { Send-Message $chatId "Bekleyen onay yok." $null | Out-Null; return $true }
        $op = $global:PendingAdminConfirm[[string]$userId]
        $global:PendingAdminConfirm.Remove([string]$userId)
        if ($t -eq "/vazgec") { Send-Message $chatId "Islem iptal edildi." $null | Out-Null; return $true }
        if ($op.type -eq "engelle") { Add-Engellenen $op.id $op.name $op.reason; Send-Message $chatId "$(E '26D4') Kullanici engellendi: $($op.id)" $null | Out-Null; return $true }
        if ($op.type -eq "kapat") { Send-Message $chatId "$(E '1F6D1') Bot guvenli kapatma moduna alindi." $null | Out-Null; $global:StopRequested = $true; return $true }
    }

    if ($t -eq "/durum") {
        $bakim = if (Is-MaintenanceMode) { "ACIK" } else { "KAPALI" }
        $gyazoBakim = if (Is-GyazoBakim) { "BAKIMDA (gorseller dosyaya kaydediliyor)" } else { "ACIK" }
        $otCount = (Get-Oturumlar).Count
        $msg = "<b>DURUM</b>`n--------------------`n<b>Excel:</b> $EXCEL_DOSYA`n<b>Excel bagli:</b> $([bool]$global:xlWb)`n<b>Bakim:</b> $bakim`n<b>Gyazo:</b> $gyazoBakim`n<b>Gorsel klasoru:</b> $GORSEL_KLASOR`n<b>OneDrive linki:</b> $(if ($GORSEL_ONEDRIVE_SITE -and $GORSEL_ONEDRIVE_KOK) { "$GORSEL_ONEDRIVE_SITE$GORSEL_ONEDRIVE_KOK" } else { "ayarli degil (yerel yol yazilir)" })`n<b>Aktif oturum:</b> $otCount`n<b>Son hata:</b> $(Escape-Html $global:LastErrorText)"
        Send-Message $chatId $msg $null | Out-Null; return $true
    }

    if ($t -eq "/istatistik") {
        $users = Get-Kullanicilar
        $msg = "<b>ISTATISTIK</b>`n--------------------`n<b>Kullanici defteri:</b> $($users.Count)`n<b>Onayli:</b> $((Get-Onaylilar).Count)`n<b>Engelli:</b> $((Get-Engellenenler).Count)`n<b>Aktif oturum:</b> $((Get-Oturumlar).Count)`n<b>Son kayit sayacli kullanici:</b> $(((Get-Kullanicilar).Values | Where-Object { $_.kayit_sayisi }).Count)`n<b>Bakim modu:</b> $(if (Is-MaintenanceMode) {'ACIK'} else {'KAPALI'})"
        Send-Message $chatId $msg $null | Out-Null; return $true
    }

    if ($t -eq "/son_kullanicilar" -or $t.StartsWith('/son_kullanicilar ')) {
        $argText = ($t -replace '^/son_kullanicilar\s*','')
        $parsed = Parse-SonKullanicilarArgs $argText
        if ($parsed.error) { Send-Message $chatId "$(E '26A0') <b>Hatali filtre.</b>`n$(Escape-Html $parsed.error)" $null | Out-Null; return $true }
        $items = (Get-Kullanicilar).Values
        if ($parsed.since) {
            $items = $items | Where-Object {
                try { ([datetime]::ParseExact([string]$_.last_seen, 'yyyy-MM-dd HH:mm:ss', $null)) -ge $parsed.since } catch { $false }
            }
        }
        $items = $items | Sort-Object last_seen -Descending
        Send-Message $chatId (Format-KullaniciListesi $items "SON KULLANICILAR ($($parsed.label))" $parsed.limit) $null | Out-Null; return $true
    }

    if ($t.StartsWith('/kullanici_ara')) {
        $q = ($t -replace '^/kullanici_ara\s*','').Trim().ToLower()
        $items = (Get-Kullanicilar).Values | Where-Object { ([string]$_.id + ' ' + [string]$_.username + ' ' + [string]$_.first_name).ToLower().Contains($q) } | Sort-Object last_seen -Descending
        Send-Message $chatId (Format-KullaniciListesi $items "ARAMA: $(Escape-Html $q)") $null | Out-Null; return $true
    }

    if ($t -eq "/engelliler") {
        $lines = Get-Engellenenler
        $msg = "<b>ENGELLILER</b>`n--------------------`n"
        foreach ($l in $lines | Select-Object -Last 30) { $msg += (Escape-Html $l) + "`n" }
        if ($lines.Count -eq 0) { $msg += "Kayit yok." }
        Send-Message $chatId $msg $null | Out-Null; return $true
    }

    if ($t -eq "/engelle") {
        Send-Message $chatId "<b>Kullanim:</b> /engelle ID sebep`n`n<b>Ornek:</b> /engelle 123456789 spam" $null | Out-Null
        return $true
    }

    if ($t.StartsWith('/engelle ')) {
        $p = $t.Split(' ',3)
        if ($p.Count -lt 2 -or [string]::IsNullOrWhiteSpace($p[1])) { Send-Message $chatId "<b>Kullanim:</b> /engelle ID sebep`n`n<b>Ornek:</b> /engelle 123456789 spam" $null | Out-Null; return $true }
        $reason = if ($p.Count -ge 3 -and -not [string]::IsNullOrWhiteSpace($p[2])) { $p[2] } else { "Admin engeli" }
        $global:PendingAdminConfirm[[string]$userId] = @{ type='engelle'; id=$p[1]; name='admin'; reason=$reason }
        Send-Message $chatId "$(E '26A0') <b>Onay gerekli</b>`nKullanici engellensin mi?`nID: $($p[1])`nSebep: $(Escape-Html $reason)`n`nOnay: /onayla`nIptal: /vazgec" $null | Out-Null; return $true
    }

    if ($t -eq "/engel_kaldir") {
        Send-Message $chatId "<b>Kullanim:</b> /engel_kaldir ID`n`n<b>Ornek:</b> /engel_kaldir 123456789" $null | Out-Null
        return $true
    }

    if ($t.StartsWith('/engel_kaldir ')) {
        $id = ($t -replace '^/engel_kaldir\s+','').Trim()
        if ([string]::IsNullOrWhiteSpace($id)) { Send-Message $chatId "<b>Kullanim:</b> /engel_kaldir ID" $null | Out-Null; return $true }
        $bulundu = Clear-KullaniciDurumu $id
        # Engel kaydi bulunsun bulunmasin, kullaniciya "tekrar giris yapabilirsiniz" bildirimi her zaman gonderilir.
        $bildirim = Send-EngelKaldirildiBildirim $id
        $durum = if ($bulundu) { "Engel kaydi silindi" } else { "Engel kaydi bulunamadi; yine de deneme ve oturum sifirlandi" }
        $bildirimDurum = if ($bildirim) { "Kullaniciya bildirim gonderildi" } else { "Bildirim gonderilemedi (kullanici botu hic baslatmamis veya botu engellemis olabilir)" }
        Send-Message $chatId "$(E '2705') <b>Engel kaldirma tamamlandi.</b>`nID: $id`nDurum: $durum`nDeneme sayaci: sifirlandi`nOturum: temizlendi`nBildirim: $bildirimDurum" $null | Out-Null
        return $true
    }

    if ($t -eq "/engel_kaldir_sifirla") {
        Send-Message $chatId "<b>Kullanim:</b> /engel_kaldir_sifirla ID`n`nBu komut engeli, onay kaydini, deneme sayacini ve oturumu birlikte temizler." $null | Out-Null
        return $true
    }
    if ($t.StartsWith('/engel_kaldir_sifirla ')) {
        $id = ($t -replace '^/engel_kaldir_sifirla\s+','').Trim()
        if ([string]::IsNullOrWhiteSpace($id)) { Send-Message $chatId "<b>Kullanim:</b> /engel_kaldir_sifirla ID" $null | Out-Null; return $true }
        $r = Clear-KullaniciTamSifirla $id
        # Engel kaydi bulunsun bulunmasin bildirim her zaman gonderilir.
        $bildirim = Send-EngelKaldirildiBildirim $id
        $bildirimDurum = if ($bildirim) { "Kullaniciya bildirim gonderildi" } else { "Bildirim gonderilemedi (kullanici botu hic baslatmamis veya botu engellemis olabilir)" }
        Send-Message $chatId "$(E '2705') <b>Kullanici tam sifirlandi.</b>`nID: $id`nEngel kaydi silindi: $($r.EngelSilindi)`nOnay kaydi silindi: $($r.OnaySilindi)`nDeneme sayaci: sifirlandi`nOturum: temizlendi`nBildirim: $bildirimDurum`n`nKullanici yeniden sifre yazarak baslamali." $null | Out-Null
        return $true
    }

    if ($t -eq "/kullanici_durum") { Send-Message $chatId "<b>Kullanim:</b> /kullanici_durum ID" $null | Out-Null; return $true }
    if ($t.StartsWith('/kullanici_durum ')) {
        $id = ($t -replace '^/kullanici_durum\s+','').Trim()
        Send-Message $chatId (Get-KullaniciDurumMesaji $id) $null | Out-Null
        return $true
    }

    if ($t -eq "/onayli_sil") { Send-Message $chatId "<b>Kullanim:</b> /onayli_sil ID" $null | Out-Null; return $true }
    if ($t.StartsWith('/onayli_sil ')) {
        $id = ($t -replace '^/onayli_sil\s+','').Trim()
        $ok = Remove-Onayli $id
        Remove-Oturum $id
        Reset-Deneme $id
        $cevap = if ($ok) { "Onay kaydi silindi" } else { "Onay kaydi bulunamadi" }
        Send-Message $chatId "$(E '2705') <b>Onayli silme tamamlandi.</b>`nID: $id`nDurum: $cevap`nOturum ve deneme temizlendi." $null | Out-Null
        return $true
    }

    if ($t -eq "/excel_mod") {
        Send-Message $chatId "<b>Excel yazma modu:</b> $(Get-ExcelWriteMode)`n`nDegistirmek icin:`n/excel_mod son_dolunun_altina`n/excel_mod ilk_bos_satir" $null | Out-Null
        return $true
    }
    if ($t.StartsWith('/excel_mod ')) {
        $mode = ($t -replace '^/excel_mod\s+','').Trim()
        if (Set-ExcelWriteMode $mode) { Send-Message $chatId "$(E '2705') Excel yazma modu degisti: $mode" $null | Out-Null }
        else { Send-Message $chatId "$(E '26A0') Gecersiz mod. Gecerli modlar: son_dolunun_altina, ilk_bos_satir" $null | Out-Null }
        return $true
    }
    if ($t -eq "/excel_son_satir") { Send-Message $chatId "<b>Kullanim:</b> /excel_son_satir PP" $null | Out-Null; return $true }
    if ($t.StartsWith('/excel_son_satir ')) {
        $sayfa = (($t -replace '^/excel_son_satir\s+','').Trim()).ToUpper()
        $info = Get-ExcelSheetWriteInfo $sayfa $HEADERS.Count
        if (-not $info) { Send-Message $chatId "$(E '26A0') Sayfa bulunamadi: $sayfa" $null | Out-Null; return $true }
        $msg = "<b>EXCEL SATIR DURUMU</b>`n--------------------`n<b>Sayfa:</b> $($info.Sayfa)`n<b>Yazma modu:</b> $($info.Mode)`n<b>Son dolu satir:</b> $($info.LastDataRow)`n<b>Ilk tamamen bos satir:</b> $($info.FirstEmptyRow)`n<b>Yeni kayit yazilacak satir:</b> $($info.NextRow)"
        Send-Message $chatId $msg $null | Out-Null
        return $true
    }

    if ($t -eq "/kayit_raporu") { Send-Message $chatId (Format-KayitRaporu 10) $null | Out-Null; return $true }
    if ($t.StartsWith('/kayit_raporu ')) {
        $nText = ($t -replace '^/kayit_raporu\s+','').Trim()
        $n = 10
        try { $n = [int]$nText } catch { $n = 10 }
        if ($n -lt 1) { $n = 1 }
        if ($n -gt 50) { $n = 50 }
        Send-Message $chatId (Format-KayitRaporu $n) $null | Out-Null
        return $true
    }

    if ($t -eq "/kategori_bilgi") { Send-Message $chatId "<b>Kullanim:</b> /kategori_bilgi KOD`nOrnek: /kategori_bilgi ARK" $null | Out-Null; return $true }
    if ($t.StartsWith('/kategori_bilgi ')) {
        $kod = ($t -replace '^/kategori_bilgi\s+','').Trim()
        Send-Message $chatId (Format-KategoriBilgi $kod) $null | Out-Null
        return $true
    }

    if ($t -eq "/kategori_liste") { Send-Message $chatId (Format-KategoriListesi) $null | Out-Null; return $true }
    if ($t -eq "/kategori_akislari") { Send-Message $chatId "<b>KATEGORI AKISLARI</b>`n--------------------`n<b>tek_uye</b>: Personel + Uye ID`n<b>ark_ana</b>: Personel + Arkadas Uye ID + Ana Uye ID`n<b>ana_only</b>: Personel + Ana Uye ID`n<b>sessiz_tip</b>: Personel + Uye ID + Sessiz/Telesekreter" $null | Out-Null; return $true }
    if ($t -eq "/kategori_yayinla") { Send-Message $chatId "$(E '2705') Kategori listesi kayitli dosyadan okunuyor. Yeni gorsel gonderen kullanicilar guncel kategori listesini gorecek." $null | Out-Null; return $true }
    if ($t -eq "/kategori_ekle") { Send-Message $chatId "<b>Kullanim:</b> /kategori_ekle KOD|Baslik|akis`n`n<b>Ornek:</b> /kategori_ekle BONUS|Bonus|tek_uye`n`n<b>Akisler:</b>`ntek_uye = Personel + Uye ID`nark_ana = Personel + Arkadas ID + Ana ID`nana_only = Personel + Ana ID`nsessiz_tip = Personel + Uye ID + Sessiz/Telesekreter" $null | Out-Null; return $true }
    if ($t.StartsWith('/kategori_ekle ')) {
        $raw = ($t -replace '^/kategori_ekle\s+','')
        $p = $raw.Split('|')
        if ($p.Count -lt 3) { Send-Message $chatId "<b>Kullanim:</b> /kategori_ekle KOD|Baslik|akis`n`n<b>Ornek:</b> /kategori_ekle BONUS|Bonus|tek_uye`n`n<b>Akisler:</b>`ntek_uye = Personel + Uye ID`nark_ana = Personel + Arkadas ID + Ana ID`nana_only = Personel + Ana ID`nsessiz_tip = Personel + Uye ID + Sessiz/Telesekreter" $null | Out-Null; return $true }
        $akis = $p[2].Trim()
        $err = Add-OrUpdate-Kategori $p[0] $p[1] $akis
        if ($err) { Send-Message $chatId "$(E '26A0') $(Escape-Html $err)" $null | Out-Null; return $true }
        Send-Message $chatId "$(E '2705') Kategori eklendi/guncellendi: $(Escape-Html $p[0])`n<b>Baslik:</b> $(Escape-Html $p[1])`n<b>Akis:</b> $(Escape-Html $akis)`n<b>Sorulacak alanlar:</b> $(Escape-Html (Get-KategoriAlanMetni $akis))`nTum projelerde yeni secim ekranlarinda gorunecek." $null | Out-Null; return $true
    }
    if ($t -eq "/kategori_sil") { Send-Message $chatId "<b>Kullanim:</b> /kategori_sil KOD`nOrnek: /kategori_sil BONUS" $null | Out-Null; return $true }
    if ($t.StartsWith('/kategori_sil ')) {
        $code = ($t -replace '^/kategori_sil\s+','').Trim()
        if ([string]::IsNullOrWhiteSpace($code)) { Send-Message $chatId "<b>Kullanim:</b> /kategori_sil KOD" $null | Out-Null; return $true }
        $ok = Remove-Kategori $code
        if ($ok) { Send-Message $chatId "$(E '2705') Kategori kaldirildi: $(Escape-Html $code)" $null | Out-Null }
        else { Send-Message $chatId "$(E '26A0') Kategori bulunamadi: $(Escape-Html $code)" $null | Out-Null }
        return $true
    }

    if ($t -eq "/oturumlar") {
        $ots = Get-Oturumlar
        $msg = "<b>AKTIF OTURUMLAR</b>`n--------------------`n"
        foreach ($k in $ots.Keys) { $msg += "ID: $k | Adim: $($ots[$k].adim) | Proje: $($ots[$k].proje) | Kategori: $($ots[$k].kategori)`n" }
        if ($ots.Count -eq 0) { $msg += "Aktif oturum yok." }
        Send-Message $chatId $msg $null | Out-Null; return $true
    }

    if ($t -eq "/oturum_temizle") {
        Send-Message $chatId "<b>Kullanim:</b> /oturum_temizle ID`n`n<b>Ornek:</b> /oturum_temizle 123456789" $null | Out-Null
        return $true
    }

    if ($t.StartsWith('/oturum_temizle ')) { $id = ($t -replace '^/oturum_temizle\s+','').Trim(); if ([string]::IsNullOrWhiteSpace($id)) { Send-Message $chatId "<b>Kullanim:</b> /oturum_temizle ID" $null | Out-Null; return $true }; Remove-Oturum $id; Send-Message $chatId "Oturum temizlendi: $id" $null | Out-Null; return $true }
    if ($t -eq "/yedekle") { $b = Invoke-Backup $true; Send-Message $chatId "$(E '1F4BE') Manuel yedek alindi:`n$(Escape-Html $b)" $null | Out-Null; return $true }
    if ($t -eq "/bakim_ac") { Set-MaintenanceMode $true; Send-Message $chatId "$(E '1F6E0') Bakim modu acildi." $null | Out-Null; return $true }
    if ($t -eq "/bakim_kapat") { Set-MaintenanceMode $false; Send-Message $chatId "$(E '2705') Bakim modu kapatildi." $null | Out-Null; return $true }
    if ($t -eq "/gyazo_bakim_ac") { Set-GyazoBakim $true; Send-Message $chatId "$(E '1F6E0') Gyazo bakim modu ACILDI. Kullanicilar Gyazo secince 'sunucu bakimda' uyarisi alir; gorseller dosyaya kaydedilir." $null | Out-Null; return $true }
    if ($t -eq "/gyazo_bakim_kapat") { Set-GyazoBakim $false; Send-Message $chatId "$(E '2705') Gyazo bakim modu KAPATILDI. Gyazo secenegi yeniden calisiyor." $null | Out-Null; return $true }
    if ($t -eq "/son_hatalar") {
        $lines = @(); if (Test-Path $LOG_DOSYA) { $lines = Get-Content $LOG_DOSYA -Encoding UTF8 | Select-Object -Last 25 }
        Send-Message $chatId ("<b>SON LOG SATIRLARI</b>`n--------------------`n" + (Escape-Html ($lines -join "`n"))) $null | Out-Null; return $true
    }
    if ($t -eq "/kapat") {
        $global:PendingAdminConfirm[[string]$userId] = @{ type='kapat' }
        Send-Message $chatId "$(E '26A0') <b>Bot guvenli sekilde kapatilacak.</b>`nOnay: /onayla`nIptal: /vazgec" $null | Out-Null; return $true
    }

    Send-Message $chatId "$(E '26A0') <b>Admin komutu eksik veya hatali parametreyle geldi.</b>`n`n$(Get-AdminHelp)" $null | Out-Null
    return $true
}

# ==================== TELEGRAM API ====================
function Send-Json($url, $json) {
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    for ($i = 1; $i -le 3; $i++) {
        try {
            $r = Invoke-RestMethod -Uri $url -Method POST `
                -ContentType "application/json; charset=utf-8" -Body $bytes -TimeoutSec 12
            return $r
        } catch {
            $global:LastErrorText = [string]$_
            Write-Log "! API hatasi ($i/3): $_"
            if ($i -lt 3) { Start-Sleep -Milliseconds (300 * $i) }
        }
    }
    return $null
}

function Escape-Json($str) {
    if ($null -eq $str) { return "" }
    $s = [string]$str
    $s = $s.Replace('\','\\')
    $s = $s.Replace('"','\"')
    $s = $s.Replace("`r","")
    $s = $s.Replace("`n","\n")
    return $s
}

function Escape-Html($str) {
    if ($null -eq $str) { return "" }
    return ([string]$str).Replace('&','&amp;').Replace('<','&lt;').Replace('>','&gt;').Replace('"','&quot;')
}

function Make-Keyboard($satirlar) {
    $satirJsonlari = @()
    foreach ($satir in $satirlar) {
        $butonJsonlari = @()
        foreach ($buton in $satir) {
            $t = Escape-Json $buton.text
            $d = Escape-Json $buton.callback_data
            $butonJsonlari += "{`"text`":`"$t`",`"callback_data`":`"$d`"}"
        }
        $satirJsonlari += "[" + ($butonJsonlari -join ",") + "]"
    }
    # DIKKAT: Bu fonksiyon raw JSON string dondurur. ConvertFrom-Json kullanmayin.
    # Aksi halde PowerShell tek elemanli dizileri bozabilir ve Telegram inline_keyboard Array of Arrays hatasi verir.
    return "{`"inline_keyboard`":" + "[" + ($satirJsonlari -join ",") + "]}"
}

function Send-Message($chatId, $metin, $keyboardJson = $null) {
    $m = Escape-Json $metin
    if ($keyboardJson) {
        $json = "{`"chat_id`":$chatId,`"text`":`"$m`",`"parse_mode`":`"HTML`",`"disable_web_page_preview`":true,`"reply_markup`":$keyboardJson}"
    } else {
        $json = "{`"chat_id`":$chatId,`"text`":`"$m`",`"parse_mode`":`"HTML`",`"disable_web_page_preview`":true}"
    }
    $r = Send-Json "https://api.telegram.org/bot$TELEGRAM_TOKEN/sendMessage" $json
    if ($r -and $r.result) { return $r.result.message_id }
    return $null
}

function Edit-Message($chatId, $messageId, $metin, $keyboardJson = $null) {
    $m = Escape-Json $metin
    if ($keyboardJson) {
        $json = "{`"chat_id`":$chatId,`"message_id`":$messageId,`"text`":`"$m`",`"parse_mode`":`"HTML`",`"disable_web_page_preview`":true,`"reply_markup`":$keyboardJson}"
    } else {
        $json = "{`"chat_id`":$chatId,`"message_id`":$messageId,`"text`":`"$m`",`"parse_mode`":`"HTML`",`"disable_web_page_preview`":true}"
    }
    $r = Send-Json "https://api.telegram.org/bot$TELEGRAM_TOKEN/editMessageText" $json
    if (-not $r) { Write-Log "! Mesaj duzenlenemedi." }
}


function Answer-Callback($callbackId) {
    $json = "{`"callback_query_id`":`"$callbackId`"}"
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    try {
        Invoke-RestMethod -Uri "https://api.telegram.org/bot$TELEGRAM_TOKEN/answerCallbackQuery" `
            -Method POST -ContentType "application/json; charset=utf-8" -Body $bytes -TimeoutSec 5 | Out-Null
    } catch {}
}

function Delete-Message($chatId, $messageId) {
    $json = "{`"chat_id`":$chatId,`"message_id`":$messageId}"
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    try {
        Invoke-RestMethod -Uri "https://api.telegram.org/bot$TELEGRAM_TOKEN/deleteMessage" `
            -Method POST -ContentType "application/json; charset=utf-8" -Body $bytes -TimeoutSec 5 | Out-Null
    } catch {}
}

# ==================== BUTONLAR ====================
function KB-Proje {
    return Make-Keyboard @(
        @( @{text="$(E '26AB') PP";callback_data="proje_pp"}, @{text="$(E '1F535') PA";callback_data="proje_pa"}, @{text="$(E '1F7E1') OF";callback_data="proje_of"} ),
        @( @{text="$(E '1F534') HI";callback_data="proje_hi"}, @{text="$(E '1F7E3') VI";callback_data="proje_vi"}, @{text="$(E '1F7E2') GA";callback_data="proje_ga"} )
    )
}

function KB-Kategori {
    $rows = @()
    $row = @()
    foreach ($k in Get-Kategoriler) {
        $row += @{text=[string]$k.label; callback_data=("kat_" + [string]$k.code)}
        if ($row.Count -ge 3) { $rows += ,$row; $row = @() }
    }
    if ($row.Count -gt 0) { $rows += ,$row }
    $rows += ,@( @{text="$(E '2B05') Geri";callback_data="geri_proje"} )
    return Make-Keyboard $rows
}

# GORSEL GELINCE SECENEK: Gyazo linkine mi donusturulsun, dogrudan dosyaya mi kaydedilsin?
function KB-KayitSecim {
    return Make-Keyboard @(
        @( @{text="$(E '1F517') Gyazo linkine donustur";callback_data="kayit_gyazo"} ),
        @( @{text="$(E '1F4BE') Gorseli direkt kaydet";callback_data="kayit_dosya"} ),
        @( @{text="$(E '274C') Iptal";callback_data="iptal_basa"} )
    )
}

# Gyazo bakimdayken: dosyaya kaydet ya da vazgec
function KB-GyazoBakim {
    return Make-Keyboard @(
        @( @{text="$(E '1F4BE') Gorseli direkt kaydet";callback_data="kayit_dosya"} ),
        @( @{text="$(E '274C') Iptal";callback_data="iptal_basa"} )
    )
}

function KB-Sessiz {
    return Make-Keyboard @(
        @( @{text="Sessiz";callback_data="tip_sessiz"}, @{text="Telesekreter";callback_data="tip_telesekreter"} ),
        @( @{text="$(E '2B05') Geri";callback_data="geri_uyeid"} )
    )
}

function KB-Onay {
    return Make-Keyboard @(
        @( @{text="$(E '2705') Onayla";callback_data="onayla"}, @{text="$(E '274C') Iptal";callback_data="iptal"} )
    )
}

# YAZILI BASLATMA: Lead ID dogrulama butonlari (Onayla / Degistir / Cik)
function KB-LeadOnay {
    return Make-Keyboard @(
        @( @{text="$(E '2705') Onayla";callback_data="lead_onay"}, @{text="$(E '270F') Degistir";callback_data="lead_degistir"} ),
        @( @{text="$(E '274C') Cik";callback_data="lead_iptal"} )
    )
}

function KB-Iptal {
    return Make-Keyboard @(
        @( @{text="$(E '1F504') Basa Don";callback_data="iptal_basa"} ),
        @( @{text="$(E '1F4C1') Proje Sec";callback_data="iptal_proje"} ),
        @( @{text="$(E '1F4CB') Kategori Sec";callback_data="iptal_kategori"} ),
        @( @{text="$(E '270F') Bilgileri Duzelt";callback_data="iptal_bilgi"} )
    )
}

function KB-Hata {
    return Make-Keyboard @(
        @( @{text="$(E '1F501') Tekrar Dene";callback_data="onayla"} ),
        @( @{text="$(E '1F504') Basa Don";callback_data="iptal_basa"} )
    )
}

function KB-Geri($callback) {
    return Make-Keyboard @(
        @( @{text="$(E '2B05') Geri";callback_data=$callback} )
    )
}

# ==================== OZET ====================
function Get-OzetMetni($oturum) {
    $proje    = Escape-Html $oturum.proje.ToUpper()
    $kategori = Escape-Html (Get-KategoriLabel $oturum.kategori)
    $personel = Escape-Html $oturum.personel
    $uyeid    = Escape-Html $oturum.uyeid
    $anaid    = Escape-Html $oturum.anaid
    $tip      = Escape-Html $oturum.tip

    $ozet  = "$(E '1F50D') <b>SON KONTROL</b>`n"
    $ozet += "--------------------`n"
    $ozet += "<b>Proje:</b> $proje`n"
    $ozet += "<b>Kategori:</b> $kategori`n"
    $ozet += "<b>Personel Kodu:</b> $personel`n"
    $katMode = Get-KategoriMode $oturum.kategori
    if ($katMode -eq "ark_ana") {
        $ozet += "<b>Arkadas Uye ID:</b> $uyeid`n"
        $ozet += "<b>Ana Uye ID:</b> $anaid`n"
    } elseif ($katMode -eq "ana_only") {
        $ozet += "<b>Ana Uye ID:</b> $anaid`n"
    } else {
        $ozet += "<b>Uye ID:</b> $uyeid`n"
    }
    if ($oturum.tip) { $ozet += "<b>Tur:</b> $tip`n" }
    $girisTipi = if ($oturum.girisTipi) { [string]$oturum.girisTipi } else { "resim" }
    if ($girisTipi -eq "yazili") {
        $ozet += "<b>Lead ID:</b> $(Escape-Html $oturum.leadId)`n"
    } else {
        $kayitModu = if ($oturum.kayitModu) { [string]$oturum.kayitModu } else { "gyazo" }
        if ($kayitModu -eq "dosya") {
            $ozet += "<b>Gorsel:</b> Alindi (dosyaya kaydedilecek)`n"
        } else {
            $ozet += "<b>Gorsel:</b> Alindi (Gyazo linkine donusturulecek)`n"
        }
    }
    $ozet += "--------------------`n"
    $ozet += "$(E '2705') <b>Bilgiler dogruysa Onayla butonuna basin.</b>`n$(E '270F') Hata varsa Iptal ile duzeltin."
    return $ozet
}

function Get-AdimMesaji($oturum, $istenenAlan, $aciklama) {
    $proje = if ($oturum.proje) { $oturum.proje.ToUpper() } else { "-" }
    $kat   = if ($oturum.kategori) { Get-KategoriLabel $oturum.kategori } else { "-" }
    $personel = if ($oturum.personel) { "`n<b>Personel:</b> $(Escape-Html $oturum.personel)" } else { "" }
    $uye = if ($oturum.uyeid) { "`n<b>Uye ID:</b> $(Escape-Html $oturum.uyeid)" } else { "" }

    $metin  = "$(E '1F4CC') <b>SECILENLER</b>`n"
    $metin += "<b>Proje:</b> $proje | <b>Kategori:</b> $kat$personel$uye`n`n"
    $metin += "$(E '1F449') <b>SIMDI SIZDEN BEKLENEN</b>`n"
    $metin += "<b>$istenenAlan</b>`n`n"
    $metin += "$(E '2139') $aciklama"
    return $metin
}


# ==================== GYAZO ====================
function Upload-ToGyazo($imagePath) {
    $boundary = [System.Guid]::NewGuid().ToString()
    $fileBytes = [System.IO.File]::ReadAllBytes($imagePath)
    $enc = [System.Text.Encoding]::GetEncoding("iso-8859-1")
    $bodyLines = "--$boundary`r`nContent-Disposition: form-data; name=`"imagedata`"; filename=`"img.jpg`"`r`nContent-Type: image/jpeg`r`n`r`n" + $enc.GetString($fileBytes) + "`r`n--$boundary--"
    $bodyBytes = $enc.GetBytes($bodyLines)
    try {
        $r = Invoke-RestMethod -Uri "https://upload.gyazo.com/api/upload" -Method POST `
            -Headers @{ Authorization = "Bearer $GYAZO_TOKEN" } `
            -ContentType "multipart/form-data; boundary=$boundary" `
            -Body $bodyBytes -TimeoutSec 30
        return $r.url
    } catch { Write-Log "Gyazo hatasi: $_"; return $null }
}

function Get-GyazoFromFileId($fileId) {
    try {
        $fileInfo = Invoke-RestMethod -Uri "https://api.telegram.org/bot$TELEGRAM_TOKEN/getFile?file_id=$fileId" -TimeoutSec 15
        # GUVENLIK: Asiri buyuk dosyalari reddet (varsayilan 8 MB). Telegram file_size byte cinsinden verir.
        $maxBytes = 8 * 1024 * 1024
        if ($fileInfo.result.file_size -and [int64]$fileInfo.result.file_size -gt $maxBytes) {
            Write-Log "! Dosya cok buyuk, reddedildi: $([int64]$fileInfo.result.file_size) byte"
            return $null
        }
        $tempFile = "$env:TEMP\tg_$fileId.jpg"
        Invoke-WebRequest -Uri "https://api.telegram.org/file/bot$TELEGRAM_TOKEN/$($fileInfo.result.file_path)" `
            -OutFile $tempFile -TimeoutSec 30
        $url = Upload-ToGyazo $tempFile
        Remove-Item $tempFile -ErrorAction SilentlyContinue
        return $url
    } catch { Write-Log "! Gorsel indirme hatasi: $_"; return $null }
}

# ==================== RENK ====================
function Get-ExcelColor($hex) {
    $r = ($hex -shr 16) -band 0xFF
    $g = ($hex -shr 8) -band 0xFF
    $b = $hex -band 0xFF
    return [int]($b -shl 16) -bor [int]($g -shl 8) -bor [int]$r
}

# ==================== EXCEL ====================
# GUVENLIK: Excel/CSV formul enjeksiyonu korumasi.
# Kullanici =, +, -, @ veya tab/CR ile baslayan bir metin gonderirse, Excel bunu
# formul/komut olarak yorumlayabilir (orn. =HYPERLINK(...), =cmd|... DDE saldirisi).
# Bu fonksiyon boyle degerlerin basina tek tirnak koyarak onlari zararsiz metne cevirir.
# Not: http ile baslayan gercek Gyazo linkleri etkilenmez.
function Protect-ExcelValue($deger) {
    $s = [string]$deger
    if ([string]::IsNullOrEmpty($s)) { return $s }
    $ilk = $s[0]
    if ($ilk -eq '=' -or $ilk -eq '+' -or $ilk -eq '-' -or $ilk -eq '@' -or $ilk -eq [char]9 -or $ilk -eq [char]13) {
        return "'" + $s
    }
    return $s
}

function Open-Excel {
    if (-not (Test-Path $EXCEL_DOSYA)) { Write-Log "! Excel bulunamadi."; exit }
    try {
        $global:xlApp = New-Object -ComObject Excel.Application
        $global:xlApp.Visible = $false
        $global:xlApp.DisplayAlerts = $false
        $global:xlWb = $global:xlApp.Workbooks.Open($EXCEL_DOSYA)
        Write-Log "  Excel acildi."
    } catch { Write-Log "! Excel acilamadi: $_"; throw }
}

function Close-Excel {
    try {
        if ($global:xlWb) {
            $global:xlWb.Save()
            $global:xlWb.Close($false)
            $global:xlApp.Quit()
            [System.Runtime.Interopservices.Marshal]::ReleaseComObject($global:xlWb) | Out-Null
            [System.Runtime.Interopservices.Marshal]::ReleaseComObject($global:xlApp) | Out-Null
            [GC]::Collect()
            $global:xlWb = $null
            $global:xlApp = $null
        }
    } catch { Write-Log "! Excel kapatma hatasi: $_" }
}

function Init-Excel {
    Open-Excel
    $mevcutlar = @{}
    foreach ($ws in $global:xlWb.Worksheets) { $mevcutlar[$ws.Name] = $true }

    foreach ($proje in $PROJELER) {
        $ad = $proje.ToUpper()
        if (-not $mevcutlar.ContainsKey($ad)) {
            $ws = $global:xlWb.Worksheets.Add()
            $ws.Name = $ad
            $renk = Get-ExcelColor $PROJE_RENK[$proje]
            $ws.Tab.Color = $renk
            for ($i = 0; $i -lt $HEADERS.Count; $i++) {
                $hucre = $ws.Cells(1, $i+1)
                $hucre.Value2 = $HEADERS[$i]
                $hucre.Font.Bold = $true
                $hucre.Font.Color = 0x000000
                $hucre.Interior.Color = $renk
                $hucre.HorizontalAlignment = -4108
            }
            for ($i = 0; $i -lt $SUTUN_GENISLIKLERI.Count; $i++) {
                $ws.Columns($i+1).ColumnWidth = $SUTUN_GENISLIKLERI[$i]
            }
            $ws.Rows(1).RowHeight = 20
            Write-Log "  Sayfa olusturuldu: $ad"
        }
    }

    if (-not $mevcutlar.ContainsKey("ONAYLILAR")) {
        $ws = $global:xlWb.Worksheets.Add()
        $ws.Name = "ONAYLILAR"
        $ws.Tab.Color = 0x00B050
        $onayHeaders = @("Kullanici ID", "Kullanici Adi", "Onay Tarihi")
        for ($i = 0; $i -lt $onayHeaders.Count; $i++) {
            $hucre = $ws.Cells(1, $i+1)
            $hucre.Value2 = $onayHeaders[$i]
            $hucre.Font.Bold = $true
            $hucre.Font.Color = 0x000000
            $hucre.Interior.Color = 0x00B050
        }
        $ws.Columns(1).ColumnWidth = 20
        $ws.Columns(2).ColumnWidth = 25
        $ws.Columns(3).ColumnWidth = 20
        $liste = Get-Onaylilar
        $satir = 2
        foreach ($kayit in $liste) {
            $parcalar = $kayit -split "\|"
            if ($parcalar.Count -ge 3) {
                $ws.Cells($satir, 1).Value2 = (Protect-ExcelValue $parcalar[0].Trim())
                $ws.Cells($satir, 2).Value2 = (Protect-ExcelValue $parcalar[1].Trim())
                $ws.Cells($satir, 3).Value2 = (Protect-ExcelValue $parcalar[2].Trim())
                $satir++
            }
        }
        Write-Log "  ONAYLILAR sayfasi olusturuldu - $($liste.Count) kisi yuklendi"
    }

    if (-not $mevcutlar.ContainsKey("HATALI")) {
        $ws = $global:xlWb.Worksheets.Add()
        $ws.Name = "HATALI"
        $ws.Tab.Color = 0x0000FF
        $hataliHeaders = @("Tarih", "Gonderen", "Gyazo Linki", "Hata Sebebi")
        for ($i = 0; $i -lt $hataliHeaders.Count; $i++) {
            $hucre = $ws.Cells(1, $i+1)
            $hucre.Value2 = $hataliHeaders[$i]
            $hucre.Font.Bold = $true
            $hucre.Font.Color = 0x000000
            $hucre.Interior.Color = 0x0000FF
        }
        $ws.Columns(1).ColumnWidth = 18
        $ws.Columns(2).ColumnWidth = 18
        $ws.Columns(3).ColumnWidth = 45
        $ws.Columns(4).ColumnWidth = 40
        Write-Log "  HATALI sayfasi olusturuldu"
    }

    $gecerliAdlar = @{ "HATALI" = $true; "ONAYLILAR" = $true }
    foreach ($proje in $PROJELER) { $gecerliAdlar[$proje.ToUpper()] = $true }
    $silList = @()
    foreach ($ws in $global:xlWb.Worksheets) {
        if (-not $gecerliAdlar.ContainsKey($ws.Name)) { $silList += $ws }
    }
    foreach ($ws in $silList) {
        if ($global:xlWb.Worksheets.Count -gt 1) { $ws.Delete() }
    }

    $global:xlWb.Save()
    Write-Log "Excel hazir."
}

function Get-ExcelWriteMode {
    if (Test-Path $EXCEL_MOD_DOSYA) {
        $m = (Get-Content $EXCEL_MOD_DOSYA -Encoding UTF8 -Raw).Trim()
        if (@("son_dolunun_altina", "ilk_bos_satir") -contains $m) { return $m }
    }
    return "son_dolunun_altina"
}

function Set-ExcelWriteMode($mode) {
    if (-not (@("son_dolunun_altina", "ilk_bos_satir") -contains $mode)) { return $false }
    Set-TextFileAtomic $EXCEL_MOD_DOSYA $mode
    return $true
}

function Get-ExcelLastDataRow($ws, [int]$columnCount) {
    $last = 1
    for ($col = 1; $col -le $columnCount; $col++) {
        try {
            $row = $ws.Cells($ws.Rows.Count, $col).End(-4162).Row
            $text = [string]$ws.Cells($row, $col).Text
            if ($row -gt $last -and -not [string]::IsNullOrWhiteSpace($text)) { $last = $row }
        } catch {}
    }
    if ($last -lt 1) { $last = 1 }
    return $last
}

function Test-ExcelRowEmpty($ws, [int]$row, [int]$columnCount) {
    for ($col = 1; $col -le $columnCount; $col++) {
        try {
            $text = [string]$ws.Cells($row, $col).Text
            if (-not [string]::IsNullOrWhiteSpace($text)) { return $false }
        } catch {}
    }
    return $true
}

function Get-ExcelFirstEmptyRow($ws, [int]$columnCount) {
    $last = Get-ExcelLastDataRow $ws $columnCount
    for ($row = 2; $row -le ($last + 1); $row++) {
        if (Test-ExcelRowEmpty $ws $row $columnCount) { return $row }
    }
    return ($last + 1)
}

function Get-NextExcelRow($ws, [int]$columnCount) {
    $mode = Get-ExcelWriteMode
    if ($mode -eq "ilk_bos_satir") { return (Get-ExcelFirstEmptyRow $ws $columnCount) }
    return ((Get-ExcelLastDataRow $ws $columnCount) + 1)
}

function Get-ExcelSheetWriteInfo($sayfaAdi, [int]$columnCount) {
    if (-not $global:xlWb) { Open-Excel }
    foreach ($s in $global:xlWb.Worksheets) {
        if ($s.Name -eq $sayfaAdi) {
            $last = Get-ExcelLastDataRow $s $columnCount
            $first = Get-ExcelFirstEmptyRow $s $columnCount
            $mode = Get-ExcelWriteMode
            $next = if ($mode -eq "ilk_bos_satir") { $first } else { $last + 1 }
            return [pscustomobject]@{ Sayfa=$sayfaAdi; Mode=$mode; LastDataRow=$last; FirstEmptyRow=$first; NextRow=$next }
        }
    }
    return $null
}

function Add-ExcelRow($sayfaAdi, [array]$degerler, $gyazoUrl) {
    if (-not $global:xlWb) { Open-Excel }
    try {
        $ws = $null
        foreach ($s in $global:xlWb.Worksheets) {
            if ($s.Name -eq $sayfaAdi) { $ws = $s; break }
        }
        if ($ws) {
            $sonSatir = Get-NextExcelRow $ws $degerler.Count
            $projeKey = $sayfaAdi.ToLower()
            $cizgiRenk = if ($PROJE_RENK.ContainsKey($projeKey)) { Get-ExcelColor $PROJE_RENK[$projeKey] } else { 0x000000 }
            for ($i = 0; $i -lt $degerler.Count; $i++) {
                $hucre = $ws.Cells($sonSatir, $i+1)
                $deger = [string]$degerler[$i]
                $hucre.NumberFormat = "@"
                $yerelDosya = ($deger -and $deger -notlike "http*" -and $deger -match '^[A-Za-z]:\\' -and (Test-Path -LiteralPath $deger))
                if ($deger -and ($deger -like "http*" -or $yerelDosya)) {
                    $hucre.Value2 = $deger
                    $ws.Hyperlinks.Add($hucre, $deger, [System.Type]::Missing, "Gorseli Ac", $deger) | Out-Null
                    $hucre.Font.Color = 0xCC6600
                    $hucre.Font.Underline = $true
                } else {
                    $hucre.Value2 = (Protect-ExcelValue $deger)
                    $hucre.Font.Color = 0x000000
                }
                $hucre.Interior.ColorIndex = -4142
                $hucre.Borders(9).LineStyle = 1
                $hucre.Borders(9).Color = $cizgiRenk
                $hucre.Borders(9).Weight = 2
            }
            $ws.Rows($sonSatir).RowHeight = 16
            $global:xlWb.Save()
            Write-Log "  Kaydedildi -> $sayfaAdi"
        }
    } catch {
        Write-Log "! Excel yazma hatasi: $_"
        try { Close-Excel } catch {}
        Start-Sleep -Seconds 3
        try { Open-Excel } catch {}
        throw
    }
}

# ==================== CALLBACK ====================
function Process-Callback($update) {
    $cb       = $update.callback_query
    $cbId     = $cb.id
    $chatId   = $cb.message.chat.id
    $msgId    = $cb.message.message_id
    $userId   = $cb.from.id
    $userName = $cb.from.username
    if (-not $userName) { $userName = $cb.from.first_name }
    $data     = $cb.data
    Update-Kullanici $userId $userName $cb.from.first_name "callback"

    Answer-Callback $cbId

    if (-not (Is-Onayli $userId)) { return }

    $oturum = Get-Oturum $userId
    if (-not $oturum) { return }

    # YAZILI BASLATMA - LEAD ID ONAY
    if ($data -eq "lead_onay") {
        if ($oturum.adim -ne "lead_onay") { return }
        $oturum.girisTipi = "yazili"
        $oturum.adim = "proje"
        Set-Oturum $userId $oturum
        Edit-Message $chatId $msgId "$(E '2705') <b>Lead ID alindi:</b> $(Escape-Html $oturum.leadId)`n`n<b>SIMDI SIZDEN BEKLENEN:</b>`n<b>-> Projeyi secin.</b>" (KB-Proje)
        return
    }

    if ($data -eq "lead_degistir") {
        if ($oturum.adim -ne "lead_onay") { return }
        Edit-Message $chatId $msgId "$(E '270F') <b>Yeni Lead ID'yi yazin.</b>`n`n<b>Su anki Lead ID:</b> $(Escape-Html $oturum.leadId)`n`nYeni metni yazdiginizda tekrar onay ekrani gelecek." $null
        return
    }

    if ($data -eq "lead_iptal") {
        Remove-Oturum $userId
        Edit-Message $chatId $msgId "$(E '274C') Iptal edildi. Yeni bir Lead ID yazabilir veya gorsel gonderebilirsiniz." $null
        return
    }

    # GORSEL KAYIT SECIMI (foto gonderildikten sonra ilk adim)
    if ($data -eq "kayit_gyazo") {
        if ($oturum.adim -ne "kayit_secim" -and $oturum.adim -ne "gyazo_bakim") { return }
        if (Is-GyazoBakim) {
            $oturum.adim = "gyazo_bakim"
            Set-Oturum $userId $oturum
            Edit-Message $chatId $msgId "$(E '26A0') <b>Gyazo sunucusu su anda bakimda.</b>`nGyazo tarafinda sorun oldugu icin link olusturulamiyor.`n`n$(E '1F4BE') <b>Gorseli direkt kaydet</b> secenegiyle devam edebilirsiniz; gorsel, girdiginiz bilgilerle adlandirilip kaydedilir." (KB-GyazoBakim)
            return
        }
        $oturum.kayitModu = "gyazo"
        $oturum.adim = "proje"
        Set-Oturum $userId $oturum
        Edit-Message $chatId $msgId "$(E '1F517') <b>Gyazo linkine donusturulecek.</b>`n`n<b>SIMDI SIZDEN BEKLENEN:</b>`n<b>-> Projeyi secin.</b>" (KB-Proje)
        return
    }

    if ($data -eq "kayit_dosya") {
        if ($oturum.adim -ne "kayit_secim" -and $oturum.adim -ne "gyazo_bakim") { return }
        $oturum.kayitModu = "dosya"
        if ($oturum.proje -and $oturum.kategori -and $oturum.personel) {
            # Ozet/onay adiminda Gyazo bakima takildi: bilgiler duruyor, dogrudan onaya don.
            $oturum.adim = "ozet"
            Set-Oturum $userId $oturum
            Edit-Message $chatId $msgId (Get-OzetMetni $oturum) (KB-Onay)
            return
        }
        $oturum.adim = "proje"
        Set-Oturum $userId $oturum
        Edit-Message $chatId $msgId "$(E '1F4BE') <b>Gorsel dosyaya kaydedilecek.</b>`nDosya adi: kategori + tarih + girdiginiz bilgiler.`n`n<b>SIMDI SIZDEN BEKLENEN:</b>`n<b>-> Projeyi secin.</b>" (KB-Proje)
        return
    }

    # PROJE
    if ($data -like "proje_*") {
        $proje = $data -replace "proje_", ""
        $oturum.proje = $proje
        $oturum.adim  = "kategori"
        Set-Oturum $userId $oturum
        Edit-Message $chatId $msgId "<b>Proje:</b> $($proje.ToUpper())`n`n<b>SIMDI SIZDEN BEKLENEN:</b>`n<b>-> Kategoriyi secin.</b>" (KB-Kategori)
        return
    }

    # KATEGORI
    if ($data -like "kat_*") {
        $kategori = Normalize-KategoriCode ($data -replace "kat_", "")
        if (-not (Get-Kategori $kategori)) { Edit-Message $chatId $msgId "$(E '26A0') Bu kategori artik aktif degil. Lutfen kategori secimine donun." (KB-Kategori); return }
        $oturum.kategori = $kategori
        $oturum.adim     = "personel"
        Set-Oturum $userId $oturum
        Edit-Message $chatId $msgId (Get-AdimMesaji $oturum "Personel kodunuzu yazin" "Ornek: 12345. Mesaji yazdiktan sonra bot bu mesaji temizler ve sonraki adima gecer.") (KB-Geri "geri_kategori")
        return
    }

    # SESSIZ/TELESEKRETER
    if ($data -like "tip_*") {
        $tip = $data -replace "tip_", ""
        $oturum.tip  = $tip
        $oturum.adim = "ozet"
        Set-Oturum $userId $oturum
        Edit-Message $chatId $msgId (Get-OzetMetni $oturum) (KB-Onay)
        return
    }

    # GERI
    if ($data -eq "geri_proje") {
        $oturum.kategori = $null; $oturum.adim = "proje"
        Set-Oturum $userId $oturum
        Edit-Message $chatId $msgId "<b>Bilgileriniz alindi.</b>`n`n<b>SIMDI SIZDEN BEKLENEN:</b>`n<b>-> Projeyi secin.</b>" (KB-Proje)
        return
    }

    if ($data -eq "geri_kategori") {
        $oturum.personel = $null; $oturum.adim = "kategori"
        Set-Oturum $userId $oturum
        Edit-Message $chatId $msgId "<b>Proje:</b> $($oturum.proje.ToUpper())`n`n<b>SIMDI SIZDEN BEKLENEN:</b>`n<b>-> Kategoriyi secin.</b>" (KB-Kategori)
        return
    }

    if ($data -eq "geri_personel") {
        $oturum.uyeid = $null; $oturum.anaid = $null; $oturum.adim = "personel"
        Set-Oturum $userId $oturum
        Edit-Message $chatId $msgId (Get-AdimMesaji $oturum "Personel kodunuzu yazin" "Ornek: 12345. Mesaji yazdiktan sonra bot bu mesaji temizler ve sonraki adima gecer.") (KB-Geri "geri_kategori")
        return
    }

    if ($data -eq "geri_uyeid") {
        $oturum.anaid = $null; $oturum.tip = $null; $oturum.adim = "uyeid"
        Set-Oturum $userId $oturum
        $katMode = Get-KategoriMode $oturum.kategori
        $baslik = if ($katMode -eq "ark_ana") { "Arkadas Uye ID'sini yazin:" } elseif ($katMode -eq "ana_only") { "Ana Uye ID'sini yazin:" } else { "Uye ID'sini yazin:" }
        Edit-Message $chatId $msgId (Get-AdimMesaji $oturum $baslik "Lutfen sadece istenen ID bilgisini yazin.") (KB-Geri "geri_personel")
        return
    }

    # ONAYLA
    if ($data -eq "onayla") {
        $girisTipi = if ($oturum.girisTipi) { [string]$oturum.girisTipi } else { "resim" }

        $kayitModu = if ($oturum.kayitModu) { [string]$oturum.kayitModu } else { "gyazo" }
        $kayitDosyaAdi = ""
        if ($girisTipi -eq "yazili") {
            # YAZILI BASLATMA: Gyazo yukleme yok; Lead ID metni dogrudan Gyazo Linki sutununa yazilir.
            $gyazoUrl = [string]$oturum.leadId
        } elseif ($kayitModu -eq "dosya") {
            # DIREKT KAYIT: Gyazo'ya gitmez; gorsel girilen bilgilerle adlandirilip diske yazilir,
            # Excel'in "Gyazo Linki" sutununa dosya yolu (tiklanabilir) yazilir.
            Edit-Message $chatId $msgId "$(E '23F3') <b>Gorsel kaydediliyor...</b>" $null
            $fotoTarih = Get-Date
            if ($oturum.fotoTarih) { try { $fotoTarih = [DateTimeOffset]::FromUnixTimeSeconds([int64]$oturum.fotoTarih).LocalDateTime } catch {} }
            $gyazoUrl = Save-GorselToDisk $oturum.fileId $oturum $fotoTarih

            if (-not $gyazoUrl) {
                Edit-Message $chatId $msgId "$(E '26A0') <b>Gorsel kaydedilemedi.</b>`nNe yapmak istersiniz?" (KB-Hata)
                return
            }
            $kayitDosyaAdi = [System.IO.Path]::GetFileName($gyazoUrl)
            # OneDrive ayarliysa Excel'e yerel yol yerine tiklanabilir web linki yaz.
            $webLink = Get-GorselWebLink (Get-DosyaParcasi ($oturum.proje.ToUpper()) 10) ([System.IO.Path]::GetFileName($gyazoUrl))
            if ($webLink) { Write-Log "  OneDrive linki -> $webLink"; $gyazoUrl = $webLink }
        } else {
            if (Is-GyazoBakim) {
                $oturum.adim = "gyazo_bakim"
                Set-Oturum $userId $oturum
                Edit-Message $chatId $msgId "$(E '26A0') <b>Gyazo sunucusu su anda bakimda.</b>`nLink olusturulamiyor. Gorseli direkt kaydetmek ister misiniz? (bilgileriniz korunur)" (KB-GyazoBakim)
                return
            }
            Edit-Message $chatId $msgId "$(E '23F3') <b>Yukleniyor...</b>" $null
            $gyazoUrl = Get-GyazoFromFileId $oturum.fileId

            if (-not $gyazoUrl) {
                Edit-Message $chatId $msgId "$(E '26A0') <b>Gorsel yuklenemedi.</b>`nNe yapmak istersiniz?" (KB-Hata)
                return
            }
        }

        $sayfaAdi = $oturum.proje.ToUpper()
        $katMode = Get-KategoriMode $oturum.kategori
        $katLabel = Get-KategoriLabel $oturum.kategori
        $kayitTarihi = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        switch ($katMode) {
            "sessiz_tip" { Add-ExcelRow $sayfaAdi @($oturum.personel, $oturum.uyeid, "", $oturum.tip, $gyazoUrl, $katLabel.ToUpper(), $kayitTarihi) $gyazoUrl }
            "ark_ana"    { Add-ExcelRow $sayfaAdi @($oturum.personel, $oturum.uyeid, $oturum.anaid, "", $gyazoUrl, $katLabel.ToUpper(), $kayitTarihi) $gyazoUrl }
            "ana_only"   { Add-ExcelRow $sayfaAdi @($oturum.personel, "", $oturum.anaid, "", $gyazoUrl, $katLabel.ToUpper(), $kayitTarihi) $gyazoUrl }
            default      { Add-ExcelRow $sayfaAdi @($oturum.personel, $oturum.uyeid, "", "", $gyazoUrl, $katLabel.ToUpper(), $kayitTarihi) $gyazoUrl }
        }

        Register-KullaniciKayit $userId $userName $cb.from.first_name $sayfaAdi $oturum.kategori $katLabel
        Remove-Oturum $userId
        if ($kayitModu -eq "dosya" -and $girisTipi -ne "yazili") {
            Edit-Message $chatId $msgId "$(E '2705') <b>Kanitiniz eklendi, tesekkurler!</b>`n$(E '1F4C1') Dosya: <code>$(Escape-Html $kayitDosyaAdi)</code>" $null
        } else {
            Edit-Message $chatId $msgId "$(E '2705') <b>Kanitiniz eklendi, tesekkurler!</b>" $null
        }
        Write-Log "Kaydedildi -> [$sayfaAdi] [$($oturum.kategori.ToUpper())] $gyazoUrl"
        return
    }

    # IPTAL
    if ($data -eq "iptal") {
        Edit-Message $chatId $msgId "Nereye donmek istersiniz?" (KB-Iptal)
        return
    }

    if ($data -eq "iptal_basa") {
        Remove-Oturum $userId
        Edit-Message $chatId $msgId "$(E '274C') Iptal edildi. Yeni bir gorsel gonderebilir veya Lead ID yazabilirsiniz." $null
        return
    }

    if ($data -eq "iptal_proje") {
        $oturum.kategori=$null; $oturum.personel=$null
        $oturum.uyeid=$null; $oturum.anaid=$null
        $oturum.tip=$null; $oturum.adim="proje"
        Set-Oturum $userId $oturum
        Edit-Message $chatId $msgId "<b>Bilgileriniz alindi.</b>`n`n<b>SIMDI SIZDEN BEKLENEN:</b>`n<b>-> Projeyi secin.</b>" (KB-Proje)
        return
    }

    if ($data -eq "iptal_kategori") {
        $oturum.personel=$null; $oturum.uyeid=$null
        $oturum.anaid=$null; $oturum.tip=$null; $oturum.adim="kategori"
        Set-Oturum $userId $oturum
        Edit-Message $chatId $msgId "<b>Proje:</b> $($oturum.proje.ToUpper())`n`n<b>SIMDI SIZDEN BEKLENEN:</b>`n<b>-> Kategoriyi secin.</b>" (KB-Kategori)
        return
    }

    if ($data -eq "iptal_bilgi") {
        $oturum.personel=$null; $oturum.uyeid=$null
        $oturum.anaid=$null; $oturum.tip=$null; $oturum.adim="personel"
        Set-Oturum $userId $oturum
        Edit-Message $chatId $msgId (Get-AdimMesaji $oturum "Personel kodunuzu yazin" "Ornek: 12345. Mesaji yazdiktan sonra bot bu mesaji temizler ve sonraki adima gecer.") (KB-Geri "geri_kategori")
        return
    }
}

# ==================== MESAJ ISLE ====================
function Process-Message($update) {
    $message   = $update.message
    $messageId = $message.message_id
    $chatId    = $message.chat.id
    $cacheKey  = "$chatId`:$messageId"
    $userId    = $message.from.id
    $userName  = $message.from.username
    if (-not $userName) { $userName = $message.from.first_name }
    Update-Kullanici $userId $userName $message.from.first_name "mesaj"

    if ($message.chat.type -ne "private") {
        Add-Cache $cacheKey
        return
    }

    Write-Log "  Mesaj geldi: $userName (ID: $userId)"

    if (Is-Cached $cacheKey) {
        Write-Log "  [CACHE] $messageId zaten islendi."
        return
    }

    if ($message.text) {
        if (Process-AdminMessage $chatId $userId $userName $message.from.first_name $message.text) {
            Add-Cache $cacheKey
            return
        }
    }

    if (Is-Engellenen $userId) {
        Delete-Message $chatId $messageId
        Add-Cache $cacheKey
        return
    }

    if ((Is-MaintenanceMode) -and -not (Is-AdminLoggedIn $userId)) {
        Send-Message $chatId "$(E '1F6E0') <b>Bot su anda bakim modunda.</b>`nLutfen biraz sonra tekrar deneyin." $null | Out-Null
        Add-Cache $cacheKey
        return
    }

    # ONAYLI KULLANICI
    if (Is-Onayli $userId) {

        # GORSEL
        if ($message.photo) {
            $fileId = $message.photo[-1].file_id
            $oturum = @{
                adim="kayit_secim"; girisTipi="resim"; kayitModu=$null; fileId=$fileId; leadId=$null; msgId=$null
                fotoTarih=$message.date
                proje=$null; kategori=$null; personel=$null
                uyeid=$null; anaid=$null; tip=$null
            }
            Set-Oturum $userId $oturum
            Add-Cache $cacheKey
            # ONCE SECENEK: Gyazo linkine mi donussun, dogrudan dosyaya mi kaydedilsin?
            # Sonraki adimlar (proje -> kategori -> personel -> ID -> ozet -> onay) iki secenekte de aynidir.
            $yeniMsgId = Send-Message $chatId "$(E '1F5BC') <b>Gorsel alindi.</b>`n`n<b>SIMDI SIZDEN BEKLENEN:</b>`n<b>-> Ne yapmak istersiniz?</b>`n`n$(E '1F517') <b>Gyazo linkine donustur</b>: gorsel Gyazo'ya yuklenir, Excel'e link yazilir.`n$(E '1F4BE') <b>Gorseli direkt kaydet</b>: gorsel, girdiginiz bilgilerle (kategori, tarih, ID'ler) adlandirilip bilgisayara kaydedilir." (KB-KayitSecim)
            if ($yeniMsgId) {
                $oturum.msgId = $yeniMsgId
                Set-Oturum $userId $oturum
            }
            return
        }

        # YAZI
        if ($message.text) {
            $metin  = $message.text.Trim()
            $oturum = Get-Oturum $userId

            # YAZILI BASLATMA: Kullanici bir yazi-giris adiminda (personel/uyeid/anaid/lead_onay)
            # DEGILSE, gelen metni yeni bir Lead ID baslatma olarak degerlendiririz.
            # Boylece yarim kalmis (foto) bir oturum olsa bile yazi ile baslatma calisir;
            # tipki foto gonderiminin her zaman sifirdan baslamasi gibi.
            $yaziGirisAdimlari = @("personel","uyeid","anaid","lead_onay")

            if (-not $oturum -or ($yaziGirisAdimlari -notcontains [string]$oturum.adim)) {
                # Bos veya komut (/...) metinleri Lead ID sayilmaz.
                if ([string]::IsNullOrWhiteSpace($metin) -or $metin -like "/*") {
                    Add-Cache $cacheKey
                    Send-Message $chatId "$(E '1F4F7') Baslamak icin bir gorsel gonderin ya da Lead ID'yi yazin." $null
                    return
                }
                $oturum = @{
                    adim="lead_onay"; girisTipi="yazili"; fileId=$null; leadId=$metin; msgId=$null
                    proje=$null; kategori=$null; personel=$null
                    uyeid=$null; anaid=$null; tip=$null
                }
                Set-Oturum $userId $oturum
                Add-Cache $cacheKey
                $yeniMsgId = Send-Message $chatId "$(E '2753') <b>Lead ID mi gireceksiniz?</b>`n`n<b>Girdiginiz metin:</b> $(Escape-Html $metin)`n`n$(E '2705') <b>Onayla</b> ile devam edin, $(E '270F') <b>Degistir</b> ile yeniden yazin, $(E '274C') <b>Cik</b> ile vazgecin." (KB-LeadOnay)
                if ($yeniMsgId) {
                    $oturum.msgId = $yeniMsgId
                    Set-Oturum $userId $oturum
                }
                return
            }

            $botMsgId = $oturum.msgId

            switch ($oturum.adim) {
                "lead_onay" {
                    # Kullanici onay beklerken yeni bir metin yazarsa Lead ID'yi guncelle ve tekrar sor.
                    $oturum.leadId = $metin
                    Set-Oturum $userId $oturum
                    Delete-Message $chatId $messageId
                    Add-Cache $cacheKey
                    if ($botMsgId) {
                        Edit-Message $chatId $botMsgId "$(E '2753') <b>Lead ID mi gireceksiniz?</b>`n`n<b>Girdiginiz metin:</b> $(Escape-Html $metin)`n`n$(E '2705') <b>Onayla</b> ile devam edin, $(E '270F') <b>Degistir</b> ile yeniden yazin, $(E '274C') <b>Cik</b> ile vazgecin." (KB-LeadOnay)
                    }
                    return
                }
                "personel" {
                    $oturum.personel = $metin
                    $oturum.adim = "uyeid"
                    Set-Oturum $userId $oturum
                    Delete-Message $chatId $messageId
                    Add-Cache $cacheKey
                    $katMode = Get-KategoriMode $oturum.kategori
        $baslik = if ($katMode -eq "ark_ana") { "Arkadas Uye ID'sini yazin:" } elseif ($katMode -eq "ana_only") { "Ana Uye ID'sini yazin:" } else { "Uye ID'sini yazin:" }
                    if ($botMsgId) {
                        Edit-Message $chatId $botMsgId (Get-AdimMesaji $oturum $baslik "Lutfen sadece istenen ID bilgisini yazin.") (KB-Geri "geri_personel")
                    }
                    return
                }
                "uyeid" {
                    $oturum.uyeid = $metin
                    Delete-Message $chatId $messageId
                    Add-Cache $cacheKey
                    $katMode = Get-KategoriMode $oturum.kategori
                    if ($katMode -eq "ark_ana") {
                        $oturum.adim = "anaid"
                        Set-Oturum $userId $oturum
                        if ($botMsgId) {
                            Edit-Message $chatId $botMsgId (Get-AdimMesaji $oturum "Ana Uye ID'sini yazin" "Arkadas ID alindi. Simdi ana uye ID bilgisini yazin.") (KB-Geri "geri_uyeid")
                        }
                    } elseif ($katMode -eq "ana_only") {
                        $oturum.anaid = $metin
                        $oturum.uyeid = $null
                        $oturum.adim = "ozet"
                        Set-Oturum $userId $oturum
                        if ($botMsgId) {
                            Edit-Message $chatId $botMsgId (Get-OzetMetni $oturum) (KB-Onay)
                        }
                    } elseif ($katMode -eq "sessiz_tip") {
                        $oturum.adim = "tip"
                        Set-Oturum $userId $oturum
                        if ($botMsgId) {
                            Edit-Message $chatId $botMsgId (Get-AdimMesaji $oturum "Sessiz / Telesekreter turunu secin" "Asagidaki butonlardan uygun turu secin.") (KB-Sessiz)
                        }
                    } else {
                        $oturum.adim = "ozet"
                        Set-Oturum $userId $oturum
                        if ($botMsgId) {
                            Edit-Message $chatId $botMsgId (Get-OzetMetni $oturum) (KB-Onay)
                        }
                    }
                    return
                }
                "anaid" {
                    $oturum.anaid = $metin
                    $oturum.adim  = "ozet"
                    Set-Oturum $userId $oturum
                    Delete-Message $chatId $messageId
                    Add-Cache $cacheKey
                    if ($botMsgId) {
                        Edit-Message $chatId $botMsgId (Get-OzetMetni $oturum) (KB-Onay)
                    }
                    return
                }
            }
        }

        Add-Cache $cacheKey
        return
    }

    # SIFRELI GIRIS
    if ($message.text) {
        $metin = $message.text.Trim()

        if ($metin -like "/*") {
            Send-Message $chatId "<b>Merhaba!</b>`n`nDevam etmek icin lutfen sifreyi yazin." $null
            Add-Cache $cacheKey
            return
        }

        $deneme = Get-Deneme $userId

        if ($metin -eq $SIFRE) {
            Add-Onayli $userId $userName
            Set-Deneme $userId 0
            if (Test-Path $CACHE_DOSYA) {
                $yeniCache = @(Get-Content $CACHE_DOSYA -Encoding UTF8 | Where-Object { $_ -ne [string]$cacheKey })
                $yeniCache | Set-Content $CACHE_DOSYA -Encoding UTF8
            }
            Send-Message $chatId "<b>Hos geldiniz!</b>`n`nBaslamak icin bir <b>gorsel</b> gonderin veya <b>Lead ID</b>'yi yazin; ardindan bot sizi adim adim yonlendirecek." $null
            Write-Log "  Sifre dogru: $userName onaylandi."
            return
        }

        $deneme++
        $kalan = $MAX_DENEME - $deneme

        if ($deneme -ge $MAX_DENEME) {
            Add-Engellenen $userId $userName "3 yanlis sifre denemesi"
            Delete-Message $chatId $messageId
            Send-Message $chatId "$(E '26D4') Erisim engellendi." $null
            Add-Cache $cacheKey
        } else {
            Set-Deneme $userId $deneme
            Send-Message $chatId "$(E '26A0') Yanlis sifre! $kalan deneme hakkiniz kaldi." $null
            Add-Cache $cacheKey
        }
        return
    }

    if ($message.photo) {
        Send-Message $chatId " Bu bota yazma yetkiniz yok." $null
        Delete-Message $chatId $messageId
        Add-Engellenen $userId $userName "Yetkisiz gorsel gonderimi"
        Add-Cache $cacheKey
        return
    }

    Send-Message $chatId "<b>Merhaba!</b>`n`nDevam etmek icin lutfen sifreyi yazin." $null
    Add-Cache $cacheKey
}

# ==================== KONTROL ====================
function Check-Telegram {
    $offset = Get-Offset
    $response = Invoke-RestMethod `
        -Uri "https://api.telegram.org/bot$TELEGRAM_TOKEN/getUpdates?offset=$offset&timeout=$POLL_TIMEOUT_SECONDS&limit=100" `
        -Method GET -TimeoutSec $HTTP_TIMEOUT_SECONDS

    if (-not $response -or $response.result.Count -eq 0) { return }
    Write-Log "  $($response.result.Count) guncelleme bulundu."

    foreach ($update in $response.result) {
        $updateId = $update.update_id
        try {
            if ($update.callback_query) {
                Process-Callback $update
            } else {
                Process-Message $update
            }
        } catch {
            $global:LastErrorText = [string]$_
            Write-Log "! Hata: $_"
        }
        Save-Offset ($updateId + 1)
    }
}


# ==================== BASLA ====================
Write-Log "========================================"
Write-Log "  Bot baslatiliyor..."
Write-Log "  Excel  : $EXCEL_DOSYA"
Write-Log "  Oturum : $OTURUM_DOSYA"
Write-Log "========================================"

if ($TELEGRAM_TOKEN -eq "BURAYA_TELEGRAM_BOT_TOKEN" -or $GYAZO_TOKEN -eq "BURAYA_GYAZO_TOKEN" -or $SIFRE -eq "BURAYA_GUVENLI_SIFRE") {
    Write-Log "! UYARI: config.json icinde TELEGRAM_TOKEN, GYAZO_TOKEN ve BOT_PASSWORD degerlerini doldurun."
}

Invoke-Backup $false | Out-Null
Init-Excel
if (-not (Test-Path $GORSEL_KLASOR)) { try { New-Item -ItemType Directory -Path $GORSEL_KLASOR -Force | Out-Null } catch {} }
Write-Log "  Gorsel klasoru: $GORSEL_KLASOR | Gyazo: $(if (Is-GyazoBakim) { 'BAKIMDA' } else { 'ACIK' })"

Write-Log "========================================"
Write-Log "  Hazir! Hizli butonlu akis aktif."
Write-Log "  Kontrol: long polling aktif, dongu beklemesi $NORMAL_SLEEP_MS ms"
Write-Log "  Durdurmak icin: CTRL+C"
Write-Log "========================================"

try {
    while (-not $global:StopRequested) {
        try {
            # Normal dongude her tur log basmiyoruz; sadece gelen guncelleme ve hatalar loglanir.
            Check-Telegram
        } catch {
            $global:LastErrorText = [string]$_
            Write-Log "! Hata: $_ - $ERROR_SLEEP_SECONDS saniye sonra tekrar..."
            try { Close-Excel } catch {}
            Start-Sleep -Seconds $ERROR_SLEEP_SECONDS
            try { Open-Excel } catch { Write-Log "! Excel yeniden acilamadi: $_" }
        }
        Start-Sleep -Milliseconds $NORMAL_SLEEP_MS
    }
} finally {
    Write-Log "Bot guvenli sekilde durduruluyor..."
    Close-Excel
}