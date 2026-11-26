# Kanıt Paneli 2.4.0 — kullanıcı gözüyle inceleme turu (26 Kasım 2026)

2.3.8 üzerine `deploy/apply-update.sh` ile uygulanır (KURULUM §13; sunucuda depodan taze kopya + güncelleme). Dört kullanıcı tipiyle (takım lideri, raporlama, yönetici, sahadaki personel) yapılan incelemenin bulguları dört bölümde toplandı. Veritabanına yalnız eklemeli tablolar/sütunlar gelir (bot giden kuyruğu, anahtar başına IP listesi, ayar kayıtları); mevcut kayıtlar değişmez.

## Güncellemeden sonra bir kez yapılacaklar

1. **Sahip hesabı:** Yönetim → Kullanıcılar sayfasında, süperadmin hesabınızı bir kez **sahip** yapın (kullanıcı adını yazarak onaylanır). Bundan sonra API anahtarları, Erişim sınırı ve Çalışma ayarları yalnız sahipte; süperadminler diğer her şeyi yapmaya devam eder.
2. **Yedek betiği:** sunucuda `cd /root/kanit-kurulum/kote/sunucu && bash deploy/setup-backup.sh` komutunu yeniden çalıştırın; gece yedeği yeni adlandırma ve durum işaretiyle çalışsın (yapılmazsa ana sayfadaki "Son yedek" satırı kırmızı kalır).
3. **.env temizliği:** daha önce elle `HATIRLATMA_SAAT=` yazdıysanız silin (2 saat özeti 2.3.8 ile geldi). Diğer ayarlar artık Yönetim → Çalışma ayarları'ndan yeniden başlatmadan değişir.
4. **IP sınırı (isteğe bağlı):** Yönetim → Erişim sınırı sayfasında ofis adreslerinizi ekleyin; sayfa kendi adresinizi gösterir ve sizi dışarıda bırakan listeyi kaydetmez. Cloudflare kuralıyla birlikte kullanılabilir.

## İçindekiler

- Bölüm A — Panel: bildirimler, bekleyen görünümü, onay akışı, dönemler ve çıktılar
- Bölüm C — Telegram botu: personele geri bildirim, ekleyene soru, albüm, /son ve /yardim, mükerrer uyarısı
- Bölüm B1 — Yetki ve güvenlik: sahip rolü, IP erişim sınırı, onaylar, işlem geçmişi
- Bölüm B2 — İşletim: yedekler, sistem durumu kartı, çalışma ayarları

---

## Bölüm A — Panel: bildirimler, bekleyen görünümü, onay akışı, dönemler ve çıktılar


Bu bölüm takım liderlerinin günlük işini (bekleyenleri sırayla onaylamak, bildirimleri izlemek, haftalık/aylık çıktı almak) kolaylaştıran değişiklikleri anlatır. Veritabanı şeması değişmez; `.env` dosyasına bir şey yazmak **gerekmez**, iki yeni ayar isteğe bağlıdır (aşağıda). Değişen dosyalar: `app/panel.py`, `app/hatirlatma.py`, `app/personel_ozeti.py`, `app/settings.py`, `app/api_kilavuz.py` (yalnız dönem listesi), `app/templates/kayitlar.html`, `app/templates/disa_aktar.html`, `app/templates/ana.html` (yalnız "Onay bekleyen" kutusu), `app/static/panel.js`, `app/static/kayit.css`.

### 1. Bildirimler: gürültü azaldı

- Bir kayıt **onaylanınca, onayı kaldırılınca, silinince ya da geri alınınca** o kayda ait "Yeni kanıt" bildirimleri ve kayda özel hatırlatmalar **herkes için okundu** sayılır. Önceden 3 kayıt onaylandıktan sonra zilde 56 "Yeni kanıt" okunmamış kalabiliyordu; artık onaylanan kaydın bildirimi kimsenin zilinde beklemez. Toplu onay da aynı kuralı uygular.
  - Soru, yanıt ve yorum bildirimlerine **dokunulmaz** (sorular yanıtlanana kadar görünür kalır).
  - Gün sonu, bekleyen özeti ve proje özeti gibi bir **listeye** bağlı satırlar da kalır.
- "Kanıt onaylandı" bildirimi artık diğer proje sorumlularına **varsayılan olarak gitmez**. Kimin neyi onayladığı her zamanki gibi **İşlem Geçmişi**'nde ve kaydın "İşlem geçmişi" bölümünde görünür. Eski davranışı isteyen kurulum `.env` dosyasına `BILDIRIM_ONAY=1` yazar.
- **Ses türe göre** ayarlanır (her tarayıcı için ayrı, varsayılan hepsi açık): zil kutusunda "Ses" anahtarının altında üç anahtar vardır:
  - **Yeni kanıt**
  - **Soru / yanıt / yorum**
  - **Hatırlatma ve özetler**

  Onay bildirimleri hiç ses çalmaz. Ana **Ses** anahtarı kapalıysa (eskisi gibi) hiçbir bildirim ses çalmaz; tür anahtarları da soluk görünür.

### 2. Gün sonu özeti (18:00) artık takım liderlerine de gider

- Varsayılan alıcılar: **süperadminler + en az bir projede onay yetkisi olan her aktif kullanıcı**.
- Takım lideri yalnız **onaylayabildiği projelerin** sayılarını görür ("Gün sonu 26.11.2026: 3 kayıt onaylanmadı (OF 3) …"); süperadmin tüm projeleri görür.
- Kişi başına günde **bir** satır (değişmedi).
- `GUN_SONU_ALICILAR` doluysa eskisi gibi **yalnız o adlara** gider (bu adlar görebildikleri projelerin özetini alır). Yalnız yöneticilere göndermek isteyen kurulum bu ayara yönetici adlarını yazar.

### 3. "Onay bekleyen" görünümü

