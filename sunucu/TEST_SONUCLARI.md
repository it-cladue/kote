# Kanıt Paneli 2.3 — test sonuçları

23 Kasım 2026 son koşu: `python3 -m pytest -q tests` → **242 passed**, yaklaşık 95 saniye (2.2'nin 150 testine güvenlik turunda 92 yeni test eklendi: `test_guvenlik_web.py` 18 + `test_web_kimlik.py` 11, `test_guvenlik_bot.py` 26, `test_guvenlik_gorsel.py` 12, `test_guvenlik_deploy.py` 25). Pillow 13.0.0 ile çalıştırıldı.

## 2.3 güvenlik turunda eklenen doğrulamalar

| Alan | Sonuç |
|---|---|
| Açık yönlendirme | `/%09/evil`, `/%0d%0a/evil`, `//evil`, `/%5Cevil`, `https://evil` hedefleri `/`'e düşer; CRLF'de eski 500 yok |
| Oturum | Çıkış sonrası eski çerez → giriş sayfası (XHR'a JSON 401); 24 saati aşan oturum "süreniz doldu" ile düşer; HTTPS=1'de `__Host-kanit_session`, HSTS includeSubDomains'siz |
| Kilit | Süresi dolan kilidin sayacı sıfırlanır; kilitli/olmayan kullanıcıda aynı mesaj ve aynı süre; `giris_kilit`/`giris_sinir`/`csrf_hata` denetim satırları; Kullanıcılar sayfasında kilit etiketi |
| CSP | Tüm sayfalarda CSP + nonce; şablonlardaki her satır içi betik nonce taşır; Playwright ile masaüstü ve telefonda sıfır CSP ihlali |
| /sifre | Yanlış mevcut parola giriş hesabını kilitlemez (ayrı sayaç 5/10 dk); aynı/kullanıcı adı içeren/yaygın parola reddi |
| Yetkisiz uçlar | `/manus-routes.json` anonim → 302, admin olmayan → 403; `/saglik` sürüm başlığı yalnız 127.0.0.1'den |
| Girdi | NUL/kontrol karakteri temizliği (yorum, soru, yanıt, bildirim, silme sebebi, görünen ad); Excel çıktısı satır üst sınırı ve Türkçe uyarı |
| Günlük/vekil | `kanit-web GIRIS_HATA/GIRIS_SINIR/GIRIS_KILIT/CSRF_HATA` satır biçimi ve satır sonu enjeksiyonu reddi; `GUVENILEN_PROXY` ile tek vekil; 13 MiB gövde sınırı (14 MiB → 413) |
| Bot | Bozuk görsel tek indirme + kullanıcı mesajı; outbox kalıcı hata → ölü, geçici hata geri çekilme; 429 retry_after duraklatması; `/admin` istem süresi, deneme sayacı, mesaj silme, oturum süresi; engelli/onaysız yanıt sınırları; sticker parola denemesi sayılmaz; budama ve pending temizliği; MAX_DENEME env; onaysız kişinin ilk fotoğrafında parola politikası; `/engel` hedef doğrulaması; maskeleme; günlük döndürme; uzun çıktı bölme; Türkçe parola denemesinde çökme yok |
| Görsel önbelleği | Boyut/yaş sınırı aşımında en eskiden %90'a inme; LRU dokunma; sembolik bağ ile önbellek dışına çıkılmaz; kullanıcı görsellerine dokunulmaz; indirme boyutu sınırı; eşzamanlı çağrı |
| Kurulum betikleri | `bash -n` ve shellcheck temiz; systemd birimleri `systemd-analyze security` ≤ 3 (web/bot 1.4); fail2ban-regex örnekleri; `requirements-diff` yalnız sürüm yükseltmesi kabul; apply-update dry-run / başarılı yükseltme + birim senkronu / pip hatasında geri alma / sağlık hatasında birim geri alma (geçici hedef); gerçek nginx 1.24 ile IP, Let's Encrypt ve Cloudflare şablonları (limit_req → 429, TLS 1.1 ve PFS'siz paket reddi, HTTP/2, Cloudflare dışı kaynak → 403, CF-Connecting-IP → gerçek IP); yedek betiği (artımlı ayna, saklama, --dogrula, bozuk yedek tespiti); ufw plan/uygula; logrotate |

## Birleşik kodun tarayıcı kontrolü ve güncelleme provası

Birleşik 2.3.0 kodu, 60 örnek kayıtlı veritabanıyla gerçek `waitress` üzerinde başlatıldı; Chromium ile masaüstü (1366×900) ve telefon (iPhone 13) görünümlerinde giriş, ana sayfa, kayıtlar (bekleyen/hepsi), kayıt detayı, kullanıcılar, katalog, bot, işlem geçmişi, bildirimler, çıktı, kanıt kontrolü, arşiv, şifre ve JSON uçları gezildi: CSP ihlali ve betik hatası yok; tek konsol kaydı örnek kayıtların görsel dosyası olmadığı için küçük resim 404'leri.

Sahte `/opt/kanit-paneli` (kanit kullanıcısı, 2.2.0 kodu ve veritabanı, `.env`, sanal ortam) üzerinde gerçek `deploy/apply-update.sh` ile 2.2.0 → 2.3.0 provası: sonuç aşağıdaki bölümde.

İlk prova bir hata yakaladı: güncelleme betiği `umask 077` altında çalıştığı için pip'in yazdığı Pillow 13 dosyaları yalnız root tarafından okunabiliyordu; kanit hesabıyla çalışan migration denetimi `ImportError` verdi, betik geri aldı ama geri kurulan eski Pillow da aynı izinle kaldığından eski web servisi açılamadı. Düzeltme: pip kurulumu ve geri kurulumu `umask 022` ile, ardından kanit hesabıyla içe aktarma denetimi (başarısızsa izin onarımı, yine olmazsa geri alma, çıkış kodu 38). İkinci prova: `DRY-RUN_TAMAM` (Pillow 12.3.0→13.0.0 planı, pip çözümleme TAMAM, iki birim dosyası), ardından `GÜNCELLEME_TAMAM`; sürüm başlığı 2.3.0, Pillow 13.0.0 kanit tarafından okunabilir (dizin 755), birim dosyaları kuruldu, 60 kayıt / 2 panel kullanıcısı / 2 Telegram kullanıcısı korundu, yedek `/var/backups/kanit-paneli/<zaman>` altında. Yükseltilmiş sahte sunucu nginx TLS vekili (18443, X-Forwarded-Proto https) arkasında Chromium ile yeniden tarandı: `__Host-kanit_session` çerezi ve CSP başlığı var, giriş ve tüm sayfalar masaüstü/telefonda açılıyor, CSP ihlali yok.

---

# Kanıt Paneli 2.2 — test sonuçları

18 Ekim 2026 son koşu: `python3 -m pytest -q tests` → **148 passed**, yaklaşık 40 saniye (2.1'deki 84 teste 2.2 için 64 yeni test eklendi: `test_genel_v22.py`, `test_kayitlar_v22.py`, `test_fixpass_genel.py`, `test_fixpass_kayitlar.py`, `test_sonqa_genel.py`, `test_sonqa_kayitlar.py`). Tek uyarı, kötü niyetli/bozuk ZIP kontrolü testinde bilerek oluşturulan yinelenen `content.xml` üyesinden gelir; bu dosyanın reddi test edilir. Python (`ast`), JavaScript (`node --check`) ve güncelleme Bash (`bash -n`) sözdizimleri doğrulandı.

## 2.2 ile eklenen doğrulamalar

| Alan | Sonuç |
|---|---|
| Menü ve sürüm | Süperadmin menüsünde Ana sayfa / Kayıtlar / Çıktı / Kanıt Kontrolü / Bildirimler / İşlem Geçmişi / Yönetim bağlantıları; normal adminde yönetim bağlantılarının bulunmaması; sayfa başlıkları, `aria-current`, hamburger ve zil kutusu, `v=2.2.3` varlık sürümü, `/saglik` başlığı `2.2.0` |
| BETA projesi | Yeni kurulumda ve BETA'sız 2.1 veritabanında bir kez eklenir (renk `#FFA500`, aktif, aktif kategoriler bağlı); admin pasife alır/yeniden adlandırırsa sonraki bağlantılar geri getirmez; mevcut proje satırları değişmez; kullanıcı formu, çıktı ve bot istatistiğinde katalogdan görünür |
| Şifre kuralı | 7 karakter reddi, 8 karakter kabulü (hesap ekleme, güncelleme, `/sifre`, yönetim formu); `minlength="8"` ipuçları |
| CLI | `admin-ekle --password-env`, `sifre-sifirla --password-env` (ilk girişte değişim) ve `--kalici` (kalıcı parola, hesap aktif); kısa parola ve boş ortam değişkeni hataları |
| Hata sayfaları | 404'te başlık, açıklama ve **Geri dön**; tarayıcı isteğinde HTML, `fetch` isteğinde JSON (`ok:false, hata`); CSRF hatasının özel metni; 500'de "Beklenmeyen hata, kayıt no …", ham hata metninin kullanıcıya sızmaması, `sunucu_hata` denetim satırı ve JSON karşılığı |
| Ana sayfa | KPI sayıları (bekleyen, bugün eklenen, bugün onaylanan, açık soru) ve **Son işlemler** listesi yalnız yetkili projeleri kapsar; yetkisiz projenin kodu, kişisi veya kaydı HTML'de yer almaz; süperadmin tüm hareketleri görür; yanıtlanan soru sayaçtan düşer |
| Diğer sayfalar | Bildirimler, İşlem Geçmişi, Arşiv, Bot, Telegram kullanıcı durumu, ekleyen profili, Kanıt Kontrolü, Çıktı, Katalog, Kullanıcılar ve Şifre sayfaları 200 döner; sayfaya özel `<title>`, üst etiket + `h1` düzeni; satır içi `onclick` yok; giriş sayfası yeni kart düzeni |

2.1 kapsamı (bot, Gyazo, katalog, yetki, bildirim/konuşma, dosya kontrolü, eşzamanlı sürüm çatışması, özel ayar, aktarım/arşiv) değişmeden geçmektedir; `test_katalog` içindeki aktif proje sayısı BETA nedeniyle 6 → 7 olarak güncellendi.

## Gerçek tarayıcı kontrolü (Playwright / Chromium)

Geçici SQLite, örnek kayıtlar ve üç hesapla panel `waitress` üzerinde başlatıldı; masaüstü (1366×900) ve telefon (390×844) görünümlerinde açık ve koyu tema için giriş, ana sayfa, kayıtlar, çıktı, kanıt kontrolü, bildirimler, işlem geçmişi, katalog, kullanıcılar, bot, arşiv, şifre, 404 ve ekleyen profili sayfalarının ekran görüntüleri alındı. Yönetim açılır menüsünün tıklamayla açılıp ekran dışına taşmadığı ve Esc ile kapandığı, zil kutusunun açıldığı, telefonda hamburger menünün yönetim bağlantılarını gösterdiği ve kayıt ayrıntı penceresinin açıldığı gerçek DOM ölçümüyle doğrulandı. Telefonda yatay sayfa kaydırması yok. Konsolda yalnız bilerek açılan 404 sayfasının kendi "404" kaynağı görüldü; başka JavaScript hatası veya başarısız istek yok.

## Son kalite kontrolü (18 Ekim 2026)

Birleşik 2.2 kodu üzerinde üç bağımsız tarayıcı turu yapıldı: masaüstü süperadmin (68 kayıt, ~330 kontrol, 115 ekran görüntüsü), telefon + sınırlı yetkili admin (ofadmin `OF:oku,kt`, paokur `PA:oku`, pasif hesap, kilit, yetki değişince oturum düşmesi; 160 ekran görüntüsü) ve veri/geçiş sağlamlığı (2.1 veritabanının 2.2 ile açılması: 41/41 ve sıfırdan 2.1 verisi ile 45/45 kontrol; 30 uç kayıt — Windows yolu, `../`, 0 bayt, 25 MB, 10×10, yanlış uzantı, boş anahtar, bozuk tarih, emoji; 3000 kayıtla yük; CLI; `apply-update.sh --dry-run`; güvenlik başlıkları; sahte Telegram ile bot akışı). 2.1 raporundaki hataların tamamının giderildiği doğrulandı. Bulunan 1 yüksek (Yenile sonrası toplu onay çubuğu), 8 orta ve 12 düşük önemli bulgu düzeltildi ve her biri için test eklendi; son turda JS hatası, beklenmeyen 4xx/5xx ve telefonda yatay taşma yok.

Ayrıca sahte bir `/opt/kanit-paneli` kurulumunda (kanit kullanıcısı, `.env`, 2.1 verisi ve sanal ortam) `deploy/apply-update.sh --dry-run`, kod değişimi, eklemeli migration, `/saglik` ve bot import adımları gerçek sırayla denendi; eski kayıtlar yeni panelde açıldı.

## Dış doğrulamalar ve sınırlamalar

Bu 2.2 paketi henüz kullanıcının canlı sunucusuna uygulanmadı; `deploy/apply-update.sh` mantığı 2.1 ile aynıdır (yalnız başlık metni güncellendi). Gerçek Gyazo erişimi, gerçek Telegram botu ve 2 GB görsel arşivi geliştirme ortamında yoktur; ilgili testler sahte sağlayıcılarla çalışır. Tarayıcı kontrolü örnek veriyle yapıldı; canlı kurulumda eski CSS önbelleği için Ctrl+F5 gerekebilir (varlıklar `v=2.2.3` ile sürümlenmiştir).
