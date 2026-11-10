<#
.SYNOPSIS
    Gala CRM Botu'nun bir Slack kanalına attığı bildirimleri (ve thread yanıtlarını) Excel'e aktarır.

.DESCRIPTION
    Bot mesajı şu formattadır:
        🔵 İLK YATIRIM SONRASI ÇEKİM – 50.000 TL VE ALTI
        İlk yatırımını yaptı, para çekti. Son çekiminin üzerinden en az 48 saat geçti.
        Üye ID: 751-505830309
        BTag: 2656818
    Script her bildirimi ayrı satıra; Tarih / Gün / Saat / Kategori / Renk / Açıklama / Üye ID / BTag
    sütunlarına ayırır. Thread'e yazılan yanıtı (kim, ne zaman, ne yazdı) aynı satıra ekler.

    Excel sayfaları:
        Bildirimler     her bildirim bir satır (yanıtsızlar kırmızı)
        Kategori Özeti  kategori bazında bildirim / yanıtlanan / yanıtsız
        BTag Özeti      BTag bazında sayılar
        Günlük          gün bazında sayılar
        Yanıtlayanlar   kim kaç yanıt yazmış
        Diğer Mesajlar  bot formatında olmayan mesajlar
        Bilgi           kanal, aralık, toplamlar

    GEREKEN SLACK APP YETKİLERİ (api.slack.com/apps > uygulaman > OAuth & Permissions > Bot Token Scopes):
        channels:history   herkese açık kanalın mesajlarını okuma
        groups:history     özel (private) kanalın mesajlarını okuma
        users:read         yanıt yazan kişilerin adını çözmek için
        channels:read      (isteğe bağlı) kanal adını almak için
        groups:read        (isteğe bağlı) özel kanal adını almak için
    Scope ekledikten sonra "Install to Workspace / Reinstall" yap, xoxb- ile başlayan Bot User OAuth Token'ı al.
    Bot kanala EKLİ olmalı: kanalda  /invite @BotAdı  yaz.

    EXCEL ÇIKTISI: ImportExcel modülü kullanılır (ilk çalıştırmada otomatik kurulur, Excel gerekmez).
    Kurulamazsa bilgisayardaki Excel ile (COM), o da yoksa CSV olarak yazar.

.EXAMPLE
    # 1) Aşağıdaki param bloğunda $Token ve $Channel değerlerini doldur
    # 2) PowerShell'de:
    Set-ExecutionPolicy -Scope Process Bypass -Force
    .\Export-GalaCrm.ps1
    .\Export-GalaCrm.ps1 -Start 2026-11-01 -End 2026-11-09
#>
[CmdletBinding()]
param(
    # ================== BURAYI DOLDUR ==================
    [string] $Token   = "xoxb-BURAYA-TOKEN",      # Bot User OAuth Token
    [string] $Channel = "C0000000000",            # Kanal ID (kanal adına sağ tık > Kanal ayrıntıları > en altta)
    [string] $BotName = "",                       # Boş = kanaldaki HER mesaj alınır. "Gala CRM Botu" yazarsan sadece o app'inkiler
    # ===================================================
    [string] $Start,                              # yyyy-MM-dd (dahil) - boşsa sınırsız
    [string] $End,                                # yyyy-MM-dd (dahil) - boşsa bugüne kadar
    [string] $Output,                             # .xlsx yolu - boşsa scriptin yanına yazar
    [switch] $SkipThreads,                        # thread yanıtlarını çekme (daha hızlı)
    [switch] $IncludeSystem,                      # katıldı/ayrıldı mesajlarını da yaz
    [int]    $PageSize = 200
)

$ErrorActionPreference = 'Stop'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }

if ($env:SLACK_BOT_TOKEN -and $Token -like 'xoxb-BURAYA*') { $Token = $env:SLACK_BOT_TOKEN }
if (-not $Token -or $Token -like 'xoxb-BURAYA*') { throw 'Token girilmemiş. Scriptin param bloğundaki $Token satırını doldur.' }
if (-not $Channel -or $Channel -eq 'C0000000000') { throw 'Kanal ID girilmemiş. Scriptin param bloğundaki $Channel satırını doldur.' }
$Channel = $Channel.Trim().TrimStart('#')

$script:PageSize = $PageSize
$script:ApiCalls = 0
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$TrDays = @('Pazar', 'Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma', 'Cumartesi')

# Saat dilimi: Türkiye
$Tz = $null
foreach ($id in @('Turkey Standard Time', 'Europe/Istanbul')) {
    if (-not $Tz) { try { $Tz = [TimeZoneInfo]::FindSystemTimeZoneById($id) } catch { } }
}
if (-not $Tz) { $Tz = [TimeZoneInfo]::Local; Write-Warning "Türkiye saat dilimi bulunamadı, bilgisayarın saati kullanılıyor." }

$ErrorHelp = @{
    invalid_auth       = "Token geçersiz ya da başka workspace'e ait."
    not_authed         = "Token gönderilmedi."
    token_revoked      = "Token iptal edilmiş; Slack App > OAuth & Permissions > Reinstall."
    account_inactive   = "Bot devre dışı."
    missing_scope      = "Eksik scope. Bot Token Scopes'a channels:history, groups:history, users:read ekle ve Reinstall yap."
    not_in_channel     = "Bot kanala ekli değil. Kanalda  /invite @BotAdı  yaz."
    channel_not_found  = "Kanal bulunamadı. ID yanlış ya da bot bu kanalı göremiyor (özel kanalsa bota ekle)."
    invalid_ts_latest  = "-End tarihi geçersiz."
    invalid_ts_oldest  = "-Start tarihi geçersiz."
    ratelimited        = "Rate limit; script bekleyip devam eder."
}

