<#
.SYNOPSIS
    Bir Slack kullanıcısını e-posta adresiyle bir user group'a (@etiket) ekler.

.DESCRIPTION
    Adımlar:
      1. auth.test               -> token hangi workspace'e ait, Enterprise Grid mi?
      2. users.lookupByEmail     -> kullanıcı BU workspace'te var mı?
                                    Yoksa: Grid + org admin token varsa admin.users.assign ile
                                    workspace'e ekler; yoksa ne yapman gerektiğini söyleyip durur.
      3. usergroups.list         -> @handle'dan grup ID'sini bulur
      4. usergroups.users.update -> mevcut üyeler + yeni kullanıcı
                                    (bu method listeyi KOMPLE değiştirir, o yüzden mevcutlar korunur)

    Gereken bot scope'ları (api.slack.com/apps > OAuth & Permissions > Bot Token Scopes):
        usergroups:read  usergroups:write  users:read  users:read.email
    Scope ekledikten sonra "Reinstall to Workspace" yapmayı unutma.

    Enterprise Grid'de başka workspace'teki kullanıcıyı bu workspace'e çekmek için ayrıca
    org seviyesinde kurulu bir app'in USER token'ı gerekir (admin.users:write, users:read.email):
        $env:SLACK_ORG_ADMIN_TOKEN = "xoxp-..."

.EXAMPLE
    $env:SLACK_BOT_TOKEN = "xoxb-..."
    .\Add-SlackUserGroupMember.ps1 -Email "ali@firma.com" -GroupHandle "petra"

.EXAMPLE
    # Enterprise Grid: kullanıcı başka workspace'te; önce bu workspace'e ekle, sonra gruba al
    $env:SLACK_BOT_TOKEN       = "xoxb-..."
    $env:SLACK_ORG_ADMIN_TOKEN = "xoxp-..."
    .\Add-SlackUserGroupMember.ps1 -Email "ali@firma.com" -GroupHandle "petra"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $Email,
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

# Slack'in döndürdüğü hata kodlarının Türkçe açıklaması
$ErrorHelp = @{
    invalid_auth               = "Token geçersiz ya da başka bir workspace'e ait."
    not_authed                 = "Token gönderilmedi."
    token_revoked              = "Token iptal edilmiş. Slack App > OAuth & Permissions > Reinstall ile yenisini al."
    account_inactive           = "Bot ya da kullanıcı devre dışı."
    missing_scope              = "App'te eksik scope var. Bot Token Scopes'a usergroups:read, usergroups:write, users:read, users:read.email ekle ve Reinstall yap."
    plan_upgrade_required      = "User group sadece ücretli planlarda (Pro / Business+ / Grid) var. Free plan desteklemiyor."
    permission_denied          = "Workspace ayarı user group yönetimini sadece Owner/Admin'e veriyor. Workspace Settings > Permissions > User Groups ayarını genişlet ya da scripti admin'in user token'ı (xoxp) ile çalıştır."
    invalid_users              = "Verilen kullanıcı ID bu workspace'in TAM üyesi değil (başka workspace'ten, guest ya da silinmiş)."
    no_such_subteam            = "Böyle bir user group yok."
    subteam_max_users_exceeded = "Gruptaki üye limiti aşıldı."
    users_not_found            = "Bu e-posta bu workspace'te kayıtlı değil."
    feature_not_enabled        = "Bu method sadece Enterprise Grid'de çalışır; burası bağımsız bir workspace."
    not_an_admin               = "Org token'ının sahibi Org Owner/Admin değil."
    user_not_found             = "Kullanıcı bulunamadı."
    team_not_found             = "Workspace ID bulunamadı."
    ratelimited                = "Rate limit. Biraz bekleyip tekrar dene."
}

