# Kanıt Paneli 2.2 — mevcut sunucuda güvenli güncelleme

Bu paket Telegram botu ile web kontrol panelinin 2.2 kaynak sürümüdür. 2.2, 2.1 üzerine kullanım kolaylığı ve modern görünüm güncellemesidir; değişiklik listesi `DEGISIKLIKLER_v2.2.md` dosyasındadır. Senin mevcut Ubuntu/Plesk kurulumun için hazırlanmıştır. Kanıt ekleme yalnız Telegram’dan yapılır; site inceleme, onay, yorum/soru, bildirim, kullanıcı ve katalog yönetimi içindir. Excel canlı kayıt kaynağı değildir.

## Mevcut kurulum

| Bileşen | Konum / adres |
|---|---|
| Uygulama | `/opt/kanit-paneli` |
| Web adresi | `https://217.156.123.36:18443` |
| İç web servisi | `http://127.0.0.1:18080` — dışarı açılmaz |
| Uygulama servisleri | `kanit-web`, `kanit-bot` |
| Ayrı HTTPS servisi | Mevcut `kanit-ip-https` — bu güncellemede değiştirilmez |
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

Yardımcı kaynak kodunu, mevcut sanal ortamı, dosya izinlerini, bağımlılık uyumunu, SQLite yolunu ve uygulama servislerinin önceki aktiflik durumunu kontrol eder. `/var/backups/kanit-paneli/<zaman>/` altında özel kaynak kodu, `.env` ve SQLite backup API ile tutarlı veritabanı yedeği oluşturur. Yalnız önceden aktif uygulama servislerini durdurur; yeni `app/` dizinini aynı dosya sisteminde aşamalı olarak değiştirir; eklemeli veritabanı geçişini `kanit` hesabıyla uygular; önceki aktif web ve bot servislerini yeniden başlatır.

`.env`, `.venv`, görsel/arşiv klasörleri, oturum anahtarı ve HTTPS yapılandırması ezilmez. Plesk’in `nginx`, `apache2` ve ayrı HTTPS servisine restart/reload komutu verilmez. Güvenlik duvarı, cron veya sertifika yenilemesi kurulmaz. Bağımlılıklar değişmişse otomatik pip/apt yerine açık hata ile durulur.

**Güncelleme yedeği 2 GB görsel arşivinin tam yedeği değildir.** Medya dosyaları değiştirilmez; yine de onları kendi yedekleme düzeninde ayrıca sakla. Hata halinde kaynak kodu ve önceki servis aktifliği geri alınır. Sonradan oluşmuş kayıtları silmemek için SQLite otomatik eski yedeğe dönülmez; gerektiğinde özel yedekteki manuel geri dönüş notunu izleyin.

Başarılı çıktıdan sonra:

```bash
curl -fsS http://127.0.0.1:18080/saglik
systemctl status kanit-web kanit-bot --no-pager -l
```

`OK` iç servis sağlığıdır (yanıt başlığı `X-Kanit-Paneli: 2.2.0`); dış HTTPS erişimini tarayıcıdaki mevcut IP adresinden kontrol et. Tarayıcı eski görünümü gösteriyorsa sayfayı Ctrl+F5 ile yenile. Daha önce kapalı olan bot yardımcı tarafından kendiliğinden başlatılmaz. Bot ayarların doluysa ve gerçekten başlatmak istiyorsan `systemctl start kanit-bot` kullan. Aynı Telegram anahtarıyla başka PowerShell, Docker veya test botu süreci çalıştırma.

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

Panel şifre kuralı **en az 8 karakter**dir. Sunucuda admin parolasını kalıcı olarak sıfırlamak (ilk girişte değiştirme zorunluluğu olmadan):

```bash
cd /opt/kanit-paneli && KANIT_PW=telecc123 .venv/bin/python -m app.cli sifre-sifirla admin --password-env KANIT_PW --kalici
```

`KANIT_PW` yerine istediğin parolayı yaz; parola komut geçmişinde görünmesin diye ortam değişkeniyle verilir. `--kalici` olmadan kullanıcı ilk girişte şifresini değiştirmek zorunda kalır. İlk hesabı açmak için:

```bash
cd /opt/kanit-paneli && KANIT_PW=GucluParola1 .venv/bin/python -m app.cli admin-ekle admin --password-env KANIT_PW
```

`--password-env` verilmezse komut parolayı iki kez sorar. Diğer komutlar: `durum`, `yedekle <hedef> [--gorseller]`, `arsiv-tara`, `ice-aktar <kaynak>`.

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

Masaüstü bildirimi tarayıcı izni ve panel açıkken çalışır; site kapalıyken yeni push/Telegram bildirim kanalı kurulmaz. **İşlem Geçmişi** aktör, zaman, işlem ve hedefi gösterir; proje ve kategori kayıtları "Proje: BETA" / "Kategori: ark" biçiminde, artık bulunmayan kayıtlar "Kayıt anahtarı" olarak etiketlenir. Normal admin kendi izinli kayıt geçmişini; süperadmin global yönetim işlemlerini görür. Parola/hash/token/ham giriş mesajları logda gösterilmez.

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

Gerçek token, parola, kullanıcı DB’si ve görsel arşivi pakete dahil değildir. Sohbette paylaşılmış anahtar/parolaları canlı kullanım öncesi yenile. Mevcut kısa ömürlü IP sertifikasının otomatik yenilemesi isteğin üzere bu güncellemeye eklenmedi; sertifika yenilemeyi ayrıca takip et.

## Son verilen özel ayar dosyası

`KanitPaneli_Ozel_Sunucu_Ayarlari.env` ayrı, özel teslim dosyasıdır; herkese açık kod ZIP’inin içinde değildir. Son verdiğin Telegram/Gyazo anahtarları, bot/admin parolası, yönetici ID’si ve deneme sayısı bu dosyaya yazılmıştır. `ADMIN_IDS` Python servisine uygun virgüllü satır biçimindedir. Web admin parolası değiştirilmez.

Dosyayı yalnız SFTP/WinSCP gibi yetkili bağlantıyla `/root/kanit-kurulum/ozel.env` konumuna taşı; herkese açık web köküne veya paylaşım bağlantısına koyma. Açılmış kaynak paketinde:

```bash
chmod 600 /root/kanit-kurulum/ozel.env
/opt/kanit-paneli/.venv/bin/python deploy/apply-private-settings.py /root/kanit-kurulum/ozel.env
```

Yardımcı yalnız yedi özel alanı birleştirir; port/HTTPS/veri yolu/oturum anahtarı ve diğer mevcut ayarlar değişmez. Ayar yedeği özel klasörde tutulur; terminale sır yazdırılmaz. Başarıdan sonra uygulama güncellemesi veya mevcut aktif uygulama servislerinin yeniden başlaması yeni ortamı yükler. Ayrı HTTPS/Plesk servisine dokunulmaz.

Gönderdiğin JSON eski yapılandırma biçimidir; Python servisi bu JSON’u değil `.env` dosyasını okur. `GYAZO_BAKIM=1` son verdiğin haliyle özel dosyada tutulmuştur, ancak incelediğimiz eski PowerShell kaynağı ve yeni 2.1/2.2 kaynak bu alanı kullanmaz. Bu yüzden tek başına bu değer dönüşüm hatasının kanıtı değildir; Gyazo access token’ın gerçek `.env` içine taşınması ve erişimin doğrulanması gerekir.
