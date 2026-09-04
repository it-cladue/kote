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

## slack/Get-SlackUserGroupVisibility.ps1

Bir user group'un (`@etiket`) hangi workspace'lerde görünür/etiketlenebilir olduğunu raporlar ve
duruma göre ne yapılacağını yazar. **Hiçbir şeyi değiştirmez**, sadece okur.

```powershell
$env:SLACK_BOT_TOKEN       = "xoxb-..."   # bakılan workspace'in bot token'ı (usergroups:read)
$env:SLACK_ORG_ADMIN_TOKEN = "xoxp-..."   # opsiyonel, Grid'de tüm org'u taramak için (admin.teams:read, usergroups:read)
.\slack\Get-SlackUserGroupVisibility.ps1 -GroupHandle "petra"
```

### "@etiketimizi diğer zone'daki birimler göremiyor, bizi etiketleyemiyor"

Slack'te user group **workspace nesnesidir**. Bir workspace'te açılmış `@petra` başka bir workspace'in
otomatik tamamlamasında çıkmaz, oradan etiketlenemez. "Herkese aç / görünür yap" gibi bir görünürlük
anahtarı **yoktur**; talep sahibi "kimseyi eklemeyin, sadece görünsün" dese de teknik olarak yalnızca
aşağıdaki iki yol vardır. Hangi durumda olduğunu script `auth.test` çıktısındaki `enterprise_id`'den söyler.

| Durum | Ne yapmalı |
|---|---|
| **Enterprise Grid (aynı org)** | Workspace grubu org-level'a **dönüştürülemez**; yenisini aç: Org Owner/Admin ile `admin.slack.com` > **Organization settings > People > Groups > Create Group** > ad `petra`, **"Make this group mentionable in Slack"** işaretli > *Create and Continue to Members* > üyeleri seç > *Save*. Eski workspace-level `@petra`'yı devre dışı bırak ya da handle'ını değiştir (çakışma). Sonradan görünürlük: grup > `...` > *Edit group visibility*. |
| **İki bağımsız workspace** | Tek yol **ayna grup**: ekibi hedef workspace'e **tam üye** olarak davet et, orada `@petra` aç, `Add-SlackUserGroupMember.ps1` ile doldur. Slack Connect kanallarında dış taraf user group'ları göremez/etiketleyemez; orada `@channel`/`@here` kullanılır. |

Etiket görünür hale gelse bile **bildirim yalnızca kanalda olan grup üyelerine gider**. Ekip üyeleri o
workspace'in üyesi değilse kanala davet edilemezler; ya kişileri o workspace'e de ekle
(`admin.slack.com` > *Manage members* > *Add to workspace*, ya da `SLACK_ORG_ADMIN_TOKEN` ile
`Add-SlackUserGroupMember.ps1`) ya da ilgili kanalları **multi-workspace kanal** yap.

Notlar:
- Org-level gruplar yalnızca admin dashboard'dan yönetilir; `usergroups.*` API'si ile açılamaz,
  `admin.usergroups.addTeams` ise IDP (SCIM) grupları içindir, normal user group'a uygulanmaz.
- Guest hesaplar user group'a alınamaz.
- Hangi workspace'te kimin user group açabileceği: *Workspace Settings > Permissions > User Groups*.
