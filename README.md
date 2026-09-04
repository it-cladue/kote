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
   paylaşımlı kanala eklenir; mesajda düz metin `@petra` görünce grup üyelerine bildirim gönderir. Kanala ve
   thread'e hiçbir şey yazmaz. Thread'de de çalışır. Sürekli çalışan bir host gerekir (Socket Mode ile dışa açık
   endpoint gerekmez). Kurulum: aşağıda *slack/mention-bridge*.
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
ilgili user group'un üyelerine **bildirime** çeviren küçük bir Python botu. `@petra`'nın olduğu workspace'e
(yeni zone) kurulur; eski zone'da hiçbir kurulum ve yetki gerekmez. Socket Mode kullanır, dışa açık endpoint
istemez.

Slack'te "mesaj atmadan bildirim tetikle" diye bir API yoktur; dış organizasyondan gelen `@petra` yazısını
gerçek mention'a çevirmenin de yolu yoktur (mesaj başkasının). Buna en yakın davranış, Slack'in kendi
"kanalda etiketlendiniz" Slackbot mesajı gibi, botun her grup üyesine **birebir DM** göndermesidir:

> **#cozum-talepleri** kanalında **@Ayşe (Finans)** **@petra** etiketini kullandı:
> > sunucu düştü, bakar mısınız
> Mesaja git

Kanala ve thread'e **hiçbir şey yazılmaz**; eski zone tarafı botun varlığını fark etmez. Ekip DM bildirimi alır
(masaüstü/mobil/rozet), linke tıklayıp mesaja gider. Thread içinde yazılan `@petra` da yakalanır, link thread'i
açar. İstenirse `ack_reaction` ile orijinal mesaja küçük bir emoji konur (yazan kişi "ulaştı" görsün diye);
varsayılan kapalı.

### Etiketler ve kime gideceği: `config.json`

Bir keyword birden fazla hedefe gidebilir, hedefler karışık olabilir; istediğin kadar keyword tanımlanır.

```json
{
  "admins": ["yonetici@firma.com"],
  "keywords": {
    "petra":  ["petra"],
    "kote":   ["kote", "mehmet@firma.com"],
    "fransa": ["ali@firma.com", "ayse@firma.com"],
    "paris":  "paris"
  },
  "channels": [],
  "notify_mode": "dm",
  "require_at": true,
  "ack_reaction": ""
}
```

| Alan | Anlamı |
|---|---|
| `admins` | Bota DM'den komut yazabilecek hesaplar (kullanıcı ID'si `U…` ya da e-posta). Boşsa komutlar kapalı. |
| `keywords` | Kanalda yazılan `@kelime` → hedef listesi. Hedef: user group handle'ı (`petra` ya da `@petra`), e-posta (`ali@firma.com`) ya da Slack kullanıcı ID'si (`U0123ABCD`). Tek hedefse düz string yazılabilir. |
| `channels` | **Boşsa (varsayılan) bot eklendiği her kanalda çalışır**; bir kanalda çalışsın istiyorsan botu o kanala ekle, istemiyorsan kanaldan çıkar (`/remove @Etiket Köprüsü`). Sadece belirli kanallarla sınırlamak istersen kanal ID'leri (`C…`) yazılır ya da DM'den `kanal ekle #kanal`. |
| `notify_mode` | `dm` (varsayılan): kanala hiçbir şey yazılmaz, üyelere DM. `thread`: mesajın thread'ine gerçek `@petra` mention'ı yazar. `channel`: kanala ayrı mesaj atar. |
| `require_at` | `true`: yalnızca `@petra` tetikler. `false`: düz `petra` kelimesi de tetikler (yanlış pozitif riski). |
| `ack_reaction` | Boş: iz yok. `bell` gibi bir emoji adı: orijinal mesaja o emoji konur. |
| `dm_template` | İsteğe bağlı. `{channel}` `{author}` `{keyword}` `{quote}` `{link}` alanları; `{link}` zorunlu. |

