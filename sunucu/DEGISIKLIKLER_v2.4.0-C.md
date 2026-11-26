# Kanıt Paneli 2.4.0 — Takım C: Telegram botu (bildirimler, soru-yanıt, daha az dokunuş)

Önceki sürüm üzerine `deploy/apply-update.sh` ile uygulanır. Veritabanına yalnız **yeni tablolar** eklenir
(`bot_giden`, `tg_tercihler`; ilk kullanımda kendiliğinden oluşur, mevcut tablolara dokunulmaz). `.env`
dosyasına bir şey yazmak gerekmez; varsayılanlar aşağıda.

Değişen dosyalar: `app/bot.py`, `app/bot_bildirim.py` (yeni), `app/discussion.py`, `app/panel.py` (yalnız kısa kancalar:
onay, silme, kayıt ayrıntısı, kanıt ekleme ve `tg_duzeltme` denetim adı), `app/static/panel.js` (soru alıcısı
seçeneği ve mükerrer onayı), `app/templates/_kanit_ekle.html` (bir gizli alan), `tests/test_v240_bot.py` (yeni);
mevcut testlerde küçük uyarlamalar (`BOT_GYAZO_SOR=1`, `yine_de=1`, tarayıcı senaryosunda onay penceresi kabulü).

## Sahadaki personel ne görür?

### Onay ve silme haberi artık Telegram'a gelir
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

### Takım lideri soruyu doğrudan ekleyene sorar (WhatsApp'a gerek yok)
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

### Daha az dokunuş
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

### Albüm ve yarım kalan işlem
- İki fotoğraf **albüm** olarak gönderilince ilki artık kaybolmaz: ikisi **tek kanıt** olur (ikinci görsel
  kaydın 2. görseli olarak saklanır). Üçüncü ve sonrası alınmaz: "En çok 2 görsel; fazlası alınmadı."
- Bir düğme beklenirken (proje/kategori seçimi, SON KONTROL vb.) yazı yazılırsa yarım kanıt **silinmez**. Bot
  şunu sorar: **"Yarım kalan kanıt işlemi var. [Devam et] [İptal et ve yeni başla]"**. Yeni Lead ID akışı ancak
  "İptal et ve yeni başla" seçilince başlar (yazılan metin Lead ID olarak alınır).

### Mükerrer uyarısı
- Botta SON KONTROL'den önce, son 30 günde silinmemiş bir kayıtta **aynı proje + kategori + üye ID** ya da
  **aynı görsel** varsa: `⚠️ Bu üye ID 12.11'de #1180 olarak kaydedilmiş. Yine de kaydet? [Evet, kaydet]
  [Vazgeç]`. Vazgeç düzeltme menüsüne döner.
- Panelden kanıt eklerken aynı bağlantı (Gyazo/Snappark/Teamzone) ya da aynı proje + kategori + üye ID son 30
  günde varsa form bir kez uyarır (kayıt açılmaz); onaylanırsa ikinci gönderim kaydeder.

## Ayarlar (.env, hepsi isteğe bağlı)

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

## İşletme notları
- Web süreci Telegram'a bağlanmaz: mesajlar `bot_giden` tablosuna yazılır, bot her poll turunda (en geç ~25-45
  saniye) gönderir. Bot kapalıysa mesajlar bekler, açılınca gider.
- Geçici hatada 30 sn, 2 dk, 10 dk, 30 dk, 1 saat arayla yeniden denenir; kalıcı hatada (kişi botu engelledi,
  sohbet yok) hemen vazgeçilir. Vazgeçilen her mesaj bot günlüğüne (`bot_log.txt`) "Panel bildirimi … teslim
  edilemedi; vazgeçildi" satırıyla yazılır.
- Onay/silme bildirimi yazılamazsa (ör. beklenmeyen veritabanı hatası) onay/silme işlemi yine tamamlanır;
  yalnız bildirim atlanır. "Ekleyene sor" sorusu ise kuyruğa yazılamazsa hiç kaydedilmez (panel hata gösterir).
- Telegram'da ekleyene iletilemeyen soru (bot engellenmiş, sohbet kapalı ya da deneme sınırı doldu) için soran
  takım liderine panelde "sorunuz Telegram'da ekleyene iletilemedi" bildirimi düşer; yanıt beklemez.

## İnceleme düzeltmeleri
- Panelin mükerrer uyarısı aynı bağlantıyı/görseli yalnız **aynı projede** arar; kullanıcının okuma yetkisi
  olmayan bir projedeki kaydın numarası ve tarihi artık uyarıda görünmez.
- `BOT_SORU_BILDIRIMI=0` yapıldığında (ya da kaydın Telegram ekleyeni yoksa) eski Telegram konuşmasına panelden
  "Yanıtla" artık hata vermez; yanıt panelde normal yanıt olarak kalır.
- Çok uzun ve özel karakterli (`<`, `&`) sorular Telegram'a giderken kaçıştan önce kısaltılır (sonuna "…"),
  "/yanit" satırı her zaman bütün kalır; mesaj Telegram tarafından reddedilmez.
- Türkçe klavyeyle yazılan `/yanıt`, `/yardım`, `/kayıtlarım` da tanınır.