# ---------------------------------------------------------------- Slack API
function Invoke-Slack {
    param([Parameter(Mandatory)] [string] $Method, [hashtable] $Params = @{})
    $attempt = 0
    while ($true) {
        $attempt++
        $script:ApiCalls++
        try {
            $r = Invoke-RestMethod -Uri "https://slack.com/api/$Method" -Method Post `
                -Headers @{ Authorization = "Bearer $Token" } `
                -ContentType 'application/x-www-form-urlencoded; charset=utf-8' `
                -Body $Params
        }
        catch {
            $resp = $_.Exception.Response
            $status = 0
            if ($resp) { try { $status = [int]$resp.StatusCode } catch { } }
            if ($status -eq 429) {
                $wait = 30
                try { $ra = @($resp.Headers.GetValues('Retry-After'))[0]; if ($ra) { $wait = [int]$ra } } catch { }
                Write-Host "  rate limit ($Method); $wait sn bekleniyor..." -ForegroundColor Yellow
                Start-Sleep -Seconds ($wait + 1)
                continue
            }
            if ($attempt -ge 5) { throw }
            $back = [math]::Pow(2, $attempt)
            Write-Host "  ağ hatası ($($_.Exception.Message)); $back sn sonra tekrar..." -ForegroundColor Yellow
            Start-Sleep -Seconds $back
            continue
        }
        if ($r.ok) { return $r }
        if ($r.error -eq 'ratelimited') {
            Write-Host "  rate limit ($Method); 30 sn bekleniyor..." -ForegroundColor Yellow
            Start-Sleep -Seconds 30
            continue
        }
        $hint = $ErrorHelp[[string]$r.error]
        throw "Slack hatası: $Method -> $($r.error)  $hint"
    }
}

function Get-SlackPages {
    # cursor sayfalaması; $Key altındaki öğeleri tek listede döndürür
    param([string] $Method, [hashtable] $Params, [string] $Key)
    $all = New-Object System.Collections.Generic.List[object]
    $cursor = $null
    while ($true) {
        $p = @{} + $Params
        if ($cursor) { $p.cursor = $cursor }
        $r = Invoke-Slack -Method $Method -Params $p
        foreach ($it in @($r.$Key)) { if ($null -ne $it) { $all.Add($it) } }
        $cursor = $null
        if ($r.response_metadata -and $r.response_metadata.next_cursor) { $cursor = $r.response_metadata.next_cursor }
        if (-not $cursor) { break }
    }
    return $all
}

function Get-SlackMessages {
    # conversations.history / replies; yeni rate-limit modelinde limit>15 reddedilirse 15'e düşer
    param([string] $Method, [hashtable] $Params)
    $all = New-Object System.Collections.Generic.List[object]
    $cursor = $null
    while ($true) {
        $p = @{} + $Params
        $p.limit = $script:PageSize
        if ($cursor) { $p.cursor = $cursor }
        try { $r = Invoke-Slack -Method $Method -Params $p }
        catch {
            if ($script:PageSize -gt 15 -and $_.Exception.Message -match 'invalid_arguments|invalid_limit') {
                Write-Host "  $Method limit=$($script:PageSize) kabul edilmedi, 15'e düşürülüyor." -ForegroundColor Yellow
                $script:PageSize = 15
                continue
            }
            throw
        }
        foreach ($m in @($r.messages)) { if ($null -ne $m) { $all.Add($m) } }
        $cursor = $null
        if ($r.response_metadata -and $r.response_metadata.next_cursor) { $cursor = $r.response_metadata.next_cursor }
        if (-not $cursor) { break }
    }
    return $all
}

# ---------------------------------------------------------------- yardımcılar
function ConvertFrom-SlackTs {
    param([string] $Ts)
    $secs = [long][math]::Floor([double]::Parse($Ts, [Globalization.CultureInfo]::InvariantCulture))
    $dto = [DateTimeOffset]::FromUnixTimeSeconds($secs)
    return [TimeZoneInfo]::ConvertTime($dto, $Tz).DateTime
}

function ConvertTo-SlackTs {
    param([string] $Date, [switch] $EndOfDay)
    if (-not $Date) { return $null }
    $d = [datetime]::ParseExact($Date, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture)
    if ($EndOfDay) { $d = $d.AddDays(1) }
    $dto = New-Object DateTimeOffset($d, $Tz.GetUtcOffset($d))
    return ('{0}.000000' -f $dto.ToUnixTimeSeconds())
}

$EmojiColor = @{
    'large_blue_circle' = 'Mavi'; 'large_orange_circle' = 'Turuncu'; 'red_circle' = 'Kırmızı'
    'large_green_circle' = 'Yeşil'; 'large_yellow_circle' = 'Sarı'; 'large_purple_circle' = 'Mor'
    'white_circle' = 'Beyaz'; 'black_circle' = 'Siyah'; 'large_brown_circle' = 'Kahverengi'
}
# Unicode emoji karşılıkları (🔵 🟠 🔴 🟢 🟡 🟣 ⚪ ⚫ 🟤)
foreach ($pair in @(@(0x1F535, 'Mavi'), @(0x1F7E0, 'Turuncu'), @(0x1F534, 'Kırmızı'), @(0x1F7E2, 'Yeşil'),
                    @(0x1F7E1, 'Sarı'), @(0x1F7E3, 'Mor'), @(0x26AA, 'Beyaz'), @(0x26AB, 'Siyah'), @(0x1F7E4, 'Kahverengi'))) {
    $EmojiColor[[char]::ConvertFromUtf32($pair[0])] = $pair[1]
}

function Format-SlackText {
    param([string] $Text)
    if (-not $Text) { return '' }
    $t = $Text
    $t = [regex]::Replace($t, '<@([UW][A-Z0-9]+)(?:\|[^>]*)?>', { param($m) $id = $m.Groups[1].Value; if ($Users.ContainsKey($id)) { '@' + $Users[$id].Name } else { '@' + $id } })
    $t = [regex]::Replace($t, '<#[CG][A-Z0-9]+\|([^>]*)>', '#$1')
    $t = [regex]::Replace($t, '<!(here|channel|everyone)(?:\|[^>]*)?>', '@$1')
    $t = [regex]::Replace($t, '<((?:https?|mailto):[^>|]+)\|([^>]*)>', '$2 ($1)')
    $t = [regex]::Replace($t, '<((?:https?|mailto):[^>]+)>', '$1')
    $t = $t -replace '&lt;', '<' -replace '&gt;', '>' -replace '&amp;', '&'
    $t = [regex]::Replace($t, '(?m)^\*(.+?)\*\s*$', '$1')      # satır başı-sonu kalın işaretleri
    return $t.Trim()
}

function Get-MessageText {
    # blocks > text; attachments eklenir
    param($M)
    $parts = New-Object System.Collections.Generic.List[string]
    foreach ($b in @($M.blocks)) {
        if ($null -eq $b) { continue }
        switch ($b.type) {
            'section' {
                if ($b.text -and $b.text.text) { $parts.Add([string]$b.text.text) }
                foreach ($f in @($b.fields)) { if ($f -and $f.text) { $parts.Add([string]$f.text) } }
            }
            'header'  { if ($b.text -and $b.text.text) { $parts.Add([string]$b.text.text) } }
            'context' { foreach ($e in @($b.elements)) { if ($e -and $e.text) { $parts.Add([string]$e.text) } } }
            'rich_text' {
                $sb = New-Object Text.StringBuilder
                foreach ($el in @($b.elements)) {
                    foreach ($x in @($el.elements)) {
                        if ($null -eq $x) { continue }
                        switch ($x.type) {
                            'text'    { [void]$sb.Append($x.text) }
                            'link'    { [void]$sb.Append($(if ($x.text) { $x.text } else { $x.url })) }
                            'user'    { [void]$sb.Append('@' + $(if ($Users.ContainsKey($x.user_id)) { $Users[$x.user_id].Name } else { $x.user_id })) }
                            'emoji'   { [void]$sb.Append(':' + $x.name + ':') }
                            'channel' { [void]$sb.Append('#' + $x.channel_id) }
                            default   { if ($x.text) { [void]$sb.Append($x.text) } }
                        }
                    }
                    [void]$sb.Append("`n")
                }
                $parts.Add($sb.ToString())
            }
        }
    }
    if ($parts.Count -eq 0 -and $M.text) { $parts.Add([string]$M.text) }
    foreach ($a in @($M.attachments)) {
        if ($null -eq $a) { continue }
        if ($a.pretext) { $parts.Add([string]$a.pretext) }
        if ($a.title)   { $parts.Add([string]$a.title) }
        if ($a.text)    { $parts.Add([string]$a.text) } elseif ($a.fallback) { $parts.Add([string]$a.fallback) }
        foreach ($f in @($a.fields)) { if ($f) { $parts.Add(('{0}: {1}' -f $f.title, $f.value)) } }
    }
    return (Format-SlackText ($parts -join "`n"))
}