`config.json` kaydedilince (elle ya da DM komutuyla) bot yeniden başlatılmadan yeni ayarı alır. Yeni açılan
grup en geç 15 dakikada, gruba eklenen/çıkarılan üye en geç 5 dakikada görülür. Yazan kişi grubun üyesiyse kendine DM gitmez. Gerçek
mention (`<!subteam^…>`) içeren mesajlar tetiklemez, ekip iki kez bildirim almaz.

### Yönetim: bota DM'den komut

`config.json` içindeki `admins` listesindeki hesaplar, Slack'te botun DM'ine (sol menü > Apps > Etiket Köprüsü,
ya da arama kutusuna "Etiket Köprüsü") yazarak her şeyi yönetir; dosyaya elle dokunmak gerekmez. Başka herkes
"Bu botu yönetme yetkin yok." yanıtı alır. Kişi ve kanal verirken Slack'in otomatik tamamlamasını kullan
(`@Ali`, `#kanal`); e-posta düz yazılabilir. Komut kelimeleri Türkçe karakter ve büyük/küçük harf duyarsızdır.

| Komut | Ne yapar |
|---|---|
| `yardım` | komut listesi |
| `liste` | tanımlı etiketler ve hedefleri |
| `ekle <etiket> [hedef…]` | etikete hedef ekler, etiket yoksa açar. Hedef: user group handle'ı, e-posta ya da `@kişi`. Hedef verilmezse etiketle aynı adlı grup. Örn. `ekle fransa ali@firma.com @Ayşe` |
| `çıkar <etiket> [hedef…]` | hedef çıkarır; hedef verilmezse etiketi siler |
| `grup liste [handle]` | Slack user group'ları / bir grubun üyeleri |
| `grup oluştur <handle> [ad]` | **Slack'te gerçek user group açar** ve aynı adla etiket tanımlar. Örn. `grup oluştur paris Paris Ekibi` |
| `grup ekle <handle> <kişi…>` | Slack user group'una üye ekler. Örn. `grup ekle paris @Ali ayse@firma.com` |
| `grup çıkar <handle> <kişi…>` | Slack user group'undan üye çıkarır (son üye çıkarılamaz, Slack izin vermez) |
| `kanallar` | botun içinde olduğu kanallar ve filtre |
| `kanal ekle #kanal` / `kanal çıkar #kanal` / `kanal temizle` | filtre; boşken bot eklendiği her kanalda çalışır |
| `mod dm` / `mod thread` / `mod channel` | bildirim biçimi |
| `emoji bell` / `emoji kapat` | orijinal mesaja konacak emoji |
| `yetkili liste` / `yetkili ekle @kişi` / `yetkili çıkar @kişi` | komut kullanabilecekler (kendini ve son yetkiliyi çıkaramazsın) |
| `durum` | workspace, mod, etiketler, çözülen gruplar, yetkililer, Slack'te olmayan gruplar |

Tipik akış, yeni bir ekip için: `grup oluştur paris Paris Ekibi` → `grup ekle paris @Ali @Ayşe` → bitti; artık
kanalda `@paris` yazılınca Ali ve Ayşe bildirim alır. Sadece kişilere gidecek, gerçek grup istemeyen bir etiket
için: `ekle fransa ali@firma.com @Ayşe`.

Not: `grup …` komutları Slack'in kendi user group yetkisine tabidir. Workspace ayarı user group yönetimini
sadece Owner/Admin'e veriyorsa (`Workspace Settings > Permissions > User Groups`) Slack `permission_denied`
döner; ayarı genişlet ya da grubu elle aç.

### Adım adım: yeni zone'da (Çözüm ekibi, `@petra`'nın olduğu workspace)

1. **`@petra` hazır olsun.** *More > People & user groups > User groups* içinde `@petra` var ve üyeleri tam.
   Bot bildirimi bu üye listesine göre gönderir.
