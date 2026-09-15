<#
    TELEGRAM KANIT BOTU - EKRAN GORUNTULERINI CEK (tek dosya)

    Nasil: Bu dosyaya SAG TIK -> "PowerShell ile calistir". Baska bir sey gerekmez.
      * Bot klasorunu kendisi bulur (bu dosya bot klasorundeyse oradan; degilse
        OneDrive\telegramkant gibi bilinen yerlerde arar).
      * config.json'daki TELEGRAM_TOKEN ve ADMIN_IDS'i kullanir; hicbir seyi degistirmez.
      * Son 2 ayin fotograflarini dogrudan TELEGRAM'dan ceker (Gyazo kullanmaz),
        PNG olarak  <bot klasoru>\telegram_gorseller\<PROJE>\  altina koyar.
      * Dosya adi: tarih_kullanici_proje_kategori_Ppersonel_UuyeID_AanaID_tip_mNo.png
      * Kesilirse tekrar calistirin; inmis olanlar atlanir.
      * Bitince pencere acik kalir, sonucu gosterir. indeks.csv her fotografin listesidir.

    Istege bagli (yazmaniza gerek yok):  -SonAy 3   -Format jpg   -Baslangic 2026-08-01
#>
[CmdletBinding()]
param(
    [string]$BotKlasoru = $PSScriptRoot,
    [string]$Token,
    [string]$HedefChatId,
    [string]$CacheDosyasi,
    [string]$LogDosyasi,
    [string]$ExcelDosyasi,
    [string]$KullaniciDosyasi,
    [string]$YedekKlasoru,
    [string]$CiktiKlasoru,
    [int]$SonAy = 2,
    [string]$Baslangic,
    [string]$Bitis,
    [string]$AdSablonu = "{tarih}_{kullanici}_{proje}_{kategori}_{personel}_{uyeid}_{anaid}_{tip}",
    [switch]$Zenginlestir = $true,
    [switch]$SadeceTara,
    [switch]$Yeniden,
    [switch]$KopyaBirak,
    [int]$EskiDurma = 400,
    [int]$BeklemeMs = 350,
    [int]$DenemeSayisi = 3,
    [int]$ZamanAsimiSn = 60,
    [ValidateSet("png","jpg")] [string]$Format = "png",
    [string]$ApiTaban = "https://api.telegram.org",
    [switch]$Sessiz
)