- **Sayılar:** Ana sayfadaki "Onay bekleyen kayıt" kutusu ve Kayıtlar'daki **Onay bekleyen** sekmesi yalnız sizin **onaylayabildiğiniz** projeleri sayar (süperadmin: hepsi). Yalnız görüntüleyebildiğiniz projelerde de bekleyen varsa yanında küçük bir not çıkar: **"+10 görüntüleyebildiğiniz projelerde"** (ana sayıya katılmaz; Kayıtlar'daki not o projelerin listesini açar). Proje çipinden o projeyi seçerseniz bekleyenleri yine listelenir. Hiçbir projede onay yetkisi olmayan kullanıcıda sayılar eskisi gibidir. Bu daraltma Kayıtlar'daki **Excel (bu görünüm)** düğmesine de uygulanır (dosya sekmeyle aynı kayıtları verir; "Bilgi" sayfası dışarıda kalan projeleri yazar). **Çıktı** sayfası değişmedi: orada "Onaysızlar (onay bekleyen)" seçildiğinde görüntüleyebildiğiniz tüm projelerin bekleyenleri dosyaya girer.
- **Sıra:** Onay bekleyen sekmesi artık **en eski önce** (en uzun bekleyen en üstte) açılır. Sağ üstteki **Sıra** seçimiyle "En yeni önce"ye geçebilirsiniz; seçim adreste (`sirala=eski|yeni`) durur, sayfalar arasında korunur. Diğer sekmeler eskisi gibi en yeni önce açılır. Hatırlatma, bekleyen özeti ve gün sonu bildirimlerinin bağlantıları da bu sırayla açılır.
- **Bekleme rozeti:** Onay bekleyen her satırda/kartta ve ayrıntı penceresinin başlığında kaydın ne zamandır beklediği yazar: **"45 dk"**, **"5 sa"**, **"3 gün"**. Süre, hatırlatmalarla aynı başlangıçtan (ilk görülme, yoksa eklenme tarihi) sayılır.
  - **Turuncu:** `BEKLEME_UYARI_SAAT` saatten (varsayılan **2**) uzun bekleyen.
  - **Kırmızı:** `HATIRLATMA_GUN` günden (varsayılan **3**) uzun bekleyen.

### 4. Onaylama akışı: "Onayla ve sonraki"

