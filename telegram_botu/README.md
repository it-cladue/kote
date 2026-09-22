# Güvenliği Sertleştirilmiş Telegram Kampanya Botu

> 📖 Günlük kullanım için ayrıntılı Türkçe rehber: **KULLANIM_KILAVUZU.md**

Bu sürüm, yönetici erişimini **Telegram kimliği beyaz listesi + süreli yönetici oturumu** ile sınırlar; istenirse `ADMIN_REQUIRE_PASSWORD=1` ile **PBKDF2-SHA256 parola** ikinci doğrulaması da açılır. Normal kullanıcılar `/start` kayıt akışı ile `/profil`, `/giris`, `/ekran`, `/iptal` komutlarında yanıt alır. Kullanıcının gönderdiği **fotoğraflar** ekran görüntüsü kaydı akışını başlatır (aşağıda); diğer komutlar, videolar ve tanınmayan metinler yerleşik asistan dışında sessizce yok sayılır.

Kullanıcı Site ID bilgisini girdikten sonra bot, Telegram bilgileriyle birlikte bir özet gösterir ve **Evet, Kaydet** veya **Hayır, Düzelt** seçeneğini sunar. Yalnızca açıkça onaylanan kayıtlar veritabanına ve bot klasöründeki sütunlu CSV/Excel dosyalarına yazılır.

## Güvenlik Modeli

| Katman | Uygulanan davranış |
|---|---|
| Yönetici görünürlüğü | `/admin` yalnızca `admins.txt` içindeki sayısal Telegram ID’leri için çalışır |
| Yetkisiz deneme | Yetkisiz kullanıcıya parola ekranı, uyarı veya yönetici paneli gösterilmez |
| İkinci doğrulama | `ADMIN_REQUIRE_PASSWORD=1` yapılırsa beyaz listedeki yönetici ayrıca güçlü parolayı girmek zorundadır (varsayılan: kapalı) |
| Parola saklama | Düz parola desteklenmez; PBKDF2-SHA256 özeti zorunludur |
| Oturum süresi | Yönetici oturumu varsayılan olarak 15 dakika sonra kapanır |
| Deneme sınırı | Başarısız yönetici girişleri hız sınırı ve geçici engelleme ile kısıtlanır |
| Normal mesajlar | Site ID, ekran görüntüsü ve asistan akışları dışında metin, komut ve medya yanıtlanmaz |
| Ekran görüntüsü dosyaları | Dosya adı yalnızca `A-Z a-z 0-9 . _ -` karakterlerinden üretilir; yol saldırıları ve `..` engellenir; kullanıcı başına günlük kota vardır |
| Site ID doğrulaması | Uzunluk, izinli karakterler ve açık kullanıcı onayı denetlenir |
| Kayıt bütünlüğü | Bir Telegram ID için tek güncel Site ID kaydı tutulur |
| Dosya güvenliği | CSV, XLSX, veritabanı ve günlükler Linux’ta `0600` izniyle korunur |
| Formül enjeksiyonu | CSV/Excel hücrelerinde `=`, `+`, `-`, `@` başlangıçları etkisizleştirilir |
| Atomik çıktı | CSV ve Excel önce geçici dosyaya yazılır, sonra tek işlemle değiştirilir |

> Hiçbir yazılım mutlak güvenlik garantisi veremez. Bot klasörü yalnızca botu çalıştıran işletim sistemi kullanıcısına açık tutulmalı; token, parola özeti, `admins.txt`, veritabanı, CSV ve Excel dosyaları paylaşılmamalıdır.

## İlk Güvenli Kurulum

Önce `admins.txt` dosyasındaki örnek ID’yi silin ve yalnızca kendi **sayısal Telegram kullanıcı ID’nizi** yazın. Her satırda bir yönetici ID’si bulunabilir. Bir kişinin kullanıcı adı veya görünen adı yönetici yetkisi vermez; kontrol yalnızca sayısal Telegram ID’siyle yapılır.

Ardından güçlü bir yönetici parolası için paketle gelen aracı çalıştırın:

```bash
python3 sifre_hash_olustur.py
```

Windows’ta aynı komutu PowerShell veya Komut İstemi içinde `py sifre_hash_olustur.py` biçiminde de çalıştırabilirsiniz. Araç parolayı cihazınızda işler ve `pbkdf2_sha256$...` biçiminde bir özet üretir. Bu değeri `config.txt` içindeki zorunlu `PASSWORD_HASH=` satırına yapıştırın. Düz metin parola alanı bulunmaz ve desteklenmez.

