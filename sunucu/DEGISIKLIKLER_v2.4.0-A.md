# Kanıt Paneli 2.4.0 — A bölümü: Kayıtlar sayfası, bildirimler, gün sonu özeti ve Excel çıktısı

Bu bölüm takım liderlerinin günlük işini (bekleyenleri sırayla onaylamak, bildirimleri izlemek, haftalık/aylık çıktı almak) kolaylaştıran değişiklikleri anlatır. Veritabanı şeması değişmez; `.env` dosyasına bir şey yazmak **gerekmez**, iki yeni ayar isteğe bağlıdır (aşağıda). Değişen dosyalar: `app/panel.py`, `app/hatirlatma.py`, `app/personel_ozeti.py`, `app/settings.py`, `app/api_kilavuz.py` (yalnız dönem listesi), `app/templates/kayitlar.html`, `app/templates/disa_aktar.html`, `app/templates/ana.html` (yalnız "Onay bekleyen" kutusu), `app/static/panel.js`, `app/static/kayit.css`.

## 1. Bildirimler: gürültü azaldı

- Bir kayıt **onaylanınca, onayı kaldırılınca, silinince ya da geri alınınca** o kayda ait "Yeni kanıt" bildirimleri ve kayda özel hatırlatmalar **herkes için okundu** sayılır. Önceden 3 kayıt onaylandıktan sonra zilde 56 "Yeni kanıt" okunmamış kalabiliyordu; artık onaylanan kaydın bildirimi kimsenin zilinde beklemez. Toplu onay da aynı kuralı uygular.
  - Soru, yanıt ve yorum bildirimlerine **dokunulmaz** (sorular yanıtlanana kadar görünür kalır).
  - Gün sonu, bekleyen özeti ve proje özeti gibi bir **listeye** bağlı satırlar da kalır.
- "Kanıt onaylandı" bildirimi artık diğer proje sorumlularına **varsayılan olarak gitmez**. Kimin neyi onayladığı her zamanki gibi **İşlem Geçmişi**'nde ve kaydın "İşlem geçmişi" bölümünde görünür. Eski davranışı isteyen kurulum `.env` dosyasına `BILDIRIM_ONAY=1` yazar.
- **Ses türe göre** ayarlanır (her tarayıcı için ayrı, varsayılan hepsi açık): zil kutusunda "Ses" anahtarının altında üç anahtar vardır:
  - **Yeni kanıt**
  - **Soru / yanıt / yorum**
  - **Hatırlatma ve özetler**

  Onay bildirimleri hiç ses çalmaz. Ana **Ses** anahtarı kapalıysa (eskisi gibi) hiçbir bildirim ses çalmaz; tür anahtarları da soluk görünür.

## 2. Gün sonu özeti (18:00) artık takım liderlerine de gider

- Varsayılan alıcılar: **süperadminler + en az bir projede onay yetkisi olan her aktif kullanıcı**.
- Takım lideri yalnız **onaylayabildiği projelerin** sayılarını görür ("Gün sonu 26.11.2026: 3 kayıt onaylanmadı (OF 3) …"); süperadmin tüm projeleri görür.
- Kişi başına günde **bir** satır (değişmedi).
- `GUN_SONU_ALICILAR` doluysa eskisi gibi **yalnız o adlara** gider (bu adlar görebildikleri projelerin özetini alır). Yalnız yöneticilere göndermek isteyen kurulum bu ayara yönetici adlarını yazar.

## 3. "Onay bekleyen" görünümü

