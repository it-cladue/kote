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

#### Bağımsız workspace ve ekibi hedef workspace'e üye olarak ekleyemiyorsan

Ayna grup düşer; user group sınırı hiçbir ayarla aşılamaz (guest de olmaz, guest user group'a alınamaz).
Geriye Slack Connect kanalı üzerinden "etiket gibi davranan" çözümler kalır, tercih sırasıyla:

1. **Slack Connect kanalı + "My keywords"** (sıfır maliyet, ~10 dk). İki zone arasında paylaşımlı bir kanal aç
   (ör. `#cozum-talepleri`), Çözüm ekibinin tamamı kanalda olsun. Diğer birimler kanala `@petra ...` yazar;
   grup orada olmadığı için düz metin kalır. Çözüm ekibindeki **her kişi** kendi Slack'inde
   *Preferences > Notifications > My keywords* alanına `petra` ekler; kelime geçince mention gibi bildirim alır.
   Sınırlar: yalnızca kanal ana akışı (**thread'de çalışmaz**), yalnızca üye olunan kanallar, kişi başı elle ayar,
   eski zone tarafında otomatik tamamlama çıkmaz (kullanıcılar `@petra` yazmayı bilmeli).
2. **Slack Connect kanalı + köprü bot** (yeni zone'a kurulur, eski zone'da kurulum gerekmez). Yeni zone'daki bir app
   paylaşımlı kanala eklenir; mesajda düz metin `@petra` görünce thread'e gerçek `<!subteam^S…|@petra>` mention'ı
   ile yanıt yazar. Ekip gerçek etiket bildirimi alır, thread'de de çalışır. Sürekli çalışan bir host gerekir
   (Socket Mode ile dışa açık endpoint gerekmez). Scope'lar: `channels:history`, `groups:history`, `chat:write`,
   `usergroups:read`.
3. **Ara çözüm, kurulumsuz**: paylaşımlı kanalda `@here` (kanal izni açıksa) ya da ekipten 1-2 kişiyi isimle
   etiketlemek. Slack Connect'te dış kullanıcılar isimle etiketlenebilir; user group etiketlenemez.

Yapısal çözüm hâlâ Enterprise Grid (org-level grup) ya da ekibin eski zone'a tam üyeliğidir; ikisi de yoksa 1 ya da 2.

Etiket görünür hale gelse bile **bildirim yalnızca kanalda olan grup üyelerine gider**. Ekip üyeleri o
workspace'in üyesi değilse kanala davet edilemezler; ya kişileri o workspace'e de ekle
(`admin.slack.com` > *Manage members* > *Add to workspace*, ya da `SLACK_ORG_ADMIN_TOKEN` ile
`Add-SlackUserGroupMember.ps1`) ya da ilgili kanalları **multi-workspace kanal** yap.

Notlar:
- Org-level gruplar yalnızca admin dashboard'dan yönetilir; `usergroups.*` API'si ile açılamaz,
  `admin.usergroups.addTeams` ise IDP (SCIM) grupları içindir, normal user group'a uygulanmaz.
- Guest hesaplar user group'a alınamaz.
- Hangi workspace'te kimin user group açabileceği: *Workspace Settings > Permissions > User Groups*.

## slack/mention-bridge (Etiket Köprüsü)

Bağımsız iki workspace arasında, Slack Connect kanalında düz metin olarak yazılan `@petra` gibi bir etiketi
**gerçek** user group / kişi mention'ına çeviren küçük bir bot. `@petra`'nın olduğu workspace'e (yeni zone)
kurulur; eski zone'da hiçbir kurulum ve yetki gerekmez. Socket Mode kullanır, dışa açık endpoint istemez.

Akış: eski zone'dan biri paylaşımlı kanala `@petra sunucu düştü` yazar → grup o workspace'te olmadığı için
düz metin kalır → bot mesajı görür, aynı thread'e `@petra <yazan kişi> sizi etiketledi.` yazar → bu kez
mention gerçek olduğu için Çözüm ekibi normal etiket bildirimi alır. Thread'lerde de çalışır.

### Etiketler ve kime gideceği: `config.json`

Bir keyword birden fazla hedefe gidebilir, hedefler karışık olabilir; istediğin kadar keyword tanımlanır.

```json
{
  "keywords": {
    "petra":  ["petra"],
    "kote":   ["kote", "mehmet@firma.com"],
    "fransa": ["ali@firma.com", "ayse@firma.com"],
    "paris":  "paris"
  },
  "channels": [],
  "reply_mode": "thread",
  "require_at": true,
  "reply_template": "{mentions} {author} sizi etiketledi."
}
```

| Alan | Anlamı |
|---|---|
| `keywords` | Kanalda yazılan `@kelime` → hedef listesi. Hedef: user group handle'ı (`petra` ya da `@petra`), e-posta (`ali@firma.com`) ya da Slack kullanıcı ID'si (`U0123ABCD`). Tek hedefse düz string yazılabilir. |
| `channels` | Boşsa botun eklendiği her kanalda çalışır. Sadece belirli kanallar istenirse kanal ID'leri (`C…`) yazılır. |
| `reply_mode` | `thread` (varsayılan): mesajın thread'ine yazar, kanal kirlenmez. `channel`: kanala ayrı mesaj atar. |
| `require_at` | `true`: yalnızca `@petra` tetikler. `false`: düz `petra` kelimesi de tetikler (yanlış pozitif riski). |
| `reply_template` | `{mentions}` zorunlu, `{author}` isteğe bağlı. |

`config.json` kaydedilince bot yeniden başlatılmadan yeni ayarı alır. Yeni açılan user group / kişi en geç
15 dakikada görülür. Gerçek mention (`<!subteam^…>`) içeren mesajlar tetiklemez, ekip iki kez bildirim almaz.

### Kurulum, adım adım

1. **App'i oluştur.** [api.slack.com/apps](https://api.slack.com/apps) > *Create New App* > *From a manifest* >
   workspace olarak **`@petra`'nın olduğu workspace'i** seç > JSON sekmesine `slack/mention-bridge/manifest.json`
   içeriğini yapıştır > *Create*. Scope'lar, event'ler ve Socket Mode manifestten gelir.
2. **Workspace'e kur.** *Install to Workspace* > izinleri onayla. *OAuth & Permissions* > **Bot User OAuth Token**
   (`xoxb-…`) kopyala.
3. **App-level token al.** *Basic Information* > *App-Level Tokens* > *Generate Token and Scopes* > ad `socket`,
   scope `connections:write` > *Generate* > `xapp-…` kopyala.
4. **Botu kur.** Sürekli açık bir makinede Node.js 20+ olsun. Repo'yu alıp:
   ```powershell
   cd .\slack\mention-bridge
   npm install
   Copy-Item config.example.json config.json    # sonra keywords bölümünü düzenle
   ```
5. **Çalıştır ve doğrula.**
   ```powershell
   $env:SLACK_BOT_TOKEN = "xoxb-..."
   $env:SLACK_APP_TOKEN = "xapp-..."
   npm start
   ```
   Çıktıda `Workspace: … bot: …`, `config yüklendi: @petra, …` ve `Hedefler çözüldü: N user group, M kişi`
   görünmeli. `@x diye bir user group yok` uyarısı varsa handle'ı düzelt.
6. **Botu paylaşımlı kanala ekle.** Kanalda `/invite @Etiket Köprüsü` yaz (ya da kanal adı > *Integrations* >
   *Add apps*). Slack Connect kanalında bunu **yeni zone tarafından** biri yapmalı. Bot yalnızca eklendiği
   kanalları görür.
7. **Test et.** Eski zone'dan biri kanala `@petra test` yazsın. Thread'e bot yanıtı gelmeli, Çözüm ekibi
   bildirim almalı. Gelmiyorsa aşağıdaki *Sorun giderme*.
8. **Servis yap.** Windows'ta [NSSM](https://nssm.cc) ile:
   ```powershell
   nssm install EtiketKoprusu "C:\Program Files\nodejs\node.exe" "C:\kote\slack\mention-bridge\app.js"
   nssm set EtiketKoprusu AppDirectory "C:\kote\slack\mention-bridge"
   nssm set EtiketKoprusu AppEnvironmentExtra SLACK_BOT_TOKEN=xoxb-... SLACK_APP_TOKEN=xapp-...
   nssm set EtiketKoprusu AppStdout "C:\kote\logs\bridge.log"
   nssm set EtiketKoprusu AppStderr "C:\kote\logs\bridge.log"
   nssm start EtiketKoprusu
   ```
   Linux'ta `pm2 start app.js --name etiket-koprusu` ya da bir systemd unit yeterli.

Geliştirme: `npm test` (Slack'e bağlanmadan eşleştirme ve config mantığını test eder), `BRIDGE_DEBUG=1` ile
ayrıntılı log, `BRIDGE_CONFIG=<yol>` ile farklı config dosyası.

### Sorun giderme

| Belirti | Sebep / çözüm |
|---|---|
| Bot hiç yanıt vermiyor | Bot kanala eklenmemiş (`/invite`). `channels` listesi doluysa kanal ID'si orada mı? `BRIDGE_DEBUG=1` ile event geliyor mu bak. Karşı org Slack Connect kanallarında app kısıtlamış olabilir. |
| `not_in_channel` | Bot kanala eklenmemiş. |
| `@petra diye bir user group bu workspace'te yok` | Handle yanlış, grup devre dışı ya da token başka workspace'e ait (`Get-SlackUserGroupVisibility.ps1` ile bak). |
| `x@firma.com bulunamadı` | Kişi bu workspace'te yok ya da `users:read.email` scope'u eksik (manifestten kurulduysa var). |
| Yanıt geliyor ama ekip bildirim almıyor | User group mention'ı yalnızca **kanalda olan** üyelere gider; ekibin tamamı kanala eklensin. Kişisel bildirim ayarlarında grup mention'ları kapalı olabilir. |
| `invalid_auth` / `not_allowed_token_type` | `xoxb` ile `xapp` yer değişmiş ya da token başka app/workspace'e ait. |
| Aynı mesaja iki yanıt | Botun iki kopyası çalışıyor (servis + elle başlatılan). |