function Invoke-Slack {
    param(
        [Parameter(Mandatory = $true)] [string] $Method,
        [hashtable] $Params    = @{},
        [string]    $AuthToken = $Token,
        [string[]]  $Ignore    = @()
    )
    $r = Invoke-RestMethod -Uri "https://slack.com/api/$Method" -Method Post `
        -Headers @{ Authorization = "Bearer $AuthToken" } `
        -ContentType 'application/x-www-form-urlencoded; charset=utf-8' `
        -Body $Params
    if (-not $r.ok -and ($Ignore -notcontains [string]$r.error)) {
        $hint = $ErrorHelp[[string]$r.error]
        if ($r.needed) { $hint = "$hint (gereken scope: $($r.needed))" }
        throw "Slack $Method hatası: $($r.error). $hint"
    }
    return $r
}

# 1) Token kime ait, Grid mi?
$me     = Invoke-Slack 'auth.test'
$teamId = $me.team_id
$isGrid = -not [string]::IsNullOrEmpty($me.enterprise_id)
Write-Host "Workspace       : $($me.team)  ($teamId)  $($me.url)"
if ($isGrid) { Write-Host "Enterprise Grid : EVET  (org: $($me.enterprise_id))" }
else         { Write-Host "Enterprise Grid : HAYIR (bağımsız workspace)" }

# 2) Kullanıcı bu workspace'te var mı?
$lookup = Invoke-Slack 'users.lookupByEmail' @{ email = $Email } -Ignore 'users_not_found'
if ($lookup.ok) {
    $user = $lookup.user
}
elseif ($isGrid -and -not [string]::IsNullOrWhiteSpace($OrgAdminToken)) {
    Write-Host "$Email bu workspace'te yok; org token'ı ile $($me.team) workspace'ine ekleniyor..."
    $orgUser = (Invoke-Slack 'users.lookupByEmail' @{ email = $Email } -AuthToken $OrgAdminToken).user
    $null    = Invoke-Slack 'admin.users.assign' @{ team_id = $teamId; user_id = $orgUser.id } -AuthToken $OrgAdminToken
    $user    = (Invoke-Slack 'users.lookupByEmail' @{ email = $Email }).user
}
else {
    Write-Host ""
    Write-Host "DURDU: $Email bu workspace'in ($($me.team)) üyesi değil." -ForegroundColor Yellow
    Write-Host "User group üyeliği workspace'e bağlıdır; kişi önce bu workspace'e TAM ÜYE olarak girmeli."
    if ($isGrid) {
        Write-Host "  Enterprise Grid: admin.slack.com > Manage members > kişiyi seç > Add to workspace ($($me.team))"
        Write-Host "  ya da bu scripti SLACK_ORG_ADMIN_TOKEN (admin.users:write) ile çalıştır, otomatik ekler."
    }
    else {
        Write-Host "  Bağımsız workspace: Slack'te $($me.team) > Invite people > $Email  (tam üye olarak, guest DEĞİL)."
        Write-Host "  Davet kabul edilince scripti tekrar çalıştır."
    }
    exit 1
}

if ($user.is_restricted -or $user.is_ultra_restricted) {
    throw "$Email bu workspace'te guest ($($user.id)). Slack guest'leri user group'a almaz; önce tam üye yap."
}
if ($user.deleted) {
    throw "$Email ($($user.id)) devre dışı bırakılmış (deactivated)."
}
Write-Host "Kullanıcı       : $($user.real_name) <$Email>  ($($user.id))"

# 3) Grubu bul
$groups = Invoke-Slack 'usergroups.list' @{ include_users = 'true'; include_disabled = 'true' }
$group  = $groups.usergroups | Where-Object { $_.handle -eq $GroupHandle } | Select-Object -First 1
if (-not $group) {
    $have = ($groups.usergroups | ForEach-Object { '@' + $_.handle }) -join ', '
    throw "@$GroupHandle diye bir user group bu workspace'te yok. Mevcutlar: $have"
}
if ($group.date_delete -ne 0) {
    Write-Host "@$GroupHandle devre dışıydı, aktif ediliyor..."
    $null = Invoke-Slack 'usergroups.enable' @{ usergroup = $group.id }
}
$current = @($group.users)
Write-Host "User group      : @$($group.handle)  ($($group.id))  mevcut üye: $($current.Count)"

# 4) Ekle (mevcut liste + yeni; update tüm listeyi değiştirdiği için mevcutlar korunur)
if ($current -contains $user.id) {
    Write-Host "Zaten üye, değişiklik yok." -ForegroundColor Green
    exit 0
}
$members = @($current + $user.id | Select-Object -Unique)
$result  = Invoke-Slack 'usergroups.users.update' @{ usergroup = $group.id; users = ($members -join ',') }
Write-Host "TAMAM: $Email -> @$($result.usergroup.handle)  (toplam üye: $(@($result.usergroup.users).Count))" -ForegroundColor Green
