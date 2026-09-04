<#
.SYNOPSIS
    Bir Slack user group'un (@etiket) hangi workspace'lerde görünür / etiketlenebilir olduğunu raporlar.
    Hiçbir şeyi DEĞİŞTİRMEZ; sadece okur ve ne yapman gerektiğini söyler.

.DESCRIPTION
    Tipik talep: "Etiketimiz @petra diğer zone'daki (workspace'teki) birimler tarafından görünmüyor,
    bizi etiketleyemiyorlar." Slack'te user group WORKSPACE nesnesidir; "herkese aç" gibi bir
    görünürlük anahtarı yoktur. Çözüm kurulumun türüne göre değişir, bu script onu tespit eder:

      1. auth.test                       -> token hangi workspace'e ait, Enterprise Grid mi?
      2. usergroups.list                 -> @handle BU workspace'te var mı, org-level mi (enterprise_subteam_id)?
      3. admin.teams.list + usergroups.list (team_id=...)
                                         -> (Grid + org token varsa) org'daki HER workspace'te aynı @handle
                                            var mı, org-level mi? Tablo halinde basar.
      4. Karar                           -> duruma göre yapılacak adımları yazar.

    Gereken scope'lar:
        Bot token (xoxb) : usergroups:read
        Org token  (xoxp, org seviyesinde kurulu app, opsiyonel) : admin.teams:read, usergroups:read

.EXAMPLE
    $env:SLACK_BOT_TOKEN = "xoxb-..."
    .\Get-SlackUserGroupVisibility.ps1 -GroupHandle "petra"

.EXAMPLE
    # Enterprise Grid: org'daki tüm workspace'leri tara
    $env:SLACK_BOT_TOKEN       = "xoxb-..."
    $env:SLACK_ORG_ADMIN_TOKEN = "xoxp-..."
    .\Get-SlackUserGroupVisibility.ps1 -GroupHandle "petra"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $GroupHandle,
    [string] $Token         = $env:SLACK_BOT_TOKEN,
    [string] $OrgAdminToken = $env:SLACK_ORG_ADMIN_TOKEN
)

$ErrorActionPreference = 'Stop'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }

if ([string]::IsNullOrWhiteSpace($Token)) {
    throw 'Token yok. Önce çalıştır:  $env:SLACK_BOT_TOKEN = "xoxb-..."'
}
$GroupHandle = $GroupHandle.TrimStart('@')

$ErrorHelp = @{
    invalid_auth           = "Token geçersiz ya da başka bir workspace'e ait."
    not_authed             = "Token gönderilmedi."
    token_revoked          = "Token iptal edilmiş. Slack App > OAuth & Permissions > Reinstall ile yenisini al."
    account_inactive       = "Bot ya da kullanıcı devre dışı."
    missing_scope          = "App'te eksik scope var (bot: usergroups:read; org token: admin.teams:read, usergroups:read). Ekleyip Reinstall yap."
    plan_upgrade_required  = "User group sadece ücretli planlarda (Pro / Business+ / Grid) var."
    feature_not_enabled    = "Bu method sadece Enterprise Grid'de çalışır; burası bağımsız bir workspace."
    not_an_admin           = "Org token'ının sahibi Org Owner/Admin değil."
    not_allowed_token_type = "Bu method bu token tipiyle çağrılamaz (org seviyesinde kurulu app'in token'ı gerekir)."
    team_not_found         = "Workspace ID bulunamadı."
    ratelimited            = "Rate limit. Biraz bekleyip tekrar dene."
}