`config.txt` içinde en az aşağıdaki alanları düzenleyin:

```text
TOKEN=YENI_BOTFATHER_TOKENI
PASSWORD_HASH=pbkdf2_sha256$...
ADMIN_SESSION_MINUTES=15
REGISTER_LINK=https://siteniz.example/kayit
ACTIVATE_LINK=https://siteniz.example/kampanya
```

Token ve parola özeti istenirse dosya yerine `TELEGRAM_BOT_TOKEN` ve `TELEGRAM_ADMIN_PASSWORD_HASH` ortam değişkenleriyle verilebilir. Ortam değişkenleri yapılandırma dosyasından önceliklidir.

> Önceki bir bot tokeni başka kişilerle paylaşılmışsa (örneğin bu klasör ZIP olarak gönderildiyse) BotFather üzerinden iptal edilip yeni token üretilmeli ve `config.txt` güncellenmelidir.

Windows’ta `BASLAT.bat` dosyasına çift tıklayın. Linux veya sunucuda aşağıdaki komutu kullanın:

```bash
chmod +x baslat.sh
./baslat.sh
```

## Kullanıcı Site ID Akışı

Kullanıcı tarafındaki kayıt akışı `/start` komutuyla başlar. Henüz kaydı olmayan kullanıcı için akış şöyledir:

1. Bot, `WELCOME_TEXT` ayarındaki kişiselleştirilmiş karşılama mesajını gösterir (örn. `Merhaba, {name} 👋!`).
2. `CHANNEL_LINK` doluysa bot tıklanabilir kanal mesajını gönderir (örn. `👉 Kanalımıza abone ol`).
3. Bot kullanıcıdan Site ID bilgisini ister; mesajda tıklanabilir **Kayıt Linki** ve `/profil` menüsü hatırlatması bulunur.
4. Kullanıcı Site ID bilgisini metin olarak gönderir.
5. Bot uzunluğu ve izinli karakterleri doğrular. Yalnızca harf, rakam, nokta, alt çizgi ve kısa çizgi kabul edilir.
6. Bot aşağıdaki bilgileri bir özet ekranında gösterir: Telegram ID, kullanıcı adı, ad-soyad ve girilen Site ID.
7. Kullanıcı **Evet, Kaydet** düğmesine basarsa kayıt yapılır.
8. Kullanıcı **Hayır, Yeniden Gir** düğmesine basarsa veri saklanmaz ve Site ID yeniden istenir; `/iptal` yazarsa akış "İşlem iptal edildi" mesajıyla kapanır.
9. Onaylanan kullanıcıya mevcut kampanya akışı gösterilir.

Kayıtlı kullanıcı tekrar `/start` yazdığında kayıt akışı tekrarlanmaz; karşılama ve kampanya akışına devam edilir. Kullanıcı `/profil` komutuyla (veya komut menüsündeki 🤴 Profil öğesiyle) kayıtlı Site ID'sini görüntüleyip **Site ID Değiştir** düğmesiyle aynı doğrulama ve onay akışından geçerek güncelleyebilir. Kullanıcının Site ID konuşması dışında gönderdiği normal mesajlar, dosyalar ve yönetici komutları yanıtlanmaz.

Kullanıcı komut menüsünde `/start`, `/profil`, `/giris` ve `/iptal` görünür; yönetici komutları yalnızca beyaz listedeki yönetici sohbetlerinde listelenir.

Telegram mesaj alanının solunda **🎮 PLAY** adlı bir menü düğmesi bulunur. Bu düğme, veritabanındaki güncel `giris_link` değerine; henüz yönetici tarafından değiştirilmediyse `config.txt` içindeki `LOGIN_LINK` adresine yönlendirir. Yönetici panelinden giriş adresi değiştirildiğinde Play düğmesi de bot yeniden başlatılmadan güncellenir. Menü yazısı gerektiğinde `MENU_BUTTON_TEXT` ayarıyla değiştirilebilir. Telegram web uygulaması gereği giriş adresi geçerli bir `https://` URL olmalıdır; adres geçersizse düğme kaybolmaz, otomatik olarak komut menüsüne dönülür ve `bot.log` dosyasına uyarı yazılır.

