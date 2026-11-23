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

Beklenen (provada aynı dosyalarla çıkan değerler): raporda `"yeni": 5498`, `"onarilan": 114`, kullanıcılar `"onayli": 153, "engelli": 1`, kategoriler 11; sayımda `kayit: 5498`, `tg kullanici (154, 153, 1)`, `kategori: 11`, sonra `OK`. Tarayıcıda Kayıtlar sayfasında proje sekmelerini kontrol edin. Sorun yoksa `rm -rf /opt/kanit-paneli/eski-veri`.

## 4. Botu gerçek hesaba geçirme

Önce Windows'taki eski botu **kapatın**; aynı anahtar iki yerde çalışmaz.

```bash
cd /root/kanit-kurulum/KanitPaneli_Sunucu_v2.3.0
python3 deploy/configure-bot.py
```

Sorulduğunda gerçek Telegram bot anahtarını ve mevcut bot giriş şifresini (`BOT_PASSWORD`) yazın. Sonra yönetici ayarları (ID yerine Telegram yönetici kimliğinizi, parola sorulduğunda bot yönetici parolasını yazın):

```bash
read -rp 'Yonetici Telegram ID: ' AID; read -rs -p 'Bot yonetici parolasi: ' AP; echo
sed -i "s/^ADMIN_IDS=.*/ADMIN_IDS=$AID/; s/^ADMIN_PASSWORD=.*/ADMIN_PASSWORD=$AP/" /opt/kanit-paneli/.env; unset AID AP
grep -E '^(ADMIN_IDS|MAX_DENEME|GYAZO_BAKIM)=' /opt/kanit-paneli/.env
systemctl restart kanit-bot && sleep 5 && systemctl is-active kanit-bot && journalctl -u kanit-bot -n 15 --no-pager
```

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

Beklenen: `BIRIM_GUNCELLENDI ... sağlık OK`, nginx yamasında `nginx -t` başarılı ve yeniden yükleme, son komutta `200`.

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

Uyguladıktan hemen sonra yeni bir PuTTY penceresiyle giriş yapabildiğinizi doğrulayın; giremezseniz açık oturumdan `ufw disable`.

## 12. Eski görseller (isteğe bağlı, 2 GB)

Gyazo bağlantılı kayıtlar panelde doğrudan görünür. Bilgisayarda saklanan `telegram_gorseller` klasörünü de panelde görmek isterseniz:

```powershell
pscp -r KLASOR\telegram_gorseller root@SUNUCU_IP:/opt/kanit-paneli/data/
```

```bash
chown -R kanit:kanit /opt/kanit-paneli/data/telegram_gorseller
runuser -u kanit -- /opt/kanit-paneli/.venv/bin/python -m app.cli arsiv-tara
```

## Sorun çıkarsa

- Güncelleme hatası: betik kendisi geri alır; notu `/var/backups/kanit-paneli/<tarih>/GERI_DONUS_NOTU.txt`.
- Deneme veritabanı: `/root/kanit-yedek-test/` altında durur; gerekirse servisleri durdurup `data/panel.db` yerine kopyalanır.
- Servis günlükleri: `journalctl -u kanit-web -n 50 --no-pager`, `journalctl -u kanit-bot -n 50 --no-pager`.
- Giriş kilidi: Kullanıcılar sayfasında "Kilitli" etiketi; kaydetmek kilidi açar, ya da 15 dakika bekleyin.