- **Sayılar:** Ana sayfadaki "Onay bekleyen kayıt" kutusu ve Kayıtlar'daki **Onay bekleyen** sekmesi yalnız sizin **onaylayabildiğiniz** projeleri sayar (süperadmin: hepsi). Yalnız görüntüleyebildiğiniz projelerde de bekleyen varsa yanında küçük bir not çıkar: **"+10 görüntüleyebildiğiniz projelerde"** (ana sayıya katılmaz; Kayıtlar'daki not o projelerin listesini açar). Proje çipinden o projeyi seçerseniz bekleyenleri yine listelenir. Hiçbir projede onay yetkisi olmayan kullanıcıda sayılar eskisi gibidir. Bu daraltma Kayıtlar'daki **Excel (bu görünüm)** düğmesine de uygulanır (dosya sekmeyle aynı kayıtları verir; "Bilgi" sayfası dışarıda kalan projeleri yazar). **Çıktı** sayfası değişmedi: orada "Onaysızlar (onay bekleyen)" seçildiğinde görüntüleyebildiğiniz tüm projelerin bekleyenleri dosyaya girer.
- **Sıra:** Onay bekleyen sekmesi artık **en eski önce** (en uzun bekleyen en üstte) açılır. Sağ üstteki **Sıra** seçimiyle "En yeni önce"ye geçebilirsiniz; seçim adreste (`sirala=eski|yeni`) durur, sayfalar arasında korunur. Diğer sekmeler eskisi gibi en yeni önce açılır. Hatırlatma, bekleyen özeti ve gün sonu bildirimlerinin bağlantıları da bu sırayla açılır.
- **Bekleme rozeti:** Onay bekleyen her satırda/kartta ve ayrıntı penceresinin başlığında kaydın ne zamandır beklediği yazar: **"45 dk"**, **"5 sa"**, **"3 gün"**. Süre, hatırlatmalarla aynı başlangıçtan (ilk görülme, yoksa eklenme tarihi) sayılır.
  - **Turuncu:** `BEKLEME_UYARI_SAAT` saatten (varsayılan **2**) uzun bekleyen.
  - **Kırmızı:** `HATIRLATMA_GUN` günden (varsayılan **3**) uzun bekleyen.

## 4. Onaylama akışı: "Onayla ve sonraki"