## Site ID Kayıt Dosyaları

Onaylanan kayıtlar öncelikle `hitbet_bot.db` içinde saklanır. Her başarılı onaydan sonra ve bot her başlatıldığında aşağıdaki iki dosya veritabanından yeniden oluşturulur:

| Dosya | Amaç |
|---|---|
| `data/site_id_kayitlari.csv` | Metin tabanlı, Excel ve benzeri uygulamalarla açılabilen kayıt dosyası |
| `data/site_id_kayitlari.xlsx` | Biçimlendirilmiş Excel çalışma kitabı |

Her iki dosyada şu sütunlar bulunur:

| Sütun | Açıklama |
|---|---|
| Telegram ID | Kullanıcının değişmeyen sayısal Telegram kimliği |
| Kullanıcı Adı | Varsa `@kullaniciadi` bilgisi |
| Ad | Telegram profilindeki ad |
| Soyad | Telegram profilindeki soyad |
| Site ID | Kullanıcının girip onayladığı değer |
| İlk Kayıt Tarihi | İlk onayın tarihi ve saati |
| Güncelleme Tarihi | Son kayıt güncellemesinin tarihi ve saati |

Aynı Telegram ID tekrar kaydedilirse yeni bir satır çoğaltılmaz; mevcut kayıt güncellenir. CSV ve Excel dosyalarını bot çalışırken elle düzenlemeyin; bunlar veritabanından üretilen rapor dosyalarıdır.

## Yönetici Paneli

Yönetici paneline erişmek için Telegram ID'nin `admins.txt` beyaz listesinde bulunması zorunludur. `config.txt` içinde `ADMIN_REQUIRE_PASSWORD=1` yapılmışsa `/admin` sonrasında ayrıca doğru yönetici parolası da girilmelidir (önerilen); varsayılan `0` değerinde yalnızca beyaz liste denetimiyle oturum açılır.

Beyaz listede olmayan bir kullanıcı `/admin`, `/setimage`, `/cancel`, `/startbroadcast` gibi yönetici komutlarını yazsa dahi bot yönetici arayüzü göstermez ve yanıt vermez. Eski veya taklit edilmiş yönetici düğmeleri de sunucu tarafındaki yetki kontrolünden geçmeden işlem yapamaz.

Panelde bağlantılar, karşılama/kampanya metinleri, kampanya kodu, medya kütüphanesi ve toplu gönderiler yönetilebilir. Yönetici oturumu süre dolduğunda yeniden parola doğrulaması gerekir.

### Medya Kütüphanesi

Yönetici oturumu açıkken gönderilen her fotoğraf veya video ayrı bir kütüphane kaydı olarak saklanır. Gönderi açıklaması kayıt adı olur; açıklama yoksa tarih ve medya türünden otomatik ad üretilir. Son yüklenen medya aktif yapılır.

`/admin → Foto / Video → Medya Kütüphanesi` yolundan kayıtlar listelenebilir, önizlenebilir ve **Aktif Et** düğmesiyle kampanyada kullanılacak medya seçilebilir. Aktif olmayan kayıtlar silinebilir. HTTPS medya URL’si veya `images` klasöründeki yerel dosya da kullanılabilir.

> Yönetici oturumu açıkken gönderilen **fotoğraf** artık iki seçenek sunar: **🗂 Kampanya Medyası Yap** (kütüphaneye ekler ve aktif yapar) veya **📸 Ekran Görüntüsü Olarak Kaydet**. Videolar eskisi gibi doğrudan kütüphaneye gider.

## Ekran Görüntüsü Kaydı

Kullanıcı (veya yönetici) bota bir **ekran görüntüsü** gönderdiğinde bot seçenek sunar: kategori düğmeleri (varsayılan: 👥 Arkadaşını Getir, 💰 Para Yatırma, 💸 Para Çekme, 🎁 Bonus Talebi, 📄 Diğer). Seçilen kategori için tanımlı bilgiler sırayla sorulur (örn. Site ID ve Arkadaş ID) ve görsel **bu bilgilerle adlandırılarak** `screenshots/` klasörüne kaydedilir:

```text
Arkadasini-Getir_2026-09-22_14-30-05_ABC123_XYZ789_123456789.jpg
```

