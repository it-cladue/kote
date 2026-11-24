# Kanıt Paneli 2.3 — güvenlik ve sağlamlık turu (23 Kasım 2026)

Bu sürüm, panelin internete açılması için yapılan bağımsız güvenlik denetiminin sonucudur. Beş alan (web kimlik/oturum, girdi ve veri, altyapı/kurulum, Telegram botu, bağımlılıklar) ayrı ayrı incelendi; 57 bulgu çıktı, orta ve üzeri önemdeki 14 bulgu ikinci bir denetçi tarafından yeniden üretilerek doğrulandı. Kritik bulgu yoktu. Aşağıdaki değişikliklerle bulguların tamamına yakını kapatıldı; bilinçli olarak yapılmayanlar en sonda listelenir.

Veritabanı yapısı yalnız eklemeli değişir; mevcut kayıtlar, kullanıcılar, katalog ve görseller korunur. Güncelleme `deploy/apply-update.sh` ile uygulanır.

## Güncelleme sonrası bilmeniz gerekenler

- **Tüm panel kullanıcıları bir kez yeniden giriş yapar.** Oturumlara giriş zamanı eklendi ve HTTPS'te çerez adı `__Host-kanit_session` oldu.
- Oturum en çok **24 saat** sürer (12 saat hareketsizlik sınırı da devam eder). **Çıkış** düğmesi aynı hesabın tüm cihazlardaki oturumlarını kapatır.
- Şifre değiştirirken yeni kurallar: en az 8 karakter, eskisiyle aynı olamaz, kullanıcı adını içeremez, çok yaygın parolalar (123456, password, telecc123 gibi) kabul edilmez. Mevcut girişler etkilenmez.
- Bot: bozuk veya çok büyük görsel gönderen personele anında "Görsel okunamadı … yeniden gönderin" denir; onaysız biri önce fotoğraf gönderirse artık engellenmez, parola istenir; aynı 20 saniye içinde gelen fotoğraflar ve albümler tek deneme sayılır, engel yalnız 3 ayrı denemede uygulanır.
- Yönetici komutları (`/admin`): parola 2 dakika içinde yazılmalı, parola mesajı sohbetten silinir, 3 yanlışta 10 dakika kilit, oturum 30 dakika hareketsizlikte kapanır.

## Web: kimlik doğrulama, oturum ve girdi