- Ayrıntı penceresinde birincil düğme **Onayla ve sonraki**: kaydı onaylar ve bu sayfadaki **sıradaki bekleyen** kaydı açar. Alt tarafta 5 saniye boyunca **"Geri al"** düğmeli bir ileti çıkar; basarsanız onay kaldırılır (İşlem Geçmişi'ne "Onay kaldırma" olarak yazılır) ve kayıt yeniden açılır. Sayfadaki bekleyenler bitince "Bu sayfadaki bekleyenler bitti" yazar.
- Yanındaki **Onayla** düğmesi eskisi gibi onaylar ve aynı kayıtta kalır.
- **Klavye kısayolları** (pencere açıkken; bir yazı alanında yazarken çalışmaz): **O** onayla ve sonraki · **U** son onayı geri al ("Geri al" yazısı görünürken, 5 sn) · **S** soru sor (soru kutusuna geçer) · **D** düzenle · **Delete** sil (her zamanki silme sorusu çıkar) · **← →** önceki/sonraki · **?** kısayol yardımını aç/kapat · **Esc** kapat. Kısayollar pencerenin üst satırında da yazar. Sıradaki kayıt yüklenirken (bağlantı yavaşsa "Yükleniyor" yazar) düğmeler ve kısayollar kısa süre çalışmaz; böylece yanlışlıkla önceki kayıt onaylanmaz.
- **Hızlı önizleme:** Tablo görünümünde küçük resmin üzerine gelince (ya da Tab ile üzerine gelince) büyük önizleme çıkar; **Esc** kapatır. Telefonda bu özellik yoktur.

## 5. Dönemler ve Excel çıktısı

- Kayıtlar'ın **Gelişmiş filtreler** bölümünde ve **Çıktı** sayfasında hızlı tarih düğmeleri: **Bugün / Bu hafta / Geçen hafta / Bu ay / Geçen ay**. Hafta pazartesi başlar; tarihler İstanbul takvimine göredir. Kayıtlar'da düğmeye basınca liste hemen süzülür; Çıktı sayfasında tarih kutuları dolar.
- Personel raporunun **Dönem** seçeneklerine **Geçen hafta** ve **Geçen ay** eklendi (adres: `donem=gecen_hafta` / `donem=gecen_ay`). "Durumlar" karşılaştırması geçen hafta için bir önceki haftayı, geçen ay için bir önceki takvim ayını kullanır.
- **Tarih ölçütü:** Kayıtlar'da ve Çıktı sayfasında tarih aralığı artık **Eklenme** (varsayılan, eskisi gibi) ya da **Onay zamanı**na göre uygulanabilir (`tarih_alani=onay`). Onay zamanına göre süzüldüğünde yalnız onaylı kayıtlar gelir. Excel çıktısı da bu seçime uyar.
- **Excel dosyası (Kayıtlar ve Çıktı):**
  - Dosya adı seçimden oluşur, ör. `kanit-kayitlari-OF-onayli-2026-11-17_2026-11-23.xlsx` (proje seçilmediyse proje yazılmaz; onay zamanına göre süzüldüyse tarihin önünde `onay-`; onay yetkiniz olmayan projelerden onaysız satır varsa sonda eskisi gibi `-ONAYSIZ-N`).
  - İlk sayfa **"Bilgi"**: uygulanan süzgeçler (proje, durum, tarih ölçütü ve aralığı, kategori, arama…), dosyayı oluşturan kişi, oluşturma zamanı ve kayıt sayısı. Dosya **"Kayıtlar"** sayfasında açılır.
  - **Tarih**, **Onay zamanı** ve **Silme zamanı** sütunları artık gerçek Excel tarihidir (sıralanır, süzülür; saatsiz eski kayıtlarda yalnız tarih). Okunamayan eski tarih metinleri olduğu gibi kalır.
  - Personel raporunun CSV çıktısı değişmedi.

## 6. Küçük arayüz düzeltmeleri

- **Telefonda (≤ 900 px)** Kayıtlar'ın süzgeç paneli varsayılan **kapalı** gelir; üstteki **"Süzgeçler (N etkin)"** düğmesiyle açılır. Açık/kapalı tercihi o tarayıcıda hatırlanır. İlk kayıt artık sayfanın en üstüne yakın görünür.
- Telefonda durum sekmeleri (Onay bekleyen / Onaylı / Silinen / Hepsi) **tek satırda** kalır, sığmazsa yana kaydırılır.
- Sunucuda Gyazo anahtarı (`GYAZO_TOKEN`) tanımlı değilse **"Gyazo'ya dönüştür" düğmesi hiç gösterilmez** (önceden soluk düğme ve açıklama çıkıyordu). Sayfaya yalnız "anahtar var/yok" bilgisi gider, anahtarın kendisi asla gitmez.

## Yeni ayarlar (isteğe bağlı, `.env`)

| Ayar | Varsayılan | Ne işe yarar |
|---|---|---|
| `BILDIRIM_ONAY` | `0` | `1` yapılırsa onay / onay kaldırma diğer proje sorumlularına zil bildirimi olarak da gider. İşlem Geçmişi her durumda yazılır. |
| `BEKLEME_UYARI_SAAT` | `2` | "Bekleme" rozetinin turuncuya döndüğü süre (saat). Kırmızı eşik mevcut `HATIRLATMA_GUN` ayarıdır (varsayılan 3 gün). |

## Kapatmak / eski davranışa dönmek isterseniz

- Onay bildirimleri geri gelsin: `BILDIRIM_ONAY=1`, ardından `systemctl restart kanit-web`.
- Gün sonu özeti yalnız yöneticilere gitsin: `GUN_SONU_ALICILAR=yonetici1,yonetici2` (virgülle kullanıcı adları). Özeti tamamen kapatmak için `GUN_SONU_SAAT=0` (değişmedi).
- Ses: zil kutusundaki tür anahtarları ya da ana **Ses** anahtarı (her kullanıcı kendi tarayıcısında).
- Turuncu eşiği değiştirmek: ör. `BEKLEME_UYARI_SAAT=4` (saat), ardından `systemctl restart kanit-web`.
- Liste sırası: Kayıtlar'daki **Sıra** seçimi (adres `sirala=yeni`).

Testler: `tests/test_v240_panel.py` ve tarayıcı senaryosu `tests/v240_panel_tarayici.js` (Node + Playwright yoksa tarayıcı testi atlanır).
