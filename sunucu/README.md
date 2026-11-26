# Kanıt Paneli 2.3 — mevcut sunucuda güvenli güncelleme

Bu paket Telegram botu ile web kontrol panelinin 2.3 kaynak sürümüdür. 2.3, 2.2 üzerine internete açılma öncesi güvenlik ve sağlamlık turudur; değişiklik listesi `DEGISIKLIKLER_v2.3.md` (2.2 ve öncesi için `DEGISIKLIKLER_v2.2.md`), 2.3.1 ekleri (hatırlatma bildirimleri, onaysız kayıt görünürlüğü, bildirimden kayda gitme, ekleyen profili özeti) `DEGISIKLIKLER_v2.3.1.md`, 2.3.2 ekleri (Snappark/Teamzone görselleri, API anahtarları ve `/api/v1` uçları; kullanım `API_KULLANIM.md`) `DEGISIKLIKLER_v2.3.2.md`, 2.3.3 ekleri (sağ üstte pop-up bildirim kartları, bildirim sesi, bekleyen kontroller hatırlatma penceresi) `DEGISIKLIKLER_v2.3.3.md` dosyasındadır. 2.3.4 ekleri (ana sayfada Personel bazında kanıtlar kartı, menüde **Rapor** sayfası: personel × kategori tablosu, Excel/CSV/yazdır çıktısı ve `/api/v1/personel-ozet`) `DEGISIKLIKLER_v2.3.4.md` dosyasındadır. 2.3.5 ekleri (API anahtarları sayfasında kopyalanabilir örnekli **Kullanım kılavuzu**, katalogda önizlemeli **Kategori temizliği** ve `app.cli kategori-temizle`) `DEGISIKLIKLER_v2.3.5.md` dosyasındadır. 2.3.3 ile hatırlatmalara iki zamanlama eklendi: onaylanmayan kayıt 2 saat dolunca onay yetkililere bir kez bildirilir ve her gün İstanbul saatiyle 18:00'de yöneticilere "kaç kayıt onaylanmadı" gün sonu özeti gider (`DEGISIKLIKLER_v2.3.3.md`). Senin mevcut Ubuntu/Plesk kurulumun için hazırlanmıştır. Kanıt ekleme yalnız Telegram’dan yapılır; site inceleme, onay, yorum/soru, bildirim, kullanıcı ve katalog yönetimi içindir. Excel canlı kayıt kaynağı değildir. Senin mevcut Ubuntu/Plesk kurulumun için hazırlanmıştır. Kanıt ekleme yalnız Telegram’dan yapılır; site inceleme, onay, yorum/soru, bildirim, kullanıcı ve katalog yönetimi içindir. Excel canlı kayıt kaynağı değildir.

## Mevcut kurulum

