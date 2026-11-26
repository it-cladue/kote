# Kanıt Paneli 2.3.0 — mevcut sunucuda adım adım geçiş

Bu belge, sunucudaki test kurulumunu (v2.2.0, deneme verisi) gerçek kullanıma geçirmek için izlenecek sırayı verir. Her adımı PuTTY'de root olarak, sırayla uygulayın; "Beklenen" satırını görmeden bir sonrakine geçmeyin. Bir adımda hata çıkarsa durun, ekrandaki çıktıyı olduğu gibi gönderin.

Kısaltmalar: `SUNUCU_IP` sunucunuzun IP adresi; `PAKET` açılmış paket dizini, bu kurulumda `/root/kanit-kurulum/KanitPaneli_Sunucu_v2.3.0`. Parolalar hiçbir komuta açık yazılmaz; `read -rs` ile sorulduğunda yazılır (ekranda görünmez).

## 0. Paketi yükleyin (Windows PowerShell)

```powershell
pscp C:\Users\IT\Downloads\KanitPaneli_Sunucu_v2.3.0.zip root@SUNUCU_IP:/root/kanit-kurulum/
```

PuTTY'de:

```bash
cd /root/kanit-kurulum && rm -rf KanitPaneli_Sunucu_v2.3.0 && unzip -q KanitPaneli_Sunucu_v2.3.0.zip && cd KanitPaneli_Sunucu_v2.3.0 && sha256sum -c --quiet DOSYA_DOGRULAMA.sha256 && echo PAKET_DOGRU
```

Beklenen: `PAKET_DOGRU`.

## 1. İşletim sistemi güncellemesi ve yeniden başlatma

Bekleyen güncellemeler ve yeniden başlatma var. Plesk'teki site 2-3 dakika kesilir; uygun saatte yapın.

```bash
apt-get update && DEBIAN_FRONTEND=noninteractive apt-get -y upgrade && apt-get -y autoremove
[ -f /var/run/reboot-required ] && echo 'YENIDEN BASLATMA GEREKLI' || echo 'yeniden baslatma gerekmiyor'
reboot
```

2-3 dakika sonra yeniden bağlanın:

```bash
systemctl is-active kanit-web kanit-bot kanit-ip-proxy nginx; curl -fsS http://127.0.0.1:18080/saglik; echo
```

Beklenen: dört satır `active`, sonra `OK`.

## 2. Panel güncellemesi (2.2.0 → 2.3.0)

Önce yalnız okuyan deneme:

```bash
cd /root/kanit-kurulum/KanitPaneli_Sunucu_v2.3.0
bash deploy/apply-update.sh --dry-run
```

Beklenen: `Pillow 12.3.0->13.0.0`, `pip çözümleme denemesi (--dry-run): TAMAM`, `Servis birim dosyaları güncellenecek ... kanit-web.service kanit-bot.service`, sonda `DRY-RUN_TAMAM`.

Gerçek güncelleme (yaklaşık 1-2 dakika; servisler kısa süre durur):

```bash
bash deploy/apply-update.sh
curl -fsS http://127.0.0.1:18080/saglik; echo; systemctl is-active kanit-web kanit-bot
/opt/kanit-paneli/.venv/bin/python -c 'import PIL; print(PIL.__version__)'
systemd-analyze security kanit-web.service kanit-bot.service --no-pager | grep Overall
journalctl -u kanit-web -u kanit-bot --since '5 min ago' --no-pager | grep -iE 'permitted|SIGSYS|Traceback' || echo 'sertlestirme uyarisi yok'
```

Beklenen: `GÜNCELLEME_TAMAM`, `OK`, iki servis `active`, `13.0.0`, iki birim için `1.x OK`, `sertlestirme uyarisi yok`. Hata olursa betik eski kodu, eski paket sürümlerini ve eski birimleri kendisi geri alır; çıktıyı gönderin.

Tarayıcıda `https://SUNUCU_IP:18443` açın (sertifika uyarısını geçin), `admin` ile girin. Bu sürümden sonra herkes bir kez yeniden giriş yapar.

Servis açılmazsa (çok düşük ihtimal): `/etc/systemd/system/kanit-web.service` içinde önce `MemoryDenyWriteExecute`, olmadı `SystemCallFilter` satırını silip `systemctl daemon-reload && systemctl restart kanit-web`.

