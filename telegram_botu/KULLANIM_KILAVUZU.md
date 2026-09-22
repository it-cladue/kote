# 📖 Telegram Kampanya Botu — Kullanım Kılavuzu

Bu kılavuz iki bölümden oluşur: **Kurulum & Yönetici** (sizin tarafınız) ve
**Kullanıcı Deneyimi** (üyelerinizin gördüğü taraf).

---

## 1. Hızlı Kurulum

### 1.1 Gerekenler
- Python 3.9 veya üzeri (Windows'ta [python.org](https://www.python.org/downloads/) üzerinden kurun, kurulumda **"Add to PATH"** işaretleyin)
- BotFather'dan alınmış bot tokeni

### 1.2 Adımlar
1. Klasörü bilgisayara/sunucuya açın.
2. `config.txt` dosyasını düzenleyin (aşağıdaki tabloya bakın).
3. `admins.txt` içine **yalnızca kendi sayısal Telegram ID'nizi** yazın
   (ID'nizi öğrenmek için bota `/whoami` yazabilirsiniz).
4. **BotFather'da komut listesini tanımlayın** (mesaj kutusundaki ⌘ komut
   simgesinin tüm istemcilerde güvenilir görünmesi için gereklidir):
   BotFather → `/setcommands` → botunuzu seçin → şunu yapıştırın
   (ana menü şablonuyla birebir aynı):
   ```
   start - 🚀 Başla
   menu - 🏠 Ana Menü
   giris - 🏠 Siteye Giriş
   miniapp - 📱 Mini App
   bonuslar - 🎁 Güncel Bonuslar
   yeniuye - 🆕 Yeni Üye Bonusları
   slot - 🎰 Slot Kampanyaları
   spor - ⚽ Spor Bonusları
   banaozel - ⭐ Bana Özel Kampanyalar
   turnuvalar - 🏆 Turnuvalar
   parayatir - 💰 Para Yatır
   paracek - 💸 Para Çek
   duyurular - 📢 Duyurular
   sss - ❓ Sık Sorulan Sorular
   destek - 💬 Canlı Destek
   profil - 🤴 Profil
   ekran - 📸 Ekran Görüntüsü Gönder
   iptal - ❌ İşlemi iptal et
   ```
   Bu komutların her biri çalışır: /bonuslar kategori listesini, /parayatir
   yatırım sayfası butonunu, /miniapp Mini App butonunu getirir. Alt klavye
   ve serbest yazı da aynı yerlere gider ("Para Yatır" yazan kullanıcı
   yatırım ekranını görür).
5. Başlatın:
   - **Windows:** `BASLAT.bat` dosyasına çift tıklayın
   - **Linux/Sunucu:** `chmod +x baslat.sh && ./baslat.sh`

> ⚠️ **GÜVENLİK:** Bot tokeni birileriyle paylaşıldıysa (örn. bu klasör ZIP olarak
> başkasına gönderildiyse) BotFather'da `/revoke` ile tokeni iptal edip yenisini
> alın ve `config.txt`'ye yeni tokeni yazın. Token = botun tam kontrolü demektir.

### 1.3 config.txt ayarları

| Ayar | Ne işe yarar |
|---|---|
| `TOKEN` | BotFather tokeni |
| `PASSWORD_HASH` | Yönetici parola özeti (`python sifre_hash_olustur.py` ile üretilir) |
| `ADMIN_REQUIRE_PASSWORD` | `0` = sadece ID beyaz listesi ile giriş (varsayılan). `1` = `/admin` sonrası **ayrıca parola** sorulur (önerilen) |
| `ADMIN_SESSION_MINUTES` | Yönetici oturumunun süresi (varsayılan 15 dk) |
| `REGISTER_LINK` | "Kayıt Linki" ve "Hemen Üye Ol" butonunun adresi |
| `LOGIN_LINK` | "Güncel Giriş" butonu ve **🎮 PLAY** butonunun adresi (**https:// zorunlu**) |
| `ACTIVATE_LINK` | Kampanya altındaki "Aktif Et" butonunun adresi |
| `CHANNEL_LINK` | Açılışta gösterilen kanal mesajının linki. **Boş bırakılırsa kanal mesajı hiç gönderilmez** |
| `CHANNEL_TEXT` | Kanal mesajının yazısı (varsayılan: `👉 Kanalımıza abone ol`) |
| `WELCOME_TEXT` | Karşılama mesajı; `{name}` kullanıcının adı olur |
| `SITE_ID_PROMPT_TEXT` | Site ID isteme mesajı |
| `REGISTER_LINK_TEXT` | Site ID mesajındaki tıklanabilir yazı (varsayılan: `Kayıt Linki`) |
| `MENU_BUTTON_TEXT` | Sol alttaki web-app butonunun yazısı (varsayılan: `🎮 PLAY`) |
| `PLAY_LINK` | 🎮 PLAY butonuna **özel** adres. Boş bırakılırsa `LOGIN_LINK` kullanılır |
| `SCHED_NOTIFY_MINUTES` | Zamanlı mesajdan kaç dk önce hatırlatma gelsin (varsayılan 5) |
| `SCREENSHOTS_ENABLED` | `1` = fotoğraf gönderene kategori seçenekleri sunulur ve görsel girilen bilgilerle adlandırılıp kaydedilir (varsayılan). `0` = kapalı |
| `SCREENSHOT_CATEGORIES` | Kategoriler ve her birinde sorulacak bilgiler: `anahtar:Buton Yazısı:Alan1\|Alan2, ...` |
| `SCREENSHOT_NAME_FORMAT` | Dosya adı şablonu (varsayılan `{kategori}_{tarih}_{saat}_{alanlar}_{tgid}`) |
| `SCREENSHOT_DAILY_LIMIT` | Kullanıcı başına günlük ekran görüntüsü kotası (varsayılan 10; yöneticiler sınırsız) |
| `SCREENSHOT_PROMPT_TEXT` | Fotoğraf gelince sorulan seçenek mesajı |

Bu metin/link ayarlarının tamamı bot çalışırken **admin panelinden de**
değiştirilebilir; panelden yapılan değişiklik config dosyasından önceliklidir
ve yeniden başlatma gerektirmez.

---

## 2. Kullanıcı Tarafı (üyelerinizin gördüğü)

### 2.1 `/start` — Açılış akışı (varsayılan)
Her kullanıcı `/start` yazınca sırasıyla şunları görür:

1. **Karşılama:** `Merhaba, {ad} 👋!` + altında iki buton:
   **🔥 Hemen Üye Ol** | **🔗 Güncel Giriş** (opsiyonel 💻 Konsol).
   Panelden bir **karşılama görseli** seçtiyseniz karşılama o görselin
   üzerinde (görsel + yazı + butonlar) gelir; seçmediyseniz metin gelir —
   hemen ardından kampanya görseli geldiği için açılış her durumda görsellidir.
2. **`👉 Kanalımıza abone ol`** — tıklanabilir kanal linki (CHANNEL_LINK doluysa)
3. **Günün Kampanyası** — görsel/video + açıklama + **🎁 Aktif Et** butonu.

> **Site ID adımı varsayılan olarak PASİFTİR** — açılışta kimseye Site ID
> sorulmaz. Kullanıcı Site ID'sini **🤴 Profil menüsünden** (`/profil` →
> Site ID Gir/Değiştir) girer; doğrulama ve Evet/Hayır onayı orada aynen çalışır.

### 2.1.1 Site ID'yi açılışta sormak isterseniz
`config.txt` içinde `SITE_ID_ON_START=1` yapın. O zaman **kayıtsız** kullanıcı
`/start` yazınca karşılama + kanal mesajının ardından Site ID istenir:

- Bot doğrular (2–64 karakter; harf, rakam, nokta, alt çizgi, tire) → onay ekranı:
  **Evet, Kaydet** → kayıt + kampanya akışı; **Hayır, Yeniden Gir** → tekrar sorulur;
  **/iptal** → "İşlem iptal edildi"; 10 dk işlemsizlikte zaman aşımı.
- Kayıtlı kullanıcıya hiçbir zaman tekrar sorulmaz.

### 2.1.2 🏠 Ana Menü (v8)
`/start` sonunda ve `/menu` komutuyla açılan hızlı erişim menüsü. Kullanıcıyı
her yere **1-2 dokunuşla** ulaştırır:

| Buton | Ne yapar |
|---|---|
| 🏠 Siteye Giriş | Güncel giriş adresini açar |
| 📱 Mini App | Telegram Mini App'i tek tıkla açar (`MINIAPP_LINK`) |
| 🎁 Güncel Bonuslar / 🆕 Yeni Üye / 🎰 Slot / ⚽ Spor | Kategorideki **aktif** kampanyaları listeler |
| ⭐ Bana Özel Kampanyalar | Kullanıcının **segmentine** (💎 Platin / 🏅 Altın / 🥈 Gümüş / 🥉 Bronz) özel + herkese açık kampanyalar |
| 🏆 Turnuvalar | Ödül havuzu ve katılım şartlarıyla turnuva listesi |
| 💰 Para Yatır / 💸 Para Çek | İlgili sayfalara yönlendirir (`DEPOSIT_LINK` / `WITHDRAW_LINK`) |
| 📢 Duyurular | Panelden paylaşılan duyurular (yeni oyun, bakım, bilgilendirme) |
| ❓ Sık Sorulan Sorular | Panelden yönetilen SSS |
| 💬 Canlı Destek | Destek kanalına yönlendirir |

- **Süresi dolan kampanyalar listeden OTOMATİK kalkar** (dakikada bir denetlenir).
- Kampanya detayında görsel/video, açıklama, buton, bitişe kalan süre; turnuvalarda
  ayrıca ödül havuzu ve katılım şartları gösterilir.

### 2.1.3 🧭 Akıllı destek yönlendirme (v8)
Kullanıcının serbest yazdığı mesaj analiz edilir ve doğru destek kanalına
yönlendirilir (link butonuyla):

| Kullanıcı ne yazarsa | Nereye gider |
|---|---|
| "Param gelmedi", "çekim", "çekemiyorum" | `WITHDRAW_SUPPORT_LINK` (Para Çekim Destek) |
| "Yatıramıyorum", "ödeme", "yatırım" | `DEPOSIT_SUPPORT_LINK` (Ödeme Destek) |
| "Bonus alamadım", "freespin" | `BONUS_SUPPORT_LINK` (Bonus Destek) |
| "Canlı destek", "destek" | `SUPPORT_LINK` |

Kanal linkleri Panel → Linkler'den değiştirilir; boş bırakılan kanal genel
destek linkine düşer. Tanınmayan mesajlar eskisi gibi sessizce yok sayılır.

### 2.2 Kullanıcı menüsü
Mesaj kutusunun **sağındaki komut simgesine (⌘/⋮ görünümlü)** dokununca veya `/`
yazınca komut menüsü açılır. Bot ilk kez başlatıldıktan sonra Telegram bu listeyi
önbelleğe alır; menü hemen görünmezse sohbeti kapatıp açın:

| Komut | İşlev |
|---|---|
| `/start` `/menu` | 🚀 Başlat / 🏠 Ana Menü |
| `/giris` `/miniapp` `/parayatir` `/paracek` | 🏠 Site, 📱 Mini App, 💰/💸 kasa sayfaları |
| `/bonuslar` `/yeniuye` `/slot` `/spor` `/banaozel` `/turnuvalar` | 🎁 Kategori kampanya listeleri |
| `/duyurular` `/sss` `/destek` `/profil` `/iptal` | 📢 Duyuru, ❓ SSS, 💬 destek, 🤴 profil, ❌ iptal |
| `/ekran` | 📸 Ekran görüntüsü gönderme akışı (önce bilgiler, sonra fotoğraf) |

`/whoami` gizli komuttur (menüde görünmez): kullanıcıya kendi Telegram ID'sini gösterir.

### 2.3 🤴 Profil menüsü (`/profil`)
Kullanıcının şunları görmesini sağlar:
- Ad, kullanıcı adı, Telegram ID
- Kayıtlı **Site ID** ve son güncelleme tarihi (kayıt yoksa "Henüz kayıtlı değil")

Altındaki butonlar:
- **🆔 Site ID Gir / Değiştir** → aynı doğrulama ve onay akışıyla Site ID günceller
- **🔗 Güncel Giriş** → giriş linkini açar
- **🎁 Kampanya** → günün kampanya medyasını gösterir

### 2.4 🎮 PLAY butonu
Mesaj yazma alanının solundaki mavi **🎮 PLAY** butonu, botun içinde
(web-app olarak) ayarlı adresi açar.

- Adres önceliği: **Play linki** (Panel → Linkler → 🎮 Play veya `PLAY_LINK`) →
  boşsa **Giriş linki** (`LOGIN_LINK`). Panelden değiştirildiği anda buton da
  güncellenir, yeniden başlatma gerekmez. Play linkini `/temizle` ile boşaltırsanız
  tekrar giriş linkine döner.
- Link **https://** ile başlamak zorundadır (Telegram kuralı). Link geçersizse
  buton kaybolmaz; otomatik olarak komut menüsüne döner ve `bot.log`'a uyarı yazılır.
- Buton yazısı `MENU_BUTTON_TEXT` veya panelden **Play butonu** alanıyla değişir.
- Telegram istemcileri menü butonunu önbelleğe alabilir: değişiklik hemen
  görünmezse sohbeti kapatıp açın veya uygulamayı yeniden başlatın.

### 2.5 📸 Ekran görüntüsü gönderme (v8.7)
Kullanıcı bota bir **ekran görüntüsü** (fotoğraf) attığında bot hemen **seçenek sunar**:

1. **Kategori düğmeleri** çıkar (varsayılan: 👥 Arkadaşını Getir · 💰 Para Yatırma · 💸 Para Çekme · 🎁 Bonus Talebi · 📄 Diğer · ❌ Vazgeç).
2. Seçilen kategoriye tanımlı bilgiler **sırayla sorulur** (örn. Arkadaşını Getir → Site ID, Arkadaş ID). Profilinde kayıtlı Site ID varsa tek dokunuşla **✅ Kayıtlı Site ID'mi kullan** düğmesi gelir.
3. Son bilgi girilince görsel **bu bilgilerle adlandırılarak** `screenshots/` klasörüne kaydedilir ve kullanıcıya dosya adı gösterilir:
   `Arkadasini-Getir_2026-09-22_14-30-05_ABC123_XYZ789_123456789.jpg`
   (kategori + gönderdiği tarih ve saat + yazdığı her bilgi + Telegram ID).

**Diğer yol — önce bilgiler, sonra fotoğraf:** `/ekran` komutu, ana menüdeki **📸 Ekran Görüntüsü Gönder** düğmesi veya alt klavyedeki **📸 Ekran Görüntüsü** tuşu ile kategori seçilir, bilgiler yazılır; bot en son fotoğrafı ister ve **fotoğraf geldiği anda doğrudan kaydeder** (ek onay sorulmaz).

- Bilgi adımındayken fotoğraf gönderilirse akış bozulmaz; fotoğraf alınır ve kalan bilgiler sorulmaya devam eder.
- Görsel **dosya olarak** (PNG/JPG/WEBP) gönderilirse de kabul edilir; uzantı korunur.
- Şikayet akışı (veya yöneticide başka bir sihirbaz) açıkken fotoğraf yeni akış başlatmaz; önce o işlem
  tamamlanmalı ya da `/iptal` yazılmalıdır. Aynı anda seçilip gönderilen albümde ilk fotoğraf alınır.
- Her kayıtta yöneticilere görsel + bilgiler + dosya adıyla bildirim gider.
- Günlük kota: kullanıcı başına `SCREENSHOT_DAILY_LIMIT` (varsayılan 10). `/iptal` her adımda çıkar; 10 dk işlemsizlikte zaman aşımı olur.
- Ayar `SCREENSHOTS_ENABLED=0` yapılırsa (veya panelden pasif edilirse) kullanıcı fotoğrafları eskisi gibi sessizce yok sayılır ve menü düğmesi kaybolur.

### 2.6 Kullanıcı ne YAPAMAZ (güvenlik)
- Site ID ve ekran görüntüsü akışları dışında gönderdiği videolar/dosyalar **yanıtlanmaz**; serbest metinler yerleşik asistana gider.
- `/admin` ve diğer yönetici komutları beyaz listede olmayan herkes için **tamamen sessizdir** — parola ekranı bile gösterilmez.
- Çok hızlı mesaj gönderen (3 sn içinde 5 mesaj) veya aynı komutu üst üste yazan
  kullanıcı **30 dk geçici engel** alır; 3 kez tekrarlayan **kalıcı ban** olur ve
  yöneticilere bildirilir.

---

## 3. Yönetici Tarafı

### 3.1 Giriş
1. Telegram ID'niz `admins.txt` içinde olmalı.
2. Bota `/admin` yazın.
   - `ADMIN_REQUIRE_PASSWORD=0` iken: doğrudan panel açılır.
   - `ADMIN_REQUIRE_PASSWORD=1` iken: önce parola sorulur (3 yanlış = 15 dk engel;
     tüm yöneticilere güvenlik alarmı gider). Parolanız mesajdan otomatik silinir.
3. Oturum `ADMIN_SESSION_MINUTES` (varsayılan 15 dk) işlemsizlikte kapanır. Çıkış: `/logout`.
   Oturum dolduktan sonra panel butonlarına basarsanız bot sizi uyarır.

Yönetici sohbetinde komut menüsü (⌘ simgesi / `/`) genişletilmiştir: `/admin`,
`/botstatus`, `/userlist`, `/banlist`, `/export`, `/backupnow`, `/zamanliiptal`,
`/logout` ve kullanıcı komutları tek dokunuşla erişilebilir. Bu komutlar normal
kullanıcıların menüsünde **görünmez**. Bot ayrıca açılışta profildeki
"What can this bot do?" tanıtımını `BOT_DESCRIPTION` ayarından otomatik günceller.

### 3.2 Panel bölümleri
| Bölüm | İşlev |
|---|---|
| 📊 İstatistik | Toplam/aktif/banlı kullanıcı, giriş gösterimleri |
| 🔗 Linkler | Giriş, Kayıt, Aktif Et, Destek ve **Kanal** linkleri |
| 🎬 Foto / Video | Medya kütüphanesi: yükle, önizle, **Aktif Et**, sil |
| ✏️ Buton & Yazı | Karşılama, kampanya metni, kod, **Kanal mesajı**, **Site ID mesajı**, **Play butonu** yazısı |
| 👥 Kullanıcılar | Arama, bilgi, kategori (segment) atama |
| 🚫 Ban | Banla / ban kaldır / liste |
| 📣 Toplu Mesaj | Sihirbazla tüm kullanıcılara / segmente gönderim |
| 📅 Zamanlı Mesaj | İleri tarihli otomatik gönderim + kayıt yönetimi (aşağıda) |
| 📋 Şablonlar | Kayıtlı toplu mesaj şablonları |
| 📩 Tekil Mesaj | Tek kullanıcıya mesaj |
| 💬 Canlı Destek / 📨 Şikayetler | Destek akışı ve şikayet kayıtları |
| 📸 Ekran Görüntüleri | Ekran görüntüsü kayıtları: aç/kapat, son kayıtlar, kategoriler ve dosya adı şablonu |
| 🛡 Güvenlik | Güvenlik olay günlüğü |
| ⚙️ Ayarlar | Diğer tüm ayarlar |

> Yönetici oturumu açıkken bota gönderdiğiniz **video** otomatik olarak medya
> kütüphanesine eklenir ve aktif kampanya medyası yapılır. **Fotoğraf** gönderince
> ise iki seçenek çıkar: **🗂 Kampanya Medyası Yap** (kütüphaneye ekler, aktif yapar;
> açıklama yazdıysanız kayıt adı olur) veya **📸 Ekran Görüntüsü Olarak Kaydet**
> (bölüm 3.2.0.4). Ekran görüntüsü özelliği kapalıysa fotoğraf eskisi gibi doğrudan
> kütüphaneye gider. Kütüphane sayfa başına 5 kayıt gösterir; kayıt sayısı arttıkça
> sayfa sayısı otomatik artar (`Sayfa 1/3` gibi). Önizleme yaptığınızda menü,
> önizlemenin **altına** yeniden gelir — yukarı kaydırmanız gerekmez.

### 3.2.0 🎯 Kampanya Yönetimi (v8)
Panel → **🎯 Kampanyalar**:

- **➕ Yeni Kampanya**: kategori seç (Bonus / Yeni Üye / Slot / Spor / Bana Özel /
  Turnuva) → başlık → açıklama (vurgu işaretleri çalışır) → foto/video (`/atla`)
  → buton `yazı | https://link` (`/atla`) → *turnuvada:* ödül havuzu + katılım
  şartları → bitiş zamanı `GG.AA.YYYY SS:DD` (`/atla` = süresiz) → yayında!
- **Kayıt detayından**: önizleme, başlık/metin/bitiş/buton (turnuvada ödül/şartlar)
  düzenleme, 🏷 segment hedefi (Bana Özel için), ⏸ pasife alma, 🗑 silme.
- **Otomatik süre yönetimi**: süresi dolan kampanya kullanıcı menüsünden anında
  kalkar ve panelde ⌛ işaretlenir. **Son GÜN** ve **son 2 SAAT** kala hedef
  kitleye otomatik bildirim gider ("bitmek üzere — kaçırma!"), sana da özet düşer.
- **Banner/görsel yönetimi**: kampanyanın kendi görseli sihirbazda yüklenir;
  karşılama ve günün kampanyası görselleri Medya Kütüphanesi'nden yönetilir.

### 3.2.0.1 📢 Duyuru Yönetimi (v8)
Panel → **📢 Duyurular** → ➕ Yeni Duyuru (başlık → metin → görsel `/atla`).
Kaydedilen duyuru kullanıcının Ana Menü → Duyurular bölümünde görünür;
istersen tek dokunuşla **tüm kullanıcılara da gönderirsin**. Yeni oyun, bakım
çalışması, giriş adresi değişikliği duyuruları için idealdir.

### 3.2.0.2 ❓ SSS Yönetimi (v8)
Panel → **❓ SSS Yönetimi** → ➕ Yeni Soru (soru → cevap). Kullanıcı Ana Menü →
SSS'den okur. Silme detay ekranından.

### 3.2.0.4 📸 Ekran Görüntüsü Kayıtları (v8.7)
Panel → **📸 Ekran Görüntüleri**:

- **Durum / Aktif Et / Pasif Yap**: özelliği bot çalışırken açıp kapatırsınız.
- **🏷 Kategoriler**: `anahtar:Buton Yazısı:Alan1|Alan2, anahtar2:...` biçiminde
  hangi seçeneklerin sunulacağını ve her seçenekte **hangi bilgilerin sorulacağını**
  belirlersiniz. Örnek: `arkadas:👥 Arkadaşını Getir:Site ID|Arkadaş ID, bonus:🎁 Bonus:Site ID`.
  Adında **ID** geçen alanlar Site ID kuralına (harf/rakam/nokta/alt çizgi/tire) tabidir.
  `/temizle` ile `config.txt` değerine dönersiniz.
- **📝 Dosya Adı Şablonu**: `{kategori}` `{tarih}` `{saat}` `{alanlar}` `{tgid}` `{kullanici}`
  `{alan1}` `{alan2}`… ve alan adı (`{site_id}`, `{arkadas_id}`, `{tutar}`) yer tutucuları.
  Varsayılan `{kategori}_{tarih}_{saat}_{alanlar}_{tgid}` →
  `Para-Yatirma_2026-09-22_14-30-05_ABC123_500-TL_123456789.jpg`.
  Türkçe karakterler dönüştürülür, boşluk ve izinsiz karakterler `-` olur; aynı ad
  varsa `_2`, `_3` eklenir.
- **💬 Seçenek Mesajı**: fotoğraf gelince kullanıcıya sorulan metin.
- **📸 Son Kayıtlar**: son 10 kayıt (🔴 yeni · 🟡 okundu · 🟢 kapatıldı).

Komutlar: `/ekranlar` (son 30), `/ekranlar yeni`, `/ekranlar arkadas` (kategori), `/ekranlar 12`
(görsel + bilgiler; kayıt okundu olur), `/ekrankapat 12`, `/ekrandosya` (Excel'de açılan CSV).
Dosyalar `screenshots/` klasöründedir; `screenshots/ekran_goruntuleri.csv` her kayıtta güncellenir.

### 3.2.0.3 🔔 Bildirim altyapısı — ne nerede?
| İhtiyaç | Araç |
|---|---|
| "Yeni kampanya başladı", "FreeSpin tanımlandı" | 📣 Toplu Mesaj (segment seçilebilir) veya 📢 Duyuru → Herkese Gönder |
| "Turnuva başladı" | 🎯 Turnuva kampanyası + Toplu Mesaj |
| "Bitmesine son 2 saat / son gün kaldı" | 🎯 Kampanyaya bitiş zamanı ver → **otomatik** gönderilir |
| Belirli saatte planlı bildirim | 📅 Zamanlı Mesaj (5 dk önce sana önizleme gelir) |
| "Giriş adresi değişti", "Mini App güncellendi" | Linki panelden değiştir (anında yansır) + istersen Duyuru gönder |

### 3.2.1 Toplu / Zamanlı mesaj türleri ve biçimlendirme

Sihirbazda 5 mesaj türü vardır:

| Tür | İçerik |
|---|---|
| 📝 Sadece Metin | Başlık + metin |
| 🖼 Foto/Video + Metin | Medya + başlık + metin |
| 🎬 Foto/Video + Metin + Buton | Medya + metin + link butonu |
| 🎫 Metin + Promo Kod + Buton | Metin + kod(lar) + buton |
| 🧩 **Tam Paket** | **Medya + başlık + metin + kod(lar) + butonlar — hepsi bir arada** |

- **Çoklu promo kod:** Kod adımında virgülle veya ayrı satırlarla en fazla 5 kod
  girebilirsiniz (`VIP100, GOLD50`). Hepsi kopyalanabilir/gizli olarak listelenir.
- **İki buton:** 1. butondan sonra "➕ İkinci Buton Ekle" seçeneği çıkar; iki buton
  yan yana görünür. Tam Pakette kod ve buton adımları `/atla` veya "Kodsuz devam"
  ile atlanabilir.
- **Metin vurgusu:** metinde şu işaretleri kullanın:
  `**kalın**` → **kalın**, `__italik__` → *italik*, `++altı çizili++`,
  `~~üstü çizili~~`, `||dokununca görünen gizli yazı||`,
  `[[TIKLA|https://site.com]]` → tıklanabilir yazı.
  > ⚠️ Telegram mesajlarda **yazı rengi ve punto büyüklüğü desteklemez** — bu
  > Telegram'ın kendi sınırıdır. Vurgu için kalın + emoji en etkili yoldur.
- Medyalı mesajlarda açıklama en fazla **1024 karakter** olabilir (Telegram sınırı);
  sihirbaz aşarsanız önizlemede uyarır.

### 3.2.2 Zamanlı mesaj yönetimi

- **Kurma:** Panel → Zamanlı Mesaj → 📅 Yeni Zamanlı Mesaj → tür/içerik/hedef →
  `GG.AA.YYYY SS:DD` biçiminde zaman.
- **Listeleme:** bekleyen her kayıt panelde tıklanabilir satır olarak görünür.
- **Detay ekranı:** kayda dokununca içerik önizlemesi ve şu butonlar gelir:
  **▶️ Şimdi Gönder** · **🕐 Zamanı Değiştir** · **🗑 İptal Et**
- **🔔 Otomatik hatırlatma:** gönderimden **5 dk önce** (ayar: `SCHED_NOTIFY_MINUTES`)
  tüm yöneticilere *"Bu şekilde paylaşılacak"* önizlemesi ve aynı yönetim butonları
  gönderilir — son dakika iptal/erteleme şansınız olur.
- İçeriği (metni/medyayı) değiştirmek isterseniz: kaydı **🗑 İptal Et** ile durdurup
  sihirbazdan yeniden kurun (içerik düzenleme kayıt kurulmadan önce, önizleme
  ekranındaki ✏️ Düzenle ile yapılır).
- Bot gönderim saatinde **kapalıysa**, açıldığında geciken mesajı hemen gönderir.
- Saatler botun çalıştığı bilgisayarın/sunucunun saat dilimindedir.

### 3.3 Açılış ekranını özelleştirme (kullanıcının gördüğü)
| Ne değişecek | Nereden |
|---|---|
| "Merhaba, {ad} 👋!" | Panel → Buton & Yazı → **Karşılama** |
| Açılış karşılama GÖRSELİ | Panel → Foto/Video → Medya Kütüphanesi → kayıt → **🙋 Karşılamada Kullan** (veya **Karşılama medya URL**; kaldırmak için URL alanında `/temizle`) |
| "👉 Kanalımıza abone ol" yazısı | Panel → Buton & Yazı → **Kanal mesajı** |
| Kanal linki | Panel → Linkler → **Kanal** |
| "Yeni bonuslar almak için Site ID'ni gir." | Panel → Buton & Yazı → **Site ID mesajı** |
| "Kayıt Linki"nin adresi | Panel → Linkler → **Kayıt** |
| Kampanya görseli/videosu | Panel → Foto / Video |
| 🎮 PLAY butonunun adresi | Panel → Linkler → **Giriş** |
| 🎮 PLAY butonunun yazısı | Panel → Buton & Yazı → **Play butonu** |

### 3.4 Site ID kayıtları
- Asıl kayıt: `hitbet_bot.db` (SQLite)
- Rapor dosyaları: `data/site_id_kayitlari.csv` ve `data/site_id_kayitlari.xlsx`
  — her onaylı kayıttan sonra ve her açılışta veritabanından yeniden üretilir.
  **Bot çalışırken elle düzenlemeyin.**
- Aynı kullanıcı Site ID'sini değiştirirse yeni satır açılmaz, mevcut kayıt güncellenir.
- Excel'e formül enjeksiyonuna karşı `=`, `+`, `-`, `@` ile başlayan değerler etkisizleştirilir.

### 3.5 Görsel boyutu önerisi
Kampanya görseli için **1920×1080** kullanılabilir; Telegram geniş görselleri
~1280px'e ölçekler. Dosya boyutunu 2 MB altında tutmak açılış hızı için idealdir.
Video için uzantı `.mp4`, `.mov` veya `.m4v` olmalıdır (bot türü uzantıdan tanır).

---

## 3.9 📋 Şablon Uyum Tablosu — istenen her madde nerede?

| İstenen (şartname) | Durum | Nerede |
|---|---|---|
| Adıyla karşılama + ana menü | ✅ | /start: "Merhaba {ad}" → kampanya → 🏠 Ana Menü |
| 13 hızlı erişim butonu | ✅ | Ana Menü (hepsi ayrıca /komut olarak da var) |
| Siteye Giriş → güncel adres | ✅ | Ana Menü / /giris (panelden anında değişir) |
| Mini App tek tıkla | ✅ | Ana Menü 📱 (gerçek web_app butonu) / /miniapp |
| Para Yatır / Para Çek yönlendirme | ✅ | Ana Menü / /parayatir /paracek |
| Canlı Destek yönlendirme | ✅ | 💬 Destek Merkezi: genel + Çekim + Ödeme + Bonus kanalları tek ekranda |
| Kategori bazlı kampanya listesi | ✅ | 6 kategori; panelden ekle/düzenle/kaldır |
| Süresi dolan otomatik kalkar | ✅ | Dakikada bir denetim; panelde ⌛ işaretlenir |
| Turnuva: ödül havuzu + katılım şartları | ✅ | Turnuva kategorisi, sihirbazda sorulur, detayda gösterilir |
| Duyurular (yeni oyun, bakım...) | ✅ | Panel → Duyurular; menüde listelenir + herkese gönderilebilir |
| Segment bazlı "Bana Özel" (Yeni Üye, Aktif, VIP) | ✅ | 🆕 Yeni Üye (ilk 7 gün, OTOMATİK) + 🕓 Aktif (son 48 saat, OTOMATİK) + 💎🏅🥈🥉 manuel kademeler |
| Akıllı yönlendirme (4 örnek) | ✅ | "Param gelmedi"→Çekim, "Yatıramıyorum"→Ödeme, "Bonus alamadım"→Bonus, "Canlı destek"→Destek |
| Push + Reminder, segmente/herkese | ✅ | Toplu Mesaj (segment seçimi), Zamanlı Mesaj (+5 dk önizleme) |
| "Yeni kampanya başladı" | ✅ | Kampanya kaydedilince tek tuş: 📣 Bildirimi Gönder |
| "FreeSpin tanımlandı" | ✅ | Toplu Mesaj / bonus kampanyası + bildirimi |
| "Turnuva başladı" | ✅ | Turnuva kampanyası kaydında 🏆 TURNUVA BAŞLADI bildirimi |
| "Son 2 saat / son gün kaldı" | ✅ | Bitiş zamanlı kampanyada OTOMATİK gönderilir |
| "Güncel giriş adresi değişti" | ✅ | Panelden link değişince tek tuş: 📣 Bildirimi Gönder |
| "Mini App güncellendi" | ✅ | Panelden link değişince tek tuş: 📣 Bildirimi Gönder |
| Panel: kampanya ekle/düzenle/kaldır | ✅ | 🎯 Kampanyalar (+ /kampanyaekle) |
| Panel: duyuru paylaşma | ✅ | 📢 Duyurular (+ /duyuruekle) |
| Panel: turnuva oluşturma | ✅ | Kampanya sihirbazı → 🏆 Turnuvalar |
| Panel: banner yönetimi | ✅ | 🎬 Banner & Medya (kütüphane + karşılama görseli) |
| Panel: Mini App bağlantısı | ✅ | 🔗 Linkler → 📱 Mini App |
| Panel: güncel giriş adresi | ✅ | 🔗 Linkler → 🔗 Giriş (PLAY/menü anında güncellenir) |
| Panel: bildirim gönderme | ✅ | 📣 Toplu Mesaj (+ /bildirim) |
| Ekran görüntüsü → seçenek → girilen bilgilerle adlandırıp kaydet | ✅ | Fotoğraf gönderince kategori seçenekleri; `/ekran` ile önce bilgiler sonra fotoğraf; `screenshots/` |
| Hızlı yanıt, 1-2 tıklama | ✅ | Ana menüden her ekran tek dokunuş |
| Dinamik içerik, kullanıcıda ek işlem yok | ✅ | Tüm metin/link/kampanya panelden; anında yansır |

## 4. Güvenlik Kontrol Listesi

- [ ] Eski token BotFather'da iptal edildi, yeni token `config.txt`'de
- [ ] `admins.txt` içinde yalnızca gerçekten gerekli ID'ler var
- [ ] `ADMIN_REQUIRE_PASSWORD=1` yapıldı ve güçlü parola hash'i üretildi *(önerilir)*
- [ ] Bot klasörüne yalnızca botu çalıştıran işletim sistemi kullanıcısı erişebiliyor
- [ ] `hitbet_bot.db`, CSV/XLSX ve `bot.log` kimseyle paylaşılmıyor
- [ ] `backups/` klasörü düzenli olarak güvenli bir yere kopyalanıyor

## 5. Sık Sorulanlar

**Komut menüsü (⌘ simgesi) görünmüyor / boş?**
1. `config.txt` içindeki `TOKEN` ile Telegram'da konuştuğunuz botun AYNI bot
   olduğundan emin olun — yeni token = yeni bot demektir; eski botun sohbetinde
   menü hiçbir zaman görünmez.
2. Bot açılırken konsolda `✅ Kullanici komut menusu: 4 komut kaydedildi` satırını
   görüyor musunuz? Görmüyorsanız `bot.log` içinde `[CMD]` satırına bakın.
3. `py menu_kontrol.py` çalıştırın — menünün Telegram'daki canlı durumunu gösterir,
   eksikse anında kurar.
4. Telegram menüyü **önbelleğe alır**: sohbeti kapatıp açın; web.telegram.org
   kullanıyorsanız sayfayı Ctrl+F5 ile yenileyin (soldaki "Update Telegram"
   butonu görünüyorsa mutlaka basın — eski web sürümü simgeyi göstermez);
   mobil/masaüstü uygulamayı yeniden başlatın. Mesaj kutusuna `/` yazınca liste
   geliyorsa komutlar kayıtlıdır, simge önbellekten ötürü gecikiyordur.

**PLAY butonu görünmüyor / eski linke gidiyor?**
Giriş linkinin `https://` ile başladığından emin olun (Panel → Linkler → Giriş).
Telegram önbelleği için sohbeti kapatıp açın. `bot.log` içinde `[PLAY MENU]`
satırlarına bakın.

**Kanal mesajı gönderilmiyor?**
`CHANNEL_LINK` boş ya da geçersiz. Panel → Linkler → Kanal'dan `https://t.me/...`
biçiminde girin.

**Kullanıcı yanlış Site ID kaydetti?**
Kullanıcı `/profil` → **Site ID Değiştir** ile kendisi güncelleyebilir; kayıt
üzerine yazılır.

**Bot açılmıyor, "TOKEN/PASSWORD_HASH ayarlayin" diyor?**
`config.txt` içindeki `TOKEN` ve `PASSWORD_HASH` dolu olmalı ve `admins.txt`'te
en az bir sayısal ID bulunmalı. Üçü birden sağlanmadan bot başlamaz.

**Ekran görüntüleri nereye kaydediliyor, adı neden böyle?**
`screenshots/` klasörüne, `kategori_tarih_saat_girilenbilgiler_telegramid.jpg` adıyla.
Şablonu Panel → 📸 Ekran Görüntüleri → Dosya Adı Şablonu'ndan (veya `SCREENSHOT_NAME_FORMAT`)
değiştirebilirsiniz. Kullanıcıya fotoğraf attığında seçenek çıkmıyorsa özellik kapalıdır
(Panel → 📸 Ekran Görüntüleri → Aktif Et) ya da o an başka bir akış (Site ID, şikayet) açıktır.

**Testleri nasıl çalıştırırım?**
```bash
python3 test_bot.py
```
"Tum otomatik testler basarili." çıktısını görmelisiniz.

---

## 10) v8.5 SÜRÜM NOTLARI (derin denetim sonrası)

4 bağımsız denetimle botun tamamı tarandı; ~30 doğrulanmış hata düzeltildi.
Öne çıkanlar:

**Sihirbazlar (asıl şikayetlerin kök nedeni):**
- Duyuru/SSS/kampanya sihirbazlarında yazılan metinler kayboluyordu
  (boş sözlük tuzağı) → SSS'te "Soru #1" görünmesi ve duyurunun ✅ 0 | ❌ N ile
  herkese başarısız gitmesi bundandı. Düzeltildi; açılışta eski boş kayıtlar
  otomatik temizlenir.
- `/sikayet` sihirbazı tanımlıydı ama kayıtlı değildi (tamamen ölüydü) → aktif edildi.
- Sihirbaz kilidi sızıntıları kapatıldı; kilit artık TÜM admin sihirbazlarını
  kapsıyor (ayar/toplu mesaj/tekil mesaj/zamanlı dahil) — metinler yanlış
  sihirbaza gitmez. `/iptal` her durumda kilidi temizler.
- Sihirbaz açıkken gönderilen foto artık kampanya görselini sessizce DEĞİŞTİRMEZ.

**Gönderim güvenliği:**
- Duyuru/şablon/toplu gönderimde çift tıklama artık İKİNCİ kez göndermez.
- Zamanlayıcı ile "Şimdi Gönder/İptal" çakışması atomik kilitle çözüldü
  (aynı mesajın iki kez gitmesi imkansızlaştı).
- Medyalı tüm gönderimlerde 1024 karakter açıklama sınırı emniyetli kısaltılır.
- Başarısız gönderimler nedenleriyle raporlanır (engellemiş / içerik hatası).

**Admin paneli:**
- 13 adet `/set...` komutu TypeError ile ölüydü → düzeltildi.
- "Çıkış Yap" butonu her seferinde hata veriyordu → düzeltildi.
- Uyarı pencereleri (ban kaldırıldı, şablon silindi...) artık kayboluyorsa
  sohbete mesaj olarak düşer.
- `/ban`, tabloda olmayan ID'de artık sessizce başarısız olmaz.
- Oturum süresi sihirbaz ortasında dolarsa gönderim/kayıt YAPILMAZ ve açıkça bildirilir.
- Süresi geçmiş sihirbaz butonları sonsuz yükleme yerine uyarı gösterir.

**Kullanıcı tarafı:**
- Menü butonuna arka arkaya hızlı basan kullanıcı yanlışlıkla banlanmaz
  (eşik 3→5) ve ban mesajı alt menüyü silmez.
- `&` gibi karakterler başlıklarda artık `&amp;` olarak görünmez.
- Tek geçersiz link (kayıt/bonus/destek) artık ekranların tamamını öldürmez;
  geçersiz butonlar atlanır.
- Silinmiş duyuru/SSS butonuna basınca "kaldırıldı" ekranı gelir (ölü buton yok).
- Ana menüden gezinmek de "Aktif Kullanıcı" segmentini canlı tutar.
- Alt klavye etiketleri özelleştirilse de tanınır ("🎁 Kampanyalar" → kampanya).

**Altyapı:**
- Haftalık yedek artık SQLite'ın kendi backup API'siyle alınır (bozuk yedek riski yok).
- Uzun şikayet + foto bildirimi artık admin'e ulaşır (1024 sınırı).
- Testler gerçek veritabanına yazmaz; 44 otomatik test.

---

## 11) v8.6 SÜRÜM NOTLARI (ikinci derin denetim — 6 bağımsız inceleme)

**KRİTİK (v8.5'te eklenen hatanın düzeltmesi):** "Eski buton" yakalayıcısı
yanlış sıraya kaydedilmişti ve **admin panelin tüm butonlarını** öldürüyordu
(her butona "buton eski" uyarısı). Düzeltildi; sıralamayı koruyan otomatik
bekçi testi eklendi. v8.5 kullandıysanız mutlaka v8.6'ya geçin.

**Kullanıcı tarafı:**
- 48 saatten eski mesajlardaki menü butonları (Ana Menü, Kampanya, Site ID)
  Telegram'ın "erişilemez mesaj" kuralı yüzünden sessizce ölüyordu → düzeltildi.
- /profil, geçersiz/boş giriş linkinde tamamen susuyordu → geçersiz buton atlanır.
- config.txt'e `&` veya `<` yazılırsa /start ve /menu tamamen ölüyordu → metinler
  yüklenirken güvenli kaçırılır.
- /start dizisinde tek adımın geçici hatası kalan adımları (menü, alt klavye)
  yutuyordu → her adım bağımsız korunur.
- Kampanya kodunda çifte kaçış: `SPIN&WIN` kodu `SPIN&amp;WIN` olarak
  kopyalanıyordu → düzeltildi. Buton yazılarındaki `&amp;` görünümü de bitti.

**Admin tarafı:**
- PLAY linki geçersizken açılış raporu "✅ PLAY aktif" diye yalan söylüyordu →
  artık "⚠️ komut menüsüne dönüldü" der.
- /removeadmin, eski adminin Telegram'daki admin komut listesini de siler.
- Tekil mesaj hatasında ham hata metni paneli kilitleyebiliyordu → düzeltildi.
- Zamanlı mesaj ön-hatırlatması çökme sonrası her dakika tekrarlanabiliyordu →
  önce işaretle sonra gönder.
- Sihirbaz finalleri (kampanya/duyuru/SSS dahil) süresi dolmuş oturumla işlem yapmaz.

**Güvenlik ve altyapı (denetim sonucu):**
- Yetki yükseltme yolu YOK: parola doğrulama sabit-zamanlı (PBKDF2 600k +
  compare_digest), sahte callback'ler yetki duvarına takılıyor, dosya yolu
  saldırıları ve CSV/Excel enjeksiyonu kapalı — bağımsız denetimle doğrulandı.
- Şikayet görseline 10 MB sınırı + kullanıcı başına günde 3 şikayet kotası.
- Uzun süre çalışan botta yavaş bellek büyümesi önlendi (eski izleme kayıtları
  her dakika tahliye edilir).
- Haftalık yedek ve /backupnow artık botu dondurmaz (ayrı iş parçacığında).
- Dışa aktarma dosya tutamaçları sızdırmaz; kayıt onayı Excel yazarken bot
  kilitlenmez.
- 46 otomatik test; testler gerçek veritabanına yazmaz.

---

## 12) v8.7 SÜRÜM NOTLARI — 📸 Ekran Görüntüsü Kaydı

- **Fotoğraf gönderince seçenek:** kullanıcı ya da yönetici bota ekran görüntüsü attığında bot
  kategori seçenekleri sunar (yöneticide ek olarak 🗂 Kampanya Medyası Yap / 📸 Ekran Görüntüsü Kaydet).
- **Girilen bilgiler dosya adı olur:** seçilen kategori + gönderilen tarih-saat + yazılan her bilgi
  (Site ID, Arkadaş ID, tutar…) + Telegram ID → `screenshots/Arkadasini-Getir_2026-09-22_14-30-05_ABC123_XYZ789_123456789.jpg`.
- **Diğer yol:** `/ekran`, ana menü ve alt klavye 📸 düğmesi ile önce bilgiler girilir, en son fotoğraf
  gönderilir; fotoğraf gelir gelmez doğrudan kaydedilir.
- Kayıtlı Site ID tek dokunuşla kullanılabilir; bilgi adımında gelen fotoğraf akışı bozmaz; PNG/WEBP dosya
  olarak gönderilen görseller de kabul edilir.
- Kayıtlar veritabanında (`screenshots` tablosu) ve `screenshots/ekran_goruntuleri.csv` dosyasında tutulur;
  yöneticilere görselli bildirim gider. Komutlar: `/ekranlar`, `/ekrankapat`, `/ekrandosya`.
- Panel → 📸 Ekran Görüntüleri: aç/kapat, kategoriler ve sorulan bilgiler, dosya adı şablonu, seçenek mesajı,
  son kayıtlar. `config.txt`: `SCREENSHOTS_ENABLED`, `SCREENSHOT_CATEGORIES`, `SCREENSHOT_NAME_FORMAT`,
  `SCREENSHOT_DAILY_LIMIT`, `SCREENSHOT_PROMPT_TEXT`.
- Güvenlik: dosya adı yalnızca güvenli karakterlerden üretilir (`..`, `/`, Windows ayrılmış adları engellenir),
  20 MB üstü indirilmez, kullanıcı başına günlük kota vardır, dosyalar `0600` izniyle yazılır.
- Videolarda ve ekran görüntüsü özelliği kapalıyken yönetici fotoğraflarında eski davranış (doğrudan kütüphane) korunur.
- 39 otomatik test fonksiyonu (5 yeni: dosya adı/kategori ayrıştırma, foto-önce akışı, bilgi-önce akışı,
  yönetici seçenekleri, handler sırası). Çalıştır: `python3 test_bot.py`.