Diğer yol: kullanıcı önce `/ekran` (ana menüdeki veya alt klavyedeki 📸 düğmesi) ile kategori ve bilgileri girer, en son fotoğrafı gönderir; fotoğraf geldiği anda doğrudan kaydedilir. Her kayıt `hitbet_bot.db` içindeki `screenshots` tablosuna ve `screenshots/ekran_goruntuleri.csv` dosyasına yazılır; yöneticilere görselle birlikte bildirim gider.

| Ayar (`config.txt`) | Açıklama |
|---|---|
| `SCREENSHOTS_ENABLED` | `1` açık (varsayılan), `0` kapalı |
| `SCREENSHOT_CATEGORIES` | `anahtar:Buton Yazısı:Alan1\|Alan2, ...` biçiminde kategori ve sorulacak bilgiler |
| `SCREENSHOT_NAME_FORMAT` | Dosya adı şablonu; `{kategori} {tarih} {saat} {alanlar} {tgid} {kullanici} {alan1}…` |
| `SCREENSHOT_DAILY_LIMIT` | Kullanıcı başına günlük kayıt sınırı (yöneticiler hariç) |

Yönetici komutları: `/ekranlar` (liste), `/ekranlar ID` (görsel + bilgiler), `/ekrankapat ID`, `/ekrandosya` (CSV). Kategoriler, dosya adı şablonu ve seçenek mesajı bot çalışırken `/admin → 📸 Ekran Görüntüleri` bölümünden de değiştirilebilir.

## Tıklanabilir Yazı ve Kampanya Kodu

Toplu mesaj açıklamasında tıklanabilir yazı için aşağıdaki biçimi kullanın:

```text
Kanalımıza hemen abone ol → [[TIKLA|https://t.me/ornekkanal]]
```

Kullanıcı yalnızca **TIKLA** yazısını görür ve dokunduğunda bağlantı açılır. Kampanya kodu kopyalanabilir kod veya dokununca görünen gizli kod olarak ayarlanabilir.

## Dosya Yapısı

| Dosya/klasör | Açıklama |
|---|---|
| `bot.py` | Ana Python kaynak kodu |
| `config.txt` | Token, zorunlu parola özeti ve başlangıç ayarları için örnek yapılandırma |
| `admins.txt` | Yönetici Telegram ID beyaz listesi |
| `sifre_hash_olustur.py` | Yerel PBKDF2 parola özeti üretme aracı |
| `requirements.txt` | Telegram ve Excel bağımlılıkları |
| `BASLAT.bat` | Windows başlatıcısı |
| `hitbet_bot.ps1` | PowerShell başlatıcısı |
| `baslat.sh` | Linux/sunucu başlatıcısı |
| `images/` | İsteğe bağlı yerel kampanya fotoğrafı veya videosu |
| `screenshots/` | Kullanıcıların gönderdiği ekran görüntüleri (adı: kategori + tarih + girilen bilgiler) ve `ekran_goruntuleri.csv` |
| `data/` | Site ID CSV ve Excel çıktıları |
| `hitbet_bot.db` | Asıl çalışma veritabanı |
| `bot.log` | Güvenlik ve çalışma günlüğü; kullanıcı mesaj içerikleri yazılmaz |
| `backups/` | Otomatik veritabanı yedekleri |

## Sunucu Güvenliği Kontrol Listesi

| Kontrol | Önerilen durum |
|---|---|
| Bot için ayrı işletim sistemi kullanıcısı | Zorunluya yakın |
| Bot klasörü izni | Yalnızca bot kullanıcısı okuyup yazabilmeli |
| Disk veya sunucu yedeği şifrelemesi | Etkin |
| `admins.txt` içeriği | Yalnızca gerçekten gerekli Telegram ID’leri |
| Yönetici parolası | Uzun, benzersiz ve başka yerde kullanılmamış |
| `PASSWORD_HASH` | Dolu |
| Düz parola alanı | Kullanılmıyor; destek dışı |
| Bot tokeni | Gizli ve yalnızca çalışma ortamında |
| İşletim sistemi güncellemeleri | Düzenli |
| CSV/XLSX paylaşımı | Yalnızca yetkili kişilerle |

Botun çalıştığı bilgisayar veya sunucu başkaları tarafından kullanılabiliyorsa, işletim sistemi hesabını ve diski ayrıca korumak gerekir. Uygulama içindeki erişim kontrolleri, ele geçirilmiş bir sunucuyu tek başına güvenli hâle getiremez.