2. **Kanal.** Hâlihazırda iki zone arasında paylaşılan bir Slack Connect kanalı varsa **onu kullan**, yeni
   kanal gerekmez; tek yapılacak 8. adımda botu o kanala eklemek. Yoksa: yeni zone'da bir kanal aç, kanal
   adına tıkla > *Share channel* (Slack Connect) > eski zone'dan bir yetkilinin e-postasını yaz ya da davet
   linkini kopyala. Çözüm ekibinin tamamı kanalda olsun (DM'deki link bu kanala gider).
3. **App'i oluştur.** [api.slack.com/apps](https://api.slack.com/apps) > *Create New App* > *From a manifest* >
   workspace olarak **yeni zone'u** seç > JSON sekmesine `slack/mention-bridge/manifest.json` içeriğini yapıştır >
   *Create*. Scope'lar, event'ler ve Socket Mode manifestten gelir.
4. **Workspace'e kur.** *Install to Workspace* > izinleri onayla. *OAuth & Permissions* > **Bot User OAuth Token**
   (`xoxb-…`) kopyala.
5. **App-level token al.** *Basic Information* > *App-Level Tokens* > *Generate Token and Scopes* > ad `socket`,
   scope `connections:write` > *Generate* > `xapp-…` kopyala.
6. **Botu kur.** Sürekli açık bir makinede Python 3.9+ olsun. Windows'ta en kısa yol `start.ps1`: Python'ı bulur,
   bağımlılığı kurar, ilk çalıştırmada `config.json` oluşturup Notepad'de açar, ikinci çalıştırmada token'ları
   sorup `.env` dosyasına yazar ve botu başlatır (`.\start.ps1 -Test` testleri koşar, `-Reset` token'ları
   yeniden sorar). Elle kurmak istersen:
   ```powershell
   cd .\slack\mention-bridge
   pip install -r requirements.txt
   Copy-Item config.example.json config.json    # sonra admins ve keywords bölümlerini düzenle
   ```
   `admins` alanına kendi e-postanı ya da kullanıcı ID'ni yaz (Slack'te profilin > `⋯` > *Copy member ID*).
   Yetkiyi sonradan DM'den `yetkili ekle @kişi` ile genişletebilirsin.
