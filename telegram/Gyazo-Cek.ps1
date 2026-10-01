<#
    TELEGRAM KANIT BOTU - GYAZO'DAKI EKRAN GORUNTULERINI CEK (tek dosya)

    Nasil: Bu dosyaya SAG TIK -> "PowerShell ile calistir". Baska bir sey gerekmez.
      * Bot klasorunu kendisi bulur (bu dosya bot klasorundeyse oradan; degilse
        OneDrive\telegramkant gibi bilinen yerlerde arar).
      * Token GEREKMEZ: bot_log.txt icindeki Gyazo linklerini dogrudan indirir.
      * Son 2 ayin kayitlarini, kaydi ekleyen kullanici + proje + kategori + personel + uye ID
        ile adlandirip PNG olarak  <bot klasoru>\ekran_goruntuleri\<PROJE>\  altina koyar.
      * Gyazo'nun sildigi gorseller inmez; indeks.csv'de Durum = gyazo_silinmis yazar.
      * Gyazo sunucusu ust uste 503 donerse saatlerce denemez, durup soyler.
      * Kesilirse tekrar calistirin; inmis olanlar atlanir. Bitince klasoru acar.

    Istege bagli (yazmaniza gerek yok):  -Ay 3   -Format jpg   -Baslangic 2026-08-17 -Bitis 2026-08-18   -Proje OF,GA
#>
[CmdletBinding()]
param(
    [string]$BotKlasoru = $PSScriptRoot,
    [string]$LogDosyasi,
    [string]$ExcelDosyasi,
    [string]$KullaniciDosyasi,
    [string]$YedekKlasoru,
    [string]$CiktiKlasoru,
    [int]$Ay = 2,
    [string]$Baslangic,
    [string]$Bitis,
    [string[]]$Proje,
    [string]$AdSablonu = "{tarih}_{proje}_{kategori}_{kullanici}_{personel}_{uyeid}_{anaid}_{tip}",
    [switch]$SadeceListele,
    [switch]$Yeniden,
    [switch]$ExcelKullanma,
    [int]$BeklemeMs = 300,
    [int]$DenemeSayisi = 3,
    [int]$ZamanAsimiSn = 60,
    [ValidateSet("png","jpg")] [string]$Format = "png",
    [switch]$Sessiz
)