| Bileşen | Konum / adres |
|---|---|
| Uygulama | `/opt/kanit-paneli` |
| Web adresi | `https://217.156.123.36:18443` |
| İç web servisi | `http://127.0.0.1:18080` — dışarı açılmaz |
| Uygulama servisleri | `kanit-web`, `kanit-bot` |
| Ayrı IP HTTPS servisi | `kanit-ip-proxy` (nginx, `217.156.123.36:18443`, `/opt/kanit-ssl/nginx.conf`) — IP sertifikası kısa ömürlüdür ve **dolmuştur**; kalıcı yol alan adı + Cloudflare (§1a), sonra bu servis kapatılır |
| Alan adı (Cloudflare) | `/etc/nginx/conf.d/zz020_kanit-panel.conf` (Plesk nginx'i), sertifika `/opt/kanit-ssl/cloudflare/` |
| Yedekler | `/var/backups/kanit-paneli/` — güncelleme yedekleri `<zaman>/`, günlük `gunluk/`, haftalık görsel aynası `haftalik/` (§11) |
| Özel ayarlar | `/opt/kanit-paneli/.env` |
| SQLite | `/opt/kanit-paneli/data/panel.db` |
| Yeni görseller | `/opt/kanit-paneli/data/gorseller` |
| Eski arşiv | `/opt/kanit-paneli/data/telegram_gorseller` |

Plesk’in Nginx/Apache dosyalarını, portlarını veya servislerini yeniden kurma. ZIP’i doğrudan çalışan uygulamanın üzerine açma. Kaynak paketi ayrı bir güncelleme klasörüne açıp aşağıdaki yardımcıyı kullan.

## 1. Güncelleme

PuTTY root oturumunda ZIP’i ayrı bir klasöre indir ve aç. Aşağıdaki örnekte açılmış kaynak klasörü `/root/kanit-kurulum/guncelleme22/KanitPaneli_Sunucu_v2.2`dir.

```bash
cd /root/kanit-kurulum/guncelleme22/KanitPaneli_Sunucu_v2.2
bash deploy/apply-update.sh --dry-run
```

Ön kontrol hata verirse gerçek güncellemeyi çalıştırma; yalnız hata metnini paylaş. `.env` içeriğini veya anahtarları paylaşma. Ön kontrol başarılı olunca:

```bash
bash deploy/apply-update.sh
```

Yardımcı kaynak kodunu, mevcut sanal ortamı, dosya izinlerini, bağımlılık uyumunu, SQLite yolunu ve uygulama servislerinin önceki aktiflik durumunu kontrol eder. `/var/backups/kanit-paneli/<zaman>/` altında özel kaynak kodu, `.env`, eski `requirements.txt`, eski birim dosyaları ve SQLite backup API ile tutarlı veritabanı yedeği oluşturur. Yalnız önceden aktif uygulama servislerini durdurur; yeni `app/` dizinini aynı dosya sisteminde aşamalı olarak değiştirir; eklemeli veritabanı geçişini `kanit` hesabıyla uygular; önceki aktif web ve bot servislerini yeniden başlatır.

**Bağımlılık yükseltmesi:** `requirements.txt` yalnız sabit **sürüm yükseltmesi** içeriyorsa (bu sürümde `Pillow==12.3.0 → 13.0.0`, 41 CVE kapatır) betik servisler kapalıyken, uygulama kodu değişmeden **önce** `/opt/kanit-paneli/.venv` içinde `pip install -r requirements.txt` çalıştırır (günlük: yedek dizininde `pip-install.log`); pip başarısızsa eski sürümleri geri kurar ve eski uygulamaya dokunmadan durur. Yeni paket adı, kaldırılan paket veya sürüm düşürme varsa pip hiç çalışmaz, betik `DURAKLATILDI [20]` ile durur. `--dry-run` farkı listeler ve `pip install --dry-run` ile çözümlenebilirliği gösterir (sunucuda internet gerekir).

**Birim dosyaları:** `deploy/kanit-web.service` ve `deploy/kanit-bot.service` kuruludan farklıysa eskileri `units.before/` altına yedeklenir, yenileri `/etc/systemd/system`e yazılır, `daemon-reload` yapılır ve servisler yeni birimle başlar; sağlık kontrolü geçmezse eski birimler ve eski kod geri gelir. `--dry-run` birim farkını (`diff -u`) gösterir. Sertleştirilmiş birimler (`systemd-analyze security` 8.5 → 1.4) ilk açılışta sorun çıkarırsa `journalctl -u kanit-web -n 50` içinde "Operation not permitted"/SIGSYS aranır; önce `MemoryDenyWriteExecute`, sonra `SystemCallFilter` satırları kaldırılıp `systemctl daemon-reload && systemctl restart kanit-web` denenir.

`.env`, `.venv`'in kendisi, görsel/arşiv klasörleri, oturum anahtarı ve HTTPS yapılandırması ezilmez. Plesk’in `nginx`, `apache2` ve `kanit-ip-proxy` servisine restart/reload komutu verilmez. Güvenlik duvarı, yedek zamanlayıcısı, fail2ban ve günlük döndürme bu betikle değil §11'deki ayrı betiklerle kurulur. Ön kontrol importu artık geçici bir dizinle çalışır; `data/` altında root sahipli dizin bırakmaz, kalmışsa sonunda uyarı yazar.

**Güncelleme yedeği 2 GB görsel arşivinin tam yedeği değildir.** Medya dosyaları değiştirilmez; yine de onları kendi yedekleme düzeninde ayrıca sakla. Hata halinde kaynak kodu ve önceki servis aktifliği geri alınır. Sonradan oluşmuş kayıtları silmemek için SQLite otomatik eski yedeğe dönülmez; gerektiğinde özel yedekteki manuel geri dönüş notunu izleyin.

Başarılı çıktıdan sonra:

```bash
curl -fsS http://127.0.0.1:18080/saglik
systemctl status kanit-web kanit-bot --no-pager -l
```

`OK` iç servis sağlığıdır (yanıt başlığı `X-Kanit-Paneli: 2.3.0`; bu başlık yalnız sunucunun kendisinden, 127.0.0.1 üzerinden yapılan isteklerde döner); dış HTTPS erişimini tarayıcıdaki mevcut IP adresinden kontrol et. Tarayıcı eski görünümü gösteriyorsa sayfayı Ctrl+F5 ile yenile. Daha önce kapalı olan bot yardımcı tarafından kendiliğinden başlatılmaz. Bot ayarların doluysa ve gerçekten başlatmak istiyorsan `systemctl start kanit-bot` kullan. Aynı Telegram anahtarıyla başka PowerShell, Docker veya test botu süreci çalıştırma.

## 1a. Alan adı ile HTTPS — Cloudflare (TURUNCU bulut), ana yol

IP sertifikası (`https://217.156.123.36:18443`) kısa ömürlüydü ve dolmuştur; yenilenmeyecek. Kalıcı yol: alan adını Cloudflare'a ekle, **turuncu bulut** (Proxied) ile sunucuya yönlendir. Ziyaretçi sertifikasını Cloudflare verir; sunucu tarafında 15 yıllık **Cloudflare Origin CA** sertifikası (yenileme yok) ya da betiğin ürettiği 10 yıllık öz imzalı sertifika kullanılır. Let's Encrypt/certbot gerekmez. Plesk'in nginx'ine tek dosya eklenir (`/etc/nginx/conf.d/zz020_kanit-panel.conf`); mevcut siteye, Apache'ye, postaya ve `IP:18443` yoluna dokunulmaz.

**Cloudflare panelinde (betikten önce ya da sonra):**

1. **DNS → Records:** A kaydı `panel` → `217.156.123.36`, Proxy status **Proxied (turuncu bulut)**.
2. **SSL/TLS → Overview:** şifreleme modu **Full (strict)** (Origin CA ile) ya da **Full** (öz imzalı ile). *Flexible* kullanmayın.
3. **SSL/TLS → Edge Certificates:** **Always Use HTTPS** = On.
4. **SSL/TLS → Origin Server → Create Certificate:** RSA 2048, 15 yıl, hostname `panel.alanadiniz.com` → çıkan iki metin bloğunu (Origin Certificate, Private Key) kaydedin; betiğe dosya olarak verin ya da sorulduğunda yapıştırın.

**Sunucuda (PuTTY root):**

```bash
cd /root/kanit-kurulum/<acilmis-paket>
bash deploy/setup-cloudflare-https.sh panel.alanadiniz.com --dry-run
# Origin CA dosyalarıyla (önerilen):
bash deploy/setup-cloudflare-https.sh panel.alanadiniz.com --sertifika /root/origin.pem --anahtar /root/origin.key
# ya da soru-cevapla (sertifikayı ve anahtarı yapıştırın, her biri Ctrl+D ile biter); sertifika yoksa 10 yıllık öz imzalı üretir:
bash deploy/setup-cloudflare-https.sh panel.alanadiniz.com
```

Betik: Plesk nginx'in sağlıklı olduğunu, panelin `/saglik` verdiğini ve DNS'in Cloudflare'a (turuncu bulut) çözüldüğünü kontrol eder; sertifikayı `/opt/kanit-ssl/cloudflare/` altına kaydeder (root 600); nginx dosyasını yazar (`listen 217.156.123.36:443 ssl`, `server_name` alan adı, 80 → 301); gerçek ziyaretçi IP'sini `CF-Connecting-IP` başlığından alır (`set_real_ip_from` Cloudflare aralıkları, betiğe gömülü; `--ip-guncelle` ile internetten tazelenir); **Cloudflare'ı atlayıp doğrudan IP'ye Host başlığıyla gelen istekler 403 alır** (`--herkese-acik` bunu kapatır); `/giris` için nginx `limit_req` (10/dk, gerçek IP) uygular; `nginx -t` + reload sonrası yerel origin kontrolü ve Cloudflare üzerinden `https://ALAN/saglik` kontrolü yapar. Sonunda **CLOUDFLARE_HTTPS_TAMAM** ve Cloudflare adımlarını yazar. Hata olursa yalnız kendi nginx dosyasını geri alır. Kaldırmak: `bash deploy/setup-cloudflare-https.sh --kaldir` (sertifika dosyaları kalır).

> **Turuncu/gri bulut karıştırılmaz.** `setup-cloudflare-https.sh` yalnız **turuncu bulut** içindir: gri bulutta ziyaretçiler doğrudan sunucuya gelir ve 403 alır. `setup-domain-https.sh` (Let's Encrypt, alternatif) yalnız **gri bulut** içindir: turuncu bulutta certbot doğrulaması başarısız olur ve `$remote_addr` Cloudflare uç IP'si olur (uygulamanın IP sınırı herkesi birlikte kilitler, fail2ban/limit_req Cloudflare'ı engeller). Alan adı Cloudflare'da **DEĞİŞTİRMEYİN**; moda göre doğru betiği kullanın. İki betik aynı dosyayı yazar; biri kuruluyken diğeri çalışmaz (`--kaldir` ile önce kaldırın).

**Alan adı çalıştıktan sonra IP yolu (isteğe bağlı, önerilir):** birkaç gün paralel kullanın, sonra dolmuş IP sertifikalı 18443'ü kapatın: `systemctl disable --now kanit-ip-proxy` (ufw kuruluysa `ufw delete allow 18443/tcp`). Geri açmak: `systemctl enable --now kanit-ip-proxy`.

**Alternatif — Let's Encrypt (gri bulut / Cloudflare yok):** `bash deploy/setup-domain-https.sh panel.alanadiniz.com eposta@ornek.com --dry-run` sonra bayraksız; betik 80 portu doğrulama yolunu, certbot'u (`/opt/kanit-certbot`) ve `kanit-sertifika.timer` yenileme zamanlayıcısını kurar. Ayrıntı betiğin başındaki açıklamada.

## 2. Telegram akışı

İlk `/start` girişinde mevcut `BOT_PASSWORD` sorulur. Web admin parolası bundan ayrıdır. Başarılı giriş bot kimliği ve kullanıcıya özel tutulur. Fotoğraf ya da görsel belge gönder; **sunucuda görsel** veya **Gyazo bağlantısı** seç; proje, kategori ve soruları tamamla; onayla.

Aktif seçim ekranı yeni mesaj olarak sohbetin altına gelir; önceki ekranın düğmeleri kaldırılır. Geri/iptal ve eski butondan güncel akışa dönüş korunur. İstenmeyen “Görünüm” tercihi kaldırılmıştır. Telegram’ın desteklediği native `primary/success/danger` buton renkleri kullanılır; Telegram mesajlarında serbest hex metin/buton rengi desteği varmış gibi sunulmaz. Panelin proje rozetleri kendi tam renklerini kullanır.

Gyazo seçimi dönüşümü kalıcı arka plan işine alır; “Gyazo linkine dönüştürülüyor” ara mesajı yoktur. Sorular dönüşümü beklemez. Onaydan sonra terminal sonuç verilir. İş yeniden başlatma sırasında kaybolmaz; belirsiz yükleme sonucunda kör tekrar yükleme yapılmaz. Yerel görsel dönüşüm başarısızlığında da korunur. Görsel işlem sırasında değiştirilmişse eski link yeni görsele uygulanmaz ve yanlış başarı mesajı gönderilmez.

## 3. Gyazo yapılandırması

`GYAZO_TOKEN` bir **Gyazo access token**dır; Telegram bot anahtarı değildir. Güncelleme mevcut `.env` dosyanı koruduğu için bu alan boşsa boş kalır. Boşken site dönüşüm düğmesi bunu belirtir ve yeni bot akışı eksik yapılandırmayı dürüstçe bildirir.

Anahtarı yalnız özel PuTTY terminalinde, açılmış güncelleme paketindeki yardımcıyla gir:

```bash
/opt/kanit-paneli/.venv/bin/python deploy/configure-gyazo.py
systemctl restart kanit-web
# Bot zaten aktifse yeni ayarı yüklemek için onu da yeniden başlat:
systemctl try-restart kanit-bot
```

Girişte karakter görünmemesi normaldir. Yardımcı yalnız `GYAZO_TOKEN` satırını değiştirir; HTTPS/port/Telegram/parola ayarlarını korur. Kaynak pakette gerçek anahtar yoktur. Gyazo’ya gönderim dış servise yüklemedir; link görünürlüğünü dikkate al. API yetki, erişim, hız limiti veya ağ hatasını panelin işlem geçmişinde kontrol et. Gerçek hesabın başarısı kullanıcı sunucusunda dönüşüm seçilerek doğrulanmalıdır; otomatik testte sahte sağlayıcı kullanılır.

## 4. Admin parolası ve sunucu komutları

Panel şifre kuralı **en az 8 karakter**dir. Sunucu komutları **`kanit` hesabıyla** çalıştırılır (`runuser -u kanit --`); root ile çalıştırılırsa `data/` altında root sahipli WAL/küçük resim dosyaları kalır ve servis "readonly database" gibi sessiz hatalar verir. Parola komut satırına yazılmaz; kabuk geçmişine düşmesin diye `read -rs` ile okunur:

```bash
cd /opt/kanit-paneli
read -rs KANIT_PW; export KANIT_PW          # parolayı yazıp Enter'a basın (ekranda görünmez)
runuser -u kanit -w KANIT_PW -- .venv/bin/python -m app.cli sifre-sifirla admin --password-env KANIT_PW --kalici
unset KANIT_PW
```

`--kalici` olmadan kullanıcı ilk girişte şifresini değiştirmek zorunda kalır. İlk hesabı açmak için:

```bash
cd /opt/kanit-paneli
read -rs KANIT_PW; export KANIT_PW
runuser -u kanit -w KANIT_PW -- .venv/bin/python -m app.cli admin-ekle admin --password-env KANIT_PW
unset KANIT_PW
```

`--password-env` verilmezse komut parolayı iki kez sorar. Diğer komutlar (hepsi `runuser -u kanit -- .venv/bin/python -m app.cli ...` ile): `durum`, `yedekle <hedef> [--gorseller]`, `arsiv-tara`, `ice-aktar <kaynak>`. Yanlışlıkla root ile çalıştırıldıysa onarım: `systemctl stop kanit-web kanit-bot; chown -R kanit:kanit /opt/kanit-paneli/data; systemctl start kanit-web kanit-bot`.

## 5. Admin ve proje sınırı

**Yönetim → Kullanıcılar** yalnız süperadmin içindir. Yeni normal admin için projeleri açıkça seç; okuma ve kontrol/onay/yorum, düzenleme, silme gibi yetkileri ver. Normal admin yalnız atanmış ve okuma izni olan projeleri görür. Diğer proje adı, renk, kategori, filtre, sayaç, kayıt, profil, bildirim, görsel ve raporlar görünmez. Değiştirilmiş URL/ID veya form da erişim sağlamaz.

Yeni proje normal adminlere otomatik açılmaz. Süperadmin seçimi ayrı ve açık yapılır. Son aktif süperadmin kapatılamaz veya düşürülemez. Yetki/parola değişimi eski oturumları geçersiz kılar; eski açık kullanıcı düzenleme formu yeni yetkiyi geri açamaz.

CLI’de `admin` tam süperadmin; `OF` yalnız OF tam işlemdir; `OF:oku` salt okuma; `OF:oku,kt` okuma/onay/yorumdur. Güncelleme ile **BETA** projesi (turuncu) katalogda bir kez otomatik oluşur; normal adminlere açmak için Kullanıcılar ekranından yetki ver. `*` yeni roller için geçerli değildir. Eski wildcard proje rolleri geçişte o anki projelerin açık listesine çevrilir; gelecekteki projeleri otomatik açmaz.

## 6. Proje, kategori ve sorular

**Yönetim → Proje / Kategoriler** ekranında **Yeni proje ekle** veya **Yeni kategori ekle** bölümünü aç. Projeye kalıcı kod, görünen ad ve renk ver. Kategoriye bağlı projeleri seç; hazır soru şablonu kullan veya Personel/Üye ID/Ana üye ID/Lead ID/Tip sorularını tek tek ekle. Kendi metin veya seçim sorunu ekleyebilirsin; seçim seçenekleri satır başına bir değerdir. Yukarı/aşağı düğmeleri sırayı değiştirir.

Mevcut kayıtları bozmamak için kodlar değiştirilmez; pasife alma kullanılır. Soru listesi ve cevaplar kayıt anında saklanır. Sonradan kategori sorusu değişse bile eski kanıtın sorusu/cevabı kaybolmaz. Özel cevaplar kayıt detayında ve dışa aktarımda görünür. Standart Personel/Üye/Lead ID düzenlemesi ilgili soru cevabını da eşitler. Devam eden akış kendi soru anlık görüntüsünü kullanır.

## 7. Kayıtlar, bildirim ve işlem geçmişi

Kayıtlar ekranında yalnız yetkili proje çipleri vardır. Kategori seçimi seçilen projelere bağlıdır. Ara, durum, tarih ve ekleyen filtreleriyle tablo/kart/galeri kullanılabilir. Otomatik tam sayfa yenilemesi yoktur. Arka plan yoklaması yalnız bildirim/sayaç ve değişiklik uyarısı getirir; **Yenile** kontrolüyle sonuçları kendin güncellersin. Filtre, açık yorum taslağı ve odak korunur. Çakışan kayıt sürümü sessizce ezilmez; güncel kayıtla yeniden deneme istenir.

Detayda onaylayan/zaman ve görünür işlem geçmişi; geniş yorum/soru/yanıt alanı vardır. Alıcı seçerek ilgili proje sorumlusuna soru yönelt; yanıt aynı kayıt konuşmasında kalır. **Bildirimler** ayrı sayfada eski/okunmuş/okunmamış, tür/tarih/proje filtreli geçmişi sunar. Okundu durumu kişiye özeldir. Yetkisi kaldırılan hesap eski bildirimle de kayıt içeriğine erişemez.

Zil listesinde her bildirim kayıt numarası ve personel koduyla görünür (örn. "#12 · 1001 ARK · Yeni kanıt eklendi"); listede en çok 15 öğe gösterilir, fazlası için **Tümünü gör** bağlantısı vardır. Ana sayfadaki hızlı arama personel, üye ID, ana üye ID, lead, bağlantı, açıklama, ekleyen ve kategori alanlarında arar; sonuç bekleyen, onaylı ve silinen tüm kayıtları kapsar.

**Pop-up ve ses (2.3.3).** Panel açıkken gelen her yeni bildirim zilin altında bir kart olarak çıkar (proje, tür, "#kayıt · personel · kategori", metin; **Aç** kayda gider, **Okundu**, ×). Normal kartlar 15 sn sonra kapanır (üzerindeyken durur), hatırlatma kartları kalır; aynı anda 3+ bildirimde tek özet kart ("5 yeni bildirim (2 hatırlatma)") çıkar. Yeni bildirimde kısa bir ses, hatırlatmada üç tonlu zil çalar; tarayıcı kuralı gereği ses, sayfaya bir kez tıklandıktan/tuşa basıldıktan sonra çalar. Sesi kapatmak: zil → **Ses** anahtarı (tercih o tarayıcıda saklanır). Okunmamış hatırlatma varsa ortada **Bekleyen kontroller hatırlatması** penceresi açılır; her hatırlatma için günde en çok bir kez kendiliğinden açılır, sayfadan sayfaya geçerken yeniden açılmaz (2.3.4). Satırdaki **Aç** kayda gider (proje özeti satırında **Bekleyenleri aç**); **Kapat**/Esc: bu hatırlatmalar için pencere bir daha kendiliğinden açılmaz, yeni hatırlatma gelirse açılır; **Daha sonra**: bugün pencere bir daha kendiliğinden açılmaz, yeni hatırlatmalar kart ve zil olarak gelir; **Tümünü okundu say** hatırlatmaları okundu sayar. Pencereyi elle açmak: zil → **Hatırlatmalar (N)**. Kayıt penceresi açıkken ya da bir alana yazılırken pencere beklenir. Sekme arka plandayken de 30 sn'de bir kontrol edilir; ses ve masaüstü bildirimi hemen, kartlar sekmeye dönünce gösterilir. Ayrıntı: `DEGISIKLIKLER_v2.3.3.md`.

Masaüstü bildirimi tarayıcı izni (zil → **Masaüstü bildirimlerini aç**) ve panel açıkken çalışır; bildirime tıklanınca panel öne gelir ve kayıt açılır; site kapalıyken yeni push/Telegram bildirim kanalı kurulmaz. **İşlem Geçmişi** aktör, zaman, işlem ve hedefi gösterir; proje ve kategori kayıtları "Proje: BETA" / "Kategori: ark" biçiminde, artık bulunmayan kayıtlar "Kayıt anahtarı" olarak etiketlenir. Normal admin kendi izinli kayıt geçmişini; süperadmin global yönetim işlemlerini görür. Parola/hash/token/ham giriş mesajları logda gösterilmez.

Ekleyenin kanıt profili güvenilir Telegram kayıtlarıyla proje dağılımını ve beklenen ana proje dışı kayıtları gösterir. Tahmini eski eşleştirme kesin sahiplik diye sunulmaz. Proje dışı olmak tek başına hatalı kanıt değildir.

## 8. Kanıt Kontrolü: XLSX, CSV/TSV, ODS, TXT

Bu ekran **kayıt eklemez**; yalnız izinli veritabanı kayıtlarını karşılaştırır. Dosya yükle, önizlemeyi kontrol et, gerekirse kodlama/ayraç/başlık satırı ve sayfayı değiştir. Başlık satırı `0` başlıksız tablo içindir. TXT’de **her satır tek ID** ve **ayraçlı tablo** modları ayrıdır; ID modunda virgül/noktalı virgül ID’nin parçası olarak korunur.

Sütunları Proje/Kategori/Personel/Üye ID/Ana üye ID/Tür/Lead ID’ye bağla; karşılaştırılacak kimlik alanlarını seç. Seçili kriterlerin tamamı tutmalıdır. Bulundu, yok, çoklu, boş/belirsiz veya kapsam dışı durumlar ayrı değerlendirilir. Eksik kanıt raporu yalnız kesin “yok” sonuçlarını içerir. Baştaki sıfırları kaynakta metin olarak koru; kaybolmuş Excel basamakları veya hesaplanmamış formüller kesin yok diye gösterilmez.

TXT için gösterilen okuma notu mavi bilgi kutusudur; kırmızı/sarı uyarı değildir. Ekrandaki düğme ve alan adları sade Türkçedir ("Dosyayı yükle", "Önizlemeyi yenile", "Kayıtlarla karşılaştır", "Onay durumu").

Limitler: 12 MB yükleme, 50.000 kaynak satırı, 20.000 ilgili karşılaştırma satırı, 512 sütun. Ekran sayfa başına 100 sonuç ve satırda ilk 20 eşleşme ID’sini gösterir; indirilen rapor saklanan tam sonucu (satır başına en çok 1.000 ID; kırpma uyarısıyla) içerir. Kontrol zamanı UTC, kapsam ve seçenekler rapora yazılır. Eski rapor indirilirken de güncel proje yetkisi doğrulanır. Özel geçici kontrol dosyaları 24 saat sonra temizlenir.

## 9. Eski kayıt ve 2 GB arşiv

Bu güncelleme mevcut veritabanını sıfırlamaz. Henüz eski verini taşımadıysan orijinal XLSX/bot günlüklerini ayrı bir eski-veri klasörüne koyup bir defalık `app.cli ice-aktar` komutuyla taşı. CSV/ODS/TXT kontrol yüklemesi veri taşıma veya kanıt ekleme değildir.

`telegram_gorseller` klasörünü alt dizin/indeks düzenini koruyarak SFTP veya sunucu dosya yöntemiyle veri dizinine taşı. Arşivi herkese açık `static`/Plesk `httpdocs` dizinine koyma. Süperadmin arşiv taraması ve belirsiz eşlemeyi elle bağlama kullanabilir. Gerçek 2 GB arşivin tamamı bu geliştirme ortamına verilmediği için gerçek eşleşme sayısı doğrulanmış değildir.

## 10. Test ve güvenlik

2.2 düzeltme turunda (genel) yapılanlar: `GET /bot?sure=...` geçersiz değerde 500 vermez; Bot sayfasında Onayla / Engelle / Tam sıfırla ayrı kartlardır ve boş ad Telegram'daki adı korur; bot durumu "son X dakikadır sinyal vermedi" gibi okunur cümledir; arşiv tarama sonucu düz cümle olarak gösterilir; giriş sonrası yönlendirme sorgu dizesini korur (`?sonraki=/kayitlar?durum=onayli`); yetki/şifre değişince kullanıcı "Oturumunuz sona erdi…" mesajıyla giriş sayfasına gönderilir, açık pencerede fetch çağrıları JSON 401 alır ve sayfa kendiliğinden giriş ekranına döner; Çıktı sayfasında ters tarih aralığı formda satır içi uyarıdır ve 0 kayıtlı seçimde boş dosya yerine uyarı gösterilir (istenirse "Yine de boş dosyayı indir"); `/saglik` ve statik dosyalar oturum çerezi yazmaz; Kullanıcılar sayfasında üretilen geçici şifre kopyala düğmeli kutuda sayfa yenilenene kadar kalır ve kullanıcı düzenleme formu çalışır (2.1'deki 500 hatası giderildi); form desen hataları Türkçe gösterilir.

`TEST_SONUCLARI.md`, `DEGISIKLIKLER_v2.2.md` ve `DEGISIKLIKLER_v2.1.md` yapılan düzeltmeleri ve doğrulama sınırlarını ayırır. Testler geçici SQLite, sahte Telegram/Gyazo ve izole arayüz verisiyle çalışır. Gerçek sunucuya bu paket kendiliğinden yüklenmez.

```bash
python -m pip install -r requirements.txt pytest
python -m pytest -q tests
```

Gerçek token, parola, kullanıcı DB’si ve görsel arşivi pakete dahil değildir. Sohbette paylaşılmış anahtar/parolaları canlı kullanım öncesi yenile. IP sertifikası (18443) dolmuştur ve yenilenmez; kalıcı erişim yolu §1a'daki Cloudflare kurulumudur. Dağıtım betiklerinin testleri `tests/test_guvenlik_deploy.py` içindedir (nginx, systemd-analyze, fail2ban-regex ve root yoksa ilgili testler atlanır).

**Bağımlılık kilidi notu:** `requirements.txt` yalnız doğrudan paketleri sabitler; geçişli paketler (Werkzeug, urllib3, certifi...) kurulum anında çözülür. Kurulu ortamın tam listesini saklamak için güncellemeden sonra sunucuda `/opt/kanit-paneli/.venv/bin/python -m pip freeze > /root/kanit-kurulum/pip-freeze-$(date +%F).txt` alın (yeniden kurulumda `pip install -r` ile aynı sürümler gelir). Depoya `requirements-lock.txt` eklenmez; `apply-update.sh` yalnız `requirements.txt`'i izler.

## 11. İşletim: yedek, günlük, fail2ban, güvenlik duvarı, kontrol listesi

Aşağıdaki betikler açılmış paketin `deploy/` dizininden, PuTTY root oturumunda çalıştırılır. Hepsi `--yardim` ve (güvenlik duvarı hariç) `--dry-run` destekler; sunucuyu kilitleyebilecek işlemler yalnız açık bayrakla yapılır.

**Yedek (bulgu: otomatik yedek yoktu).** `bash deploy/setup-backup.sh --dry-run` sonra `bash deploy/setup-backup.sh`: `kanit-yedek.timer` kurulur (her gün 03:17 + rastgele 15 dk, kaçırılan çalışma açılışta telafi). Her gün: SQLite yedeği (backup API, `kanit` hesabıyla, bütünlük denetimli) → `/var/backups/kanit-paneli/gunluk/panel-YYYYMMDD.db.gz` ve `.env` kopyası `env-YYYYMMDD` (root 600). Pazar günleri (ve ilk kez): `data/gorseller` + `data/telegram_gorseller` aynası → `haftalik/YYYY-Www/` (rsync `--link-dest` ile değişmeyen dosyalar hardlink; 2 GB arşiv ilk hafta tam, sonraki haftalar yalnız fark; disk yetmezse UYARI ile atlar). Saklama: 14 günlük, 8 haftalık; `apply-update` yedek dizinlerinden en yeni 5 kalır (60 günden eskiler silinir); panel "Yedek al" dosyalarından son 5 kalır. Doğrulama: `kanit-yedek.sh --dogrula` (son yedeği açar, `PRAGMA integrity_check` + kayıt sayısı). Günlük: `journalctl -t kanit-yedek -n 20`. Geri yükleme: `kanit-yedek.sh --geri-yukle /var/backups/kanit-paneli/gunluk/panel-YYYYMMDD.db.gz` — servisleri kendisi durdurur, mevcut `panel.db` (varsa `-wal`/`-shm` yan dosyalarıyla) `/root/kanit-onceki/<zaman>/` altına kopyalanır, yedek açılıp `PRAGMA integrity_check` ile doğrulanır, eski `panel.db-wal`/`panel.db-shm` artıkları silinir (silinmezse SQLite eski WAL sayfalarını geri yüklenen dosyanın üzerine bindirir ve veri karışır), dosya `kanit:kanit` olarak yerleştirilir ve servisler açılır; sonda `GERI_YUKLEME_TAMAM` yazar. Önce `--dry-run` ekleyerek planı görebilirsiniz. Kurulu kopya `/usr/local/sbin/kanit-yedek.sh`'tır; paket güncellendikçe `bash deploy/setup-backup.sh` ile yenilenir. Elle yapmayın. Haftalık görsel aynası sırasında silinen/değişen dosya (rsync 23/24) hata değil UYARI'dır; yedek yine tamamlanır. **Dış kopya şart** (aynı disk tek arıza noktasıdır); betik kurmaz, örnek: `rsync -a --delete /var/backups/kanit-paneli/ yedek@DIS-SUNUCU:/yedek/kanit/` ya da `rclone sync /var/backups/kanit-paneli uzak:kanit-yedek` (rclone yapılandırması ayrı; günlük cron/timer olarak ekleyin).

**Günlük döndürme.** `install -m 644 deploy/logrotate-kanit /etc/logrotate.d/kanit-paneli && logrotate -d /etc/logrotate.d/kanit-paneli` — kanit-ip-proxy nginx access/error günlükleri haftalık, 8 kopya, sıkıştırılmış. `bot_log.txt` uygulama içinde döndürülür. Görsel önbelleği (`data/tmp/gyazo`, `data/tmp/thumbs`) boyut/yaş sınırını uygulama kendi içinde uygular; disk takibi: `du -sh /opt/kanit-paneli/data/* /var/backups/kanit-paneli`.

**fail2ban (yalnız IP yolu 18443 açıkken anlamlı).** Plesk'in fail2ban'ı zaten çalışıyor (sshd ve Plesk jail'leri); `bash deploy/setup-fail2ban.sh --dry-run` sonra `bash deploy/setup-fail2ban.sh` ona `kanit-web` jail'ini ekler (`/etc/fail2ban/jail.d/kanit-web.local`, `/etc/fail2ban/filter.d/kanit-web.conf`, `fail2ban-client reload`): journald'daki `kanit-web GIRIS_HATA/GIRIS_SINIR/GIRIS_KILIT ip=...` satırlarından 10 hata / 10 dk → 1 saat engel (portlar 18443, 443). Durum: `fail2ban-client status kanit-web`. **Cloudflare arkasında bu engel etkisizdir:** TCP bağlantısı Cloudflare uçlarından gelir, iptables gerçek ziyaretçiyi göremez (Cloudflare uçları `ignoreip`'tedir, hiçbir zaman engellenmez). Orada asıl koruma uygulamanın hesap kilidi + IP sınırı ve nginx `limit_req` (gerçek IP) katmanıdır. İstenirse fail2ban'ın `cloudflare` action'ı (Cloudflare API token ile uç tarafında engel) kurulabilir; bu paket onu kurmaz, yalnız belirtir.

**Güvenlik duvarı (isteğe bağlı; Plesk sunucusunda dikkat).** `bash deploy/setup-firewall.sh` yalnız durumu ve planı yazar; `--uygula` ile ufw kurallarını uygular: SSH portu `sshd_config`'den okunur ve **önce** izin verilir; 80, 443, 18443 açık; 18080 dışa kapalı; Plesk 8443/8880 varsayılan **kapalı** (`--plesk` açar); posta portları (25/465/587/993/995/110/143) varsayılan **açık** bırakılır çünkü sunucuda Plesk posta alanları var (`--posta-kapat` kapatır). Plesk'in kendi güvenlik duvarı ya da fail2ban iptables zincirleri varsa betik uyarır. Uyguladıktan sonra oturumu kapatmadan yeni bir PuTTY oturumuyla girişi doğrulayın; girilemiyorsa `ufw disable`. Betik herhangi bir kuralda hata verip durursa ufw etkinleştirilmemiştir; elle `ufw enable` yazmayın (kuralsız etkinleştirme SSH dahil her şeyi kapatır).

**Gyazo kopyaları.** `runuser -u kanit -- .venv/bin/python -m app.cli gyazo-onbellekle` kayıtlardaki tüm Gyazo bağlantılarını sunucu önbelleğine bir kez indirir (yeniden çalıştırılabilir, kaldığı yerden sürer; 429'da bekler), açılamayanları `data/gyazo-acilamayan.csv` dosyasına yazar ve önbellek sınırına yaklaşılırsa uyarır. Eski Excel kayıtlarının tek kopyası Gyazo'da olduğu için aktarımdan sonra çalıştırın (KURULUM 3e). Gece planı: `bash deploy/setup-gyazo-gece.sh` her gece 22:30 (Europe/Istanbul) başlayıp gecede en çok 900 bağlantı indiren, 07:30'da duran ve kaldığı yerden süren `kanit-gyazo.timer` kurar (`--saat/--bitis/--gecelik/--kaldir`; günlük `journalctl -u kanit-gyazo`). Komut seçenekleri: `--en-cok N` deneme, `--yeni-en-cok N` gecelik sınır, `--pencere 22:30-07:30`, `--ayrintili`; başta Gyazo erişimini dener, yanıt alamazsa 1 sn sonra bir kez daha dener, yine ulaşılamıyorsa (yaklaşık yarım dakikada) `GYAZO_ONBELLEK_YARIM` ile durur (çıkış kodu 1). Snappark ve Teamzone görselleri de Gyazo gibi sunucu üzerinden getirilip `data/tmp/dis/` altında saklanır ve aynı komutla kopyalanır (`DIS_GORSEL_PROXY=0` kapatır). Güncellemeler GitHub'dan taze kopya olarak alınır, depo geçmişi sunucuda tutulmaz (KURULUM §13).
**API (2.3.2).** Süperadmin, Yönetim → API anahtarları ekranından başka sistemler için salt okunur anahtar oluşturur (`Authorization: Bearer kp_…`); uçlar `/api/v1/ozet`, `/kayitlar`, `/kayit/<id>`, `/gorsel/<id>` ve kısıtlı `SELECT` için `/api/v1/sorgu`; anahtar başına dakikalık sınır, istek günlüğü, `API_ACIK=0` ile kapatma. Ayrıntı ve curl örnekleri: `API_KULLANIM.md`.
**IP yolu (kanit-ip-proxy) bakımı.** Mevcut `/opt/kanit-ssl/nginx.conf`'a `/giris` sınırı + TLS/HTTP2 satırlarını eklemek: `bash deploy/nginx-giris-siniri.sh --dry-run` sonra bayraksız (eski dosya `.before-*` olarak kalır, `nginx -t` geçmeden yazılmaz). Birimi sertleştirmek: `bash deploy/setup-ip-https.sh --servis-guncelle --dry-run` sonra bayraksız (eski birim yedeklenir; sağlık kontrolü geçmezse geri alınır; bu yoldaki sağlık kontrolü sertifika doğrulamaz, dolmuş IP sertifikasıyla da çalışır). Alan adı çalışınca servis kapatılır (§1a).

**İşletim kontrol listesi (ayda bir):**

```bash
timedatectl                                   # Time zone Europe/Istanbul, NTP synchronized: yes
grep ^TZ= /opt/kanit-paneli/.env              # TZ=Europe/Istanbul
systemctl is-active unattended-upgrades; apt list --upgradable 2>/dev/null | wc -l   # unattended-upgrades aktif; bekleyen güncelleme sayısı
[ -f /var/run/reboot-required ] && echo 'yeniden başlatma bekliyor'
df -h / /var/backups; du -sh /opt/kanit-paneli/data/* /var/backups/kanit-paneli 2>/dev/null
/usr/local/sbin/kanit-yedek.sh --dogrula; systemctl list-timers kanit-yedek.timer --no-pager
openssl x509 -in /opt/kanit-ssl/cloudflare/panel.alanadiniz.com.pem -noout -enddate   # Origin CA 15 yıl
fail2ban-client status; fail2ban-client status kanit-web 2>/dev/null | head -8
systemd-analyze security kanit-web.service kanit-bot.service kanit-ip-proxy.service --no-pager | grep Overall
journalctl -p warning -u kanit-web -u kanit-bot --since '7 days ago' --no-pager | tail -30
```

## Son verilen özel ayar dosyası

`KanitPaneli_Ozel_Sunucu_Ayarlari.env` ayrı, özel teslim dosyasıdır; herkese açık kod ZIP’inin içinde değildir. Son verdiğin Telegram/Gyazo anahtarları, bot/admin parolası, yönetici ID’si ve deneme sayısı bu dosyaya yazılmıştır. `ADMIN_IDS` Python servisine uygun virgüllü satır biçimindedir. Web admin parolası değiştirilmez.

Dosyayı yalnız SFTP/WinSCP gibi yetkili bağlantıyla `/root/kanit-kurulum/ozel.env` konumuna taşı; herkese açık web köküne veya paylaşım bağlantısına koyma. Açılmış kaynak paketinde:

```bash
chmod 600 /root/kanit-kurulum/ozel.env
/opt/kanit-paneli/.venv/bin/python deploy/apply-private-settings.py /root/kanit-kurulum/ozel.env
```

Yardımcı yalnız yedi özel alanı birleştirir; port/HTTPS/veri yolu/oturum anahtarı ve diğer mevcut ayarlar değişmez. Ayar yedeği özel klasörde tutulur; terminale sır yazdırılmaz. Başarıdan sonra uygulama güncellemesi veya mevcut aktif uygulama servislerinin yeniden başlaması yeni ortamı yükler. Ayrı HTTPS/Plesk servisine dokunulmaz.

Gönderdiğin JSON eski yapılandırma biçimidir; Python servisi bu JSON’u değil `.env` dosyasını okur. `GYAZO_BAKIM=1` son verdiğin haliyle özel dosyada tutulmuştur, ancak incelediğimiz eski PowerShell kaynağı ve yeni 2.1/2.2 kaynak bu alanı kullanmaz. Bu yüzden tek başına bu değer dönüşüm hatasının kanıtı değildir; Gyazo access token’ın gerçek `.env` içine taşınması ve erişimin doğrulanması gerekir.