7. **Çalıştır ve doğrula.** Token'ları ortam değişkeni olarak ver ya da `app.py`'nin yanına `.env` dosyası koy
   (`SLACK_BOT_TOKEN=xoxb-...` ve `SLACK_APP_TOKEN=xapp-...` satırları; dosya git'e girmez):
   ```powershell
   $env:SLACK_BOT_TOKEN = "xoxb-..."
   $env:SLACK_APP_TOKEN = "xapp-..."
   python app.py
   ```
   Çıktıda `Workspace: … bot: …`, `config yüklendi: @petra, … (mod: dm)` ve `Hedefler çözüldü: N user group, M kişi`
   görünmeli. `@x diye bir user group yok` uyarısı varsa handle'ı düzelt.
8. **Botu kanala ekle.** Paylaşımlı kanalın içinde `/invite @Etiket Köprüsü` yaz (ya da kanal adı >
   *Integrations* > *Add apps*). Bot yalnızca eklendiği kanalları görür; **başka kanallarda da çalışsın
   istiyorsan aynı şekilde oraya da ekle**, `config.json` değişmez. Hangi kanallarda olduğunu DM'den
   `kanallar` komutu gösterir. Bir kanalda artık çalışmasın: `/remove @Etiket Köprüsü`.
9. **Servis yap.** Windows'ta [NSSM](https://nssm.cc) ile (Python yolunu `(Get-Command python).Source` verir):
   ```powershell
   nssm install EtiketKoprusu "C:\Python312\python.exe" "C:\kote\slack\mention-bridge\app.py"
   nssm set EtiketKoprusu AppDirectory "C:\kote\slack\mention-bridge"
   nssm set EtiketKoprusu AppEnvironmentExtra SLACK_BOT_TOKEN=xoxb-... SLACK_APP_TOKEN=xapp-...   # .env varsa gerekmez
   nssm set EtiketKoprusu AppStdout "C:\kote\logs\bridge.log"
   nssm set EtiketKoprusu AppStderr "C:\kote\logs\bridge.log"
   nssm start EtiketKoprusu
   ```
   Linux'ta bir systemd unit ya da `pm2 start app.py --interpreter python3 --name etiket-koprusu` yeterli.

### Adım adım: eski zone'da (Canlı / Finans / Risk)

1. **Daveti kabul et.** 2. adımdaki Slack Connect daveti eski zone'daki yetkiliye gelir; kabul eder. Eski zone
   Slack Connect için yönetici onayı istiyorsa: `admin` > *Slack Connect* > *Requests* > onayla. (Her iki taraf
   da ücretli planda olmalı; user group kullanan workspace'ler zaten ücretlidir.)
2. **Kanala kişileri ekle.** Kanal eski zone'da da görünür; Canlı, Finans, Risk ekiplerini kanala ekle ya da
   kanalı herkese açık bırak.
3. **Kullanıma anlat.** Kanal açıklamasına yaz: "Çözüm ekibine ulaşmak için mesajınıza `@petra` ekleyin."
   `@petra` eski zone'da otomatik tamamlamada **çıkmaz**, düz metin kalır; bu normaldir, bot yine yakalar.
4. **Kurulacak bir şey yok.** App, token, yetki gerekmez.

**App daha önce eski manifestle oluşturulduysa:** api.slack.com/apps > app > *App Manifest* > yeni
`manifest.json` içeriğini yapıştır > *Save Changes*, sonra *OAuth & Permissions* > **Reinstall to Workspace**
(yeni scope'lar: `im:history`, `usergroups:write`, `channels:read`, `groups:read`; DM sekmesi açılır).
Token'lar değişmez.

### Test

Eski zone'dan biri kanala `@petra test` yazsın. Kanalda hiçbir şey olmaz; Çözüm ekibindeki herkese
"Etiket Köprüsü" botundan DM gelir, linke tıklayınca mesaj açılır. Gelmiyorsa aşağıdaki *Sorun giderme*.

Sonra kendi hesabından bota DM at: `yardım`, `durum`, `kanallar`. Yanıt gelmiyorsa `admins` alanını ve
app'in *App Home > Messages Tab* ayarını kontrol et (manifestten kurulduysa açık).

Geliştirme: `python -m unittest` (Slack'e bağlanmadan eşleştirme, config, DM komutları ve olay işleme mantığını test eder),
`BRIDGE_DEBUG=1` ile ayrıntılı log, `BRIDGE_CONFIG=<yol>` ile farklı config dosyası.

### Sorun giderme

| Belirti | Sebep / çözüm |
|---|---|
| Hiç DM gelmiyor, log'da mesaj yok | Bot kanala eklenmemiş (`/invite`). `channels` listesi doluysa kanal ID'si orada mı? `BRIDGE_DEBUG=1` ile event geliyor mu bak. Eski zone yöneticisi Slack Connect ayarlarında dış organizasyon app'lerini kısıtlamış olabilir. |
| Log'da `eşleşti ama bildirim gidecek kimse yok` | Grup boş ya da handle yanlış (`Get-SlackUserGroupVisibility.ps1` ile bak). Yazan kişi grubun tek üyesiyse kendine DM gitmez. |
| `@petra diye bir user group bu workspace'te yok` | Handle yanlış, grup devre dışı ya da token başka workspace'e ait. |
| `x@firma.com bulunamadı` | Kişi bu workspace'te yok ya da `users:read.email` scope'u eksik (manifestten kurulduysa var). |
| `DM gönderilemedi (…)` | Kişi devre dışı, ya da `im:write` scope'u eksik (manifest güncellendiyse app'i *Reinstall* et). |
| `invalid_auth` / `not_allowed_token_type` | `xoxb` ile `xapp` yer değişmiş ya da token başka app/workspace'e ait. |
| Aynı mesaja iki DM | Botun iki kopyası çalışıyor (servis + elle başlatılan). |
| Bota DM yazınca yanıt yok | *App Home > Messages Tab* kapalı (manifesti güncelle) ya da `im:history` scope'u eksik (Reinstall). `admins` boşsa "Yönetici tanımlı değil" yanıtı gelir. |
| `grup ekle` → `permission_denied` | Workspace ayarı user group yönetimini sadece admin'e veriyor: *Workspace Settings > Permissions > User Groups*. |
| `grup ekle` → `invalid_users` | Kişi bu workspace'in tam üyesi değil (guest ya da başka workspace). |