- **Açık yönlendirme kapatıldı.** Giriş sonrası `sonraki` hedefi yalnız site içi yol olabilir; sekme/satır sonu karakteri, ters bölü, `//` ve şema içeren hedefler ana sayfaya düşer (eski kodda kontrol karakteriyle atlatılabiliyor, CRLF'de 500 veriyordu).
- **Çıkış oturumu sunucu tarafında geçersizleştirir.** Eski çerez bir daha çalışmaz (önceden 12 saat geçerli kalıyordu); çıkış İşlem Geçmişi'ne yazılır.
- **Hesap kilidi düzeltildi.** Süresi dolan kilidin sayacı sıfırlanır (15 dakikada bir istekle hesabı süresiz kilitlemek artık mümkün değil); kilit ve IP sınırı olayları İşlem Geçmişi'ne yazılır (`giris_kilit`, `giris_sinir`); Kullanıcılar sayfasında "Kilitli: HH:MM kadar" etiketi görünür ve kaydetmek kilidi açar. Giriş ekranı kilidi söylemez; olmayan ve kilitli kullanıcılarda da aynı süre ve aynı mesaj verilir (kullanıcı adı tahmini zorlaştırıldı).
- **İçerik güvenlik politikası (CSP)** her yanıtta: betikler yalnız siteden ve sayfaya özel nonce ile; `frame-ancestors 'none'`, `form-action 'self'`, `base-uri 'self'`, `object-src 'none'`. Ayrıca `Permissions-Policy` ve `Cross-Origin-Opener-Policy`. Tüm sayfalar gerçek tarayıcıda sıfır CSP ihlaliyle doğrulandı.
- Geçici parola artık çerezde değil, sunucuda 10 dakika ömürlü ve tek kullanımlık saklanır.
- `/manus-routes.json` yalnız süperadmine açık; `/saglik` sürüm başlığı yalnız sunucunun kendisinden (127.0.0.1) yapılan isteklerde döner.
- `/sifre`: yanlış mevcut parola giriş hesabını kilitlemez (ayrı sayaç: 10 dakikada 5 hata → 10 dakika bekleme), mesaj doğru ("Mevcut parolanız yanlış"), deneme İşlem Geçmişi'ne yazılır.
- Yönetici bir kullanıcıya web formundan parola yazarsa kullanıcı ilk girişte değiştirmek zorundadır.
- Güvenilmeyen `Host` başlığı için `GUVENILEN_HOSTLAR` ayarı (boşsa eski davranış); güvenilmeyen Host'ta 500 yerine sade 400.
- Oturum anahtarı döndürme: `SESSION_SECRET_ESKI` ile eski anahtarlar bir süre kabul edilir.
- Oturumlu kullanıcıdan gelen geçersiz CSRF denemesi İşlem Geçmişi'ne `csrf_hata` olarak yazılır (dakikada en fazla bir).
- Yorum, soru, yanıt, mesaj bildirimi, silme sebebi ve görünen ad metinlerinden NUL ve kontrol karakterleri temizlenir.
- Excel çıktısı tek dosyada en çok 30.000 kayıt (`CIKTI_SATIR_SINIRI`); aşılırsa anlaşılır uyarı ve tarih aralığı daraltma önerisi; dosya akışla yazılır (bellek dostu).
- Başarısız giriş, IP sınırı, kilit ve CSRF olayları sunucu günlüğüne (journald) sabit biçimde tek satır yazılır: `kanit-web GIRIS_HATA ip=… kullanici=…`, `GIRIS_SINIR`, `GIRIS_KILIT`, `CSRF_HATA`. fail2ban filtresi bu satırları okur.
- İstek gövdesi üst sınırı sunucu katmanında da uygulanır (13 MiB); daha büyük yüklemeler okunmadan kesilir.
- Ters vekil güveni daraltıldı: `trusted_proxy='*'` yerine tek güvenilen vekil (`GUVENILEN_PROXY`, varsayılan 127.0.0.1).
- Kanıt Kontrolü geçici dosyaları (data/checks) yalnız yüklemede değil, uygulama başlangıcında da temizlenir.

## Telegram botu

- **Bozuk görsel tekrar tekrar indirilmiyor.** Boyut, tür ve Pillow doğrulama hataları kalıcı sayılır: tek indirme, kullanıcıya tek açıklama; yalnız ağ hataları sınırlı sayıda yeniden denenir. İndirme tavanı 20 MiB.
- **Gönderim kuyruğu (outbox) sağlamlaştırıldı.** "bot engellendi", "sohbet bulunamadı", "metin ayrıştırılamadı" gibi kalıcı Telegram hataları bir kez denenir; geçici hatalar en çok 5 kez, artan bekleme ile (5/30/120/600 sn). Tek takılı mesaj artık long-poll süresini kalıcı olarak kısaltmıyor. Telegram 429 yanıtında `retry_after` okunur ve tüm gönderimler o süre duraklar.
- **Yönetici parolası akışı:** istem 2 dakika geçerli (`ADMIN_PROMPT_SANIYE`), parola mesajı silinir, 3 yanlışta 10 dakika kilit, denetim kaydı (`telegram_admin_giris`, `telegram_admin_giris_hata`), oturum 30 dakika hareketsizlikte kapanır, ADMIN_IDS'ten çıkarılan kişi hemen yetkisiz olur.
- **Mesaj seline karşı:** engelli kullanıcıya 10 dakikada bir, onaysız kullanıcıya 20 saniyede bir yanıt verilir. Sticker, ses, konum gibi metinsiz mesajlar parola denemesi sayılmaz.
- **Budama:** tg_gelen/tg_giden tablolarının 30 günden eski tamam/ölü satırları günde bir silinir; sahipsiz bekleyen görsel dosyaları 24 saat sonra temizlenir; bot günlüğü 5 MB'ta döndürülür (`bot_log.txt.1..3`).
- Bakım modunda görsel indirilmez. Parola içerebilecek başarısız mesajların ham verisi saklanmaz.
- `.env`'deki `MAX_DENEME` artık gerçekten okunur (1-10).
- `/engel` ve benzeri komutlar yalnız 5-15 haneli sayısal Telegram ID kabul eder; `/engel` panelle aynı yoldan çalışır (onay korunur, işlem geçmişinde görünür); ölü yerleşik `/engel_kaldir` kopyası kaldırıldı.
- Günlük maskeleme kapsamlı: çıplak token, `bot<id>:` biçimi ve ortamdaki gerçek parola/token değerleri `[GİZLİ]` olur. Kısa ve yaygın bir BOT_PASSWORD günlükte de maskelenir; en az 8 karakter seçin.
- Uzun yönetici çıktıları HTML etiketini bölmeyen parçalara ayrılır ("… (devamı var)"); `/son_kullanicilar` en çok 100 kayıt; `/durum` çıktısına "Teslim edilemeyen mesaj" satırı eklendi.
- Yapılandırma hatalarında (token/parola yok, webhook tanımlı) açık Türkçe mesaj ve çıkış kodu 2; ağ hatasında süreç çıkmaz, artan bekleme ile yeniden dener.
- Türkçe karakter içeren parola denemeleri botu çökertip 5 kez yeniden deneme döngüsüne sokuyordu; düzeltildi.
- Her bağlantı açılışında tüm tabloyu güncelleyen dönüşüm işleri şema onarımı yalnız gerektiğinde çalışır (yazma kilidi azaldı).

## Görsel önbelleği

- `data/tmp/gyazo` (tam boy Gyazo kopyaları) ve `data/tmp/thumbs` (küçük resimler) artık sınırlı: `GYAZO_ONBELLEK_MB` 2000, `GYAZO_ONBELLEK_GUN` 0 (yaşa göre silme kapalı; bu kopyalar yalnız Gyazo'da duran eski kanıtların sunucudaki tek kopyası olabildiği için varsayılan olarak süreyle silinmez), `KUCUK_ONBELLEK_MB` 300 (0 = sınır yok). Sınır aşılınca en eski kullanılandan başlayarak %90'a inilir; temizlik en fazla 10 dakikada bir çalışır ve yalnız önbellek klasörlerine dokunur. Kullanıcı görselleri (`data/gorseller`, `data/telegram_gorseller`) kapsam dışıdır.
- Yarım kalan indirmeler (`.part`) temizlenir; tek indirme sınırı 20 MB korunur.
- `python -m app.cli durum` önbellek doluluğunu da gösterir.

## Altyapı ve kurulum

- **Alan adı için ana yol artık Cloudflare turuncu bulut:** yeni `deploy/setup-cloudflare-https.sh` Plesk'in nginx'ine panel alan adı için bir blok ekler; Cloudflare Origin sertifikasını (15 yıl, yenileme yok) dosyadan ya da yapıştırarak alır, yoksa 10 yıllık öz imzalı sertifika üretir; gerçek ziyaretçi IP'sini `CF-Connecting-IP` başlığından alır; Cloudflare dışından gelen doğrudan bağlantıları 403 ile reddeder; `/giris` için dakikada 10 istek sınırı; `--dry-run`, `--kaldir`, `--ip-guncelle` (Cloudflare IP listesini tazeler). Let's Encrypt yolu (`setup-domain-https.sh`, gri bulut) alternatif olarak kaldı; IP sertifikası yenileme zamanlayıcısı kullanıcı kararıyla yazılmadı. Alan adı çalışınca IP yolu (`kanit-ip-proxy`, 18443) kapatılabilir.
- **Otomatik yedek:** `deploy/setup-backup.sh` günlük 03:17'de çalışan `kanit-yedek.timer` kurar. Günlük SQLite yedeği (bütünlük kontrolüyle, sıkıştırılmış) ve `.env` kopyası; haftalık görsel aynası (rsync ile artımlı, 2 GB arşiv tek seferde kopyalanır, sonrası yalnız fark); saklama 14 gün / 8 hafta; `kanit-yedek.sh --dogrula` son yedeği açıp doğrular. Dış kopya için README §11'de rclone/scp örneği.
- **systemd sertleştirme:** kanit-web ve kanit-bot birimleri `systemd-analyze security` puanında 8.5 (EXPOSED) → 1.4 (OK): yalnız data dizinine yazma, yetenek yok, sistem çağrısı filtresi, özel /tmp, aygıt ve çekirdek koruması. kanit-ip-proxy 8.7 → 4.2. Bot için başlangıç sınırı (5 dakikada 10 deneme) eklendi; kalıcı yapılandırma hatasında sonsuz yeniden başlatma yok. `apply-update.sh` birim dosyaları farklıysa yedekleyip günceller, açılmazsa geri alır.
- **Bağımlılık yükseltmesi:** Pillow 12.3.0 → 13.0.0 (açık CVE'ler kapandı). `apply-update.sh` artık yalnız sürüm yükseltmesi içeren requirements değişikliğini kabul eder: deneme çözümlemesi dry-run'da, gerçek kurulum servisler kapalıyken ve uygulama değişiminden önce; başarısızsa eski sürüm geri kurulur ve eski uygulama dokunulmaz kalır. Yeni paket adı, kaldırma veya düşürme reddedilir.
- **nginx:** üç şablonda da (IP, Let's Encrypt, Cloudflare) `/giris` için istek sınırı (dakikada 10, 429), yalnız TLS 1.2/1.3 ve ileri gizlilikli şifre paketleri, HTTP/2, oturum bileti kapalı, gövde sınırı 64 MB. Mevcut IP kurulumu için `deploy/nginx-giris-siniri.sh` aynı ayarları yerinde ve geri alınabilir biçimde uygular; `setup-ip-https.sh --servis-guncelle` birimi sertleştirir.
- **fail2ban:** `deploy/setup-fail2ban.sh` Plesk'in mevcut fail2ban'ına `kanit-web` filtresini ve jail'ini ekler (10 hata / 10 dk → 1 saat; GIRIS_HATA, GIRIS_SINIR, GIRIS_KILIT satırları). Cloudflare arkasında IP engeli etkisizdir; o yolda asıl koruma uygulama kilidi ve nginx istek sınırıdır (README'de açıklandı).
- **Güvenlik duvarı:** `deploy/setup-firewall.sh` önce planı gösterir, `--uygula` ile ufw kurar: SSH portu önce ve her zaman açık, 80/443/18443 açık, 18080 kapalı, Plesk 8443 ve posta portları için bayraklar. Plesk sunucusunda isteğe bağlıdır.
- **Günlük döndürme:** `deploy/logrotate-kanit` IP proxy günlükleri için haftalık döndürme.
- `apply-update.sh` ön kontrolü artık data dizininde root sahipli dosya bırakmaz; README'deki sunucu komutları `runuser -u kanit` ile ve parolayı `read -rs` ile alır (kabuk geçmişine düşmez); README'ye işletim kontrol listesi (§11) eklendi; `nginx.conf.example` güncellendi.

## Bağımsız inceleme turu (24 Kasım 2026)

Birleşik 2.3.0 kodu, düzeltmeleri yapan ekiplerden bağımsız dört inceleyici (web, bot, kurulum betikleri, yükseltme uyumu) tarafından yeniden incelendi; orta ve üzeri önemde görülen her bulgu ayrı bir denetçi tarafından çürütülmeye çalışıldı ve yalnız yeniden üretilenler kabul edildi. Yeni bir güvenlik açığı çıkmadı; aşağıdakiler bu turda kapatıldı:

- **Güvenlik duvarı betiği (`setup-firewall.sh --uygula`) gerçek ufw'de ilk kuralda duruyordu** (kural kelimeleri tek argüman olarak gidiyordu; sahte ufw ile yapılan test bunu göremedi). Düzeltildi; varsayılan politikalar artık kurallar başarıyla eklendikten sonra yazılır; hata hâlinde "ufw ETKİNLEŞTİRİLMEDİ, elle `ufw enable` yapmayın" uyarısı verilir.
- **`setup-ip-https.sh --servis-guncelle` dolmuş IP sertifikasıyla hiç başarılı olamıyordu** (sağlık kontrolü sertifika doğruluyordu, her denemede eski birime geri dönüp 18443'ü iki kez yeniden başlatıyordu). Bu yolda sağlık kontrolü artık sertifika doğrulamaz; dolmuş sertifika bilgi satırıyla belirtilir.
- **`setup-cloudflare-https.sh` DNS kontrolü** birden fazla adres çözüldüğünde (Cloudflare her zaman 2+ adres döndürür) yanlış "ne Cloudflare ne bu sunucu" uyarısı veriyordu; adresler tek tek sınıflandırılır, "turuncu bulut ✓" satırı canlıda da çıkar.
- **Geri yükleme reçetesi** WAL yan dosyalarını silmiyordu (kalan `-wal` dosyası geri yüklenen yedeğin üzerine bayat sayfalar bindirip indeksleri bozuyor; gerçek uygulamayla yeniden üretildi). Yeni `kanit-yedek.sh --geri-yukle DOSYA` komutu doğru sırayı uygular (durdur → eskiyi kenara al → bütünlük denetimi → yan dosyaları sil → yerleştir → başlat); README §11 ona yönlendirir.
- **Çıkış ile yönetici formu çakışması:** 2.3.0'da çıkış tüm cihazları düşürmek için oturum sürümünü artırıyordu; Kullanıcılar sayfası aynı sayacı eşzamanlılık denetimi için kullandığından, admin sayfayı açtıktan sonra hedef kullanıcı çıkış yaparsa "başka bir admin değiştirdi" hatası çıkıyordu. İyimser kilit ayrı bir `hesap_surumu` sütununa bağlandı (eklemeli şema değişikliği, ilk açılışta kendiliğinden); çıkışın tüm cihazları kapatma davranışı korunur.
- **Bot albüm davranışı:** onaysız yeni kullanıcı ilk mesaj olarak 3+ fotoğraflı albüm gönderirse her fotoğraf ayrı deneme sayılıp anında engelleniyordu; aynı 20 saniye içindeki fotoğraflar tek deneme sayılır.
- Bot: `getFile` kalıcı hataları (çok büyük dosya, geçersiz dosya kimliği) artık 5 kez yeniden denenmez, personele "Görsel okunamadı" denir; teslim edilemeyen korumalı ekran mesajı oturumu kilitlemez (düğmeler "hazırlanıyor" döngüsüne girmez); parola mesajı geçici bir hatada işlenemezse kullanıcıya "yeniden yazın" denir; servis durdurma başlangıç beklemesini keser (SIGKILL'e düşmez); 6 karakterden kısa sır değerleri günlük maskelemesinde kullanılmaz (kimlikleri bozuyordu), 8 karakterden kısa bot parolaları açılışta uyarı verir; 2.2'den kalan ve deneme sınırını aşmış kuyruk satırları güncellemede kapatılır; Telegram 429 duraklaması yalnız ilgili sohbeti bekletir (bir sohbetin seli diğerlerini durdurmaz).
- Web: güncellemeden önce açılmış (giriş zamanı olmayan) oturum "24 saat doldu" yerine genel yeniden giriş mesajı alır; geçici parolanın süresi geçen kayıtları her okumada ve Kullanıcılar sayfasında temizlenir; "kaydet = kilidi aç" etiketi gerçek davranışla eşlendi (değişiklik olmasa da kaydetmek kilidi açar, denetime `kilit_ac` yazılır); önbellek temizliğiyle görsel servisi arasındaki nadir yarış 500 yerine yeniden çözümleme/yer tutucu ile karşılanır; `--yetki superadmin` komut satırında `admin` eş anlamlısı olarak kabul edilir.
- Varsayılanlar: `GYAZO_ONBELLEK_GUN` 30 → **0** (Gyazo kopyaları yaşa göre silinmez; eski Excel kayıtlarının tek sunucu kopyası olabilir), `GYAZO_ONBELLEK_MB` 500 → **2000**, `CIKTI_SATIR_SINIRI` 100.000 → **30.000** (tek istek sunucuyu 20 saniye meşgul etmesin).
- Kurulum: `apply-update.sh` SQLite anlık görüntüsü artık `data/` kökünde `-wal`/`-shm` artığı bırakmaz ve bot açıldıktan 5 saniye sonra hâlâ çalışıyor mu diye bakar (değilse uyarı yazar); `kanit-yedek.sh` ayna sırasında silinen bir dosyada (rsync 24) durmaz; `configure-bot.py --yonetici` yönetici kimliği ve parolasını `.env`'e güvenli yazar (kabuk komutunda parola geçmez); `DOSYA_DOGRULAMA.sha256` güncelliği `tests/test_paket_manifesti.py` ile kilitlendi (manifest eskiyse paket adım 0'daki `PAKET_DOGRU` denetimi başarısız oluyordu).

## Yeni `.env` anahtarları (hepsi isteğe bağlı; yazılmazsa varsayılan geçerli)

| Anahtar | Varsayılan | Anlam |
|---|---|---|
| `GUVENILEN_HOSTLAR` | boş | Virgülle ayrılmış Host beyaz listesi (örn. `217.156.123.36,panel.alanadi.com`); doluysa 127.0.0.1 ve localhost kendiliğinden eklenir |
| `GUVENILEN_PROXY` | `127.0.0.1` | TRUST_PROXY=1 iken X-Forwarded-* başlıklarına güvenilen tek vekil |
| `SESSION_SECRET_ESKI` | boş | Anahtar döndürmede eski SESSION_SECRET değerleri (virgülle); 1-2 gün sonra silin |
| `CIKTI_SATIR_SINIRI` | `30000` | Excel çıktısında tek dosyaya yazılacak en çok kayıt |
| `GYAZO_ONBELLEK_MB` | `2000` | Gyazo önbelleği toplam üst sınırı (MB) |
| `GYAZO_ONBELLEK_GUN` | `0` | Bu kadar gün açılmamış Gyazo kopyası silinir; `0` = yaşa göre silme yok (varsayılan) |
| `KUCUK_ONBELLEK_MB` | `300` | Küçük resim önbelleği toplam üst sınırı (MB) |
| `MAX_DENEME` | `3` | Bot parolası yanlış deneme sayısı (1-10) |
| `BOT_YETKISIZ_GORSEL_POLITIKA` | `parola` | Onaysız kişinin ilk görseli: `parola` (parola iste, MAX_DENEME'de engel) ya da `engelle` (eski davranış, hemen engel) |
| `BOT_OUTBOX_MAX_DENEME` | `5` | Geçici Telegram hatasında bir mesajın en fazla deneme sayısı |
| `BOT_ENGELLI_UYARI_SANIYE` | `600` | Engelli kullanıcıya uyarılar arası en az süre |
| `BOT_PAROLA_ISTEM_SANIYE` | `20` | Onaysız kullanıcıya parola istemleri arası en az süre |
| `BOT_GUNLUK_SAKLAMA_GUN` | `30` | tg_gelen/tg_giden tamam/ölü satırlarının saklanma süresi |
| `BOT_PENDING_SAKLAMA_SAAT` | `24` | Sahipsiz bekleyen görsel dosyalarının silinme yaşı |
| `BOT_LOG_MAX_MB` | `5` | bot_log.txt döndürme eşiği |
| `ADMIN_PROMPT_SANIYE` | `120` | `/admin` parola isteminin geçerlilik süresi |
| `ADMIN_MAX_DENEME` | `3` | Yanlış yönetici parolası sayısı → kilit |
| `ADMIN_KILIT_SANIYE` | `600` | Yönetici parola kilidi süresi |
| `ADMIN_OTURUM_SANIYE` | `1800` | Yönetici oturumu hareketsizlik süresi |

## Bilinçli olarak yapılmayanlar

- İki aşamalı doğrulama (2FA): ayrı bir tasarım; parola kuralları ve kilit yeterli görüldü.
- Oturumu IP/tarayıcıya bağlama: mobil ağlarda IP değişir, kullanıcıyı düşürür.
- HSTS `includeSubDomains`: aynı sunucuda Plesk altında başka site var.
- IP sertifikasının yenilenmesi: kullanıcı kararıyla yapılmadı; alan adı Cloudflare üzerinden gelecek.