Güncelleme bitince bir kez (eski güncellemelerden kalmış olabilecek artıklar için, zararsız): `rm -f /opt/kanit-paneli/data/.kanit-update-snapshot-*.db-wal /opt/kanit-paneli/data/.kanit-update-snapshot-*.db-shm`

## 3. Temiz veritabanı ve gerçek verinin aktarılması

Sunucudaki deneme verisi kenara alınır, gerçek veri eski bot klasöründen bir kez içeri aktarılır.

3a. Servisleri durdurun, deneme veritabanını kenara alın, boş veritabanı ve admin hesabı oluşturun (parola sorulduğunda kararlaştırdığınız panel yönetici parolasını yazın):

```bash
systemctl stop kanit-bot kanit-web
cd /opt/kanit-paneli
mkdir -p /root/kanit-yedek-test && mv data/panel.db /root/kanit-yedek-test/panel.db.test-$(date +%F); rm -f data/panel.db-wal data/panel.db-shm
runuser -u kanit -- .venv/bin/python -m app.cli veritabani-kur
read -rs KANIT_PW; export KANIT_PW
runuser -u kanit -w KANIT_PW -- .venv/bin/python -m app.cli admin-ekle admin --password-env KANIT_PW --kalici
unset KANIT_PW
mkdir -p /opt/kanit-paneli/eski-veri && chown kanit:kanit /opt/kanit-paneli/eski-veri
```

Beklenen: `Veritabanı hazır: ...` ve `Panel hesabı hazır: admin (parola kalıcı)`.

3b. Windows'taki bot klasöründen şu 7 dosyayı yükleyin (PowerShell; `KLASOR` yerine kendi yolunuzu yazın). `config.json` dosyasını **yüklemeyin**:

```powershell
cd KLASOR
pscp telegrambot_gyazo.xlsx onaylilar.txt engellenenler.txt kullanicilar.json kategoriler.json bot_log.txt kayitlar.jsonl root@SUNUCU_IP:/opt/kanit-paneli/eski-veri/
```

3c. Aktarın ve sayın:

```bash
cd /opt/kanit-paneli && chown -R kanit:kanit eski-veri
runuser -u kanit -- .venv/bin/python -m app.cli ice-aktar /opt/kanit-paneli/eski-veri
runuser -u kanit -- .venv/bin/python - <<'EOF2'
import sqlite3; c=sqlite3.connect('file:/opt/kanit-paneli/data/panel.db?mode=ro',uri=True)
print('kayit:',c.execute('select count(*) from kayitlar').fetchone()[0],'| proje:',c.execute('select proje,count(*) from kayitlar group by proje').fetchall())
print('tg kullanici (toplam,onayli,engelli):',c.execute('select count(*),sum(onayli),sum(engelli) from tg_kullanicilar').fetchone())
print('kategori:',c.execute('select count(*) from kategoriler').fetchone()[0])
EOF2
systemctl start kanit-web && curl -fsS http://127.0.0.1:18080/saglik; echo
```