function ConvertFrom-GalaText {
    # Kategori / Renk / Açıklama / Üye ID / BTag ayrıştırma; bildirim değilse $null
    param([string] $Text)
    $uye  = [regex]::Match($Text, '(?i)Üye\s*ID\s*[:：]\s*([0-9][0-9\-]*)')
    $btag = [regex]::Match($Text, '(?i)B\s*Tag\s*[:：]\s*([^\s]+)')
    if (-not $uye.Success -and -not $btag.Success) { return $null }

    $lines = @($Text -split "`r?`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ -and $_ -notmatch '^[-_—–=]{3,}$' })
    $title = ''; $color = ''; $emoji = ''
    if ($lines.Count -gt 0) {
        $title = $lines[0]
        $m = [regex]::Match($title, '^:([a-z0-9_+\-]+):\s*')
        if ($m.Success) {
            $emoji = $m.Groups[1].Value
            $title = $title.Substring($m.Length)
        }
        else {
            $m = [regex]::Match($title, '^[^\p{L}\p{N}]+')
            if ($m.Success) { $emoji = $m.Value.Trim(); $title = $title.Substring($m.Length) }
        }
        $title = $title.Trim(' ', '*', '_')
        if ($emoji) {
            $key = ($emoji -replace '[\uFE0F\u200D]', '')
            if ($EmojiColor.ContainsKey($key)) { $color = $EmojiColor[$key] } else { $color = $emoji }
        }
    }
    $desc = @()
    for ($i = 1; $i -lt $lines.Count; $i++) {
        $l = $lines[$i]
        if ($l -match '(?i)^Üye\s*ID\s*[:：]' -or $l -match '(?i)^B\s*Tag\s*[:：]') { continue }
        $desc += $l
    }
    return [pscustomobject]@{
        Kategori = $title
        Renk     = $color
        Aciklama = ($desc -join ' ')
        UyeId    = $(if ($uye.Success) { $uye.Groups[1].Value } else { '' })
        BTag     = $(if ($btag.Success) { $btag.Groups[1].Value } else { '' })
    }
}

function Get-Author {
    param($M)
    if ($M.user -and $Users.ContainsKey($M.user)) { return $Users[$M.user].Name }
    if ($M.user) { return [string]$M.user }
    if ($M.username) { return "$($M.username) (bot)" }
    if ($M.bot_profile -and $M.bot_profile.name) { return "$($M.bot_profile.name) (bot)" }
    if ($M.bot_id) { return "$($M.bot_id) (bot)" }
    return ''
}

$SystemSubtypes = @('channel_join', 'channel_leave', 'channel_purpose', 'channel_topic', 'channel_name',
    'channel_archive', 'channel_unarchive', 'group_join', 'group_leave', 'bot_add', 'bot_remove',
    'pinned_item', 'unpinned_item')

# ---------------------------------------------------------------- çekim
Write-Host "Bağlanılıyor..." -ForegroundColor Cyan
$auth = Invoke-Slack -Method 'auth.test'
$TeamUrl = ([string]$auth.url).TrimEnd('/')
Write-Host "Workspace: $($auth.team)   bot: $($auth.user)"

$ChannelName = $Channel
try { $ci = Invoke-Slack -Method 'conversations.info' -Params @{ channel = $Channel }; if ($ci.channel.name) { $ChannelName = $ci.channel.name } }
catch { Write-Host "  (kanal adı alınamadı, ID kullanılacak: $($_.Exception.Message))" -ForegroundColor DarkGray }
Write-Host "Kanal: #$ChannelName ($Channel)"

Write-Host "Kullanıcı listesi çekiliyor..." -ForegroundColor Cyan
$Users = @{}
try {
    foreach ($u in (Get-SlackPages -Method 'users.list' -Params @{ limit = 200 } -Key 'members')) {
        $p = $u.profile
        $name = $null
        if ($p) { if ($p.display_name) { $name = $p.display_name } elseif ($p.real_name) { $name = $p.real_name } }
        if (-not $name) { if ($u.real_name) { $name = $u.real_name } else { $name = $u.name } }
        if ($u.deleted) { $name = "$name (silinmiş hesap)" }
        $Users[[string]$u.id] = [pscustomobject]@{ Name = $name; Handle = $u.name; Email = $(if ($p) { $p.email } else { '' }) }
    }
    Write-Host "  $($Users.Count) kullanıcı."
}
catch { Write-Warning "users.list okunamadı ($($_.Exception.Message)); isimler ID olarak yazılacak." }

$histParams = @{ channel = $Channel; inclusive = 'true' }
$oldest = ConvertTo-SlackTs -Date $Start
$latest = ConvertTo-SlackTs -Date $End -EndOfDay
if ($oldest) { $histParams.oldest = $oldest }
if ($latest) { $histParams.latest = $latest }

Write-Host "Kanal mesajları çekiliyor..." -ForegroundColor Cyan
$history = Get-SlackMessages -Method 'conversations.history' -Params $histParams
Write-Host "  $($history.Count) kayıt geldi."

function Test-FromBot {
    # Mesaj istenen app'ten mi? (bot adı / username / profil adı / kullanıcı adı)
    param($M)
    if (-not $BotName) { return $true }
    $names = @()
    if ($M.username) { $names += [string]$M.username }
    if ($M.bot_profile -and $M.bot_profile.name) { $names += [string]$M.bot_profile.name }
    if ($M.user -and $Users.ContainsKey([string]$M.user)) { $names += [string]$Users[[string]$M.user].Name; $names += [string]$Users[[string]$M.user].Handle }
    foreach ($x in $names) { if ($x -and $x.Trim() -ieq $BotName.Trim()) { return $true } }
    return $false
}

$seen = @{}
$parents = New-Object System.Collections.Generic.List[object]
$filteredOut = 0
foreach ($m in $history) {
    if (-not $m.ts -or $seen.ContainsKey([string]$m.ts)) { continue }
    $seen[[string]$m.ts] = 1
    if ($m.subtype -eq 'thread_broadcast' -and $m.thread_ts -and $m.thread_ts -ne $m.ts) { continue }
    if (-not $IncludeSystem -and $m.subtype -and $SystemSubtypes -contains $m.subtype) { continue }
    if (-not (Test-FromBot -M $m)) { $filteredOut++; continue }
    $parents.Add($m)
}
if ($BotName) { Write-Host "  '$BotName' filtresi: $($parents.Count) mesaj alındı, $filteredOut mesaj başkasına ait (atlandı)." }
if ($BotName -and $parents.Count -eq 0 -and $history.Count -gt 0) {
    $gorulen = @($history | ForEach-Object { if ($_.username) { $_.username } elseif ($_.bot_profile) { $_.bot_profile.name } elseif ($_.user -and $Users.ContainsKey([string]$_.user)) { $Users[[string]$_.user].Name } } | Where-Object { $_ } | Sort-Object -Unique)
    Write-Warning "'$BotName' adında gönderen bulunamadı. Kanalda görülen gönderenler: $($gorulen -join ', ')  ->  `$BotName değerini bunlardan biriyle değiştir."
}
$parents = @($parents | Sort-Object { [double]::Parse($_.ts, [Globalization.CultureInfo]::InvariantCulture) })

$Threads = @{}
if (-not $SkipThreads) {
    $withThread = @($parents | Where-Object { $_.reply_count -gt 0 })
    Write-Host "  $($parents.Count) ana mesaj, $($withThread.Count) tanesinde thread var. Yanıtlar çekiliyor..." -ForegroundColor Cyan
    $i = 0
    foreach ($p in $withThread) {
        $i++
        try {
            $reps = Get-SlackMessages -Method 'conversations.replies' -Params @{ channel = $Channel; ts = $p.ts }
        }
        catch {
            if ($_.Exception.Message -match 'thread_not_found') { continue }
            throw
        }
        $Threads[[string]$p.ts] = @($reps | Where-Object { $_.ts -ne $p.ts } | Sort-Object { [double]::Parse($_.ts, [Globalization.CultureInfo]::InvariantCulture) })
        if ($i % 10 -eq 0 -or $i -eq $withThread.Count) { Write-Host "  thread $i / $($withThread.Count)" }
    }
}

# users.list'te olmayan (dış) kullanıcılar
$allMsgs = @($parents) + @($Threads.Values | ForEach-Object { $_ })
foreach ($uid in ($allMsgs | ForEach-Object { $_.user } | Where-Object { $_ } | Sort-Object -Unique)) {
    if ($Users.ContainsKey([string]$uid)) { continue }
    try {
        $ui = (Invoke-Slack -Method 'users.info' -Params @{ user = $uid }).user
        $n = $null
        if ($ui.profile) { if ($ui.profile.display_name) { $n = $ui.profile.display_name } elseif ($ui.profile.real_name) { $n = $ui.profile.real_name } }
        if (-not $n) { $n = $ui.name }
        $Users[[string]$uid] = [pscustomobject]@{ Name = $n; Handle = $ui.name; Email = '' }
    }
    catch { $Users[[string]$uid] = [pscustomobject]@{ Name = [string]$uid; Handle = ''; Email = '' } }
}

# ---------------------------------------------------------------- satırlar
$Rows   = New-Object System.Collections.Generic.List[object]
$Others = New-Object System.Collections.Generic.List[object]
$n = 0
foreach ($p in $parents) {
    $dt   = ConvertFrom-SlackTs -Ts $p.ts
    $text = Get-MessageText -M $p
    $g    = ConvertFrom-GalaText -Text $text
    $link = "$TeamUrl/archives/$Channel/p$(([string]$p.ts) -replace '\.', '')"
    $author = Get-Author -M $p

    if ($null -eq $g) {
        $Others.Add([pscustomobject]@{
            'Tarih' = $dt.Date; 'Gün' = $TrDays[[int]$dt.DayOfWeek]; 'Saat' = $dt.ToString('HH:mm:ss')
            'Gönderen' = $author; 'Mesaj' = $text; 'Slack Linki' = $link
        })
        continue
    }

    $reps = @()
    if ($Threads.ContainsKey([string]$p.ts)) { $reps = $Threads[[string]$p.ts] }
    $first = $null; $firstDt = $null; $mins = $null; $replyText = ''; $responders = ''; $allReplies = ''
    if ($reps.Count -gt 0) {
        $first   = $reps[0]
        $firstDt = ConvertFrom-SlackTs -Ts $first.ts
        $mins    = [math]::Round(([double]::Parse($first.ts, [Globalization.CultureInfo]::InvariantCulture) -
                                  [double]::Parse($p.ts, [Globalization.CultureInfo]::InvariantCulture)) / 60, 1)
        $replyText  = Get-MessageText -M $first
        $responders = (@($reps | ForEach-Object { Get-Author -M $_ } | Select-Object -Unique) -join ', ')
        if ($reps.Count -gt 1) {
            $allReplies = (@($reps | ForEach-Object {
                $rd = ConvertFrom-SlackTs -Ts $_.ts
                '[{0}] {1}: {2}' -f $rd.ToString('dd.MM HH:mm'), (Get-Author -M $_), (Get-MessageText -M $_)
            }) -join "`n")
        }
    }
    elseif ($p.reply_count -gt 0 -and $SkipThreads) { $responders = "($($p.reply_count) yanıt - çekilmedi)" }

    $n++
    $Rows.Add([pscustomobject]@{
        'Sıra'              = $n
        'Tarih'             = $dt.Date
        'Gün'               = $TrDays[[int]$dt.DayOfWeek]
        'Saat'              = $dt.ToString('HH:mm:ss')
        'Kategori'          = $g.Kategori
        'Renk'              = $g.Renk
        'Açıklama'          = $g.Aciklama
        'Üye ID'            = $g.UyeId
        'BTag'              = $g.BTag
        'Yanıt Durumu'      = $(if ($reps.Count -gt 0 -or ($SkipThreads -and $p.reply_count -gt 0)) { 'Yanıtlandı' } else { 'YANITSIZ' })
        'Yanıtlayan'        = $responders
        'Yanıt Tarihi'      = $(if ($firstDt) { $firstDt.Date } else { $null })
        'Yanıt Saati'       = $(if ($firstDt) { $firstDt.ToString('HH:mm:ss') } else { '' })
        'Yanıt Süresi (dk)' = $mins
        'Yanıt'             = $replyText
        'Yanıt Sayısı'      = $(if ($reps.Count -gt 0) { $reps.Count } elseif ($p.reply_count) { [int]$p.reply_count } else { 0 })
        'Diğer Yanıtlar'    = $allReplies
        'Gönderen'          = $author
        'Tam Metin'         = $text
        'Slack Linki'       = $link
        'ts'                = [string]$p.ts
    })
}

Write-Host "  $($Rows.Count) bildirim, $($Others.Count) diğer mesaj." -ForegroundColor Cyan
if ($Rows.Count -eq 0) {
    Write-Warning "Hiç bildirim bulunamadı. Mesajlarda 'Üye ID:' / 'BTag:' alanı aranıyor; 'Diğer Mesajlar' sayfasına bak."
}

# ---------------------------------------------------------------- özetler
function Get-Rate { param($a, $b) if ($b) { [math]::Round($a / $b, 3) } else { 0 } }

$CatSummary = @($Rows | Group-Object 'Kategori' | Sort-Object Count -Descending | ForEach-Object {
    $ans = @($_.Group | Where-Object { $_.'Yanıt Durumu' -eq 'Yanıtlandı' }).Count
    $m = @($_.Group | Where-Object { $null -ne $_.'Yanıt Süresi (dk)' } | ForEach-Object { $_.'Yanıt Süresi (dk)' })
    [pscustomobject]@{
        'Kategori' = $_.Name; 'Bildirim' = $_.Count; 'Yanıtlanan' = $ans; 'Yanıtsız' = $_.Count - $ans
        'Yanıt Oranı' = Get-Rate $ans $_.Count
        'Ort. Yanıt (dk)' = $(if ($m.Count) { [math]::Round(($m | Measure-Object -Average).Average, 1) } else { $null })
        'Farklı Üye' = @($_.Group | ForEach-Object { $_.'Üye ID' } | Select-Object -Unique).Count
    }
})

$BtagSummary = @($Rows | Group-Object 'BTag' | Sort-Object Count -Descending | ForEach-Object {
    $ans = @($_.Group | Where-Object { $_.'Yanıt Durumu' -eq 'Yanıtlandı' }).Count
    [pscustomobject]@{
        'BTag' = $_.Name; 'Bildirim' = $_.Count; 'Yanıtlanan' = $ans; 'Yanıtsız' = $_.Count - $ans
        'Yanıt Oranı' = Get-Rate $ans $_.Count
        'Farklı Üye' = @($_.Group | ForEach-Object { $_.'Üye ID' } | Select-Object -Unique).Count
        'Kategoriler' = (@($_.Group | ForEach-Object { $_.Kategori } | Select-Object -Unique) -join ' | ')
    }
})

$Daily = @($Rows | Group-Object { $_.Tarih.ToString('yyyy-MM-dd') } | Sort-Object Name | ForEach-Object {
    $ans = @($_.Group | Where-Object { $_.'Yanıt Durumu' -eq 'Yanıtlandı' }).Count
    $d = $_.Group[0].Tarih
    [pscustomobject]@{
        'Tarih' = $d; 'Gün' = $TrDays[[int]$d.DayOfWeek]; 'Bildirim' = $_.Count; 'Yanıtlanan' = $ans
        'Yanıtsız' = $_.Count - $ans; 'Yanıt Oranı' = Get-Rate $ans $_.Count
        'Farklı Üye' = @($_.Group | ForEach-Object { $_.'Üye ID' } | Select-Object -Unique).Count
    }
})

$Responders = @($Rows | Where-Object { $_.'Yanıtlayan' -and $_.'Yanıtlayan' -notlike '(*' } |
    ForEach-Object { $row = $_; $row.'Yanıtlayan' -split ',\s*' | ForEach-Object { [pscustomobject]@{ Kisi = $_; Row = $row } } } |
    Group-Object Kisi | Sort-Object Count -Descending | ForEach-Object {
        $m = @($_.Group | ForEach-Object { $_.Row.'Yanıt Süresi (dk)' } | Where-Object { $null -ne $_ })
        [pscustomobject]@{
            'Yanıtlayan' = $_.Name; 'Yanıt Sayısı' = $_.Count
            'Ort. Yanıt (dk)' = $(if ($m.Count) { [math]::Round(($m | Measure-Object -Average).Average, 1) } else { $null })
            'İlk Yanıt' = ($_.Group | ForEach-Object { $_.Row.'Yanıt Tarihi' } | Sort-Object | Select-Object -First 1)
            'Son Yanıt' = ($_.Group | ForEach-Object { $_.Row.'Yanıt Tarihi' } | Sort-Object | Select-Object -Last 1)
        }
    })

$answered = @($Rows | Where-Object { $_.'Yanıt Durumu' -eq 'Yanıtlandı' }).Count
$Info = @(
    [pscustomobject]@{ Alan = 'Workspace';         Değer = [string]$auth.team }
    [pscustomobject]@{ Alan = 'Kanal';             Değer = "#$ChannelName ($Channel)" }
    [pscustomobject]@{ Alan = 'Gönderen filtresi'; Değer = $(if ($BotName) { "$BotName ($filteredOut başka mesaj atlandı)" } else { 'yok' }) }
    [pscustomobject]@{ Alan = 'Çekim zamanı';      Değer = (Get-Date).ToString('dd.MM.yyyy HH:mm') }
    [pscustomobject]@{ Alan = 'Saat dilimi';       Değer = $Tz.Id }
    [pscustomobject]@{ Alan = 'İstenen aralık';    Değer = "$(if ($Start) { $Start } else { 'başlangıç' }) -> $(if ($End) { $End } else { 'bugün' })" }
    [pscustomobject]@{ Alan = 'Bildirim sayısı';   Değer = $Rows.Count }
    [pscustomobject]@{ Alan = 'Yanıtlanan';        Değer = $answered }
    [pscustomobject]@{ Alan = 'Yanıtsız';          Değer = $Rows.Count - $answered }
    [pscustomobject]@{ Alan = 'Farklı üye';        Değer = @($Rows | ForEach-Object { $_.'Üye ID' } | Select-Object -Unique).Count }
    [pscustomobject]@{ Alan = 'Farklı BTag';       Değer = @($Rows | ForEach-Object { $_.BTag } | Select-Object -Unique).Count }
    [pscustomobject]@{ Alan = 'Diğer mesaj';       Değer = $Others.Count }
    [pscustomobject]@{ Alan = 'API çağrısı';       Değer = $script:ApiCalls }
    [pscustomobject]@{ Alan = 'Not';               Değer = 'Bildirimler sayfasında kırmızı satır = thread yanıtı yok. Yanıt Süresi = bildirim ile ilk yanıt arasındaki dakika.' }
)

$Sheets = [ordered]@{
    'Bildirimler'    = @($Rows)
    'Kategori Özeti' = $CatSummary
    'BTag Özeti'     = $BtagSummary
    'Günlük'         = $Daily
    'Yanıtlayanlar'  = $Responders
    'Diğer Mesajlar' = @($Others)
    'Bilgi'          = $Info
}

# ---------------------------------------------------------------- Excel
if (-not $Output) {
    $tag = if ($Start -or $End) { "$(if ($Start) { $Start } else { 'bas' })_$(if ($End) { $End } else { 'bugun' })" } else { (Get-Date).ToString('yyyyMMdd_HHmm') }
    $Output = Join-Path $ScriptDir ("gala_{0}_{1}.xlsx" -f ($ChannelName -replace '[^\w\-]', '_'), $tag)
}
if (Test-Path $Output) { Remove-Item $Output -Force }

function Initialize-ImportExcel {
    if (Get-Module -ListAvailable -Name ImportExcel) { Import-Module ImportExcel -ErrorAction Stop; return $true }
    try {
        Write-Host "ImportExcel modülü kuruluyor (tek seferlik, PowerShell Gallery)..." -ForegroundColor Cyan
        try { $null = Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force -Scope CurrentUser -ErrorAction Stop } catch { }
        Install-Module ImportExcel -Scope CurrentUser -Force -AllowClobber -ErrorAction Stop
        Import-Module ImportExcel -ErrorAction Stop
        return $true
    }
    catch { Write-Warning "ImportExcel kurulamadı: $($_.Exception.Message)"; return $false }
}

function Write-WithImportExcel {
    $widths = @{ 'Kategori' = 42; 'Açıklama' = 60; 'Yanıt' = 60; 'Diğer Yanıtlar' = 45; 'Tam Metin' = 50; 'Mesaj' = 80; 'Kategoriler' = 60; 'Değer' = 90 }
    foreach ($name in $Sheets.Keys) {
        $data = @($Sheets[$name])
        if ($data.Count -eq 0) { $data = @([pscustomobject]@{ 'Bilgi' = '(kayıt yok)' }) }
        $tbl = ($name -replace '[^A-Za-z0-9]', '') + 'Tbl'
        $data | Export-Excel -Path $Output -WorksheetName $name -TableName $tbl -TableStyle 'Medium2' -AutoSize -FreezeTopRow -NoNumberConversion '*'
    }
    $pkg = Open-ExcelPackage -Path $Output
    foreach ($ws in $pkg.Workbook.Worksheets) {
        if (-not $ws.Dimension) { continue }
        $rows = $ws.Dimension.Rows
        $cols = $ws.Dimension.Columns
        for ($c = 1; $c -le $cols; $c++) {
            $h = [string]$ws.Cells[1, $c].Value
            if ($widths.ContainsKey($h)) { $ws.Column($c).Width = $widths[$h]; $ws.Column($c).Style.WrapText = $true }
            elseif ($ws.Column($c).Width -gt 40) { $ws.Column($c).Width = 40; $ws.Column($c).Style.WrapText = $true }
            if ($h -in @('Tarih', 'Yanıt Tarihi', 'İlk Yanıt', 'Son Yanıt')) { $ws.Cells[2, $c, $rows, $c].Style.Numberformat.Format = 'dd.mm.yyyy' }
            if ($h -eq 'Yanıt Oranı') { $ws.Cells[2, $c, $rows, $c].Style.Numberformat.Format = '0.0%' }
            if ($h -eq 'Slack Linki') {
                for ($r = 2; $r -le $rows; $r++) {
                    $u = [string]$ws.Cells[$r, $c].Value
                    if ($u -like 'http*') {
                        $ws.Cells[$r, $c].Hyperlink = [uri]$u
                        $ws.Cells[$r, $c].Value = 'Aç'
                        try { $ws.Cells[$r, $c].Style.Font.UnderLine = $true; $ws.Cells[$r, $c].Style.Font.Color.SetColor([System.Drawing.Color]::FromArgb(5, 99, 193)) } catch { }
                    }
                }
                $ws.Column($c).Width = 8
            }
        }
        $ws.Cells[2, 1, $rows, $cols].Style.VerticalAlignment = 'Top'
        if ($ws.Name -eq 'Bildirimler' -and $rows -gt 1) {
            $statusCol = $null
            for ($c = 1; $c -le $cols; $c++) { if ([string]$ws.Cells[1, $c].Value -eq 'Yanıt Durumu') { $statusCol = $c } }
            if ($statusCol) {
                $letter = [OfficeOpenXml.ExcelCellAddress]::GetColumnLetter($statusCol)
                $rng = $ws.Cells[2, 1, $rows, $cols]
                $cf = $ws.ConditionalFormatting.AddExpression($rng)
                $cf.Formula = ('${0}2="YANITSIZ"' -f $letter)
                $cf.Style.Fill.PatternType = 'Solid'
                $cf.Style.Fill.BackgroundColor.Color = [System.Drawing.Color]::FromArgb(253, 226, 226)
            }
        }
    }
    Close-ExcelPackage $pkg
}

function Write-WithExcelCom {
    $xl = New-Object -ComObject Excel.Application
    $xl.Visible = $false; $xl.DisplayAlerts = $false
    try {
        $wb = $xl.Workbooks.Add()
        while ($wb.Worksheets.Count -gt 1) { $wb.Worksheets.Item($wb.Worksheets.Count).Delete() }
        $firstSheet = $true
        foreach ($name in $Sheets.Keys) {
            $data = @($Sheets[$name])
            if ($firstSheet) { $ws = $wb.Worksheets.Item(1); $firstSheet = $false }
            else { $ws = $wb.Worksheets.Add([Type]::Missing, $wb.Worksheets.Item($wb.Worksheets.Count)) }
            $ws.Name = $name
            if ($data.Count -eq 0) { $ws.Cells.Item(1, 1).Value2 = '(kayıt yok)'; continue }
            $props = @($data[0].PSObject.Properties.Name)
            $arr = [Array]::CreateInstance([object], ($data.Count + 1), $props.Count)
            for ($c = 0; $c -lt $props.Count; $c++) { $arr[0, $c] = $props[$c] }
            for ($r = 0; $r -lt $data.Count; $r++) {
                for ($c = 0; $c -lt $props.Count; $c++) {
                    $v = $data[$r].($props[$c])
                    if ($v -is [datetime]) { $arr[($r + 1), $c] = $v }
                    elseif ($null -eq $v) { $arr[($r + 1), $c] = '' }
                    elseif ($v -is [int] -or $v -is [double] -or $v -is [long] -or $v -is [decimal]) { $arr[($r + 1), $c] = $v }
                    else { $s = [string]$v; if ($s -match '^[=+\-@]') { $s = "'" + $s }; $arr[($r + 1), $c] = $s }
                }
            }
            $rng = $ws.Range($ws.Cells.Item(1, 1), $ws.Cells.Item($data.Count + 1, $props.Count))
            $rng.Value2 = $arr
            $ws.Rows.Item(1).Font.Bold = $true
            $ws.Rows.Item(1).Interior.Color = 0x64381F   # BGR: 1F3864
            $ws.Rows.Item(1).Font.Color = 0xFFFFFF
            $null = $ws.Columns.AutoFit()
            for ($c = 1; $c -le $props.Count; $c++) { if ($ws.Columns.Item($c).ColumnWidth -gt 60) { $ws.Columns.Item($c).ColumnWidth = 60; $ws.Columns.Item($c).WrapText = $true } }
            try { $null = $rng.AutoFilter() } catch { }
            if ($name -eq 'Bildirimler') {
                $sc = [array]::IndexOf($props, 'Yanıt Durumu') + 1
                if ($sc -gt 0) {
                    for ($r = 0; $r -lt $data.Count; $r++) {
                        if ($data[$r].'Yanıt Durumu' -eq 'YANITSIZ') { $ws.Rows.Item($r + 2).Interior.Color = 0xE2E2FD }
                    }
                }
            }
        }
        $wb.Worksheets.Item(1).Activate()
        $wb.SaveAs($Output, 51)   # 51 = xlsx
        $wb.Close($false)
    }
    finally {
        $xl.Quit()
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($xl)
    }
}

function Write-AsCsv {
    $base = [IO.Path]::Combine([IO.Path]::GetDirectoryName($Output), [IO.Path]::GetFileNameWithoutExtension($Output))
    $files = @()
    foreach ($name in $Sheets.Keys) {
        $f = "{0}_{1}.csv" -f $base, ($name -replace '[^\w\-]', '_')
        @($Sheets[$name]) | Export-Csv -Path $f -NoTypeInformation -Encoding UTF8 -Delimiter ';'
        $files += $f
    }
    return $files
}

Write-Host "Excel yazılıyor..." -ForegroundColor Cyan
$written = $null
if (Initialize-ImportExcel) {
    try { Write-WithImportExcel; $written = $Output }
    catch { Write-Warning "ImportExcel ile yazılamadı: $($_.Exception.Message)" }
}
if (-not $written) {
    try { Write-WithExcelCom; $written = $Output }
    catch { Write-Warning "Excel (COM) ile yazılamadı: $($_.Exception.Message)" }
}
if (-not $written) {
    $files = Write-AsCsv
    Write-Host "Excel yazılamadı; CSV olarak kaydedildi (Excel'de Veri > Metinden içe aktar, ayraç ';'):" -ForegroundColor Yellow
    $files | ForEach-Object { Write-Host "  $_" }
    return
}

Write-Host ""
Write-Host ("Bitti: {0} bildirim ({1} yanıtlı, {2} yanıtsız), {3} diğer mesaj." -f $Rows.Count, $answered, ($Rows.Count - $answered), $Others.Count) -ForegroundColor Green
Write-Host "Excel dosyası: $written" -ForegroundColor Green