Set-StrictMode -Version 2
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Inv = [System.Globalization.CultureInfo]::InvariantCulture
try { [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor [System.Net.SecurityProtocolType]::Tls12 } catch {}

function Wait-Kapat {
    if ($Sessiz) { return }
    Write-Host ""
    Write-Host "Kapatmak icin bir tusa basin..." -ForegroundColor Yellow
    try { $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown") } catch { try { $null = Read-Host } catch {} }
}
function Find-BotKlasoru($ilk) {
    # 1) verilen / scriptin oldugu klasor  2) bilinen yerler  3) kullanici profilinde sinirli arama
    $adaylar = New-Object System.Collections.Generic.List[string]
    if ($ilk) { $adaylar.Add($ilk) }
    $adaylar.Add((Get-Location).Path)
    $profil = $(if ($env:USERPROFILE) { $env:USERPROFILE } else { $HOME })
    foreach ($k in @("OneDrive - Park\telegramkant", "OneDrive\telegramkant", "telegramkant", "Desktop\telegramkant", "Documents\telegramkant")) { $adaylar.Add((Join-Path $profil $k)) }
    try { foreach ($d in (Get-ChildItem $profil -Directory -Filter "OneDrive*" -ErrorAction SilentlyContinue)) { $adaylar.Add((Join-Path $d.FullName "telegramkant")) } } catch {}
    foreach ($a in $adaylar) { if ($a -and (Test-Path (Join-Path $a "telegram_cache.txt")) -and (Test-Path (Join-Path $a "config.json"))) { return (Resolve-Path $a).Path } }
    try {
        $bulunan = Get-ChildItem $profil -Recurse -Depth 4 -Filter "telegram_cache.txt" -File -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($bulunan -and (Test-Path (Join-Path $bulunan.DirectoryName "config.json"))) { return $bulunan.DirectoryName }
    } catch {}
    return $null
}

$Host.UI.RawUI.WindowTitle = "Telegram gorselleri cekiliyor"
Write-Host ""
Write-Host "=== TELEGRAM KANIT BOTU - GORSELLERI CEK ===" -ForegroundColor Cyan
$bulunanKlasor = Find-BotKlasoru $BotKlasoru
if (-not $bulunanKlasor) {
    Write-Host ""
    Write-Host "Bot klasoru bulunamadi." -ForegroundColor Red
    Write-Host "Bu dosyayi botun klasorune (bot_log.txt, telegram_cache.txt ve config.json'un oldugu yere) kopyalayip oradan calistirin."
    Wait-Kapat
    exit 1
}
$BotKlasoru = $bulunanKlasor
Write-Host "Bot klasoru : $BotKlasoru"
try {
if (-not $CacheDosyasi)     { $CacheDosyasi     = Join-Path $BotKlasoru "telegram_cache.txt" }
if (-not $LogDosyasi)       { $LogDosyasi       = Join-Path $BotKlasoru "bot_log.txt" }
if (-not $ExcelDosyasi)     { $ExcelDosyasi     = Join-Path $BotKlasoru "telegrambot_gyazo.xlsx" }
if (-not $KullaniciDosyasi) { $KullaniciDosyasi = Join-Path $BotKlasoru "kullanicilar.json" }
if (-not $YedekKlasoru)     { $YedekKlasoru     = Join-Path $BotKlasoru "backups" }
if (-not $CiktiKlasoru)     { $CiktiKlasoru     = Join-Path $BotKlasoru "telegram_gorseller" }
$ConfigDosyasi = Join-Path $BotKlasoru "config.json"

New-Item -ItemType Directory -Path $CiktiKlasoru -Force | Out-Null
$CiktiKlasoru   = (Resolve-Path $CiktiKlasoru).Path
$IndeksDosyasi  = Join-Path $CiktiKlasoru "indeks.csv"
$CalismaLogu    = Join-Path $CiktiKlasoru "indirme_log.txt"

function Write-Bilgi($mesaj) {
    $satir = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $mesaj"
    Write-Host $satir
    try { Add-Content -Path $CalismaLogu -Value $satir -Encoding UTF8 } catch {}
}
function Get-Prop($obj, $name) {
    # StrictMode -Version 2 altinda olmayan uyeye erisim 5.1'de HATA verir; guvenli erisim.
    if ($null -eq $obj) { return $null }
    try {
        $p = $obj.PSObject.Properties[$name]
        if ($p) { return $p.Value }
    } catch {}
    return $null
}

# Token / hedef
if (-not $Token -or -not $HedefChatId) {
    $cfg = $null
    if (Test-Path $ConfigDosyasi) { try { $cfg = [System.IO.File]::ReadAllText($ConfigDosyasi, [System.Text.Encoding]::UTF8) | ConvertFrom-Json } catch { Write-Bilgi "! config.json okunamadi: $($_.Exception.Message)" } }
    if (-not $Token -and $cfg) { $Token = [string](Get-Prop $cfg "TELEGRAM_TOKEN") }
    if (-not $HedefChatId -and $cfg) {
        # Istege bagli: config.json icine "KURTARMA_HEDEF_CHAT_ID": "-100..." yazarsaniz dokme sohbeti o olur.
        $HedefChatId = [string](Get-Prop $cfg "KURTARMA_HEDEF_CHAT_ID")
        if (-not $HedefChatId) { $ids = Get-Prop $cfg "ADMIN_IDS"; if ($ids) { $HedefChatId = [string](@($ids)[0]) } }
    }
}
if (-not (Test-Path $CacheDosyasi)) { throw "telegram_cache.txt bulunamadi ($CacheDosyasi). Bu dosyalari BOT KLASORUNE (bot_log.txt ve telegram_cache.txt'nin oldugu yere) cikarip oradan calistirin ya da -BotKlasoru verin." }
if (-not $Token)       { throw "Telegram token yok. config.json icinde TELEGRAM_TOKEN olmali (bot klasorundeki config.json) ya da -Token verin." }
if (-not $HedefChatId) { throw "HedefChatId yok. config.json icinde ADMIN_IDS ya da KURTARMA_HEDEF_CHAT_ID olmali, ya da -HedefChatId verin." }
if ($Token -like "BURAYA_*") { throw "config.json icindeki TELEGRAM_TOKEN doldurulmamis." }

$ApiTaban = $ApiTaban.TrimEnd("/")
$BitisTarihi     = if ($Bitis) { [datetime]::Parse($Bitis, $Inv) } else { [datetime]::MaxValue }
if ($Bitis -and $BitisTarihi.TimeOfDay -eq [timespan]::Zero) { $BitisTarihi = $BitisTarihi.AddDays(1).AddTicks(-1) }
$BaslangicTarihi = if ($Baslangic) { [datetime]::Parse($Baslangic, $Inv) } else { [datetime]::Today.AddMonths(-$SonAy) }

Write-Bilgi "========================================"
Write-Bilgi "Telegram gorsel cekme basliyor (bot acik olsa da olur; getUpdates kullanilmaz)"
Write-Bilgi "  Cache  : $CacheDosyasi"
Write-Bilgi "  Hedef  : $HedefChatId (yonlendirme dokme sohbeti)"
Write-Bilgi "  Cikti  : $CiktiKlasoru"
Write-Bilgi "  Aralik : $($BaslangicTarihi.ToString('yyyy-MM-dd', $Inv)) -> $(if ($BitisTarihi -eq [datetime]::MaxValue) { 'simdi' } else { $BitisTarihi.ToString('yyyy-MM-dd', $Inv) }) (orijinal gonderim tarihine gore)"
Write-Bilgi "  Format : $Format"
Write-Bilgi "  API    : $ApiTaban"
if ($SadeceTara) { Write-Bilgi "  MOD    : sadece tara (indirme yok)" }

# ==================== ORTAK YARDIMCILAR ====================
function ConvertTo-GuvenliAd($metin, [int]$maksUzunluk = 40) {
    if ($null -eq $metin) { return "" }
    $s = ([string]$metin).Trim()
    if ($s.Length -eq 0) { return "" }
    $s = $s -replace "'", ""
    $cift = @{
        [char]0x00E7='c'; [char]0x00C7='C'; [char]0x011F='g'; [char]0x011E='G'
        [char]0x0131='i'; [char]0x0130='I'; [char]0x00F6='o'; [char]0x00D6='O'
        [char]0x015F='s'; [char]0x015E='S'; [char]0x00FC='u'; [char]0x00DC='U'
    }
    $sb = New-Object System.Text.StringBuilder
    foreach ($ch in $s.ToCharArray()) { if ($cift.ContainsKey($ch)) { [void]$sb.Append($cift[$ch]) } else { [void]$sb.Append($ch) } }
    $s = $sb.ToString().Normalize([System.Text.NormalizationForm]::FormD)
    $s = [regex]::Replace($s, '\p{Mn}', '')
    $s = [regex]::Replace($s, '\s+', '-')
    $s = [regex]::Replace($s, '[^A-Za-z0-9._-]', '')
    $s = [regex]::Replace($s, '-{2,}', '-')
    $s = $s.Trim('-', '.', '_')
    if ($s.Length -gt $maksUzunluk) { $s = $s.Substring(0, $maksUzunluk) }
    return $s
}
function ConvertTo-Tarih($metin) {
    if ([string]::IsNullOrWhiteSpace([string]$metin)) { return $null }
    $fmt = @("yyyy-MM-dd HH:mm:ss","yyyy-MM-dd HH:mm","yyyy-MM-dd","dd.MM.yyyy HH:mm:ss","dd.MM.yyyy HH:mm","dd.MM.yyyy")
    $r = [datetime]::MinValue
    if ([datetime]::TryParseExact([string]$metin, [string[]]$fmt, $Inv, [System.Globalization.DateTimeStyles]::None, [ref]$r)) { return $r }
    try { return [datetime]::Parse([string]$metin, $Inv) } catch { return $null }
}
function Format-SayiMetni($ham) {
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
$epoch = [datetime]::new(1970,1,1,0,0,0,[System.DateTimeKind]::Utc)
function ConvertFrom-Unix([long]$sn) {
    # Telegram tarihleri UTC; yerel saate cevir (log/Excel yerel saatle yazilmis).
    return $epoch.AddSeconds($sn).ToLocalTime()
}

# ==================== ZENGINLESTIRME INDEKSI (log + Excel) ====================
# Kurtarilan foto (gercek kullaniciID + orijinal tarih) -> ayni kullanicinin, tarihe en yakin
# "Kaydedildi" kaydi -> proje/kategori (+ Excel'den personel/uye).
$zenginKullanici = @{}   # kullaniciId -> List[ kayit ]
if ($Zenginlestir) {
    Write-Bilgi "Zenginlestirme icin log + Excel okunuyor..."
    try {
        # --- log ---
        $rxSatir = [regex]'^\uFEFF?\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*(.*?)\s*$'
        $rxMesaj = [regex]'^Mesaj geldi: (.+) \(ID: (\d+)\)$'
        $rxKayit = [regex]'^Kaydedildi (?:->|\u2192) \[([^\]]+)\] \[([^\]]+)\] (\S+)$'
        $olaylar = New-Object System.Collections.Generic.List[object]
        if (Test-Path $LogDosyasi) {
            $fs = New-Object System.IO.FileStream($LogDosyasi, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
            $sr = New-Object System.IO.StreamReader($fs, [System.Text.Encoding]::UTF8, $true)
            try {
                while ($null -ne ($satir = $sr.ReadLine())) {
                    $m = $rxSatir.Match($satir); if (-not $m.Success) { continue }
                    $g = $m.Groups[2].Value
                    $mm = $rxMesaj.Match($g)
                    if ($mm.Success) { $olaylar.Add([pscustomobject]@{ T="msg"; Z=[datetime]::ParseExact($m.Groups[1].Value,"yyyy-MM-dd HH:mm:ss",$Inv); Id=$mm.Groups[2].Value; Ad=$mm.Groups[1].Value }); continue }
                    $mk = $rxKayit.Match($g)
                    if ($mk.Success) { $olaylar.Add([pscustomobject]@{ T="kay"; Z=[datetime]::ParseExact($m.Groups[1].Value,"yyyy-MM-dd HH:mm:ss",$Inv); Proje=$mk.Groups[1].Value.ToUpperInvariant(); Kat=$mk.Groups[2].Value.ToUpperInvariant(); Link=$mk.Groups[3].Value })
                    }
                }
            } finally { $sr.Dispose(); $fs.Dispose() }
        }
        # --- kesin kullanici (kullanicilar.json + yedekler) ---
        $kesin = @{}
        $jf = New-Object System.Collections.Generic.List[string]
        if (Test-Path $KullaniciDosyasi) { $jf.Add($KullaniciDosyasi) }
        if (Test-Path $YedekKlasoru) { Get-ChildItem $YedekKlasoru -Recurse -Filter "kullanicilar.json" -ErrorAction SilentlyContinue | ForEach-Object { $jf.Add($_.FullName) } }
        foreach ($f in $jf) {
            try {
                $ham = [System.IO.File]::ReadAllText($f, [System.Text.Encoding]::UTF8)
                if ([string]::IsNullOrWhiteSpace($ham)) { continue }
                foreach ($p in ($ham | ConvertFrom-Json).PSObject.Properties) {
                    $t = [string](Get-Prop $p.Value "son_kayit_tarihi"); $pr = [string](Get-Prop $p.Value "son_kayit_proje")
                    if ($t -and $pr) { $kesin["$t|$($pr.ToUpperInvariant())"] = [string]$p.Name }
                }
            } catch {}
        }
        # --- attribution (Gyazo scriptiyle ayni: kesin + tuketim, geriye donuk) ---
        $tuk = @{}; $sira = 0
        $kayitlar = New-Object System.Collections.Generic.List[object]
        foreach ($o in $olaylar) {
            $sira++
            if ($o.T -eq "msg") { if (-not $tuk.ContainsKey($o.Id)) { $tuk[$o.Id]=New-Object System.Collections.Generic.List[int] }; $tuk[$o.Id].Add($sira); continue }
            $sec = $null
            $kk = $null
            for ($d=0; $d -le 5; $d++) { $k=$o.Z.AddSeconds(-$d).ToString("yyyy-MM-dd HH:mm:ss",$Inv)+"|"+$o.Proje; if ($kesin.ContainsKey($k)) { $kk=@{Id=$kesin[$k];Key=$k}; break } }
            if ($kk) { $sec=$kk.Id; $kesin.Remove($kk.Key) }
            else {
                $ad=@(); foreach ($kid in @($tuk.Keys)) { if ($tuk[$kid].Count -ge 3) { $ad += [pscustomobject]@{Id=$kid;S=$tuk[$kid][$tuk[$kid].Count-1]} } }
                if ($ad.Count -eq 0) { foreach ($kid in @($tuk.Keys)) { if ($tuk[$kid].Count -ge 1) { $ad += [pscustomobject]@{Id=$kid;S=$tuk[$kid][$tuk[$kid].Count-1]} } } }
                if ($ad.Count -gt 0) { $sec = (@($ad | Sort-Object S -Descending))[0].Id }
            }
            if ($sec -and $tuk.ContainsKey($sec)) { $tuk[$sec].Clear() }
            $kayitlar.Add([pscustomobject]@{ Zaman=$o.Z; Proje=$o.Proje; Kat=$o.Kat; Link=$o.Link; KullaniciId=$sec; GyazoId=([regex]::Match([string]$o.Link,'([0-9a-f]{32})').Groups[1].Value) })
        }
        # --- Excel: gyazoId -> (personel,uye,ana,tip) ; COM'suz zip+regex ---
        $excel = @{}
        if (Test-Path $ExcelDosyasi) {
            $kopya = Join-Path ([System.IO.Path]::GetTempPath()) ("tgrec_"+[guid]::NewGuid().ToString("N")+".xlsx")
            $zip = $null
            try {
                Copy-Item $ExcelDosyasi $kopya -Force
                Add-Type -AssemblyName System.IO.Compression.FileSystem
                $zip = [System.IO.Compression.ZipFile]::OpenRead($kopya)
                function Read-Zip($zip,$ad) { $e=$zip.GetEntry($ad); if (-not $e) { $e=$zip.Entries | Where-Object { $_.FullName -ieq $ad } | Select-Object -First 1 }; if (-not $e) { return $null }; $st=$e.Open(); $rd=New-Object System.IO.StreamReader($st,[System.Text.Encoding]::UTF8); try { return $rd.ReadToEnd() } finally { $rd.Dispose(); $st.Dispose() } }
                $ss = New-Object System.Collections.Generic.List[string]
                $ssXml = Read-Zip $zip "xl/sharedStrings.xml"
                if ($ssXml) { foreach ($si in [regex]::Matches($ssXml,'<si>(.*?)</si>','Singleline')) { $sb=New-Object System.Text.StringBuilder; foreach ($tm in [regex]::Matches($si.Groups[1].Value,'<t(?:\s[^>]*)?>(.*?)</t>','Singleline')) { [void]$sb.Append($tm.Groups[1].Value) }; $ss.Add([System.Net.WebUtility]::HtmlDecode($sb.ToString())) } }
                $ssG = @{}; for ($i=0;$i -lt $ss.Count;$i++) { $gm=[regex]::Match($ss[$i],'([0-9a-f]{32})'); if ($gm.Success -and $ss[$i] -match 'gyazo') { $ssG[$i]=$gm.Groups[1].Value.ToLowerInvariant() } }
                $relXml = Read-Zip $zip "xl/_rels/workbook.xml.rels"; $wbXml = Read-Zip $zip "xl/workbook.xml"
                $rel=@{}; foreach ($r in [regex]::Matches($relXml,'<Relationship\b[^>]*>')) { $idm=[regex]::Match($r.Value,'\bId="([^"]*)"'); $tg=[regex]::Match($r.Value,'\bTarget="([^"]*)"'); if ($idm.Success -and $tg.Success) { $h=$tg.Groups[1].Value; if ($h.StartsWith("/")) { $h=$h.TrimStart("/") } else { $h="xl/"+$h }; $rel[$idm.Groups[1].Value]=$h } }
                $sheets=@(); foreach ($s in [regex]::Matches($wbXml,'<sheet\b[^>]*>')) { $nm=[regex]::Match($s.Value,'\bname="([^"]*)"'); $rid=[regex]::Match($s.Value,'\br:id="([^"]*)"'); if ($nm.Success -and $rid.Success -and $rel.ContainsKey($rid.Groups[1].Value)) { $sheets += [pscustomobject]@{ Ad=[System.Net.WebUtility]::HtmlDecode($nm.Groups[1].Value); Dosya=$rel[$rid.Groups[1].Value] } } }
                $rxH=[regex]'<c r="([A-F])(\d+)"([^>]*?)(?:/>|>(.*?)</c>)'
                $rxT=[regex]'<c r="[A-Z]+(\d+)"[^>]*\bt="s"[^>]*>\s*<v>(\d+)</v>'
                foreach ($sf in $sheets) {
                    if ($sf.Ad -in @("ONAYLILAR","HATALI")) { continue }
                    $sx = Read-Zip $zip $sf.Dosya; if (-not $sx) { continue }
                    $rows=@{}
                    foreach ($hm in $rxH.Matches($sx)) {
                        $sut=$hm.Groups[1].Value; $sat=[int]$hm.Groups[2].Value; if ($sat -le 1) { continue }
                        $ic=$hm.Groups[4].Value; if (-not $ic) { continue }
                        $tur=[regex]::Match($hm.Groups[3].Value,'\bt="(\w+)"'); $tur=$(if ($tur.Success){$tur.Groups[1].Value}else{"n"})
                        $val=""
                        if ($tur -eq "inlineStr") { $tm=[regex]::Match($ic,'<t(?:\s[^>]*)?>(.*?)</t>','Singleline'); if ($tm.Success){$val=[System.Net.WebUtility]::HtmlDecode($tm.Groups[1].Value)} }
                        else { $vm=[regex]::Match($ic,'<v>(.*?)</v>','Singleline'); if (-not $vm.Success){continue}; $v=$vm.Groups[1].Value; switch ($tur) { "s" {$ix=[int]$v; if ($ix -ge 0 -and $ix -lt $ss.Count){$val=$ss[$ix]}} "str" {$val=[System.Net.WebUtility]::HtmlDecode($v)} default {$val=Format-SayiMetni $v} } }
                        if (-not $rows.ContainsKey($sat)) { $rows[$sat]=@{} }
                        $rows[$sat][$sut]=[string]$val
                    }
                    $rowId=@{}
                    foreach ($tm in $rxT.Matches($sx)) { $ix=[int]$tm.Groups[2].Value; if ($ssG.ContainsKey($ix)) { $sat=[int]$tm.Groups[1].Value; if (-not $rowId.ContainsKey($sat)){$rowId[$sat]=New-Object System.Collections.Generic.List[string]}; $rowId[$sat].Add($ssG[$ix]) } }
                    foreach ($sat in $rowId.Keys) {
                        $d = $(if ($rows.ContainsKey($sat)){$rows[$sat]}else{@{}})
                        foreach ($gid in ($rowId[$sat] | Select-Object -Unique)) {
                            if (-not $excel.ContainsKey($gid)) {
                                $excel[$gid]=[pscustomobject]@{ Personel=$(if($d.ContainsKey("A")){$d["A"]}else{""}); UyeId=$(if($d.ContainsKey("B")){$d["B"]}else{""}); AnaId=$(if($d.ContainsKey("C")){$d["C"]}else{""}); Tip=$(if($d.ContainsKey("D")){$d["D"]}else{""}); Kat=$(if($d.ContainsKey("F")){$d["F"]}else{""}) }
                            }
                        }
                    }
                }
            } catch { Write-Bilgi "  ! Excel okunamadi (zenginlestirme kisitli): $($_.Exception.Message)" }
            finally { if ($zip) { $zip.Dispose() }; Remove-Item $kopya -Force -ErrorAction SilentlyContinue }
        }
        # kullaniciId -> kayitlar (Excel bilgisiyle)
        foreach ($k in $kayitlar) {
            if (-not $k.KullaniciId) { continue }
            $ex = $(if ($k.GyazoId -and $excel.ContainsKey($k.GyazoId)) { $excel[$k.GyazoId] } else { $null })
            $kayit = [pscustomobject]@{ Zaman=$k.Zaman; Proje=$k.Proje; Kat=$(if($ex -and $ex.Kat){$ex.Kat}else{$k.Kat}); Personel=$(if($ex){$ex.Personel}else{""}); UyeId=$(if($ex){$ex.UyeId}else{""}); AnaId=$(if($ex){$ex.AnaId}else{""}); Tip=$(if($ex){$ex.Tip}else{""}) }
            if (-not $zenginKullanici.ContainsKey($k.KullaniciId)) { $zenginKullanici[$k.KullaniciId]=New-Object System.Collections.Generic.List[object] }
            $zenginKullanici[$k.KullaniciId].Add($kayit)
        }
        $topK = 0; foreach ($v in $zenginKullanici.Values) { $topK += $v.Count }
        Write-Bilgi "  Zenginlestirme: $($zenginKullanici.Count) kullanici, $topK kayit noktasi."
    } catch { Write-Bilgi "  ! Zenginlestirme hazirlanamadi, sadece kullanici+tarih ile devam: $($_.Exception.Message)" }
}
function Find-ZenginKayit($kullaniciId, $zaman) {
    if (-not $zenginKullanici.ContainsKey($kullaniciId)) { return $null }
    $enIyi = $null; $enFark = 1e9
    foreach ($k in $zenginKullanici[$kullaniciId]) {
        $fark = ($k.Zaman - $zaman).TotalSeconds
        # kayit fotograftan SONRA gelir; -60 sn tolerans, +30 dk pencere
        if ($fark -ge -60 -and $fark -le 1800 -and [math]::Abs($fark) -lt $enFark) { $enFark=[math]::Abs($fark); $enIyi=$k }
    }
    return $enIyi
}

# ==================== TELEGRAM API ====================
function Get-HataGovdesi($err) {
    # HTTP hata govdesini hem Windows PowerShell 5.1 hem PowerShell 7'de oku.
    $body = $null
    try { if ($err.ErrorDetails -and $err.ErrorDetails.Message) { $body = [string]$err.ErrorDetails.Message } } catch {}   # PS7
    if (-not $body) {
        try {
            $resp = $err.Exception.Response
            if ($resp -and $resp.GetType().GetMethod("GetResponseStream")) {   # PS 5.1 (HttpWebResponse)
                $s = New-Object System.IO.StreamReader($resp.GetResponseStream()); $body = $s.ReadToEnd(); $s.Close()
            }
        } catch {}
    }
    return $body
}
function Get-HataKodu($err) {
    try {
        $resp = $err.Exception.Response
        if ($resp) {
            $sc = $resp.StatusCode
            if ($sc -is [int]) { return [int]$sc }
            return [int][int64]$sc   # enum -> int (her iki surumde)
        }
    } catch {}
    return 0
}
function Invoke-Telegram($metod, $govde) {
    $uri = "$ApiTaban/bot$Token/$metod"
    for ($deneme=1; $deneme -le $DenemeSayisi; $deneme++) {
        try {
            if ($govde) { return Invoke-RestMethod -Uri $uri -Method Post -Body $govde -TimeoutSec $ZamanAsimiSn }
            return Invoke-RestMethod -Uri $uri -Method Get -TimeoutSec $ZamanAsimiSn
        } catch {
            $kod = Get-HataKodu $_
            $body = Get-HataGovdesi $_
            $aciklama = ""
            if ($body) { try { $j = $body | ConvertFrom-Json; $aciklama = [string](Get-Prop $j "description") } catch { $aciklama = $body } }
            # 429: too many requests -> retry_after
            if ($kod -eq 429) {
                $bekle = 3
                if ($body) { try { $j = $body | ConvertFrom-Json; $ra = Get-Prop (Get-Prop $j "parameters") "retry_after"; if ($ra) { $bekle = [int]$ra } } catch {} }
                Write-Bilgi "  429 limit; $bekle sn bekleniyor..."
                Start-Sleep -Seconds ($bekle + 1); continue
            }
            # 400 (mesaj/sohbet yok) ve 403 (engelli) -> kalici, tekrar deneme
            if ($kod -eq 400 -or $kod -eq 403 -or $kod -eq 404) {
                return [pscustomobject]@{ ok=$false; error_code=$kod; description=$aciklama }
            }
            if ($deneme -ge $DenemeSayisi) { return [pscustomobject]@{ ok=$false; error_code=$kod; description=$(if ($aciklama) { $aciklama } else { $_.Exception.Message }) } }
            Start-Sleep -Seconds (2*$deneme)
        }
    }
    return [pscustomobject]@{ ok=$false; error_code=0; description="bilinmeyen" }
}

function Test-GorselDosyasi($yol) {
    try {
        $fi=Get-Item $yol; if ($fi.Length -lt 100) { return $false }
        $b=New-Object byte[] 4; $st=[System.IO.File]::OpenRead($yol); try { [void]$st.Read($b,0,4) } finally { $st.Dispose() }
        if ($b[0] -eq 0xFF -and $b[1] -eq 0xD8) { return $true }
        if ($b[0] -eq 0x89 -and $b[1] -eq 0x50) { return $true }
        if ($b[0] -eq 0x47 -and $b[1] -eq 0x49 -and $b[2] -eq 0x46) { return $true }
        if ($b[0] -eq 0x52 -and $b[1] -eq 0x49 -and $b[2] -eq 0x46 -and $b[3] -eq 0x46) { return $true }
        return $false
    } catch { return $false }
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
    # Gecici (dogrulanmis) gorseli son yerine koy; png istendiyse cevir, olmazsa .jpg olarak birak. Son yolu doner.
    if ($Format -eq "png") {
        if (ConvertTo-PngDosyasi $gecici $hedef) { Remove-Item $gecici -Force -ErrorAction SilentlyContinue; return $hedef }
        $jpg = [System.IO.Path]::ChangeExtension($hedef, ".jpg")
        Move-Item $gecici $jpg -Force
        return $jpg
    }
    Move-Item $gecici $hedef -Force
    return $hedef
}
function Save-TelegramDosya($filePath, $hedef) {
    # Basarili: son dosya yolu (png ya da yedek olarak jpg). Basarisiz: $null
    $url = "$ApiTaban/file/bot$Token/$filePath"
    $gecici = "$hedef.indiriliyor"
    for ($deneme=1; $deneme -le $DenemeSayisi; $deneme++) {
        try {
            Remove-Item $gecici -Force -ErrorAction SilentlyContinue
            Invoke-WebRequest -Uri $url -OutFile $gecici -UseBasicParsing -TimeoutSec $ZamanAsimiSn | Out-Null
            if (-not (Test-GorselDosyasi $gecici)) { throw "indirilen dosya gorsel degil" }
            return (Complete-GorselDosyasi $gecici $hedef)
        } catch { Remove-Item $gecici -Force -ErrorAction SilentlyContinue; if ($deneme -ge $DenemeSayisi) { return $null }; Start-Sleep -Seconds (2*$deneme) }
    }
    return $null
}
function Find-MevcutGorsel($hedef) {
    # Daha once inmis dosya var mi (png ya da jpg yedegi)?
    foreach ($aday in @($hedef, [System.IO.Path]::ChangeExtension($hedef, ".jpg"), [System.IO.Path]::ChangeExtension($hedef, ".png"))) {
        if ((Test-Path $aday) -and (Test-GorselDosyasi $aday)) { return $aday }
    }
    return $null
}

# ==================== CACHE OKU ====================
Write-Bilgi "Cache okunuyor..."
$ciftler = New-Object System.Collections.Generic.List[object]   # sirasi korunur (kronolojik)
$gorulen = New-Object System.Collections.Generic.HashSet[string]
$bareSayi = 0
if (-not (Test-Path $CacheDosyasi)) { throw "Cache dosyasi yok: $CacheDosyasi" }
foreach ($satir in [System.IO.File]::ReadAllLines($CacheDosyasi, [System.Text.Encoding]::UTF8)) {
    $s = $satir.Trim(); if (-not $s) { continue }
    $p = $s.Split(":")
    if ($p.Count -lt 2) { $bareSayi++; continue }   # eski surum: sadece mesajID, sohbet yok -> yonlendirilemez
    $cid = $p[0].Trim(); $mid = $p[1].Trim()
    if ($cid -notmatch '^\d+$' -or $mid -notmatch '^\d+$') { continue }
    $anahtar = "$cid`:$mid"
    if ($gorulen.Add($anahtar)) { $ciftler.Add([pscustomobject]@{ ChatId=$cid; MesajId=[int]$mid }) }
}
Write-Bilgi "  $($ciftler.Count) benzersiz (kullanici:mesaj), $bareSayi eski/sohbetsiz kayit atlandi."

# Kullanici adlari (kullanicilar.json)
$kullaniciAdi = @{}
if (Test-Path $KullaniciDosyasi) {
    try { foreach ($p in ([System.IO.File]::ReadAllText($KullaniciDosyasi,[System.Text.Encoding]::UTF8) | ConvertFrom-Json).PSObject.Properties) { $ad=[string](Get-Prop $p.Value "username"); if (-not $ad) { $ad=[string](Get-Prop $p.Value "first_name") }; if ($ad) { $kullaniciAdi[[string]$p.Name]=$ad } } } catch {}
}

# ==================== ISLE (SONDAN basa: en yeni once) ====================
$plan = New-Object System.Collections.Generic.List[object]
$kullanilanAd = @{}
$sayac = @{ foto=0; foto_yok=0; mesaj_yok=0; erisim_yok=0; hata=0; indirildi=0; zaten_var=0; aralik_disi=0 }
$eskiUstUste = 0
$islenen = 0
$kategoriEtiket = @{}
$katDosya = Join-Path $BotKlasoru "kategoriler.json"
if (Test-Path $katDosya) { try { foreach ($k in ([System.IO.File]::ReadAllText($katDosya,[System.Text.Encoding]::UTF8) | ConvertFrom-Json)) { $kategoriEtiket[([string](Get-Prop $k "code")).ToUpperInvariant()]=[string](Get-Prop $k "label") } } catch {} }

function New-Ad($tarih,$chatId,$mesajId,$kayit) {
    $al = @{
        tarih       = $tarih.ToString("yyyy-MM-dd_HH-mm-ss",$Inv)
        kullanici   = $(if ($kullaniciAdi.ContainsKey($chatId)) { ConvertTo-GuvenliAd $kullaniciAdi[$chatId] } else { "kullanici$chatId" })
        kullaniciid = $chatId
        proje       = $(if ($kayit) { ConvertTo-GuvenliAd $kayit.Proje } else { "" })
        kategori    = $(if ($kayit -and $kayit.Kat) { (ConvertTo-GuvenliAd $kayit.Kat).ToUpperInvariant() } else { "" })
        personel    = $(if ($kayit -and $kayit.Personel) { "P"+(ConvertTo-GuvenliAd $kayit.Personel) } else { "" })
        uyeid       = $(if ($kayit -and $kayit.UyeId) { "U"+(ConvertTo-GuvenliAd $kayit.UyeId) } else { "" })
        anaid       = $(if ($kayit -and $kayit.AnaId) { "A"+(ConvertTo-GuvenliAd $kayit.AnaId) } else { "" })
        tip         = $(if ($kayit -and $kayit.Tip) { ConvertTo-GuvenliAd $kayit.Tip } else { "" })
        mesajid     = "m$mesajId"
    }
    $ad = [regex]::Replace($AdSablonu, '\{(\w+)\}', { param($m) $k=$m.Groups[1].Value.ToLowerInvariant(); if ($al.ContainsKey($k)) { [string]$al[$k] } else { "" } })
    $ad = [regex]::Replace($ad, '_{2,}', '_').Trim('_','-','.')
    if (-not $ad) { $ad = "gorsel_$($chatId)_$mesajId" }
    return $ad
}

function Save-Plan {
    $utf8Bom = New-Object System.Text.UTF8Encoding $true
    $csv = @($plan | ConvertTo-Csv -NoTypeInformation -Delimiter ';')
    if ($csv.Count -eq 0) { $csv = @("Tarih;KullaniciAdi;KullaniciId;Proje;Kategori;Personel;UyeID;AnaUyeID;Tip;MesajId;Zenginlik;DosyaAdi;DosyaYolu;Durum") }
    [System.IO.File]::WriteAllLines($IndeksDosyasi, [string[]]$csv, $utf8Bom)
}

for ($idx = $ciftler.Count - 1; $idx -ge 0; $idx--) {
    $c = $ciftler[$idx]
    $islenen++
    # forwardMessage
    $r = Invoke-Telegram "forwardMessage" @{ chat_id=$HedefChatId; from_chat_id=$c.ChatId; message_id=$c.MesajId }
    if ($BeklemeMs -gt 0) { Start-Sleep -Milliseconds $BeklemeMs }
    if (-not (Get-Prop $r "ok")) {
        $desc = [string](Get-Prop $r "description")
        $kod  = [int](Get-Prop $r "error_code")
        if ($kod -eq 403 -or $desc -match 'forbidden|blocked|kicked|chat not found|user is deactivated') { $sayac.erisim_yok++ }
        elseif ($kod -eq 400 -or $desc -match 'not found|to forward|to copy|message.*delete') { $sayac.mesaj_yok++ }
        else { $sayac.hata++; if (($sayac.hata % 20) -eq 1) { Write-Bilgi "  ! forward hata ($($c.ChatId):$($c.MesajId)) kod=$kod : $desc" } }
        continue
    }
    $sonuc = Get-Prop $r "result"
    $yeniMsgId = Get-Prop $sonuc "message_id"
    $foto = Get-Prop $sonuc "photo"
    # orijinal gonderim tarihi: forward_date (yonlendirilenin orijinali), yoksa date
    $odate = Get-Prop $sonuc "forward_date"; if (-not $odate) { $odate = Get-Prop $sonuc "date" }
    $tarih = $(if ($odate) { ConvertFrom-Unix ([long]$odate) } else { $null })
    # yonlendirilen kopyayi hedef sohbetten sil (varsayilan). -KopyaBirak verilirse birak.
    if (-not $KopyaBirak -and $yeniMsgId) { Invoke-Telegram "deleteMessage" @{ chat_id=$HedefChatId; message_id=$yeniMsgId } | Out-Null; if ($BeklemeMs -gt 0) { Start-Sleep -Milliseconds ([math]::Min($BeklemeMs,150)) } }

    if (-not $foto) { $sayac.foto_yok++; if ($tarih -and $tarih -lt $BaslangicTarihi) { $eskiUstUste++ } else { $eskiUstUste = 0 }; }
    else {
        $sayac.foto++
        # aralik filtresi (orijinal tarihe gore)
        if ($tarih -and ($tarih -lt $BaslangicTarihi -or $tarih -gt $BitisTarihi)) {
            $sayac.aralik_disi++
            if ($tarih -lt $BaslangicTarihi) { $eskiUstUste++ } else { $eskiUstUste = 0 }
        } else {
            $eskiUstUste = 0
            if (-not $tarih) { $tarih = [datetime]::Today }   # tarih yoksa bugun (nadir)
            $kayit = $(if ($Zenginlestir) { Find-ZenginKayit $c.ChatId $tarih } else { $null })
            # en buyuk foto boyutu
            $enBuyuk = $null
            foreach ($ph in @($foto)) { if (-not $enBuyuk -or ([int](Get-Prop $ph "file_size") -gt [int](Get-Prop $enBuyuk "file_size"))) { $enBuyuk = $ph } }
            $fileId = [string](Get-Prop $enBuyuk "file_id")
            $klasor = Join-Path $CiktiKlasoru $(if ($kayit -and $kayit.Proje) { (ConvertTo-GuvenliAd $kayit.Proje).ToUpperInvariant() } else { "PROJESIZ" })
            if (-not (Test-Path $klasor)) { New-Item -ItemType Directory -Path $klasor -Force | Out-Null }
            $temelAd = New-Ad $tarih $c.ChatId $c.MesajId $kayit
            $uz = $(if ($Format -eq "png") { ".png" } else { ".jpg" })
            $dosyaAdi = "$temelAd`_m$($c.MesajId)$uz"
            $anahtar = (Join-Path $klasor $dosyaAdi).ToLowerInvariant()
            $n=2; while ($kullanilanAd.ContainsKey($anahtar)) { $dosyaAdi = "$temelAd`_m$($c.MesajId)_$n$uz"; $anahtar=(Join-Path $klasor $dosyaAdi).ToLowerInvariant(); $n++ }
            $kullanilanAd[$anahtar]=$true
            $hedef = Join-Path $klasor $dosyaAdi
            $durum = "tarandi"
            if (-not $SadeceTara) {
                $mevcut = $(if ($Yeniden) { $null } else { Find-MevcutGorsel $hedef })
                if ($mevcut) { $durum="zaten_var"; $sayac.zaten_var++; $hedef = $mevcut; $dosyaAdi = Split-Path $mevcut -Leaf }
                else {
                    $gf = Invoke-Telegram "getFile" @{ file_id=$fileId }
                    if ($BeklemeMs -gt 0) { Start-Sleep -Milliseconds ([math]::Min($BeklemeMs,150)) }
                    if (Get-Prop $gf "ok") {
                        $fp = [string](Get-Prop (Get-Prop $gf "result") "file_path")
                        $son = $(if ($fp) { Save-TelegramDosya $fp $hedef } else { $null })
                        if ($son) {
                            $durum = $(if ($son -ne $hedef) { "indirildi_jpg" } else { "indirildi" })
                            $sayac.indirildi++; $hedef = $son; $dosyaAdi = Split-Path $son -Leaf
                        } else { $durum="indirilemedi"; $sayac.hata++ }
                    } else { $durum="getfile_hata:$([string](Get-Prop $gf 'description'))"; $sayac.hata++ }
                }
            }
            $plan.Add([pscustomobject]@{
                Tarih=$tarih.ToString("yyyy-MM-dd HH:mm:ss",$Inv); KullaniciAdi=$(if ($kullaniciAdi.ContainsKey($c.ChatId)){$kullaniciAdi[$c.ChatId]}else{""}); KullaniciId=$c.ChatId
                Proje=$(if($kayit){$kayit.Proje}else{""}); Kategori=$(if($kayit){$kayit.Kat}else{""}); Personel=$(if($kayit){$kayit.Personel}else{""}); UyeID=$(if($kayit){$kayit.UyeId}else{""}); AnaUyeID=$(if($kayit){$kayit.AnaId}else{""}); Tip=$(if($kayit){$kayit.Tip}else{""})
                MesajId=$c.MesajId; Zenginlik=$(if($kayit){"eslesti"}else{"sadece_kullanici_tarih"}); DosyaAdi=$dosyaAdi; DosyaYolu=$hedef; Durum=$durum
            })
        }
    }

    if (($islenen % 50) -eq 0) {
        Write-Bilgi "  $islenen/$($ciftler.Count) tarandi | foto=$($sayac.foto) indirildi=$($sayac.indirildi) zaten=$($sayac.zaten_var) mesaj_yok=$($sayac.mesaj_yok) erisim_yok=$($sayac.erisim_yok) aralik_disi=$($sayac.aralik_disi) hata=$($sayac.hata)"
        Save-Plan
    }
    if (($Baslangic -or $SonAy -gt 0) -and $eskiUstUste -ge $EskiDurma) {
        Write-Bilgi "  Ust uste $eskiUstUste mesaj aralik oncesinden; tarama durduruluyor (cache kronolojik)."
        break
    }
}

Save-Plan
Write-Bilgi "========================================"
Write-Bilgi "BITTI. taranan=$islenen foto=$($sayac.foto) indirildi=$($sayac.indirildi) zaten_var=$($sayac.zaten_var) aralik_disi=$($sayac.aralik_disi) mesaj_yok=$($sayac.mesaj_yok) erisim_yok=$($sayac.erisim_yok) hata=$($sayac.hata)"
Write-Bilgi "Klasor : $CiktiKlasoru"
Write-Bilgi "Indeks : $IndeksDosyasi"
if ($sayac.hata -gt 0 -or $sayac.indirildi -gt 0) { Write-Bilgi "Eksik/hatali icin tekrar calistirin; inmis olanlar atlanir." }
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