Set-StrictMode -Version 2
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # PS 5.1'de Invoke-WebRequest ilerleme cubugu indirmeyi cok yavaslatir
$Inv = [System.Globalization.CultureInfo]::InvariantCulture
try { [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor [System.Net.SecurityProtocolType]::Tls12 } catch {}

function Wait-Kapat {
    if ($Sessiz) { return }
    Write-Host ""
    Write-Host "Kapatmak icin bir tusa basin..." -ForegroundColor Yellow
    try { $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown") } catch { try { $null = Read-Host } catch {} }
}
function Find-BotKlasoru($ilk) {
    $adaylar = New-Object System.Collections.Generic.List[string]
    if ($ilk) { $adaylar.Add($ilk) }
    $adaylar.Add((Get-Location).Path)
    $profil = $(if ($env:USERPROFILE) { $env:USERPROFILE } else { $HOME })
    foreach ($k in @("OneDrive - Get Mails\telegramkant", "OneDrive - Get Mails\telegramkant\telegramkant", "OneDrive - Park\telegramkant", "OneDrive\telegramkant", "telegramkant", "Desktop\telegramkant", "Documents\telegramkant")) { $adaylar.Add((Join-Path $profil $k)) }
    try { foreach ($d in (Get-ChildItem $profil -Directory -Filter "OneDrive*" -ErrorAction SilentlyContinue)) { $adaylar.Add((Join-Path $d.FullName "telegramkant")); $adaylar.Add((Join-Path $d.FullName "telegramkant\telegramkant")) } } catch {}
    foreach ($a in $adaylar) { if ($a -and (Test-Path (Join-Path $a "bot_log.txt")) -and (Test-Path (Join-Path $a "telegrambot_gyazo.xlsx"))) { return (Resolve-Path $a).Path } }
    try {
        $bulunan = Get-ChildItem $profil -Recurse -Depth 4 -Filter "bot_log.txt" -File -ErrorAction SilentlyContinue | Where-Object { Test-Path (Join-Path $_.DirectoryName "telegrambot_gyazo.xlsx") } | Select-Object -First 1
        if ($bulunan) { return $bulunan.DirectoryName }
    } catch {}
    return $null
}

$Host.UI.RawUI.WindowTitle = "Gyazo gorselleri cekiliyor"
Write-Host ""
Write-Host "=== TELEGRAM KANIT BOTU - GYAZO GORSELLERINI CEK ===" -ForegroundColor Cyan
$bulunanKlasor = Find-BotKlasoru $BotKlasoru
if (-not $bulunanKlasor) {
    Write-Host ""
    Write-Host "Bot klasoru bulunamadi." -ForegroundColor Red
    Write-Host "Bu dosyayi botun klasorune (bot_log.txt ve telegrambot_gyazo.xlsx'in oldugu yere) kopyalayip oradan calistirin."
    Wait-Kapat
    exit 1
}
$BotKlasoru = $bulunanKlasor
Write-Host "Bot klasoru : $BotKlasoru"
try {
# ==================== YOLLAR ====================
if (-not $LogDosyasi)       { $LogDosyasi       = Join-Path $BotKlasoru "bot_log.txt" }
if (-not $ExcelDosyasi)     { $ExcelDosyasi     = Join-Path $BotKlasoru "telegrambot_gyazo.xlsx" }
if (-not $KullaniciDosyasi) { $KullaniciDosyasi = Join-Path $BotKlasoru "kullanicilar.json" }
if (-not $YedekKlasoru)     { $YedekKlasoru     = Join-Path $BotKlasoru "backups" }
if (-not $CiktiKlasoru)     { $CiktiKlasoru     = Join-Path $BotKlasoru "ekran_goruntuleri" }

if (-not (Test-Path $LogDosyasi)) { throw "Log dosyasi bulunamadi: $LogDosyasi  (-LogDosyasi veya -BotKlasoru verin)" }
New-Item -ItemType Directory -Path $CiktiKlasoru -Force | Out-Null
$CiktiKlasoru = (Resolve-Path $CiktiKlasoru).Path
$IndeksDosyasi = Join-Path $CiktiKlasoru "indeks.csv"
$CalismaLogu   = Join-Path $CiktiKlasoru "indirme_log.txt"

function Write-Bilgi($mesaj) {
    $satir = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $mesaj"
    Write-Host $satir
    try { Add-Content -Path $CalismaLogu -Value $satir -Encoding UTF8 } catch {}
}

function ConvertTo-Tarih($metin, $varsayilan) {
    if ([string]::IsNullOrWhiteSpace([string]$metin)) { return $varsayilan }
    $formatlar = @("yyyy-MM-dd HH:mm:ss", "yyyy-MM-dd HH:mm", "yyyy-MM-dd", "dd.MM.yyyy HH:mm:ss", "dd.MM.yyyy HH:mm", "dd.MM.yyyy")
    $sonuc = [datetime]::MinValue
    if ([datetime]::TryParseExact([string]$metin, [string[]]$formatlar, $Inv, [System.Globalization.DateTimeStyles]::None, [ref]$sonuc)) { return $sonuc }
    return [datetime]::Parse([string]$metin, $Inv)
}

$BaslangicTarihi = ConvertTo-Tarih $Baslangic ([datetime]::Today.AddMonths(-$Ay))
$BitisTarihi     = ConvertTo-Tarih $Bitis     ([datetime]::MaxValue)
if ($Bitis -and $BitisTarihi.TimeOfDay -eq [timespan]::Zero) { $BitisTarihi = $BitisTarihi.AddDays(1).AddTicks(-1) }  # "2026-08-31" -> gunun sonu
$ProjeFiltre = @()
if ($Proje) { $ProjeFiltre = @($Proje | ForEach-Object { ([string]$_) -split ',' } | ForEach-Object { ([string]$_).Trim().ToUpperInvariant() } | Where-Object { $_ }) }   # "OF,GA" tek parca gelse de ayir (powershell -File ile cagrildiginda)

Write-Bilgi "========================================"
Write-Bilgi "Gyazo gorsel geri alma basliyor"
Write-Bilgi "  Log    : $LogDosyasi"
Write-Bilgi "  Excel  : $ExcelDosyasi $(if ($ExcelKullanma) { '(KULLANILMAYACAK)' })"
Write-Bilgi "  Cikti  : $CiktiKlasoru"
Write-Bilgi "  Format : $Format"
Write-Bilgi "  Aralik : $($BaslangicTarihi.ToString('yyyy-MM-dd HH:mm:ss', $Inv)) -> $(if ($BitisTarihi -eq [datetime]::MaxValue) { 'simdi' } else { $BitisTarihi.ToString('yyyy-MM-dd HH:mm:ss', $Inv) })"
if ($ProjeFiltre.Count -gt 0) { Write-Bilgi "  Proje  : $($ProjeFiltre -join ', ')" }
if ($SadeceListele) { Write-Bilgi "  MOD    : sadece listele (indirme yok)" }

# ==================== YARDIMCILAR ====================
function Get-GyazoId($metin) {
    # https://i.gyazo.com/<32 hex>.jpg, https://gyazo.com/<id>, https://teamzone.gyazo.com/<id> ...
    # Gyazo id'si olmayan ama http ile baslayan bir link gelirse dosya adi kismi kimlik olarak kullanilir.
    if (-not $metin) { return $null }
    $s = [string]$metin
    $m = [regex]::Match($s, 'gyazo\.com/(?:[a-z0-9_-]+/)*([0-9a-f]{32})', 'IgnoreCase')
    if ($m.Success) { return $m.Groups[1].Value.ToLowerInvariant() }
    if ($s -notmatch '^https?://') { return $null }
    if ($s -notmatch 'gyazo\.com') { return $null }   # OneDrive/SharePoint gibi Gyazo disi linkler: bu script indirmez (gorsel zaten diskte)
    $m = [regex]::Match($s, '([0-9a-f]{32})', 'IgnoreCase')
    if ($m.Success) { return $m.Groups[1].Value.ToLowerInvariant() }
    return $null
}

function ConvertTo-GuvenliAd($metin, [int]$maksUzunluk = 40) {
    # Turkce karakterleri sadelestir, dosya adinda sorun cikaracak her seyi at.
    if ($null -eq $metin) { return "" }
    $s = [string]$metin
    $s = $s.Trim()
    if ($s.Length -eq 0) { return "" }
    $s = $s -replace "'", ""                       # Excel korumasi icin eklenen tek tirnak (Protect-ExcelValue)
    $cift = @{
        [char]0x00E7 = 'c'; [char]0x00C7 = 'C'; [char]0x011F = 'g'; [char]0x011E = 'G'
        [char]0x0131 = 'i'; [char]0x0130 = 'I'; [char]0x00F6 = 'o'; [char]0x00D6 = 'O'
        [char]0x015F = 's'; [char]0x015E = 'S'; [char]0x00FC = 'u'; [char]0x00DC = 'U'
    }
    $sb = New-Object System.Text.StringBuilder
    foreach ($ch in $s.ToCharArray()) {
        if ($cift.ContainsKey($ch)) { [void]$sb.Append($cift[$ch]) } else { [void]$sb.Append($ch) }
    }
    $s = $sb.ToString()
    # Diger aksanli harfleri temel harfe indir (e -> e vb.)
    $s = $s.Normalize([System.Text.NormalizationForm]::FormD)
    $s = [regex]::Replace($s, '\p{Mn}', '')
    $s = [regex]::Replace($s, '\s+', '-')
    $s = [regex]::Replace($s, '[^A-Za-z0-9._-]', '')
    $s = [regex]::Replace($s, '-{2,}', '-')
    $s = $s.Trim('-', '.', '_')
    if ($s.Length -gt $maksUzunluk) { $s = $s.Substring(0, $maksUzunluk) }
    return $s
}

function Format-SayiMetni($ham) {
    # Excel XML'deki "4.01221888E8" gibi sayilari duz metne cevir; sayi degilse oldugu gibi birak.
    $d = 0.0
    if ([double]::TryParse([string]$ham, [System.Globalization.NumberStyles]::Float, $Inv, [ref]$d)) {
        if ([math]::Abs($d - [math]::Round($d)) -lt 1e-9) {
            if ([math]::Abs($d) -lt 1e15) { return ([decimal]$d).ToString("0", $Inv) }
            return $d.ToString("0", $Inv)
        }
        return $d.ToString("0.############", $Inv)
    }
    return [string]$ham
}

# ==================== 1) LOG OKU ====================
Write-Bilgi "Log okunuyor..."
$rxSatir  = [regex]'^\uFEFF?\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*(.*?)\s*$'
$rxMesaj  = [regex]'^Mesaj geldi: (.+) \(ID: (\d+)\)$'
$rxKayit  = [regex]'^Kaydedildi (?:->|\u2192) \[([^\]]+)\] \[([^\]]+)\] (\S+)$'

$olaylar = New-Object System.Collections.Generic.List[object]
$fs = New-Object System.IO.FileStream($LogDosyasi, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
$sr = New-Object System.IO.StreamReader($fs, [System.Text.Encoding]::UTF8, $true)
try {
    while ($null -ne ($satir = $sr.ReadLine())) {
        $m = $rxSatir.Match($satir)
        if (-not $m.Success) { continue }
        $govde = $m.Groups[2].Value
        $mm = $rxMesaj.Match($govde)
        if ($mm.Success) {
            $olaylar.Add([pscustomobject]@{ Tur = "mesaj"; Zaman = [datetime]::ParseExact($m.Groups[1].Value, "yyyy-MM-dd HH:mm:ss", $Inv); KullaniciId = $mm.Groups[2].Value; KullaniciAdi = $mm.Groups[1].Value })
            continue
        }
        $mk = $rxKayit.Match($govde)
        if ($mk.Success) {
            $olaylar.Add([pscustomobject]@{ Tur = "kayit"; Zaman = [datetime]::ParseExact($m.Groups[1].Value, "yyyy-MM-dd HH:mm:ss", $Inv); Proje = $mk.Groups[1].Value.ToUpperInvariant(); Kategori = $mk.Groups[2].Value.ToUpperInvariant(); Link = $mk.Groups[3].Value })
        }
    }
} finally { $sr.Dispose(); $fs.Dispose() }
$kayitSayisi = @($olaylar | Where-Object { $_.Tur -eq "kayit" }).Count
Write-Bilgi "  $($olaylar.Count) olay, $kayitSayisi kayit satiri bulundu."
if ($kayitSayisi -eq 0) { throw "Logda hic 'Kaydedildi -> [..] [..] link' satiri yok. Dogru log dosyasi mi?" }

# ==================== 2) KESIN KULLANICI BILGISI (kullanicilar.json + yedekler) ====================
# Her kullanicinin son kaydinin tarihi/projesi json'da tutulur. Yedeklerdeki eski kopyalar da
# her kullanici icin o gunku "son kayit"i verir -> bunlar kesin eslesme kaynagi.
$kesin = @{}   # "yyyy-MM-dd HH:mm:ss|PROJE" -> @{ Id=..; Ad=.. }
$jsonDosyalari = New-Object System.Collections.Generic.List[string]
if (Test-Path $KullaniciDosyasi) { $jsonDosyalari.Add($KullaniciDosyasi) }
if (Test-Path $YedekKlasoru) {
    Get-ChildItem -Path $YedekKlasoru -Recurse -Filter "kullanicilar.json" -ErrorAction SilentlyContinue | ForEach-Object { $jsonDosyalari.Add($_.FullName) }
}
foreach ($jf in $jsonDosyalari) {
    try {
        $ham = [System.IO.File]::ReadAllText($jf, [System.Text.Encoding]::UTF8)
        if ([string]::IsNullOrWhiteSpace($ham)) { continue }
        $json = $ham | ConvertFrom-Json
        foreach ($p in $json.PSObject.Properties) {
            $u = $p.Value
            $t = $null; $pr = $null
            try { $t = [string]$u.son_kayit_tarihi } catch {}
            try { $pr = [string]$u.son_kayit_proje } catch {}
            if ($t -and $pr) {
                $ad = $null; try { $ad = [string]$u.username } catch {}
                if (-not $ad) { try { $ad = [string]$u.first_name } catch {} }
                $kesin["$t|$($pr.ToUpperInvariant())"] = @{ Id = [string]$p.Name; Ad = $ad }
            }
        }
    } catch { Write-Bilgi "  ! $jf okunamadi: $($_.Exception.Message)" }
}
Write-Bilgi "  $($jsonDosyalari.Count) kullanici dosyasindan $($kesin.Count) kesin eslesme noktasi."

function Find-KesinKullanici($zaman, $proje) {
    # Bot her kayitta once json'a (son_kayit_tarihi) sonra loga yazar; yani json zamani log
    # zamanindan SONRA olamaz. Bu yuzden sadece geriye (0..-5 sn) bakariz -- ileriye bakmak
    # ayni projede saniyeler icinde biten BASKA bir kaydin noktasini yanlislikla secebilir.
    for ($d = 0; $d -le 5; $d++) {
        $k = $zaman.AddSeconds(-$d).ToString("yyyy-MM-dd HH:mm:ss", $Inv) + "|" + $proje
        if ($kesin.ContainsKey($k)) { return [pscustomobject]@{ Id = $kesin[$k].Id; Ad = $kesin[$k].Ad; Anahtar = $k } }
    }
    return $null
}

# ==================== 3) KAYITLARI KULLANICIYA ESLE ====================
# Akis: foto -> proje -> kategori -> personel (yazi) -> uye id (yazi) [-> ana id (yazi)] -> ONAYLA.
# Yani her kayittan once ayni kullanicidan en az 3 "Mesaj geldi" satiri gelir ve bu mesajlar
# o kayitla "tuketilir". Bu modelle onaylayan kisi = en son mesaj yazan aday.
$tuketilmemis = @{}   # kullaniciId -> List[ @{ Zaman; Sira } ]  (Sira = log satir sirasi; ayni saniyedeki mesajlarda kesin siralama icin)
$adlar = @{}          # kullaniciId -> son gorulen ad
$kayitlar = New-Object System.Collections.Generic.List[object]
$sira = 0
foreach ($o in $olaylar) {
    $sira++
    if ($o.Tur -eq "mesaj") {
        if (-not $tuketilmemis.ContainsKey($o.KullaniciId)) { $tuketilmemis[$o.KullaniciId] = New-Object System.Collections.Generic.List[object] }
        $tuketilmemis[$o.KullaniciId].Add([pscustomobject]@{ Zaman = $o.Zaman; Sira = $sira })
        $adlar[$o.KullaniciId] = $o.KullaniciAdi
        continue
    }
    $secilen = $null; $ikinci = $null; $guven = "yok"
    $kesinK = Find-KesinKullanici $o.Zaman $o.Proje
    if ($kesinK) {
        # json noktasi (son_kayit_tarihi + proje) authoritative kabul edilir.
        $secilen = $kesinK.Id
        if ($kesinK.Ad) { $adlar[$secilen] = $kesinK.Ad }
        $guven = "kesin"
        $kesin.Remove($kesinK.Anahtar)   # ayni noktayi ikinci bir kayit tekrar kullanamasin
    } else {
        $adaylar = New-Object System.Collections.Generic.List[object]
        foreach ($kid in @($tuketilmemis.Keys)) {
            $lst = $tuketilmemis[$kid]
            if ($lst.Count -ge 3) { $adaylar.Add([pscustomobject]@{ Id = $kid; Son = $lst[$lst.Count - 1].Zaman; Sira = $lst[$lst.Count - 1].Sira }) }
        }
        if ($adaylar.Count -eq 0) {
            foreach ($kid in @($tuketilmemis.Keys)) {
                $lst = $tuketilmemis[$kid]
                if ($lst.Count -ge 1) { $adaylar.Add([pscustomobject]@{ Id = $kid; Son = $lst[$lst.Count - 1].Zaman; Sira = $lst[$lst.Count - 1].Sira }) }
            }
        }
        if ($adaylar.Count -gt 0) {
            $sirali = @($adaylar | Sort-Object Sira -Descending)   # en son mesaj yazan (satir sirasina gore, deterministik)
            $secilen = $sirali[0].Id
            $guven = "tahmini"
            if ($sirali.Count -gt 1) {
                $ikinci = $sirali[1]
                if (($sirali[0].Son - $ikinci.Son).TotalSeconds -lt 30) { $guven = "belirsiz" }
            }
        }
    }
    if ($secilen -and $tuketilmemis.ContainsKey($secilen)) { $tuketilmemis[$secilen].Clear() }
    $kayitlar.Add([pscustomobject]@{
        Zaman = $o.Zaman; Proje = $o.Proje; KategoriKodu = $o.Kategori; Link = $o.Link
        GyazoId = (Get-GyazoId $o.Link)
        KullaniciId = $secilen
        KullaniciAdi = $(if ($secilen -and $adlar.ContainsKey($secilen)) { $adlar[$secilen] } else { "" })
        KullaniciGuven = $guven
        IkinciAday = $(if ($ikinci -and $adlar.ContainsKey($ikinci.Id)) { $adlar[$ikinci.Id] } else { "" })
    })
}

# Tarih / proje / gorsel filtresi
$secilenKayitlar = @($kayitlar | Where-Object {
    $_.Zaman -ge $BaslangicTarihi -and $_.Zaman -le $BitisTarihi -and
    ($ProjeFiltre.Count -eq 0 -or $ProjeFiltre -contains $_.Proje)
})
$gorselKayitlar = @($secilenKayitlar | Where-Object { $_.GyazoId })
$yaziliKayit = $secilenKayitlar.Count - $gorselKayitlar.Count
Write-Bilgi "  Aralikta $($secilenKayitlar.Count) kayit; $($gorselKayitlar.Count) tanesi Gyazo gorseli ($yaziliKayit tanesi Lead ID ya da Gyazo disi link, atlandi)."
$guvenOzet = $gorselKayitlar | Group-Object KullaniciGuven | ForEach-Object { "$($_.Name)=$($_.Count)" }
Write-Bilgi "  Kullanici eslesme guveni: $($guvenOzet -join ', ')"

# ==================== 4) EXCEL OKU (COM'suz, gecici kopya uzerinden) ====================
# Excel satirlari Gyazo id'sine gore eslenir. Sayfalarin A..G sutunlari okunur:
# A Personel Kodu, B Uye ID, C Ana Uye ID, D Sessiz/Telesekreter, E Gyazo Linki, F Kategori, G Tarih/Saat
$excelSatirlari = @{}   # gyazoId -> List[ satir nesnesi ]
$excelOkundu = $false
if (-not $ExcelKullanma) {
    if (-not (Test-Path $ExcelDosyasi)) {
        Write-Bilgi "  ! Excel bulunamadi ($ExcelDosyasi); personel/uye bilgisi olmadan devam ediliyor."
    } else {
        Write-Bilgi "Excel okunuyor (kopya uzerinden)..."
        $kopya = Join-Path ([System.IO.Path]::GetTempPath()) ("gyazo_geri_al_" + [guid]::NewGuid().ToString("N") + ".xlsx")
        $zip = $null
        try {
            Copy-Item -Path $ExcelDosyasi -Destination $kopya -Force
            Add-Type -AssemblyName System.IO.Compression.FileSystem
            $zip = [System.IO.Compression.ZipFile]::OpenRead($kopya)

            function Read-ZipMetin($zip, $ad) {
                $giris = $zip.GetEntry($ad)
                if (-not $giris) { $giris = $zip.Entries | Where-Object { $_.FullName -ieq $ad } | Select-Object -First 1 }
                if (-not $giris) { return $null }
                $st = $giris.Open()
                $okuyucu = New-Object System.IO.StreamReader($st, [System.Text.Encoding]::UTF8)
                try { return $okuyucu.ReadToEnd() } finally { $okuyucu.Dispose(); $st.Dispose() }
            }
            function ConvertFrom-XmlMetin($s) { return [System.Net.WebUtility]::HtmlDecode([string]$s) }

            # Paylasilan metinler
            $paylasilan = New-Object System.Collections.Generic.List[string]
            $ssXml = Read-ZipMetin $zip "xl/sharedStrings.xml"
            if ($ssXml) {
                foreach ($si in [regex]::Matches($ssXml, '<si>(.*?)</si>', 'Singleline')) {
                    $parcalar = [regex]::Matches($si.Groups[1].Value, '<t(?:\s[^>]*)?>(.*?)</t>', 'Singleline')
                    $sbT = New-Object System.Text.StringBuilder
                    foreach ($pm in $parcalar) { [void]$sbT.Append($pm.Groups[1].Value) }
                    $paylasilan.Add((ConvertFrom-XmlMetin $sbT.ToString()))
                }
            }
            # Gyazo id iceren paylasilan metin indeksleri (baska sutunlara tasinmis linkleri de yakalamak icin)
            $gyazoSs = @{}
            for ($i = 0; $i -lt $paylasilan.Count; $i++) { $gid = Get-GyazoId $paylasilan[$i]; if ($gid) { $gyazoSs[$i] = $gid } }

            # Sayfa adi -> dosya
            $wbXml = Read-ZipMetin $zip "xl/workbook.xml"
            $relXml = Read-ZipMetin $zip "xl/_rels/workbook.xml.rels"
            $relHedef = @{}
            foreach ($r in [regex]::Matches($relXml, '<Relationship\b[^>]*>')) {
                $idM = [regex]::Match($r.Value, '\bId="([^"]*)"'); $tgM = [regex]::Match($r.Value, '\bTarget="([^"]*)"')
                if ($idM.Success -and $tgM.Success) {
                    $hedef = $tgM.Groups[1].Value
                    if ($hedef.StartsWith("/")) { $hedef = $hedef.TrimStart("/") } else { $hedef = "xl/" + $hedef }
                    $relHedef[$idM.Groups[1].Value] = $hedef
                }
            }
            $sayfalar = @()
            foreach ($s in [regex]::Matches($wbXml, '<sheet\b[^>]*>')) {
                $nm = [regex]::Match($s.Value, '\bname="([^"]*)"'); $rid = [regex]::Match($s.Value, '\br:id="([^"]*)"')
                if ($nm.Success -and $rid.Success -and $relHedef.ContainsKey($rid.Groups[1].Value)) {
                    $sayfalar += [pscustomobject]@{ Ad = (ConvertFrom-XmlMetin $nm.Groups[1].Value); Dosya = $relHedef[$rid.Groups[1].Value] }
                }
            }

            $rxHucre = [regex]'<c r="([A-G])(\d+)"([^>]*?)(?:/>|>(.*?)</c>)'          # sadece A..G sutunlari
            $rxMetinHucre = [regex]'<c r="[A-Z]+(\d+)"[^>]*\bt="s"[^>]*>\s*<v>(\d+)</v>'  # tum metin hucreleri (link baska sutuna tasinmis olabilir)
            $sutunAd = @{ A = "Personel"; B = "UyeId"; C = "AnaId"; D = "Tip"; E = "Gyazo"; F = "Kategori"; G = "Tarih" }
            $toplamSatir = 0
            foreach ($sf in $sayfalar) {
                if ($sf.Ad -in @("ONAYLILAR", "HATALI")) { continue }
                if ($ProjeFiltre.Count -gt 0 -and ($ProjeFiltre -notcontains $sf.Ad.ToUpperInvariant())) { continue }
                $sxml = Read-ZipMetin $zip $sf.Dosya
                if (-not $sxml) { continue }
                $satirlar = @{}   # satirNo -> hashtable
                foreach ($hm in $rxHucre.Matches($sxml)) {
                    $sut = $hm.Groups[1].Value; $sat = [int]$hm.Groups[2].Value
                    if ($sat -le 1) { continue }
                    $ozn = $hm.Groups[3].Value; $ic = $hm.Groups[4].Value
                    if (-not $ic) { continue }
                    $tur = [regex]::Match($ozn, '\bt="(\w+)"')
                    $tur = $(if ($tur.Success) { $tur.Groups[1].Value } else { "n" })
                    $deger = ""
                    if ($tur -eq "inlineStr") {
                        $tm = [regex]::Match($ic, '<t(?:\s[^>]*)?>(.*?)</t>', 'Singleline'); if ($tm.Success) { $deger = ConvertFrom-XmlMetin $tm.Groups[1].Value }
                    } else {
                        $vm = [regex]::Match($ic, '<v>(.*?)</v>', 'Singleline')
                        if (-not $vm.Success) { continue }
                        $v = $vm.Groups[1].Value
                        switch ($tur) {
                            "s"   { $ix = [int]$v; if ($ix -ge 0 -and $ix -lt $paylasilan.Count) { $deger = $paylasilan[$ix] } }
                            "b"   { $deger = $(if ($v -eq "1") { "TRUE" } else { "FALSE" }) }
                            "e"   { $deger = "" }
                            "str" { $deger = ConvertFrom-XmlMetin $v }
                            default {
                                if ($sut -eq "G") {
                                    # Tarih sutununa gercek Excel tarihi girilmisse (OLE Automation sayisi)
                                    $dd = 0.0
                                    if ([double]::TryParse($v, [System.Globalization.NumberStyles]::Float, $Inv, [ref]$dd) -and $dd -gt 20000 -and $dd -lt 80000) {
                                        $deger = [datetime]::FromOADate($dd).ToString("yyyy-MM-dd HH:mm:ss", $Inv)
                                    } else { $deger = Format-SayiMetni $v }
                                } else { $deger = Format-SayiMetni $v }
                            }
                        }
                    }
                    if (-not $satirlar.ContainsKey($sat)) { $satirlar[$sat] = @{} }
                    $satirlar[$sat][$sutunAd[$sut]] = [string]$deger
                }
                # Hangi satirda hangi gyazo id'ler var (E sutunu + diger sutunlar)
                $satirId = @{}   # satirNo -> List[id]
                foreach ($tm in $rxMetinHucre.Matches($sxml)) {
                    $ix = [int]$tm.Groups[2].Value
                    if ($gyazoSs.ContainsKey($ix)) {
                        $sat = [int]$tm.Groups[1].Value
                        if (-not $satirId.ContainsKey($sat)) { $satirId[$sat] = New-Object System.Collections.Generic.List[string] }
                        $satirId[$sat].Add($gyazoSs[$ix])
                    }
                }
                foreach ($sat in $satirId.Keys) {
                    $degerler = $(if ($satirlar.ContainsKey($sat)) { $satirlar[$sat] } else { @{} })
                    $eIdx = Get-GyazoId $(if ($degerler.ContainsKey("Gyazo")) { $degerler["Gyazo"] } else { "" })
                    foreach ($gid in ($satirId[$sat] | Select-Object -Unique)) {
                        $satirTarih = $null
                        if ($degerler.ContainsKey("Tarih") -and $degerler["Tarih"]) { try { $satirTarih = ConvertTo-Tarih $degerler["Tarih"] $null } catch { $satirTarih = $null } }
                        $nesne = [pscustomobject]@{
                            Sayfa = $sf.Ad; Satir = $sat
                            Personel = $(if ($degerler.ContainsKey("Personel")) { $degerler["Personel"] } else { "" })
                            UyeId    = $(if ($degerler.ContainsKey("UyeId"))    { $degerler["UyeId"] }    else { "" })
                            AnaId    = $(if ($degerler.ContainsKey("AnaId"))    { $degerler["AnaId"] }    else { "" })
                            Tip      = $(if ($degerler.ContainsKey("Tip"))      { $degerler["Tip"] }      else { "" })
                            Kategori = $(if ($degerler.ContainsKey("Kategori")) { $degerler["Kategori"] } else { "" })
                            Tarih    = $satirTarih
                            AnaSutun = ($eIdx -eq $gid)   # link E sutununda mi (yoksa "2. gorsel" gibi baska sutunda mi)
                        }
                        if (-not $excelSatirlari.ContainsKey($gid)) { $excelSatirlari[$gid] = New-Object System.Collections.Generic.List[object] }
                        $excelSatirlari[$gid].Add($nesne)
                        $toplamSatir++
                    }
                }
                Write-Bilgi "  Sayfa $($sf.Ad): $($satirId.Count) linkli satir"
            }
            $excelOkundu = $true
            Write-Bilgi "  Excel'den $($excelSatirlari.Count) farkli Gyazo linki ($toplamSatir satir) okundu."
        } catch {
            Write-Bilgi "  ! Excel okunamadi, personel/uye bilgisi olmadan devam ediliyor: $($_.Exception.Message)"
        } finally {
            if ($zip) { $zip.Dispose() }
            Remove-Item $kopya -Force -ErrorAction SilentlyContinue
        }
    }
}

function Find-ExcelSatiri($kayit) {
    if (-not $excelSatirlari.ContainsKey($kayit.GyazoId)) { return $null }
    $adaylar = @($excelSatirlari[$kayit.GyazoId])
    if ($adaylar.Count -eq 1) { return $adaylar[0] }
    # Birden fazla satirda ayni link: ayni sayfa + E sutunu + tarihi en yakin olan
    $puanli = foreach ($a in $adaylar) {
        $fark = 1e9
        if ($a.Tarih) { $fark = [math]::Abs(($a.Tarih - $kayit.Zaman).TotalSeconds) }
        [pscustomobject]@{ Satir = $a; Puan = ($(if ($a.Sayfa -eq $kayit.Proje) { 0 } else { 1 }) * 1e12) + ($(if ($a.AnaSutun) { 0 } else { 1 }) * 1e10) + $fark }
    }
    return ($puanli | Sort-Object Puan | Select-Object -First 1).Satir
}

# ==================== 5) DOSYA ADLARI ====================
$kategoriEtiket = @{}
$katDosya = Join-Path $BotKlasoru "kategoriler.json"
if (Test-Path $katDosya) {
    try { foreach ($k in ([System.IO.File]::ReadAllText($katDosya, [System.Text.Encoding]::UTF8) | ConvertFrom-Json)) { $kategoriEtiket[([string]$k.code).ToUpperInvariant()] = [string]$k.label } } catch {}
}

function New-DosyaAdi($kayit, $satir) {
    $kat = $kayit.KategoriKodu
    if ($satir -and $satir.Kategori) { $kat = $satir.Kategori }
    elseif ($kategoriEtiket.ContainsKey($kayit.KategoriKodu)) { $kat = $kategoriEtiket[$kayit.KategoriKodu] }
    $personel = $(if ($satir) { ConvertTo-GuvenliAd $satir.Personel } else { "" })
    $uyeid    = $(if ($satir) { ConvertTo-GuvenliAd $satir.UyeId }    else { "" })
    $anaid    = $(if ($satir) { ConvertTo-GuvenliAd $satir.AnaId }    else { "" })
    $tip      = $(if ($satir) { ConvertTo-GuvenliAd $satir.Tip }      else { "" })
    $alanlar = @{
        tarih       = $kayit.Zaman.ToString("yyyy-MM-dd_HH-mm-ss", $Inv)
        proje       = ConvertTo-GuvenliAd $kayit.Proje
        kategori    = (ConvertTo-GuvenliAd $kat).ToUpperInvariant()
        kullanici   = $(if ($kayit.KullaniciAdi) { ConvertTo-GuvenliAd $kayit.KullaniciAdi } else { "bilinmiyor" })
        kullaniciid = $(if ($kayit.KullaniciId) { [string]$kayit.KullaniciId } else { "" })
        personel    = $(if ($personel) { "P$personel" } else { "" })
        uyeid       = $(if ($uyeid)    { "U$uyeid" }    else { "" })
        anaid       = $(if ($anaid)    { "A$anaid" }    else { "" })
        tip         = $tip
        gyazoid     = $kayit.GyazoId
    }
    $ad = [regex]::Replace($AdSablonu, '\{(\w+)\}', { param($m) $k = $m.Groups[1].Value.ToLowerInvariant(); if ($alanlar.ContainsKey($k)) { [string]$alanlar[$k] } else { "" } })
    $ad = [regex]::Replace($ad, '_{2,}', '_').Trim('_', '-', '.')
    if (-not $ad) { $ad = $kayit.GyazoId }
    $uz = [System.IO.Path]::GetExtension(($kayit.Link -split '\?')[0])
    if (-not $uz -or $uz.Length -gt 5 -or $uz -notmatch '^\.[A-Za-z0-9]+$') { $uz = ".jpg" }
    if ($Format -eq "png") { $uz = ".png" }
    return @{ Ad = $ad; Uzanti = $uz.ToLowerInvariant(); Kategori = $kat }
}

$kullanilanAdlar = @{}
$plan = New-Object System.Collections.Generic.List[object]
$excelEslesen = 0
foreach ($k in $gorselKayitlar) {
    $satir = $null
    if ($excelOkundu) { $satir = Find-ExcelSatiri $k }
    if ($satir) { $excelEslesen++ }
    $adBilgi = New-DosyaAdi $k $satir
    $projeKlasoru = Join-Path $CiktiKlasoru (ConvertTo-GuvenliAd $k.Proje)
    $temelAd = $adBilgi.Ad
    $dosyaAdi = $temelAd + $adBilgi.Uzanti
    $anahtar = (Join-Path $projeKlasoru $dosyaAdi).ToLowerInvariant()
    $n = 2
    while ($kullanilanAdlar.ContainsKey($anahtar)) {
        $dosyaAdi = "$temelAd`_$n" + $adBilgi.Uzanti
        $anahtar = (Join-Path $projeKlasoru $dosyaAdi).ToLowerInvariant()
        $n++
    }
    $kullanilanAdlar[$anahtar] = $true
    $not = @()
    if ($excelOkundu -and -not $satir) { $not += "excel_satiri_yok" }
    if ($satir -and -not $satir.AnaSutun) { $not += "link_excelde_baska_sutunda" }
    if ($satir -and $satir.Sayfa -ne $k.Proje) { $not += "excel_sayfasi_farkli:$($satir.Sayfa)" }
    if ($k.KullaniciGuven -eq "belirsiz" -and $k.IkinciAday) { $not += "diger_aday:$($k.IkinciAday)" }
    $plan.Add([pscustomobject]@{
        Tarih          = $k.Zaman.ToString("yyyy-MM-dd HH:mm:ss", $Inv)
        Proje          = $k.Proje
        Kategori       = $adBilgi.Kategori
        KullaniciAdi   = $k.KullaniciAdi
        KullaniciId    = $k.KullaniciId
        KullaniciGuven = $k.KullaniciGuven
        PersonelKodu   = $(if ($satir) { $satir.Personel } else { "" })
        UyeID          = $(if ($satir) { $satir.UyeId } else { "" })
        AnaUyeID       = $(if ($satir) { $satir.AnaId } else { "" })
        Tip            = $(if ($satir) { $satir.Tip } else { "" })
        GyazoLinki     = $k.Link
        GyazoId        = $k.GyazoId
        ExcelSayfa     = $(if ($satir) { $satir.Sayfa } else { "" })
        ExcelSatir     = $(if ($satir) { $satir.Satir } else { "" })
        DosyaAdi       = $dosyaAdi
        DosyaYolu      = (Join-Path $projeKlasoru $dosyaAdi)
        Durum          = "listelendi"
        Not            = ($not -join "; ")
    })
}
if ($excelOkundu) { Write-Bilgi "  Excel satiri bulunan kayit: $excelEslesen / $($plan.Count) (bulunamayanlar sadece log bilgisiyle adlandirilir)" }

function Save-Indeks {
    # Turkce Excel ';' ayiracini kullanir; UTF8 (BOM'lu) ile Turkce karakterler dogru acilir.
    $utf8Bom = New-Object System.Text.UTF8Encoding $true
    $csv = @($plan | ConvertTo-Csv -NoTypeInformation -Delimiter ';')
    if ($csv.Count -eq 0) { $csv = @("Tarih;Proje;Kategori;KullaniciAdi;KullaniciId;KullaniciGuven;PersonelKodu;UyeID;AnaUyeID;Tip;GyazoLinki;GyazoId;ExcelSayfa;ExcelSatir;DosyaAdi;DosyaYolu;Durum;Not") }
    [System.IO.File]::WriteAllLines($IndeksDosyasi, [string[]]$csv, $utf8Bom)
}
Save-Indeks
Write-Bilgi "  Indeks yazildi: $IndeksDosyasi ($($plan.Count) kayit)"

if ($SadeceListele -or $plan.Count -eq 0) {
    Write-Bilgi "Bitti (sadece listeleme)."
    return
}

# ==================== 6) INDIR ====================
function Test-GorselDosyasi($yol) {
    try {
        $fi = Get-Item $yol
        if ($fi.Length -lt 100) { return $false }
        $bayt = New-Object byte[] 8
        $st = [System.IO.File]::OpenRead($yol)
        try { [void]$st.Read($bayt, 0, 8) } finally { $st.Dispose() }
        if ($bayt[0] -eq 0xFF -and $bayt[1] -eq 0xD8) { return $true }                                   # JPEG
        if ($bayt[0] -eq 0x89 -and $bayt[1] -eq 0x50 -and $bayt[2] -eq 0x4E -and $bayt[3] -eq 0x47) { return $true }  # PNG
        if ($bayt[0] -eq 0x47 -and $bayt[1] -eq 0x49 -and $bayt[2] -eq 0x46) { return $true }             # GIF
        if ($bayt[0] -eq 0x52 -and $bayt[1] -eq 0x49 -and $bayt[2] -eq 0x46 -and $bayt[3] -eq 0x46) { return $true }  # WEBP
        return $false
    } catch { return $false }
}

function Get-HttpDurumKodu($hata) {
    try {
        $yanit = $hata.Exception.Response
        if ($yanit) { return [int]$yanit.StatusCode }
    } catch {}
    return 0
}

$script:PngDestek = $null
function ConvertTo-PngDosyasi($kaynak, $hedefPng) {
    # Windows'ta GDI+ (System.Drawing) ile JPEG -> PNG. Basarisizsa $false doner, dosya dokunulmadan kalir.
    # Not: tipler yansima (reflection) ile cozulur; boylece System.Drawing olmayan ortamlarda hata try icinde yakalanir.
    if ($script:PngDestek -eq $false) { return $false }
    try {
        Add-Type -AssemblyName System.Drawing -ErrorAction Stop
        $asm = [System.AppDomain]::CurrentDomain.GetAssemblies() | Where-Object { $_.GetName().Name -in @("System.Drawing", "System.Drawing.Common") } | Select-Object -First 1
        if (-not $asm) { throw "System.Drawing yuklenemedi" }
        $imgType = $asm.GetType("System.Drawing.Image", $true)
        $bmpType = $asm.GetType("System.Drawing.Bitmap", $true)
        $fmtType = $asm.GetType("System.Drawing.Imaging.ImageFormat", $true)
        $pngFmt  = $fmtType.GetProperty("Png").GetValue($null, $null)
        $img = $imgType.GetMethod("FromFile", [type[]]@([string])).Invoke($null, @([string]$kaynak))
        try {
            $bmp = [System.Activator]::CreateInstance($bmpType, @($img))
            try { $bmp.Save([string]$hedefPng, $pngFmt) } finally { $bmp.Dispose() }
        } finally { $img.Dispose() }
        if (-not (Test-GorselDosyasi $hedefPng)) { Remove-Item $hedefPng -Force -ErrorAction SilentlyContinue; return $false }
        $script:PngDestek = $true
        return $true
    } catch {
        $msg = $_.Exception.Message
        if ($_.Exception.InnerException) { $msg = $_.Exception.InnerException.Message }
        if ($null -eq $script:PngDestek) { Write-Bilgi "  ! PNG donusumu bu makinede calismadi ($msg); dosyalar .jpg olarak kaydedilecek."; $script:PngDestek = $false }
        Remove-Item $hedefPng -Force -ErrorAction SilentlyContinue
        return $false
    }
}
function Complete-GorselDosyasi($gecici, $hedef) {
    if ($Format -eq "png") {
        if (ConvertTo-PngDosyasi $gecici $hedef) { Remove-Item $gecici -Force -ErrorAction SilentlyContinue; return $hedef }
        $jpg = [System.IO.Path]::ChangeExtension($hedef, ".jpg")
        Move-Item $gecici $jpg -Force
        return $jpg
    }
    Move-Item -Path $gecici -Destination $hedef -Force
    return $hedef
}
function Find-MevcutGorsel($hedef) {
    foreach ($aday in @($hedef, [System.IO.Path]::ChangeExtension($hedef, ".jpg"), [System.IO.Path]::ChangeExtension($hedef, ".png"))) {
        if ((Test-Path $aday) -and (Test-GorselDosyasi $aday)) { return $aday }
    }
    return $null
}
# Gyazo'nun gorsel sunucusu (i.gyazo.com) tarayici olmayan istekleri 503/403 ile reddedebiliyor;
# istekleri normal bir tarayici gibi tanitiriz.
$script:TarayiciUA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
$script:TarayiciBaslik = @{ "Accept" = "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"; "Accept-Language" = "tr-TR,tr;q=0.9,en;q=0.8"; "Referer" = "https://gyazo.com/" }
function Invoke-GorselIndir($url, $hedef) {
    # Donus: @{ Durum = "indirildi" | "indirildi_jpg" | "gyazo_silinmis" | "gyazo_503" (gecici/engel) | "hata: ..."; Yol = son dosya yolu; Kod = HTTP kodu }
    $gecici = "$hedef.indiriliyor"
    for ($deneme = 1; $deneme -le $DenemeSayisi; $deneme++) {
        try {
            Remove-Item $gecici -Force -ErrorAction SilentlyContinue
            Invoke-WebRequest -Uri $url -OutFile $gecici -UseBasicParsing -TimeoutSec $ZamanAsimiSn -UserAgent $script:TarayiciUA -Headers $script:TarayiciBaslik | Out-Null
            if (-not (Test-GorselDosyasi $gecici)) { throw "indirilen dosya gorsel degil (bos ya da HTML sayfasi)" }
            $son = Complete-GorselDosyasi $gecici $hedef
            return @{ Durum = $(if ($son -ne $hedef) { "indirildi_jpg" } else { "indirildi" }); Yol = $son; Kod = 200 }
        } catch {
            $kod = Get-HttpDurumKodu $_
            Remove-Item $gecici -Force -ErrorAction SilentlyContinue
            if ($kod -eq 404 -or $kod -eq 410) { return @{ Durum = "gyazo_silinmis"; Yol = $null; Kod = $kod } }
            if ($kod -eq 503 -or $kod -eq 502 -or $kod -eq 429 -or $kod -eq 403) {
                # Sunucu gecici olarak vermiyor ya da engelliyor: biraz bekle, olmazsa bu kodu bildir (ust uste gelirse tarama durur)
                if ($deneme -ge 2) { return @{ Durum = "gyazo_$kod"; Yol = $null; Kod = $kod } }
                Start-Sleep -Seconds 4
                continue
            }
            if ($deneme -ge $DenemeSayisi) { return @{ Durum = "hata: $($_.Exception.Message)"; Yol = $null; Kod = $kod } }
            Start-Sleep -Seconds (2 * $deneme)
        }
    }
    return @{ Durum = "hata: bilinmeyen"; Yol = $null; Kod = 0 }
}

Write-Bilgi "Indirme basliyor: $($plan.Count) gorsel"
$sayac = @{ indirildi = 0; kopyalandi = 0; zaten_var = 0; gyazo_silinmis = 0; hata = 0 }
$inmisDosya = @{}   # gyazoId -> yerel dosya (ayni gorsel birden fazla kayitta kullanilmissa bir kez indir, digerlerine kopyala)
$ardisikGecici = 0  # ust uste 503/403 gibi "sunucu vermiyor" cevabi; 5 olunca saatlerce bosuna denemek yerine durulur
$erkenDurdu = $false
$i = 0
foreach ($p in $plan) {
    $i++
    $klasor = Split-Path -Parent $p.DosyaYolu
    if (-not (Test-Path $klasor)) { New-Item -ItemType Directory -Path $klasor -Force | Out-Null }
    $mevcut = $(if ($Yeniden) { $null } else { Find-MevcutGorsel $p.DosyaYolu })
    if ($mevcut) {
        $p.Durum = "zaten_var"; $sayac.zaten_var++
        $p.DosyaYolu = $mevcut; $p.DosyaAdi = Split-Path $mevcut -Leaf
        $inmisDosya[$p.GyazoId] = $mevcut
    } elseif ($inmisDosya.ContainsKey($p.GyazoId) -and (Test-Path $inmisDosya[$p.GyazoId])) {
        $kaynak = $inmisDosya[$p.GyazoId]
        $hedefKopya = [System.IO.Path]::ChangeExtension($p.DosyaYolu, [System.IO.Path]::GetExtension($kaynak))
        Copy-Item -Path $kaynak -Destination $hedefKopya -Force
        $p.DosyaYolu = $hedefKopya; $p.DosyaAdi = Split-Path $hedefKopya -Leaf
        $p.Durum = "kopyalandi"; $sayac.kopyalandi++
        if ($p.Not) { $p.Not += "; " }
        $p.Not += "ayni_gorsel_baska_kayitta_da_var"
    } else {
        $sonuc = Invoke-GorselIndir $p.GyazoLinki $p.DosyaYolu
        $p.Durum = $sonuc.Durum
        if ($sonuc.Yol) { $sayac.indirildi++; $p.DosyaYolu = $sonuc.Yol; $p.DosyaAdi = Split-Path $sonuc.Yol -Leaf; $inmisDosya[$p.GyazoId] = $sonuc.Yol; $ardisikGecici = 0 }
        elseif ($sonuc.Durum -eq "gyazo_silinmis") { $sayac.gyazo_silinmis++; $ardisikGecici = 0; Write-Bilgi "  ! Gyazo'da yok (404): $($p.GyazoLinki)" }
        elseif ($sonuc.Durum -like "gyazo_*") { $sayac.hata++; $ardisikGecici++; Write-Bilgi "  ! $($p.GyazoLinki) -> Gyazo sunucusu vermedi (HTTP $($sonuc.Kod))" }
        else { $sayac.hata++; Write-Bilgi "  ! $($p.GyazoLinki) -> $($sonuc.Durum)" }
        if ($ardisikGecici -ge 5) {
            Write-Bilgi "========================================"
            Write-Bilgi "DURDURULDU: Gyazo gorsel sunucusu (i.gyazo.com) ust uste $ardisikGecici istege HTTP $($sonuc.Kod) dondu."
            Write-Bilgi "Gyazo su anda scriptlere gorsel vermiyor (bakim ya da bot korumasi). Bir sure sonra tekrar calistirin;"
            Write-Bilgi "inmis olanlar atlanir. Gyazo'ya bagimli olmadan almak icin Telegram surumunu (Gorselleri-Cek.ps1) kullanin."
            $erkenDurdu = $true
            break
        }
        if ($BeklemeMs -gt 0) { Start-Sleep -Milliseconds $BeklemeMs }
    }
    if (($i % 25) -eq 0 -or $i -eq $plan.Count) {
        Write-Bilgi "  $i / $($plan.Count)  (indirildi=$($sayac.indirildi) kopyalandi=$($sayac.kopyalandi) zaten_var=$($sayac.zaten_var) silinmis=$($sayac.gyazo_silinmis) hata=$($sayac.hata))"
        Save-Indeks
    }
}
Save-Indeks
Write-Bilgi "========================================"
Write-Bilgi "$(if ($erkenDurdu) { 'YARIM KALDI (Gyazo vermedi).' } else { 'BITTI.' }) indirildi=$($sayac.indirildi) kopyalandi=$($sayac.kopyalandi) zaten_var=$($sayac.zaten_var) gyazo_silinmis=$($sayac.gyazo_silinmis) hata=$($sayac.hata)"
Write-Bilgi "Klasor : $CiktiKlasoru"
Write-Bilgi "Indeks : $IndeksDosyasi  (Durum ve KullaniciGuven sutunlarina bakin)"
if ($sayac.hata -gt 0) { Write-Bilgi "Hatali olanlar icin scripti tekrar calistirin; inmis olanlar atlanir." }
Write-Host ""
Write-Host "Tamamlandi. Gorseller: $CiktiKlasoru" -ForegroundColor Green
try { if (-not $Sessiz -and (Test-Path $CiktiKlasoru)) { Start-Process explorer.exe $CiktiKlasoru } } catch {}
} catch {
    Write-Host ""
    Write-Host "HATA: $($_.Exception.Message)" -ForegroundColor Red
    try { Add-Content -Path $CalismaLogu -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] HATA: $($_.Exception.Message) | $($_.InvocationInfo.PositionMessage)" -Encoding UTF8 } catch {}
    Write-Host "Ayrintili kayit: $CalismaLogu"
} finally {
    Wait-Kapat
}