Beklenen (24 Kasım 2026'da gönderdiğiniz `telegramkan123t` arşiviyle provada çıkan değerler; bot o tarihten sonra da çalıştıysa sayılar biraz büyür): raporda `"sayfalar"` GA 1522, BETA 95, VI 709, HI 1260, PA 859, OF 1642, PP 841; `"yeni": 6928`, `"onarilan": 114` (bağlantısı Kategori sütununa kaymış satırlar düzeltilir), kullanıcılar `"onayli": 164, "engelli": 0`, kategoriler 11; sayımda `kayit: 6928`, `tg kullanici (164, 164, 0)`, `kategori: 11`, sonra `OK`. Excel'deki **KT edildi** sütunu panelde onay durumu olur: 6628 kayıt **Onaylı**, 300 kayıt **Bekleyen** (BETA 2, GA 126, HI 18, OF 7, PA 123, PP 2, VI 22). Excel'in **Açıklama** sütunu (127 satır: `M`, `Y`, serbest notlar) kaydın Açıklama alanına gelir; kayıt detayında görünür ve düzenlenebilir. Tarayıcıda Kayıtlar → Bekleyen listesinde bu 300 kaydı görürsünüz; proje sekmelerini kontrol edin. Sorun yoksa `rm -rf /opt/kanit-paneli/eski-veri`. Onaylama ve yorum akışı için 3d'ye bakın.

3d. Aktarımdan sonra onay ve yorum nasıl çalışır (eski Excel'deki "KT edildi" sütununun yerini alır):

1. **Onay durumu Excel'den gelir.** Excel'de `KT edildi` = True olan satırlar panelde **Onaylı**, boş/False olanlar **Bekleyen** olur. Kayıtlar sayfasının üstünde Bekleyen / Onaylı / Silinen / Hepsi sekmeleri ve proje seçimi vardır; "Bekleyen" sekmesi Excel'de işaretlenmemiş kayıtları listeler.
2. **Tek kayıt onaylama:** Kayıtlar → satıra tıklayın → açılan pencerede kaydın bilgileri, görseli, Excel'den gelen **Açıklama** alanı ve onay özeti görünür ("Onay bekliyor" ya da "Eski kaynaktan onaylı aktarıldı"). **Onayla** düğmesi kaydı onaylar; onaylayan kişi ve saat kayda yazılır, İşlem Geçmişi'ne düşer. Yanlışsa aynı pencerede **Onayı kaldır**.
3. **Toplu onay:** Bekleyen listesinde satırların başındaki kutuları işaretleyin; üstte beliren araç çubuğundan seçilenleri tek seferde onaylayın (onay sorusu çıkar).
4. **Yorum / soru / yanıt:** Aynı pencerenin altındaki **Konuşma** bölümüne yorum yazılır. "Soru yönelt" ile projenin sorumlusuna (ya da tüm ilgili sorumlulara) soru gönderilir; soru gelen kişi panelde bildirim alır ve aynı yerden yanıtlar. Yorumlar kayda bağlı kalır, Excel çıktısında ve İşlem Geçmişi'nde görünür.
5. **Excel'deki Açıklama sütunu** (`M`, `Y`, "link iletilen wp patladığı için…" gibi notlar) kaydın Açıklama alanında saklanır; **Düzenle** ile değiştirilebilir. Bu notlar yorum değildir; yorum olarak görünmesini isterseniz kaydı açıp Konuşma bölümüne yazın.
6. **Yetki:** Onaylama ve yorum, kullanıcının o projede "kt" (onay) yetkisi varsa açılır; yalnız görüntüleme yetkisi olan kullanıcı düğmeleri görmez (Kullanıcılar sayfasından proje bazında verilir, örn. `GA:oku,kt`).

Bundan sonra yeni kanıtlar Telegram botundan gelir ve Bekleyen listesine düşer; Excel dosyasına geri yazılmaz, Excel çıktısı panelden "Excel çıktısı" ile alınır.

3e. Gyazo görsellerini sunucuya kopyalama (2.3.1 ile; isteğe bağlı ama önerilir):

Eski kayıtların görselleri Gyazo'da duruyor; panel ilk açılışta indirip saklar, ama Gyazo tarafında silinen görsel kaybolur. 2.3.1'deki gece planı bunları mesai dışında sunucuya kopyalar. Önce 20 bağlantıyla deneme (her bağlantı için satır yazar; Gyazo'ya ulaşılamıyorsa hemen söyler, Ctrl+C gerekmez):

```bash
cd /opt/kanit-paneli
runuser -u kanit -- .venv/bin/python -m app.cli gyazo-onbellekle --en-cok 20
```

Beklenen: `Gyazo erişimi: ulaşıldı (deneme isteği HTTP 503 …)` (var olmayan kimlik için 503/404 normaldir), ardından `1/20 … indirildi (123 KB)` satırları (birkaçı `açılamadı: Gyazo'da görsel yok (404)` olabilir), sonda `GYAZO_ONBELLEK_TAMAM`. `GYAZO_ONBELLEK_YARIM: Gyazo'ya ulaşılamıyor` çıkarsa ya sunucunun dış HTTPS erişimi engellidir ya da Gyazo arızalıdır; mesajdaki `curl` satırını çalıştırın (çıktı 000 ise sunucu Gyazo'dan hiç yanıt alamadı (dış erişim engelli ya da Gyazo asılı); 200/403/503 gibi üç basamaklı başka bir sayı yazarsa erişim var, Gyazo arızalıdır) ve çıktıyı gönderin. Art arda 10 bağlantı `HTTP 503` ya da zaman aşımı verirse komut kalan bağlantıları bir kez daha denemeden geçer ("… bir kez daha denenmeden geçilir" satırı); Gyazo silinmiş görsellere de 503 verdiği için bu tek başına arıza değildir. Görseller yanıt vermeden asılı kalıyorsa bu 20 bağlantılık deneme ~10 dakikaya kadar sürebilir (asılı bağlantı başına ~20 sn, ilk 10'u bir kez daha denendiği için ~40 sn), bekleyin. Gece planında (sınırsız aday) son 30 bağlantının 25'inde hiç yanıt alınamazsa kalan Gyazo bağlantıları denenmeden geçilir, sonda `ARIZA: Gyazo yanıt vermiyor …` satırı çıkar, komut kendiliğinden erken biter ve sonraki gece yeniden dener. Silinmiş görsellerin her gece yeniden denenen 503'leri `ARIZA:` satırı çıkarmaz.

Deneme iyiyse gece zamanlayıcısı (her gece TR 22:30'da başlar, gecede en çok 900 bağlantı indirir, en geç 07:30'da durur, kaldığı yerden sürer; gün içinde çalışmaz):

```bash
bash deploy/setup-gyazo-gece.sh --dry-run
bash deploy/setup-gyazo-gece.sh
```

Beklenen: `DRY-RUN_TAMAM`, sonra `GYAZO_GECE_TAMAM` ve `list-timers` çıktısında bir sonraki çalışma saati. İzlemek: `journalctl -u kanit-gyazo -n 30 --no-pager` (her gece bir özet; `GYAZO_ONBELLEK_DEVAM` kalan sayıyı söyler, iş bitince `GYAZO_ONBELLEK_TAMAM`). Günlükte `GYAZO_ONBELLEK_YARIM: Gyazo'ya ulaşılamıyor` olan gece `systemctl status kanit-gyazo` birimi başarısız (failed, çıkış kodu 1) gösterir; bu durumda mesajdaki `curl` satırını çalıştırın (çıktı 000 ise sunucu Gyazo'dan hiç yanıt alamadı). Zamanlayıcı bozulmaz, sonraki gece kendiliğinden yeniden dener. Açılamayan bağlantılar `data/gyazo-acilamayan.csv` dosyasındadır. Saat/sayı değiştirmek: `bash deploy/setup-gyazo-gece.sh --saat 23:00 --bitis 07:00 --gecelik 600`; kaldırmak: `--kaldir`.

## 4. Botu gerçek hesaba geçirme

Önce Windows'taki eski botu **kapatın**; aynı anahtar iki yerde çalışmaz.

```bash
cd /root/kanit-kurulum/KanitPaneli_Sunucu_v2.3.0
python3 deploy/configure-bot.py
```

Sorulduğunda gerçek Telegram bot anahtarını ve mevcut bot giriş şifresini (`BOT_PASSWORD`) yazın. Sonra yönetici ayarları (Telegram yönetici kimliğinizi ve bot yönetici parolasını sorar; parola ekranda görünmez, hiçbir yere yazdırılmaz, `.env` dosyası yerinde güncellenir):

```bash
python3 deploy/configure-bot.py --yonetici
grep -E '^(ADMIN_IDS|MAX_DENEME|GYAZO_BAKIM)=' /opt/kanit-paneli/.env
systemctl restart kanit-bot && sleep 5 && systemctl is-active kanit-bot && journalctl -u kanit-bot -n 15 --no-pager
```

Beklenen: `YONETICI_AYARLARI_KAYDEDILDI`, sonra `active`. Birden fazla yönetici kimliği virgülle yazılır (`123456,987654`). Parolada `/`, `&`, `\` gibi karakterler sorun değildir. Bot parolaları (`BOT_PASSWORD`, `ADMIN_PASSWORD`) en az 8 karakter olsun; kısaysa bot açılışta uyarı yazar.

Beklenen: `active`; günlükte hata yok. Telegram'dan bota `/start` yazıp şifreyle girin, bir deneme fotoğrafı gönderin; panelde Kayıtlar'da görünsün. Onaylı 153 kullanıcı yeni botta ilk mesajda şifreyi bir kez yazar. `GYAZO_TOKEN` boş kalır; görseller sunucuda saklanır.

## 5. Otomatik yedek

```bash
cd /root/kanit-kurulum/KanitPaneli_Sunucu_v2.3.0 && apt-get install -y rsync
bash deploy/setup-backup.sh --dry-run
bash deploy/setup-backup.sh
ls -la /var/backups/kanit-paneli/gunluk/; systemctl list-timers kanit-yedek.timer --no-pager
```

Beklenen: `YEDEK_DOGRULANDI ... integrity=ok ... kayit=5498`, `YEDEK_ZAMANLAYICI_TAMAM`, listede `kanit-yedek.timer`. Her gece 03:17'de çalışır; 14 günlük ve 8 haftalık kopya tutar. Sunucu dışına kopya için README §11'deki örnek.

## 6. IP yolu (18443) için servis ve nginx güncellemesi

Alan adı gelene kadar 18443 kullanılacağı için:

```bash
cd /root/kanit-kurulum/KanitPaneli_Sunucu_v2.3.0
bash deploy/setup-ip-https.sh --servis-guncelle --dry-run
bash deploy/setup-ip-https.sh --servis-guncelle
bash deploy/nginx-giris-siniri.sh --dry-run
bash deploy/nginx-giris-siniri.sh
curl -sk -o /dev/null -w '%{http_code}\n' https://127.0.0.1:18443/giris
```

Beklenen: `BIRIM_GUNCELLENDI ... sağlık OK` (IP sertifikası dolmuş olsa da çalışır; çıktıda "sertifika dolmuş" bilgi satırı görünür, sorun değildir), nginx yamasında `nginx -t` başarılı ve yeniden yükleme, son komutta `200`.

## 7. Günlük döndürme

```bash
install -m 644 /root/kanit-kurulum/KanitPaneli_Sunucu_v2.3.0/deploy/logrotate-kanit /etc/logrotate.d/kanit-paneli && logrotate -d /etc/logrotate.d/kanit-paneli 2>&1 | tail -3
```

Beklenen: `error` satırı yok.

## 8. fail2ban (isteğe bağlı; yalnız 18443 açıkken anlamlı)

```bash
cd /root/kanit-kurulum/KanitPaneli_Sunucu_v2.3.0
python3 -c 'import systemd.journal' 2>/dev/null || apt-get install -y python3-systemd
bash deploy/setup-fail2ban.sh --dry-run
bash deploy/setup-fail2ban.sh
fail2ban-client status kanit-web
```

Beklenen: `FAIL2BAN_TAMAM`, durumda `kanit-web` jail'i. Plesk'in kendi jail'leri aynen kalır.

## 9. Alan adı: Cloudflare turuncu bulut

Cloudflare panelinde:

1. DNS → Records: A kaydı `panel` → sunucu IP'si, Proxy status **Proxied** (turuncu bulut).
2. SSL/TLS → Overview: **Full (strict)**.
3. SSL/TLS → Edge Certificates: **Always Use HTTPS** açık.
4. SSL/TLS → Origin Server → Create Certificate: RSA 2048, 15 yıl, hostname `panel.ALANADINIZ`. Çıkan iki metni Not Defteri ile `origin.pem` (Origin Certificate) ve `origin.key` (Private Key) olarak kaydedip yükleyin:

```powershell
pscp origin.pem origin.key root@SUNUCU_IP:/root/
```

Sunucuda (`panel.ALANADINIZ` yerine gerçek adı yazın):

```bash
cd /root/kanit-kurulum/KanitPaneli_Sunucu_v2.3.0
bash deploy/setup-cloudflare-https.sh panel.ALANADINIZ --dry-run
bash deploy/setup-cloudflare-https.sh panel.ALANADINIZ --sertifika /root/origin.pem --anahtar /root/origin.key
curl -s https://panel.ALANADINIZ/saglik; echo
printf 'GUVENILEN_HOSTLAR=SUNUCU_IP,panel.ALANADINIZ\n' >> /opt/kanit-paneli/.env && systemctl restart kanit-web
```

Beklenen: dry-run'da `turuncu bulut ✓` ve `DRY-RUN_TAMAM`; kurulumda `CLOUDFLARE_HTTPS_TAMAM`; `OK` (DNS yeni ise 5-10 dakika sonra). Tarayıcıda `https://panel.ALANADINIZ` giriş ekranını açar. Geri almak: `bash deploy/setup-cloudflare-https.sh --kaldir`.

## 10. IP yolunu kapatma (alan adı birkaç gün sorunsuz çalıştıktan sonra)

```bash
systemctl disable --now kanit-ip-proxy; systemctl is-active kanit-ip-proxy
```

Beklenen: `inactive`. Geri açmak: `systemctl enable --now kanit-ip-proxy`.

## 11. Güvenlik duvarı (isteğe bağlı, en son)

```bash
cd /root/kanit-kurulum/KanitPaneli_Sunucu_v2.3.0 && apt-get install -y ufw
bash deploy/setup-firewall.sh            # yalnız plan; SSH portu ve posta/Plesk kararını okuyun
bash deploy/setup-firewall.sh --uygula   # gerekirse --plesk / --posta-kapat
```

Beklenen: her kural için bir satır ve sonda `GUVENLIK_DUVARI_TAMAM`. Uyguladıktan hemen sonra yeni bir PuTTY penceresiyle giriş yapabildiğinizi doğrulayın; giremezseniz açık oturumdan `ufw disable`. Betik bir kuralda hata verip durursa güvenlik duvarı etkinleştirilmemiştir; elle `ufw enable` yazmayın.

## 12. Eski görseller (isteğe bağlı, 2 GB)

Gyazo bağlantılı kayıtlar panelde doğrudan görünür. Bilgisayarda saklanan `telegram_gorseller` klasörünü de panelde görmek isterseniz:

```powershell
pscp -r KLASOR\telegram_gorseller root@SUNUCU_IP:/opt/kanit-paneli/data/
```

```bash
chown -R kanit:kanit /opt/kanit-paneli/data/telegram_gorseller
runuser -u kanit -- /opt/kanit-paneli/.venv/bin/python -m app.cli arsiv-tara
```

## 13. Güncellemeler GitHub'dan (2.3.1 ve sonrası)

Zip taşımaya gerek yok: sunucu paketi doğrudan depodan alır. Her güncellemede (ilk kez de) aynı blok: `git` yoksa kurar, eski kopyayı siler, taze kopyayı indirir ve depo geçmişini (`.git` klasörü: dal adı, yazar ve işleme bilgileri) sunucuda tutmaz; sunucuda yalnız paket dosyaları kalır.

```bash
command -v git >/dev/null || apt-get install -y git
cd /root/kanit-kurulum && rm -rf kote && git clone -q --depth 1 -b claude/busy-feynman-cibo22 https://github.com/it-cladue/kote.git kote && rm -rf kote/.git
cd /root/kanit-kurulum/kote/sunucu && sha256sum -c --quiet DOSYA_DOGRULAMA.sha256 && echo PAKET_DOGRU && grep -n "^SURUM" app/panel.py
```

Beklenen: `PAKET_DOGRU` ve `SURUM = '2.3.2'` (ya da daha yenisi). `git pull` kullanılmaz; her seferinde taze kopya alınır, bu yüzden eski kopyada yapılmış elle değişiklik varsa kaybolur (paket klasöründe elle değişiklik yapılmaz; ayarlar `/opt/kanit-paneli/.env` içindedir).

Güncellemeyi uygulama (her sürümde aynı; veritabanı değişmez, yalnız panel servisleri kısa süre durur):

```bash
cd /root/kanit-kurulum/kote/sunucu
bash deploy/apply-update.sh --dry-run
bash deploy/apply-update.sh
curl -fsS http://127.0.0.1:18080/saglik; echo; systemctl is-active kanit-web kanit-bot
```

Beklenen: `DRY-RUN_TAMAM`, `GÜNCELLEME_TAMAM`, `OK`, iki `active`. 2.3.1'e özel isteğe bağlı ayar: raporlama ekibi onaysız kayıtları hiç görmesin istiyorsanız `/opt/kanit-paneli/.env` dosyasına `ONAYSIZ_GORUNUM=gizle` ekleyip `systemctl restart kanit-web`; yazılmazsa kırmızı uyarı modu geçerlidir. İlk hatırlatmaları beklemeden görmek için: `runuser -u kanit -- /opt/kanit-paneli/.venv/bin/python -m app.cli hatirlatma-uret`. Ayrıntı: `DEGISIKLIKLER_v2.3.1.md`.

2.3.2 ile gelenler (aynı indirme + güncelleme yolu): Snappark/Teamzone görselleri panelde içeride açılır ve gece planı onları da kopyalar; sunucudan kontrol: `curl -sS -o /dev/null -w '%{http_code} %{content_type}\n' --max-time 20 https://img.snappark.net/s/MduBQ4TiGc/raw/` → `200 image/png`. API anahtarları: Yönetim → API anahtarları; kullanım `API_KULLANIM.md`; API'yi kapatmak için `.env`'e `API_ACIK=0`. Ayrıntı: `DEGISIKLIKLER_v2.3.2.md`.

2.3.3 ile gelenler (aynı indirme + güncelleme yolu; veritabanı ve `.env` değişmez, yeni ayar yok): yeni bildirimler sağ üstte zilin altında pop-up kart olarak ve kısa bir sesle gelir; okunmamış hatırlatma varsa ortada "Bekleyen kontroller hatırlatması" penceresi açılır (**Daha sonra** o gün için kapatır, **Tümünü okundu say** okundu sayar). Ekibe söylenecekler: ses tarayıcı kuralı gereği sayfaya bir kez tıkladıktan sonra çalar; sesi kapatmak için zil → **Ses**; masaüstü bildirimi için zil → **Masaüstü bildirimlerini aç** → İzin ver. Güncellemeden sonra kontrol: panel açıkken Telegram'dan bir deneme kanıtı ekletin; o projede onay yetkisi olan hesabın panelinde 10 sn içinde sağ üstte kart çıkmalı. Ayrıntı: `DEGISIKLIKLER_v2.3.3.md`.

2.3.3 hatırlatma zamanlaması: ayar gerekmez. Onaylanmayan kayıt 2 saati doldurunca o projede onay yetkisi olanlara bir kez "Kayıt #… 2 saattir onay bekliyor." bildirimi düşer (aynı projeden 5'ten fazla kayıt birlikte dolarsa tek toplu bildirim); her gün İstanbul saatiyle 18:00–18:10 arasında yöneticilere "Gün sonu …: N kayıt onaylanmadı (proje dağılımı)…" özeti gider. Saati ya da alıcıları değiştirmek için `/opt/kanit-paneli/.env` içine örn. `GUN_SONU_SAAT=17:30`, `GUN_SONU_ALICILAR=ali,veli` (boş = tüm yöneticiler), `HATIRLATMA_SAAT=3` yazıp `systemctl restart kanit-web`. Özeti 18:00'i beklemeden denemek için: `runuser -u kanit -- /opt/kanit-paneli/.venv/bin/python -m app.cli hatirlatma-uret --gun-sonu-zorla` (sonda Türkçe özet satırları; aynı gün ikinci kez yeni bildirim üretmez). Dikkat: bu komut o günün özetini o anki sayılarla gönderir; aynı gün 18:00'de ikinci özet gitmez, bu yüzden denemeyi tercihen 18:00'den sonra ya da test sunucusunda yapın. Ayrıntı: `DEGISIKLIKLER_v2.3.3.md`.

2.3.4 ile gelenler (aynı indirme + güncelleme yolu; veritabanı ve `.env` değişmez, yeni ayar yok): ana sayfada "Proje bazında iş yükü"nün altında **Personel bazında kanıtlar** kartı (hangi personel hangi kategoriden kaç kanıt eklemiş; proje / dönem / durum seçimi, ilk 3, ilk 10 kişilik tablo) ve üst menüde **Rapor** sayfası (tüm tablo, Kategori/Tip sütunları, özel tarih aralığı, sütuna göre sıralama, **Excel'e aktar**, **CSV**, **Yazdır**). Sayıya tıklamak o kayıtları Kayıtlar listesinde açar. Dış sistemler için `GET /api/v1/personel-ozet` (`API_KULLANIM.md` §3.6). Güncellemeden sonra kontrol: ana sayfada kartın göründüğünü ve **Rapor → Excel'e aktar** ile dosyanın indiğini görün. Ayrıntı: `DEGISIKLIKLER_v2.3.4.md`.

## Sorun çıkarsa

- Güncelleme hatası: betik kendisi geri alır; notu `/var/backups/kanit-paneli/<tarih>/GERI_DONUS_NOTU.txt`.
- Deneme veritabanı: `/root/kanit-yedek-test/` altında durur; gerekirse servisleri durdurup `data/panel.db` yerine kopyalanır.
- Servis günlükleri: `journalctl -u kanit-web -n 50 --no-pager`, `journalctl -u kanit-bot -n 50 --no-pager`.
- Giriş kilidi: Kullanıcılar sayfasında "Kilitli" etiketi; kaydetmek kilidi açar, ya da 15 dakika bekleyin.
