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

## slack/Export-SlackChannel.py

Bir kanaldaki tüm mesajları ve thread yanıtlarını (kim, tarih, gün, saat) tek Excel dosyasına aktarır.
Thread yanıtları ait oldukları ana mesajın hemen altında, gri zeminli ve girintili olarak listelenir;
Excel'in satır gruplama (+/-) özelliğiyle açılıp kapatılabilir.

```powershell
pip install openpyxl
$env:SLACK_BOT_TOKEN = "xoxb-..."
python .\slack\Export-SlackChannel.py --channel genel
python .\slack\Export-SlackChannel.py --channel C0123ABCD --start 2026-09-01 --end 2026-09-30 --output eylul.xlsx
```

| Sayfa | İçerik |
|---|---|
| Mesajlar | Her mesaj bir satır: Thread No, Thread Sırası (0 = ana mesaj), Tür, Tarih, Gün, Saat, Yazan, Kullanıcı adı, E-posta, Mesaj, Yanıt sayısı, Reaksiyonlar, Dosyalar, Düzenlendi, Slack linki |
| Threadler | Her thread bir satır: başlatan, başlangıç, son yanıt, yanıt ve katılımcı sayısı, katılımcılar |
| Kişi Özeti | Kişi bazında ana mesaj / yanıt / toplam, başlattığı thread, ilk-son mesaj |
| Günlük Özet | Gün bazında sayılar ve aktif kişi |
| Bilgi | Kanal, aralık, saat dilimi, toplamlar |

Gereken bot scope'ları: `channels:history`, `channels:read`, `groups:history`, `groups:read`, `users:read`
(+ e-posta için `users:read.email`). Bot kanala ekli olmalı: kanalda `/invite @BotAdı`.

Seçenekler: `--tz` (varsayılan Europe/Istanbul), `--json yedek.json` (ham veri), `--include-system`
(katıldı/ayrıldı mesajları), `--page-size 15` ve `--delay 2` (rate limit düşük app'ler için).

## slack/Build-MemnuniyetReport.py

`Export-SlackChannel.py` çıktısını okuyup "yatırımsız oyuncu" bildirim kanalı için
kim-hangi-bildirime-yanıt-verdi raporu üretir. Bot mesajındaki `PC:` kodunun numarası sorumlu
TS'yi belirler; thread'deki ilk yanıt o bildirimin cevabı sayılır.

```powershell
python .\slack\Build-MemnuniyetReport.py slack_p-ft-memnuniyet_2026-09-16_2026-09-30.xlsx
```

| Sayfa | İçerik |
|---|---|
| Rapor | Her bildirim bir satır: oyuncu ID, PC, sorumlu TS, durum, yanıtlayan, yanıt zamanı ve süresi, yanıt metni. Yanıtsız kırmızı, yanlış kişi turuncu |
| TS Performans | TS bazında atanan / yanıtlanan / yanıtsız / oran / ortalama ve medyan süre |
| Yanıtsızlar | Sadece yanıtlanmamış bildirimler |
| Günlük, Günlük x TS, Gün Tipi | Gün, gün x TS ve 8/15/21. gün kırılımları |
| Ham Mesajlar, Bilgi | Kaynak veri ve uyarılar (Slack'in göstermediği bot mesajları dahil) |