function Invoke-Slack {
    param(
        [Parameter(Mandatory = $true)] [string] $Method,
        [hashtable] $Params    = @{},
        [string]    $AuthToken = $Token
    )
    $r = Invoke-RestMethod -Uri "https://slack.com/api/$Method" -Method Post `
        -Headers @{ Authorization = "Bearer $AuthToken" } `
        -ContentType 'application/x-www-form-urlencoded; charset=utf-8' `
        -Body $Params
    if (-not $r.ok) {
        $hint = $ErrorHelp[[string]$r.error]
        if ($r.needed) { $hint = "$hint (gereken scope: $($r.needed))" }
        throw "Slack $Method hatası: $($r.error). $hint"
    }
    return $r
}

# Org-level (enterprise) user group'larda enterprise_subteam_id dolu gelir; workspace-level'da boş/yok.
function Test-OrgLevelGroup {
    param($Group)
    return -not [string]::IsNullOrEmpty([string]$Group.enterprise_subteam_id)
}

function Find-Group {
    param($List, [string] $Handle)
    return $List.usergroups | Where-Object { $_.handle -eq $Handle } | Select-Object -First 1
}

# 1) Token kime ait, Grid mi?
$me     = Invoke-Slack 'auth.test'
$isGrid = -not [string]::IsNullOrEmpty($me.enterprise_id)
Write-Host "Workspace       : $($me.team)  ($($me.team_id))  $($me.url)"
if ($isGrid) { Write-Host "Enterprise Grid : EVET  (org: $($me.enterprise_id))" }
else         { Write-Host "Enterprise Grid : HAYIR (bağımsız workspace)" }
Write-Host ""

# 2) Grup bu workspace'te var mı, ne tür?
$groups = Invoke-Slack 'usergroups.list' @{ include_disabled = 'true'; include_count = 'true' }
$group  = Find-Group $groups $GroupHandle
if ($group) {
    $kind   = if (Test-OrgLevelGroup $group) { 'ORG-LEVEL' } else { 'WORKSPACE-LEVEL' }
    $state  = if ($group.date_delete -ne 0) { 'DEVRE DIŞI' } else { 'aktif' }
    Write-Host "@$($group.handle) bu workspace'te VAR : $($group.id)  tür: $kind  durum: $state  üye: $($group.user_count)"
}
else {
    $have = ($groups.usergroups | ForEach-Object { '@' + $_.handle }) -join ', '
    Write-Host "@$GroupHandle bu workspace'te YOK. Mevcut gruplar: $have" -ForegroundColor Yellow
}
Write-Host ""

# 3) Grid + org token: org'daki her workspace'i tara
$scan = @()
if ($isGrid -and -not [string]::IsNullOrWhiteSpace($OrgAdminToken)) {
    Write-Host "Org'daki workspace'ler taranıyor..."
    $teams  = @()
    $cursor = ''
    do {
        $p = @{ limit = '100' }
        if ($cursor) { $p.cursor = $cursor }
        $r = Invoke-Slack 'admin.teams.list' $p -AuthToken $OrgAdminToken
        $teams += @($r.teams)
        $cursor = [string]$r.response_metadata.next_cursor
    } while ($cursor)

    foreach ($t in $teams) {
        $row = [pscustomobject]@{ Workspace = $t.name; Id = $t.id; Grup = '-'; Tur = '-'; Durum = '-'; Uye = '-' }
        try {
            $gl = Invoke-Slack 'usergroups.list' @{ team_id = $t.id; include_disabled = 'true'; include_count = 'true' } -AuthToken $OrgAdminToken
            $g  = Find-Group $gl $GroupHandle
            if ($g) {
                $tur       = if (Test-OrgLevelGroup $g) { 'org-level' } else { 'workspace-level' }
                $durum     = if ($g.date_delete -ne 0) { 'devre dışı' } else { 'aktif' }
                $row.Grup  = $g.id
                $row.Tur   = $tur
                $row.Durum = $durum
                $row.Uye   = $g.user_count
            }
            else { $row.Grup = 'YOK' }
        }
        catch {
            $row.Grup = "kontrol edilemedi: $($_.Exception.Message)"
        }
        $scan += $row
    }
    $scan | Format-Table -AutoSize | Out-String | Write-Host
}
elseif ($isGrid) {
    Write-Host "Not: SLACK_ORG_ADMIN_TOKEN verilmedi; diğer workspace'ler taranmadı." -ForegroundColor DarkGray
    Write-Host "     (admin.teams:read + usergroups:read scope'lu org token'ı ile çalıştırırsan tüm org'u tarar.)"
    Write-Host ""
}

# 4) Karar
Write-Host "==== SONUÇ ====" -ForegroundColor Cyan
if (-not $isGrid) {
    Write-Host "Bağımsız workspace. @$GroupHandle yalnızca $($me.team) içinde vardır; başka bir workspace'ten"
    Write-Host "görülmesi ya da etiketlenmesi MÜMKÜN DEĞİLDİR (Slack Connect kanallarında da dış taraf user group göremez)."
    Write-Host "Yapılacak:"
    Write-Host "  1. Ekibi hedef workspace'e TAM ÜYE olarak davet et (guest olmaz)."
    Write-Host "  2. Hedef workspace'te aynı handle ile grup aç: More > People & user groups > User groups > Create User Group."
    Write-Host "  3. Üyeleri doldur:  .\Add-SlackUserGroupMember.ps1 -Email <kişi> -GroupHandle $GroupHandle  (hedef workspace token'ı ile)."
}
elseif ($group -and (Test-OrgLevelGroup $group)) {
    Write-Host "@$GroupHandle ORG-LEVEL bir grup; org'daki tüm workspace'lerde etiketlenebilir olması gerekir."
    Write-Host "Yine de görünmüyorsa sırayla kontrol et:"
    Write-Host "  1. admin.slack.com > Organization settings > People > Groups > @$GroupHandle > ... > Edit group visibility"
    Write-Host "     -> 'mentionable in Slack' AÇIK olmalı."
    Write-Host "  2. Etiketleyen kişi kanalda @$GroupHandle yazınca otomatik tamamlamada çıkmıyorsa istemciyi yenilesin (Ctrl+R / yeniden giriş)."
    Write-Host "  3. Etiket görünüyor ama ekip bildirim almıyorsa: user group mention'ı yalnızca KANALDA olan üyelere gider."
    Write-Host "     Ekip üyeleri o workspace'in üyesi değilse kanala davet edilemez -> ya kişileri o workspace'e ekle"
    Write-Host "     (admin.slack.com > Manage members > Add to workspace) ya da kanalı multi-workspace kanal yap."
}
elseif ($group) {
    Write-Host "@$GroupHandle WORKSPACE-LEVEL bir grup; yalnızca $($me.team) içinde görünür ve etiketlenebilir."
    Write-Host "Diğer workspace'lerden etiketlenebilmesi için ORG-LEVEL grup gerekir (workspace grubu org-level'a DÖNÜŞTÜRÜLEMEZ):"
    Write-Host "  1. Org Owner/Admin ile admin.slack.com > Organization settings > People > Groups > Create Group."
    Write-Host "     Ad: $GroupHandle, 'Make this group mentionable in Slack' işaretli, Create and Continue to Members > üyeleri seç > Save."
    Write-Host "  2. Handle çakışmasın diye bu workspace'teki eski @$GroupHandle grubunu devre dışı bırak ya da handle'ını değiştir"
    Write-Host "     (User groups > @$GroupHandle > Edit / Disable)."
    Write-Host "  3. Bildirim için ekip üyelerinin etiketlendikleri kanalda olması gerekir: kişileri diğer workspace'e de ekle"
    Write-Host "     (admin.slack.com > Manage members > Add to workspace) ya da ilgili kanalları multi-workspace yap."
    Write-Host "  Not: Org-level gruplar yalnızca admin dashboard'dan yönetilir; usergroups.* API'si ve IDP grupları ile birleştirilemez."
}
else {
    Write-Host "@$GroupHandle bu workspace'te yok. Ya yanlış workspace'in token'ı verildi ya da grup başka bir workspace'te."
    if ($scan.Count -gt 0) { Write-Host "Yukarıdaki tabloda hangi workspace'te olduğunu görebilirsin." }
    else { Write-Host "SLACK_ORG_ADMIN_TOKEN ile çalıştırırsan org'daki tüm workspace'leri tarar." }
}
