# kote

Slack yönetim scriptleri.

## slack/Add-SlackUserGroupMember.ps1

Bir kullanıcıyı e-posta adresiyle bir Slack user group'a (`@etiket`) ekler.

```powershell
$env:SLACK_BOT_TOKEN = "xoxb-..."          # token'ı koda gömme, ortam değişkeninden oku
.\slack\Add-SlackUserGroupMember.ps1 -Email "ali@firma.com" -GroupHandle "petra"
```

Gereken bot scope'ları: `usergroups:read`, `usergroups:write`, `users:read`, `users:read.email`.

### Farklı workspace'teki kullanıcı (bzone.slack.com -> azone.slack.com)

Slack'te user group üyeliği **workspace'e bağlıdır**. Kişi hedef workspace'in tam üyesi değilse
hiçbir API çağrısı onu o workspace'teki gruba ekleyemez (`users_not_found` / `invalid_users`).
Guest hesaplar ve Slack Connect üzerinden gelen dış kullanıcılar da user group'a alınamaz.

| Durum | Ne yapmalı |
|---|---|
| İki bağımsız workspace | Kişiyi hedef workspace'e **tam üye** olarak davet et, sonra scripti çalıştır. |
| Enterprise Grid (aynı org) | `$env:SLACK_ORG_ADMIN_TOKEN` (org seviyesinde app, `admin.users:write`) ver; script `admin.users.assign` ile kişiyi önce workspace'e ekler, sonra gruba alır. |

Script `auth.test` çıktısındaki `enterprise_id` alanına bakarak hangi durumda olduğunu kendisi söyler.