- Ayrıntı penceresinde birincil düğme **Onayla ve sonraki**: kaydı onaylar ve bu sayfadaki **sıradaki bekleyen** kaydı açar. Alt tarafta 5 saniye boyunca **"Geri al"** düğmeli bir ileti çıkar; basarsanız onay kaldırılır (İşlem Geçmişi'ne "Onay kaldırma" olarak yazılır) ve kayıt yeniden açılır. Sayfadaki bekleyenler bitince "Bu sayfadaki bekleyenler bitti" yazar.
- Yanındaki **Onayla** düğmesi eskisi gibi onaylar ve aynı kayıtta kalır.
- **Klavye kısayolları** (pencere açıkken; bir yazı alanında yazarken çalışmaz): **O** onayla ve sonraki · **U** son onayı geri al ("Geri al" yazısı görünürken, 5 sn) · **S** soru sor (soru kutusuna geçer) · **D** düzenle · **Delete** sil (her zamanki silme sorusu çıkar) · **← →** önceki/sonraki · **?** kısayol yardımını aç/kapat · **Esc** kapat. Kısayollar pencerenin üst satırında da yazar. Sıradaki kayıt yüklenirken (bağlantı yavaşsa "Yükleniyor" yazar) düğmeler ve kısayollar kısa süre çalışmaz; böylece yanlışlıkla önceki kayıt onaylanmaz.
- **Hızlı önizleme:** Tablo görünümünde küçük resmin üzerine gelince (ya da Tab ile üzerine gelince) büyük önizleme çıkar; **Esc** kapatır. Telefonda bu özellik yoktur.

### 5. Dönemler ve Excel çıktısı

- Kayıtlar'ın **Gelişmiş filtreler** bölümünde ve **Çıktı** sayfasında hızlı tarih düğmeleri: **Bugün / Bu hafta / Geçen hafta / Bu ay / Geçen ay**. Hafta pazartesi başlar; tarihler İstanbul takvimine göredir. Kayıtlar'da düğmeye basınca liste hemen süzülür; Çıktı sayfasında tarih kutuları dolar.
- Personel raporunun **Dönem** seçeneklerine **Geçen hafta** ve **Geçen ay** eklendi (adres: `donem=gecen_hafta` / `donem=gecen_ay`). "Durumlar" karşılaştırması geçen hafta için bir önceki haftayı, geçen ay için bir önceki takvim ayını kullanır.
- **Tarih ölçütü:** Kayıtlar'da ve Çıktı sayfasında tarih aralığı artık **Eklenme** (varsayılan, eskisi gibi) ya da **Onay zamanı**na göre uygulanabilir (`tarih_alani=onay`). Onay zamanına göre süzüldüğünde yalnız onaylı kayıtlar gelir. Excel çıktısı da bu seçime uyar.
- **Excel dosyası (Kayıtlar ve Çıktı):**
  - Dosya adı seçimden oluşur, ör. `kanit-kayitlari-OF-onayli-2026-11-17_2026-11-23.xlsx` (proje seçilmediyse proje yazılmaz; onay zamanına göre süzüldüyse tarihin önünde `onay-`; onay yetkiniz olmayan projelerden onaysız satır varsa sonda eskisi gibi `-ONAYSIZ-N`).
  - İlk sayfa **"Bilgi"**: uygulanan süzgeçler (proje, durum, tarih ölçütü ve aralığı, kategori, arama…), dosyayı oluşturan kişi, oluşturma zamanı ve kayıt sayısı. Dosya **"Kayıtlar"** sayfasında açılır.
  - **Tarih**, **Onay zamanı** ve **Silme zamanı** sütunları artık gerçek Excel tarihidir (sıralanır, süzülür; saatsiz eski kayıtlarda yalnız tarih). Okunamayan eski tarih metinleri olduğu gibi kalır.
  - Personel raporunun CSV çıktısı değişmedi.

### 6. Küçük arayüz düzeltmeleri

- **Telefonda (≤ 900 px)** Kayıtlar'ın süzgeç paneli varsayılan **kapalı** gelir; üstteki **"Süzgeçler (N etkin)"** düğmesiyle açılır. Açık/kapalı tercihi o tarayıcıda hatırlanır. İlk kayıt artık sayfanın en üstüne yakın görünür.
- Telefonda durum sekmeleri (Onay bekleyen / Onaylı / Silinen / Hepsi) **tek satırda** kalır, sığmazsa yana kaydırılır.
- Sunucuda Gyazo anahtarı (`GYAZO_TOKEN`) tanımlı değilse **"Gyazo'ya dönüştür" düğmesi hiç gösterilmez** (önceden soluk düğme ve açıklama çıkıyordu). Sayfaya yalnız "anahtar var/yok" bilgisi gider, anahtarın kendisi asla gitmez.

### Yeni ayarlar (isteğe bağlı, `.env`)

| Ayar | Varsayılan | Ne işe yarar |
|---|---|---|
| `BILDIRIM_ONAY` | `0` | `1` yapılırsa onay / onay kaldırma diğer proje sorumlularına zil bildirimi olarak da gider. İşlem Geçmişi her durumda yazılır. |
| `BEKLEME_UYARI_SAAT` | `2` | "Bekleme" rozetinin turuncuya döndüğü süre (saat). Kırmızı eşik mevcut `HATIRLATMA_GUN` ayarıdır (varsayılan 3 gün). |

### Kapatmak / eski davranışa dönmek isterseniz

- Onay bildirimleri geri gelsin: `BILDIRIM_ONAY=1`, ardından `systemctl restart kanit-web`.
- Gün sonu özeti yalnız yöneticilere gitsin: `GUN_SONU_ALICILAR=yonetici1,yonetici2` (virgülle kullanıcı adları). Özeti tamamen kapatmak için `GUN_SONU_SAAT=0` (değişmedi).
- Ses: zil kutusundaki tür anahtarları ya da ana **Ses** anahtarı (her kullanıcı kendi tarayıcısında).
- Turuncu eşiği değiştirmek: ör. `BEKLEME_UYARI_SAAT=4` (saat), ardından `systemctl restart kanit-web`.
- Liste sırası: Kayıtlar'daki **Sıra** seçimi (adres `sirala=yeni`).

Testler: `tests/test_v240_panel.py` ve tarayıcı senaryosu `tests/v240_panel_tarayici.js` (Node + Playwright yoksa tarayıcı testi atlanır).

---

## Bölüm C — Telegram botu: personele geri bildirim, ekleyene soru, albüm, /son ve /yardim, mükerrer uyarısı


Önceki sürüm üzerine `deploy/apply-update.sh` ile uygulanır. Veritabanına yalnız **yeni tablolar** eklenir
(`bot_giden`, `tg_tercihler`; ilk kullanımda kendiliğinden oluşur, mevcut tablolara dokunulmaz). `.env`
dosyasına bir şey yazmak gerekmez; varsayılanlar aşağıda.

Değişen dosyalar: `app/bot.py`, `app/bot_bildirim.py` (yeni), `app/discussion.py`, `app/panel.py` (yalnız kısa kancalar:
onay, silme, kayıt ayrıntısı, kanıt ekleme ve `tg_duzeltme` denetim adı), `app/static/panel.js` (soru alıcısı
seçeneği ve mükerrer onayı), `app/templates/_kanit_ekle.html` (bir gizli alan), `tests/test_v240_bot.py` (yeni);
mevcut testlerde küçük uyarlamalar (`BOT_GYAZO_SOR=1`, `yine_de=1`, tarayıcı senaryosunda onay penceresi kabulü).

### Sahadaki personel ne görür?

#### Onay ve silme haberi artık Telegram'a gelir
"✅ Kanıtınız panele işlendi" mesajından sonra kişi kaydının ne olduğunu öğrenemiyordu. Şimdi:

- Kayıt **onaylanınca**: `✅ 5 kanıtın onaylandı: #1203, #1204, #1205, #1206, #1207 (OF)`
  - Toplu onayda ve art arda yapılan tek tek onaylarda kişi başına **tek mesaj** gider (en çok 10 numara
    yazılır, fazlası `…` ile kısalır). Onaydan sonra ~20 saniye beklenir; bu sürede gelen onaylar aynı mesaja
    eklenir.
- Kayıt **silinince**: `❌ #1203 kaydın silindi. Neden: Yanlış üye ID` (panelde neden yazılmadıysa yalnız ilk
  cümle).
- **Onay kaldırılınca** mesaj gitmez (henüz gönderilmemiş onay mesajından o kayıt çıkarılır).
- Yalnız **Telegram botuyla eklenen** kayıtlar için gider. Panelden eklenen ve eski Excel aktarımından gelen
  kayıtlar için gitmez. **30 günden eski** kayıtlar için gitmez (toplu temizlikte kimse mesaj yağmuruna tutulmaz).

#### Takım lideri soruyu doğrudan ekleyene sorar (WhatsApp'a gerek yok)
- Paneldeki kayıt penceresinde "Soru yönelt" listesinde **"Ekleyene sor (Telegram)"** seçeneği vardır (kayıt
  Telegram botuyla eklendiyse görünür).
- Ekleyen Telegram'da şunu görür:
  `❓ #1203 için takım liderinin sorusu (OF / HGST · 445566): Üye ID doğru mu? — Yanıtlamak için bu mesaja yanıt
  verin (Reply) ya da /yanit 1203 metniniz yazın.`
- Kişi mesaja **Reply** ile ya da `/yanit 1203 metin` komutuyla yanıt verir. Yanıt kayda **"Telegram: <ad>"**
  yazarıyla yanıt olarak eklenir, soran lidere zilde **yanıt** bildirimi düşer, kişiye "✅ Yanıtınız #1203
  kaydına eklendi" onayı gider.
- Aynı kayıtta birden çok açık soru olabilir: Reply hangi soru mesajına yapıldıysa o soruya bağlanır; `/yanit`
  o kayıttaki **en son** soruya bağlanır. Lider, Telegram yanıtına panelden "Yanıtla" derse yanıtı yine
  Telegram'a gider.

#### Daha az dokunuş
- **Saklama sorusu kalktı.** Görsel varsayılan olarak sunucuda saklanır; fotoğraftan sonra doğrudan proje
  seçimi gelir. Gyazo bağlantısı isteyen kişi **/gyazo** yazarak kendisi için açar/kapatır (sunucuda
  `GYAZO_TOKEN` yoksa açılmaz). Eski "her görselde sor" davranışı için `BOT_GYAZO_SOR=1`.
- **⚡ Son kullanılan: OF / HGST** düğmesi: daha önce kayıt girmiş kişide proje listesinin en üstünde durur;
  tek dokunuşla proje + kategori seçilir.
- **Kayıt numarası hemen** gelir: Onayla'ya basınca her durumda `Kayıt: N` yazılır. Gyazo açıksa mesajda
  "Gyazo bağlantısı arka planda ekleniyor" yazar, sonuç ("Gyazo bağlantısı kayda eklendi" ya da "eklenemedi;
  yerel görsel korunuyor") ayrıca kısa bir mesajla gelir. Artık numara geç geldiği için görsel yeniden
  gönderilmez.
- **/son** (eşi **/kayitlarim**): son 10 kaydı durumuyla listeler — ⏳ bekliyor / ✅ onaylı / ❌ silindi. Onay
  bekleyen kayıtlar için **"Düzelt #1203"** düğmesi çıkar: yazılı bilgiler (personel, üye ID, ana üye ID, tür,
  Lead ID ya da kategori soruları) sırayla yeniden sorulur, her adımda şu anki değer görünür ve **"= Aynı
  kalsın"** düğmesiyle geçilebilir; sonunda değişen alanlar gösterilir ve **Kaydet** ile yazılır. Denetimde
  `tg_duzeltme` olarak görünür. Onaylanmış ya da silinmiş kayıt düzeltilemez.
- **/yardim**: kısa Türkçe rehber.
- Telegram'ın **komut menüsü** (sohbetteki "/" düğmesi) bot her açıldığında yazılır: /start, /son, /yanit,
  /gyazo, /iptal, /yardim.

#### Albüm ve yarım kalan işlem
- İki fotoğraf **albüm** olarak gönderilince ilki artık kaybolmaz: ikisi **tek kanıt** olur (ikinci görsel
  kaydın 2. görseli olarak saklanır). Üçüncü ve sonrası alınmaz: "En çok 2 görsel; fazlası alınmadı."
- Bir düğme beklenirken (proje/kategori seçimi, SON KONTROL vb.) yazı yazılırsa yarım kanıt **silinmez**. Bot
  şunu sorar: **"Yarım kalan kanıt işlemi var. [Devam et] [İptal et ve yeni başla]"**. Yeni Lead ID akışı ancak
  "İptal et ve yeni başla" seçilince başlar (yazılan metin Lead ID olarak alınır).

#### Mükerrer uyarısı
- Botta SON KONTROL'den önce, son 30 günde silinmemiş bir kayıtta **aynı proje + kategori + üye ID** ya da
  **aynı görsel** varsa: `⚠️ Bu üye ID 12.11'de #1180 olarak kaydedilmiş. Yine de kaydet? [Evet, kaydet]
  [Vazgeç]`. Vazgeç düzeltme menüsüne döner.
- Panelden kanıt eklerken aynı bağlantı (Gyazo/Snappark/Teamzone) ya da aynı proje + kategori + üye ID son 30
  günde varsa form bir kez uyarır (kayıt açılmaz); onaylanırsa ikinci gönderim kaydeder.

### Ayarlar (.env, hepsi isteğe bağlı)

| Ayar | Varsayılan | Anlamı |
|---|---|---|
| `BOT_ONAY_BILDIRIMI` | 1 | Onaylanan kaydın ekleyenine Telegram mesajı (0 = kapalı) |
| `BOT_SILME_BILDIRIMI` | 1 | Silinen kaydın ekleyenine Telegram mesajı (0 = kapalı) |
| `BOT_SORU_BILDIRIMI` | 1 | "Ekleyene sor (Telegram)" seçeneği (0 = seçenek gizlenir) |
| `BOT_GYAZO_SOR` | 0 | 1 = eski davranış: her görselde saklama yöntemi sorulur |
| `BOT_ONAY_TOPLAMA_SN` | 20 | Onay mesajı gönderilmeden önce aynı kişinin onaylarının toplanacağı süre (0-600 sn) |
| `BOT_BILDIRIM_MAX_DENEME` | 5 | Panel bildirimi teslim edilemezse en çok deneme (1-20) |

Ayarlar değişince **bot** ve **panel** servisi yeniden başlatılmalıdır (panel onay/silme anında, bot gönderim
anında okur).

### İşletme notları
- Web süreci Telegram'a bağlanmaz: mesajlar `bot_giden` tablosuna yazılır, bot her poll turunda (en geç ~25-45
  saniye) gönderir. Bot kapalıysa mesajlar bekler, açılınca gider.
- Geçici hatada 30 sn, 2 dk, 10 dk, 30 dk, 1 saat arayla yeniden denenir; kalıcı hatada (kişi botu engelledi,
  sohbet yok) hemen vazgeçilir. Vazgeçilen her mesaj bot günlüğüne (`bot_log.txt`) "Panel bildirimi … teslim
  edilemedi; vazgeçildi" satırıyla yazılır.
- Onay/silme bildirimi yazılamazsa (ör. beklenmeyen veritabanı hatası) onay/silme işlemi yine tamamlanır;
  yalnız bildirim atlanır. "Ekleyene sor" sorusu ise kuyruğa yazılamazsa hiç kaydedilmez (panel hata gösterir).
- Telegram'da ekleyene iletilemeyen soru (bot engellenmiş, sohbet kapalı ya da deneme sınırı doldu) için soran
  takım liderine panelde "sorunuz Telegram'da ekleyene iletilemedi" bildirimi düşer; yanıt beklemez.

### İnceleme düzeltmeleri
- Panelin mükerrer uyarısı aynı bağlantıyı/görseli yalnız **aynı projede** arar; kullanıcının okuma yetkisi
  olmayan bir projedeki kaydın numarası ve tarihi artık uyarıda görünmez.
- `BOT_SORU_BILDIRIMI=0` yapıldığında (ya da kaydın Telegram ekleyeni yoksa) eski Telegram konuşmasına panelden
  "Yanıtla" artık hata vermez; yanıt panelde normal yanıt olarak kalır.
- Çok uzun ve özel karakterli (`<`, `&`) sorular Telegram'a giderken kaçıştan önce kısaltılır (sonuna "…"),
  "/yanit" satırı her zaman bütün kalır; mesaj Telegram tarafından reddedilmez.
- Türkçe klavyeyle yazılan `/yanıt`, `/yardım`, `/kayıtlarım` da tanınır.

---

## Bölüm B1 — Yetki ve güvenlik: sahip rolü, IP erişim sınırı, onaylar, işlem geçmişi


Bu belge 2.4.0'ın "roller ve güvenlik" parçasını anlatır. Sürüm numarası ve README/KURULUM birleştirmesi ayrıca yapılır.

### Kısaca ne değişti?

| Konu | Önce | Şimdi |
|---|---|---|
| En üst rol | Süperadmin | **Sahip** (süperadminin üstü). Süperadminler aynen çalışmaya devam eder |
| API anahtarları sayfası | Her süperadmin | **Yalnız sahip** (menüde de yalnız sahibe görünür) |
| Süperadmin hesaplarını açma / düzenleme / pasife alma / şifre sıfırlama, rol yükseltme-düşürme | Her süperadmin | **Yalnız sahip** |
| IP ile erişim sınırı | Yok (yalnız Cloudflare kuralı mümkündü, IP:18443 yolu açıktı) | **Yönetim → Erişim sınırı**: panel ve API için izin listesi, iki yolda da çalışır |
| Tehlikeli işlemler | Tek tıkla (bazılarında tarayıcı "Emin misiniz?") | Kullanıcı adını / anahtar adını **yazarak onay** (sunucu da doğrular) |
| Başlıktaki rol yazısı | Herkese "SÜPERADMIN" ya da "ADMIN" | Gerçek yetkiden: **Sahip / Süperadmin / Takım lideri / Düzenleyici / Görüntüleyici** |
| İşlem Geçmişi | Kullanıcı/işlem/anahtar araması, ham JSON ayrıntı | Kayıt no, personel, açıklama, IP ile arama; **IP sütunu**; okunur ayrıntı (+ "Ham"); **CSV indir**; Bugün / Son 7 gün / Son 30 gün / Bu ay düğmeleri |

### 1. Sahip rolü

* Sahip her şeyi yapar: süperadminin yaptığı her şey + süperadmin/sahip hesaplarını yönetme + API anahtarları + erişim sınırı.
* Süperadmin: tüm projeler, kullanıcılar (proje kullanıcıları), katalog, bot, arşiv, raporlar, çıktı, kategori temizliği — eskisi gibi.
* Mevcut hesaplar değişmez: süperadminler süperadmin kalır, veri taşıma yoktur.

#### İlk kurulum: sahibi belirleme (bir kez)

Güncellemeden sonra hiç sahip yoktur. Bir süperadmin **Yönetim → Kullanıcılar** sayfasının üstündeki **"Sahip hesabını belirleyin"** kartından:

1. "Sahip olacak hesap" listesinden kendini (ya da başka bir hesabı) seçer.
2. Onay kutusuna o kullanıcı adını yazar → **Sahip yap**.

Bu yalnız etkin sahip yokken çalışır ve İşlem Geçmişi'ne **Sahip ataması** olarak yazılır. Kendini seçen oturumda kalır; başkasını seçerseniz onun açık oturumları kapanır. Sonrasında yeni sahip/süperadmin atamasını yalnız sahip yapar (hesabın **Düzenle** formunda "Sahip" seçip kullanıcı adını yazarak).

Sunucudan (SSH) da yapılabilir:

```
cd /opt/kanit-paneli
runuser -u kanit -- .venv/bin/python -m app.cli kullanici-rol admin sahip
```

`kullanici-rol <ad> sahip | admin | 'OF:oku,kt;PA:oku'` rolü değiştirir; `admin-ekle <ad> --sahip --password-env KANIT_PW` sahip hesabı açar. Son etkin sahip kapatılamaz ve rolü düşürülemez (önce başka bir hesabı sahip yapın).

#### Yazılı onay isteyen işlemler

| İşlem | Ne yazılır |
|---|---|
| Rol sınıfı değişikliği (proje kullanıcısı ↔ süperadmin ↔ sahip), yeni süperadmin/sahip hesabı açma | Hedef kullanıcı adı |
| Süperadmin/sahip hesabını pasife alma | Hedef kullanıcı adı |
| İlk sahip ataması | Seçilen kullanıcı adı |
| API anahtarını iptal etme | Anahtarın adı |
| Erişim listesini temizleme / dolu listeyi boşaltma | Kendi kullanıcı adınız |

Onay alanı Kullanıcılar formunda yalnız gerektiğinde açılır ve nedeni yazar ("Rol değişikliği: Proje kullanıcısı → Süperadmin"). Onay sunucuda tekrar denetlenir; büyük/küçük harf ve baştaki/sondaki boşluk önemsizdir. Hepsi İşlem Geçmişi'ne eski/yeni değerlerle yazılır.

### 2. Erişim sınırı (IP izin listesi) — işletmen kılavuzu

#### Hangi yolu seçmeliyim?

Panele iki yoldan girilebiliyor: **alan adı** (Cloudflare üzerinden) ve **sunucunun IP adresi** (`https://217.156.123.36:18443`).

| Seçenek | Alan adı yolu | IP:18443 yolu | API | Not |
|---|---|---|---|---|
| (a) Yalnız Cloudflare WAF kuralı | Korunur | **Açık kalır** (kanit-ip-proxy kapatılana kadar) | Alan adından gelen API korunur | Cloudflare paneli: Security → WAF → Custom rules → "IP Source Address is not in {ofis IP}" → Block |
| (b) Panelin kendi listesi (bu sürüm) | Korunur | Korunur | Ayrı liste + anahtar başına liste | Giriş sayfası dahil her sayfa; sunucuda tek yerden |
| (c) İkisi birden | Korunur (Cloudflare'da daha erken kesilir) | Korunur | Korunur | En sıkı |

**Öneri: (b), istenirse (c).** Yalnız Cloudflare'da (a) kalırsanız IP:18443 yolu açık kalır; o yolu kapatmak için kurulum belgesindeki son adım (`systemctl disable --now kanit-ip-proxy`) gerekir.

#### Panelden ayarlama (sahip)

1. **Yönetim → Erişim sınırı** sayfasını açın. "Şu anki adresiniz" kutusunda internete çıktığınız adres yazar.
2. **Panel listesine ekle** düğmesi bu adresi kutuya yazar. Gerekirse diğer adresleri ekleyin (satır başına bir tane).
3. **Kaydet**. Değişiklik hemen geçerli olur.

Yazım örnekleri: tek adres `85.105.12.34` · blok `85.105.12.0/24` (85.105.12.0–255) · geniş blok `85.0.0.0/8` · IPv6 `2a02:4780:1::/48` · açıklama `85.105.12.34  # ofis`. Boş liste = sınır yok.

* **API listesi** (sayfadaki ikinci kutu) bütün API anahtarlarına uygulanır; ayrıca **API anahtarları** sayfasında her anahtara ayrı IP listesi verilebilir (oluştururken ya da sonra "Yönet" → "IP listesini kaydet"). İkisi de doluysa istek ikisine de uymalıdır. İzinsiz adres `403` ve `"neden": "ip_izinsiz"` alır.
* Panel listesi API'yi, API listesi paneli etkilemez.

#### Ofisin dış (public) IP adresini bulmak

* Ofisteki bir bilgisayardan paneli açın: **Erişim sınırı** sayfasındaki "Şu anki adresiniz" doğrudan budur (en güvenilir yol).
* Ya da Cloudflare paneli → alan adı → Analytics/Security Events'te kendi isteğinizin "Source IP" değeri.
* **Dikkat:** ev/ofis internet hatlarının çoğunda adres sabit değildir; modem yeniden başlayınca ya da sağlayıcı değiştirince değişir. Değişirse panel sizi engeller. Kalıcı çözüm: sağlayıcıdan **sabit IP** istemek. Geçici çözüm: sağlayıcınızın bloğunu yazmak (ör. `/24`); blok genişledikçe koruma zayıflar. Mobil veriden girecek kişiler için liste uygun değildir (adresleri sürekli değişir).

#### Kendinizi dışarıda bırakmamak için

* Şu anki adresinizi içermeyen bir panel listesi, **"Kendi adresimi dışarıda bırakmayı anlıyorum"** işaretlenmeden kaydedilmez.
* Dolu bir listeyi tamamen boşaltmak (sınırı kaldırmak) kendi kullanıcı adınızı yazmayı ister.
* Sunucunun kendisinden doğrudan gelen istekler (127.0.0.1, ör. sağlık denetimi) sınırdan muaftır (`ERISIM_LOOPBACK_SERBEST=1`, varsayılan). `0` yapılırsa yalnız `/saglik` muaf kalır.
* `/saglik` (yalnız "OK" döndürür), sunucu kendini kendi nginx'i üzerinden (IP:18443 yolu, `X-Forwarded-For: 127.0.0.1`) denetlediğinde de muaftır; `setup-ip-https.sh` sağlık denetimi liste doluyken de çalışır.
* **Kurulum betiğini yeniden çalıştırmadan önce:** `setup-cloudflare-https.sh` 2/3 adımında alan adını sunucunun **kendi dış IP'si** üzerinden dener; panel listesi doluysa bu istek 403 alır ve betik hata verir. Betiği çalıştırmadan önce sunucunun dış IP'sini (ör. `217.156.123.36`) listeye ekleyin ya da listeyi geçici olarak boşaltın (`erisim-izin --temizle`, iş bitince yeniden doldurun). `apply-update.sh` etkilenmez (doğrudan `127.0.0.1:18080` kullanır).
* **Veritabanı okunamazsa:** liste ayarı okunamadığında (ör. anlık veritabanı kilidi) panel kapanmasın diye o istek **sınırsız geçer** ve durum `journalctl -u kanit-web` günlüğüne "Erişim sınırı okunamadı" diye yazılır. Kesin koruma isteniyorsa Cloudflare kuralını da kullanın (seçenek c).
* Engellenen kişi şu sayfayı görür: "Bu adresten erişim izinli değil (IP: …)". Bu IP'yi size iletmesi yeterlidir.

**Acil durum (SSH):**

```
cd /opt/kanit-paneli
runuser -u kanit -- .venv/bin/python -m app.cli erisim-izin --goster              # listeleri göster
runuser -u kanit -- .venv/bin/python -m app.cli erisim-izin --ekle 85.105.12.34   # panel listesine ekle (--tur api ile API'ye)
runuser -u kanit -- .venv/bin/python -m app.cli erisim-izin --temizle             # iki listeyi de boşalt (--tur panel|api)
```

Komutlar İşlem Geçmişi'ne `sunucu-cli` adıyla yazılır; yeniden başlatma gerekmez.

#### TRUST_PROXY=1 şart

Panel ziyaretçi adresini nginx'in ilettiği `X-Forwarded-For` başlığından öğrenir; waitress bu başlığa yalnız `TRUST_PROXY=1` iken ve yalnız `GUVENILEN_PROXY` (127.0.0.1) adresinden gelen bağlantıda güvenir. Alan adı yolunda nginx gerçek adresi Cloudflare'ın `CF-Connecting-IP` başlığından (yalnız Cloudflare aralıklarından gelirse) alır; IP:18443 yolunda doğrudan bağlantı adresidir. İki nginx de `X-Forwarded-For $remote_addr` ile başlığı ezer, bu yüzden dışarıdan sahte başlık gönderilemez.

`TRUST_PROXY=0` iken her ziyaretçi 127.0.0.1 görünür. Bu durumda waitress `X-Forwarded-For` başlığını silmez ama uygulamaz (`clear_untrusted_proxy_headers=False`); panel böylece durumu fark eder (döngü adresi + `X-Forwarded-For`): bu durumda muafiyet uygulanmaz (liste doluysa herkes engellenir — güvenli taraf), Erişim sınırı sayfası kırmızı **"TRUST_PROXY=1 gerekli"** uyarısı gösterir ve panel listesi kaydedilemez. IP:18443 kurulum betiği (`deploy/setup-ip-https.sh`) `.env` dosyasına `TRUST_PROXY=1` yazar ve güncelleme betiği bunu denetler; `erisim-izin --goster` de değilse uyarır.

#### .env ile (isteğe bağlı)

`IZINLI_IPLER=85.105.12.34,10.0.0.0/8` ve `API_IZINLI_IPLER=...` başlangıç değeri olarak okunur. Panelden ya da `erisim-izin` komutuyla bir kez kaydedildikten sonra veritabanındaki değer geçerlidir (`--temizle` bu yüzden her zaman işe yarar).

### 3. İşlem Geçmişi

* **Ara** kutusu: kayıt numarası (`1234` ya da `#1234`), kayıt anahtarı, kaydın personeli, kullanıcı, işlem, açıklama ve (yöneticilerde) IP adresi.
* **IP** sütunu yalnız süperadmin/sahipte görünür; IP'ye tıklamak o adresin işlemlerini süzer. Kullanıcı işlemleri (ekleme/güncelleme/kilit açma) artık IP ile yazılır.
* Ayrıntı sütunu rol, durum, alan değişikliklerini ve erişim listesi değişikliğini okunur yazar ("Rol: OF: oku → Süperadmin — …", "Panel listesi: (boş — sınır yok) → 85.105.12.34"). Özgün değer **Ham** düğmesinin altında.
* **CSV indir**: ekrandaki süzgecin tamamı (en çok 50.000 satır), Türkçe Excel biçiminde (UTF-8 BOM, `;`), formül enjeksiyonuna karşı güvenli. İndirme İşlem Geçmişi'ne yazılır.
* Hızlı tarih düğmeleri: Bugün, Son 7 gün, Son 30 gün, Bu ay.
* Yeni işlem adları: Sahip ataması, Erişim sınırı ayarı, Erişim engeli (IP) — dakikada IP başına en çok bir satır —, API anahtarı IP listesi, İşlem Geçmişi CSV.

### 4. Teknik notlar (geliştirici)

* `app/yetki.py`: `coz('sahip')` → `admin=True, sahip=True`; `kanonikle` eş anlamlıları (`owner`, `sistem sahibi`) `sahip`e çevirir; `rol_etiketi`, `rol_kodu`, `sahip_mi`; `SAHIP_GEREKLI_EYLEMLER` kümesi (endpoint adları). `panel.sahip_gerekli` süsleyicisi ucu kümeye ekler; `panel.before()` kümedeki uçlarda sahip olmayana 403 döner — başka modüller uç adlarını kümeye ekleyerek aynı korumayı alır.
* `app/kullanicilar.py`: `yonetim_denetimi` (Yasak → 403), `onay_gerekli`, `onay_dogru`, `sahip_ata`, son sahip koruması; `ekle/guncelle` `ip=` alır.
* `app/erisim.py`: liste ayrıştırma (IPv4/IPv6/CIDR, IPv4-eşlemeli IPv6), `ayar_oku(conn, 'panel'|'api')` / `ayar_yaz(conn, tur, metin, kim, ip)` (Ayarlar sayfası bu ikisini çağırabilir), `panel_izinli`, `api_izinli`, `red_kaydet`, `durum_ozeti`. Saklama: `ayarlar` tablosu `izinli_ipler`, `api_izinli_ipler`.
* Şema (eklemeli): `api_anahtarlari.izinli_ipler TEXT`; bayrak `core_schema_240_erisim`.
* API: genel liste anahtar doğrulamasından önce (izinsiz adres anahtar deneyemez), anahtar listesi doğrulamadan sonra, kapsam/hız denetiminden önce.
* Yeni uçlar: `/yonetim/erisim` (sahip), `/denetim.csv`.

---

## Bölüm B2 — İşletim: yedekler, sistem durumu kartı, çalışma ayarları


Bu bölüm sunucuyu yöneten kişi içindir. Üç yenilik var: geri yüklenebilir yedekler ve yedek listesi, ana sayfada
"Sistem durumu" kartı, .env'e dokunmadan değiştirilebilen "Çalışma ayarları" sayfası.

### Güncellemeden sonra bir kez yapın

```
cd /opt/kanit-paneli && sudo bash deploy/setup-backup.sh
```

Bu komut yeni yedek betiğini ve zamanlayıcı birimini kurar (gece çalışması artık `--zamanlayici` ile çağrılır). Yapılmazsa
eski betik çalışmaya devam eder; yedek alınır ama panel son yedeği ve listeyi göremez (kartta "Son yedek" kırmızı kalır).

### 1. Yedekler

**Nerede?**

| Tür | Klasör | Dosya adı | Saklama |
|---|---|---|---|
| Gece (otomatik, 03:17) | `/var/backups/kanit-paneli/gunluk/` (yalnız root) | `panel-YYYYAAGG.db.gz` | 14 gün |
| Sunucuda elle | aynı klasör | `panel-YYYYAAGG-SSDDSS.db.gz` | son 10 |
| Panelden ("Yedek al") | `/opt/kanit-paneli/data/yedekler/` | `panel-YYYYAAGG-SSDDSS.db.gz` | son 10 |

- Elle ya da panelden alınan yedek **gece dosyasının üzerine yazmaz** (adında saat vardır). Eskiden aynı gün elle alınan yedek
  o günün gece dosyasını eziyordu.
- Panelin düğmesi artık **"Yedek al (geri yüklenebilir)"** adını taşır ve gece yedeğiyle **aynı biçimde** (`.db.gz`, bütünlük
  denetimli) yazar. Eski "SQLite yedeği al" dosyası (`.sqlite3`) `--geri-yukle` ile açılmıyordu; bu sorun kalktı.
- Panel yedekleri veri klasöründedir, çünkü web servisi güvenlik gereği yalnız oraya yazabilir. Gece yedekleri root'a ait
  klasörde kalır; panel ele geçirilse bile onları silemez.
- Her yedekten sonra betik `data/son_yedek.json` (son yedek) ve `data/yedekler.json` (liste özeti: ad, boyut, tarih, kayıt sayısı)
  yazar; panel bunları okur. Her yedek klasöründe `MANIFEST.tsv` vardır (kayıt sayısı buradan gelir).
- Gece (zamanlayıcı) yedeği ayrıca `data/son_gece_yedegi.json` yazar. Sistem durumu kartındaki "Son yedek" rengi **yalnız gece
  yedeğine** bakar: panelden ya da sunucuda elle alınan yedek satırda ek bilgi olarak görünür ama satırı yeşile çevirmez
  (gece işi bozulduysa bunu gizlemesin; panel yedekleri ayrıca panelin silebileceği veri diskindedir).
- Telegram'daki `/yedekle` komutu bu sürümde eski biçimde kalır (bot ekibinin işi); panel düğmesini kullanın.

**Listeleme**

- Panel: Yönetim menüsü → Bot sayfası → "Yedekler" bölümü (son 5) ya da `/yonetim/yedekler` (tamamı). Ana sayfadaki Sistem durumu
  kartında da "Yedekler" düğmesi var.
- Sunucu: `sudo /usr/local/sbin/kanit-yedek.sh --liste` (tablo) ya da `--liste --json`.

**Geri yükleme — adım adım**

1. Sunucuya SSH ile bağlanın.
2. Listeden yedeği seçin (panelde her satırın yanında komut ve "Kopyala" düğmesi var).
3. Önce deneyin (hiçbir şeye dokunmaz):
   `sudo /usr/local/sbin/kanit-yedek.sh --geri-yukle panel-20261126-101500.db.gz --dry-run`
   (yalnız dosya adı yeterli; betik gece ve panel klasörlerinde arar. Tam yol da verilebilir.)
4. Plan doğruysa `--dry-run` olmadan çalıştırın. Betik yedeği açıp doğrular (bozuksa durur), paneli ve botu durdurur, mevcut
   veritabanını `/root/kanit-onceki/<zaman>/` altına kopyalar, yedeği yerine koyar, servisleri başlatır.
5. Çıktının sonunda `GERI_YUKLEME_TAMAM` yazar. Yedekten sonra eklenen kayıtlar geri gelmez.

**Kategori temizliği:** sayfanın üstünde "Önce yedek al" düğmesi var; yedek alınır, aynı sayfaya dönülür, dosya adı ve geri
yükleme komutu üstte yazar. (Düğme başka sayfalara da eklenebilir: `templates/_yedek_dugmesi.html`.)

### 2. Sistem durumu kartı (ana sayfa, yalnız süperadmin)

Her satır yeşil (normal), sarı (dikkat), kırmızı (sorun) ya da gri (bilgi yok) olur. Sarı/kırmızı satırın altında kısa açıklama ve
sunucuda çalıştırılacak komut (kopyalama düğmesiyle) yazar.

| Satır | Yeşil | Sarı | Kırmızı |
|---|---|---|---|
| Web sunucusu | sürüm ve çalışma süresi | — | — |
| Telegram botu | son sinyal < 2 dk | < 10 dk, ya da bot duraklatılmış | ≥ 10 dk ya da hiç sinyal yok |
| Son yedek (gece yedeği) | < 26 saat | < 50 saat | daha eski, hiç gece yedeği yok ya da bütünlük bozuk (panel yedeği sayılmaz) |
| Gece görsel işi | son 36 saatte başarılı | daha eski (< 7 gün), hız sınırı ya da servis arızası | erişim hatası / hata / 7 günden eski (hiç çalışmadıysa gri) |
| Hatırlatma işi | son çalışma < 20 dk (aralık 10 dk iken) | < 60 dk | daha eski (aralık 0 ise gri: kapalı) |
| Disk | < %80 dolu | < %90 | ≥ %90 |
| Veritabanı boyutu | bilgi | — | — |
| Bot kuyruğu | işlenemeyen yok, bekleyen < 20 | işlenemeyen var ya da bekleyen ≥ 20 | bekleyen ≥ 200 |

- Kırmızı satır için süperadminlere **günde bir, satır başına bir** "Sistem" bildirimi gider (zil + Bildirimler sayfasında "Sistem"
  türü; proje rozeti yoktur, düğme "Sistem durumunu aç"). Tıklayınca ana sayfadaki kart açılır. Bildirim, panelin 10 dakikalık hatırlatma işiyle üretilir.
- JSON: `/yonetim/sistem-durumu.json`. Sunucuda: `cd /opt/kanit-paneli && sudo runuser -u kanit -- .venv/bin/python -m app.cli durum` (kırmızı satır varsa çıkış kodu 1; `--json`, `--uyar`).
  (Not: eski `/durum.json` adresi aynen duruyor; yeni kart onu kullanmaz.)

### 3. Çalışma ayarları (`/yonetim/ayarlar`)

Hatırlatma, bildirim, görünürlük, API ve görsel ayarları artık panelden değiştirilebilir. Gizli anahtarlar, parolalar, dosya
yolları ve port **listede yoktur** ve buradan hiçbir şekilde yazılamaz.

**Hangi değer geçerli? (öncelik)**

1. Panelde kaydedilen değer (sayfada **DB** etiketi),
2. yoksa `.env` dosyasındaki değer (**.env**),
3. o da yoksa varsayılan (**varsayılan**).

"Varsayılana dön" yalnız panel değerini siler; `.env`'de değer varsa o geçerli olur. `.env`'deki değer geçersizse sayfa bunu
kırmızıyla yazar ve **okuyucunun gerçekte kullandığı değeri** gösterir (eskiden sessizce varsayılana düşüyordu): geçersiz
yazım → varsayılan; bazı üst sınırlar kırpılır (ör. `BEKLEYEN_OZET_SAAT=30` → 24); bazı sınır dışı değerler olduğu gibi kullanılır
(ör. `HATIRLATMA_GUN=500`). "Şu an geçerli değer" sütunu ve `ayar --listele` bu gerçek değeri yazar. `DIS_GORSEL_PROXY` .env'de
yoksa `GYAZO_PROXY` değeri geçerlidir (sayfada not olarak yazar).

- Her alan kaydedilirken denetlenir; hatalı değerde Türkçe açıklama alanın yanında çıkar, girilen değer kaybolmaz.
- Her değişiklik İşlem Geçmişi'ne eski ve yeni değerle yazılır ("Çalışma ayarını değiştirdi").
- Yeniden başlatma gerekmez: değer bir sonraki istekte (görünürlük, API) ya da hatırlatma işinin bir sonraki turunda geçerli olur.
  İstisnalar sayfada "Not" olarak yazar: Gyazo/Snappark görsel ayarları panel görünümü için `sudo systemctl restart kanit-web`
  ister (gece işi bir sonraki çalışmada uygular); hatırlatma işi sunucu açılırken 0 (kapalı) idiyse açmak için bir kez restart.
- Değiştirme yetkisi **sahip** hesabındadır; süperadmin sayfayı salt okunur görür. (Sahip rolü aynı sürümde ayrıca geliyor;
  o gelene kadar süperadmin değiştirebilir.)
- Sunucudan (kanit hesabıyla; root olarak çalıştırmayın, veritabanı yan dosyaları root sahipli kalır):
  `cd /opt/kanit-paneli && sudo runuser -u kanit -- .venv/bin/python -m app.cli ayar --listele`,
  `… ayar BEKLEYEN_OZET_SAAT 3`, `… ayar BEKLEYEN_OZET_SAAT --sil`.

Gruplar ve ayarlar: **Hatırlatmalar** (HATIRLATMA_GUN, HATIRLATMA_TEKRAR_GUN, HATIRLATMA_GUNLUK_SINIR, HATIRLATMA_KONTROL_DK,
HATIRLATMA_SAAT, HATIRLATMA_SAAT_TOPLU), **Bildirimler** (BEKLEYEN_OZET_SAAT, BEKLEYEN_OZET_PENCERE, BEKLEYEN_OZET_YONETICI,
GUN_SONU_SAAT, GUN_SONU_ALICILAR), **Görünürlük** (ONAYSIZ_GORUNUM, PANEL_EKLEME_KATEGORI), **API** (API_ACIK, API_DAKIKA_SINIRI),
**Görseller** (GYAZO_PROXY, DIS_GORSEL_PROXY).

### Teknik özet (geliştirici / koordinatör)

- Yeni: `app/ayarlar.py` (katman + kayıt listesi), `app/durum.py`, `app/yedek.py`, `app/isletim.py` (blueprint; panel.py sonunda
  kaydedilir), şablonlar `ayarlar.html`, `yedekler.html`, `_sistem_durumu.html`, `_yedekler_tablo.html`, `_yedek_dugmesi.html`,
  `static/isletim.css`. Şema değişikliği yok (mevcut `ayarlar` tablosu: `ayar:<AD>`, `is:hatirlatma`, `is:gece_gorsel`).
- Okuyucular katmana bağlandı: `hatirlatma.ayarlar(ayar, conn)`, `panel._onaysiz_modu/_hatirlatma_gun`, `api.acik_mi/dakika_siniri`,
  `katalog.panel_kategori_etiketi(conn)`, `cli gyazo-onbellekle`, panel açılışındaki görsel çözücü.
- `kanit-yedek.sh`: `--zamanlayici`, `--liste [--json]`, ad ile `--geri-yukle`, her yedekte `YEDEK_DOGRULANDI` satırı, MANIFEST,
  işaretler; elle/gece yedekleri ayrı saklanır. `kanit-yedek.service` `--zamanlayici` ile çalışır.
- Sahip kapısı: `isletim.sahip_gerekli` / `_sahip_mi()` — B1'in `panel.sahip_gerekli`, `panel.sahip_mi` ya da `g.yk['sahip']`
  alanı varsa onu kullanır; yoksa süperadmin (TODO B1). `durum._alicilar` şu an yetkisi `admin` olanları alır; sahip rolü ayrı
  bir yetki metniyle gelirse oraya eklenmeli.
- Menü için tek satır (base.html, Yönetim açılır menüsü, "API anahtarları" satırının altına):
  `<a href="{{ url_for('isletim.ayarlar') }}" class="{{ 'aktif' if ep in ('isletim.ayarlar','isletim.yedekler') }}">Çalışma ayarları / Yedekler</a>`

