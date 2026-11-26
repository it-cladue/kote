# Kanıt Paneli 2.3.3 — bildirimler pop-up ve sesli; 2 saat ve gün sonu hatırlatmaları (26 Kasım 2026)

2.3.2 üzerine `deploy/apply-update.sh` ile uygulanır (sunucuda depodan taze kopya + güncelleme, KURULUM §13). Panel ekranı (şablon, `panel.js`, `stil.css`) ve hatırlatma işi değişir; veritabanına yalnız küçük bir işaret tablosu eklenir (`hatirlatma_isaret`), mevcut kayıtlar, bot ve `.env` aynı kalır (yeni ayarlar isteğe bağlı, aşağıda). Tarayıcı yeni dosyaları kendiliğinden alır (sürüm numaralı adresler), Ctrl+F5 gerekmez.

## Ekip ne görür?

### Sağ üstte bildirim kartları

- Panel açıkken yeni bir bildirim gelince (yeni kanıt, soru, yanıt, yorum, onay, onay kaldırma, hatırlatma) zilin hemen altında bir **kart** çıkar. Kartta proje rozeti (proje rengiyle), bildirim türü, "#kayıt · personel · kategori" satırı, bildirim metni ve saat vardır.
- Kart düğmeleri: **Aç** (bildirimi okundu sayar ve kayda gider; yorum/soru/yanıtta ilgili yorum vurgulanır, hatırlatma özetinde projenin bekleyen listesi açılır — zildeki satırla aynı yer), **Okundu** (yalnız okundu sayar, kart kapanır), **×** (kartı kapatır; bildirim okunmamış kalır, zilde durur).
- Normal kartlar 15 saniye sonra kendiliğinden kapanır; fare kartın üzerindeyken ya da klavye odağı kartın içindeyken süre durur. **Hatırlatma kartları kendiliğinden kapanmaz.**
- Aynı anda en çok 4 kart görünür. Bir yoklamada 3 ya da daha fazla yeni bildirim gelirse tek bir **özet kart** çıkar: "5 yeni bildirim (2 hatırlatma)" — **Bildirimleri aç** (zil listesini açar) ve **Tümünü gör** (okunmamış bildirimler sayfası). Masaüstü bildirimi izni henüz sorulmadıysa özet kartta bir kez "Masaüstü bildirimlerini aç" düğmesi de görünür.
- Bildirim başka yerde okunursa (zil, Bildirimler sayfası, başka sekme, hatırlatma penceresindeki **Tümünü okundu say**) ilgili kart kendiliğinden kalkar. Özet kart da kapsadığı bildirimlerin hepsi okununca kalkar.
- Klavyeyle: kartlar sekme (Tab) sırasında üst menünün hemen ardındadır; zilden sonra birkaç Tab ile kartın düğmelerine gelinir. Yeni kart odağı kendine çekmez; Esc odaktaki kartı kapatır.
- Sayfa ilk açıldığında zaten var olan okunmamış bildirimler için kart ya da ses çıkmaz; onlar her zamanki gibi zilde sayılır.
- Alttaki küçük şerit (tost) artık bildirimler için kullanılmaz; yalnız "Kaydedildi", "Okundu işaretlendi" gibi işlem geri bildirimleri için kalır.
- Telefonda kartlar üst menünün altında tam genişlikte görünür. Açık ve koyu temada okunur.
- Kayıt ayrıntı penceresi ya da görsel büyütme açıkken kartlar onların arkasında kalır, pencere kapanınca görünür.

### Ses

- Yeni bildirimde kısa ve yumuşak iki tonlu bir ses, hatırlatmada ayırt edilsin diye üç tonlu bir zil sesi çalar. Ses dosyası yoktur; tarayıcı sesi kendisi üretir (Web Audio).
- **Tarayıcı kuralı:** sayfa açıldıktan sonra sayfaya bir kez tıklanmadan ya da bir tuşa basılmadan tarayıcı ses çalmaya izin vermez. Bu yüzden panel her açılışta ilk tıklamadan/tuştan sonra sesli olur; ondan önce gelen bildirimler sessiz ama kartlı gelir. Ses çalamadığında hiçbir hata gösterilmez.
- **Sesi kapatmak:** zil (Bildirimler) → listenin üst satırındaki **Ses** anahtarının işaretini kaldırın. Tercih o tarayıcıda saklanır (varsayılan açık); her kişi kendi bilgisayarında ayrı seçer. Anahtar açılınca örnek ses bir kez çalar.

### Hatırlatma penceresi

- Onay bekleyen kayıtlar için okunmamış hatırlatma varsa ekranın ortasında **"Bekleyen kontroller hatırlatması"** penceresi açılır. Listede kayıt başına bir satır (ekranda "**Kayıt #id · personel** Bu ID'nin kontrolü N gündür bekliyor.") ve proje özetleri ("**OF · Proje özeti** …") vardır. Kayıt satırındaki **Aç** kayda gider; proje özeti satırındaki **Bekleyenleri aç** projenin bekleyen listesini açar. İkisi de o hatırlatmayı okundu sayar.
- Ne zaman açılır (2.3.4 ile güncellendi): her hatırlatma için günde en çok **bir kez** kendiliğinden açılır. (a) Panel sayfası açıldığında bugün henüz pencerede gösterilmemiş okunmamış bir hatırlatma varsa (tarayıcı kuralı gereği sayfa açılışında henüz tıklama olmadığı için bu açılış sessizdir); (b) panel açıkken yeni hatırlatma gelince (hatırlatma sesiyle birlikte). Pencere açılınca listedeki tüm okunmamış hatırlatmalar görünür. Sayfadan sayfaya geçerken aynı hatırlatmalar için pencere yeniden açılmaz. Ertesi gün okunmamış kalan hatırlatmalar bir kez daha gösterilir.
- Alt düğmeler:
  - **Daha sonra**: bugün pencere bir daha kendiliğinden açılmaz; yeni hatırlatmalar kart ve zil olarak gelir (ses de çalar). Ertesi gün okunmamış hatırlatma kaldıysa pencere yeniden açılır. Seçim o tarayıcıda, kişiye göre saklanır.
  - **Tümünü okundu say**: listedeki hatırlatmaları okundu sayar ve pencereyi kapatır (kayıtların onay durumu değişmez).
  - **Kapat** (ya da Esc, pencere dışına tıklamak): bu hatırlatmalar için pencere bir daha kendiliğinden açılmaz; yeni hatırlatma gelirse açılır.
  - **Tüm hatırlatmalar**: Bildirimler sayfasını okunmamış hatırlatmalar süzgeciyle açar.
- Kayıt ayrıntı penceresi ya da görsel büyütme açıkken veya kullanıcı bir alana (arama kutusu, yorum, düzenleme) yazarken pencere **açılmaz**; kayıt penceresi kapanınca ya da yazma alanından çıkıldıktan sonraki yoklamada (en geç 10 sn) açılır. Yazı yazan kişinin imleci alınmaz.
- Pencereyi istediğiniz zaman açmak için: zil (Bildirimler) → listenin üst satırındaki **Hatırlatmalar (N)** düğmesi (yalnız okunmamış hatırlatma varken görünür; "Daha sonra" denmiş olsa da açar).
- Klavye: pencere açılınca odak ilk "Aç" düğmesine gelir, Tab pencere içinde döner, Esc kapatır ve odak önceki yere döner.

### Arka plandaki sekme

- Panel sekmesi arka plandayken de bildirimler kontrol edilir (10 sn yerine 30 sn'de bir). Yeni bildirim gelince ses (izin varsa) ve masaüstü bildirimi hemen çıkar; kartlar ve hatırlatma penceresi sekmeye dönünce gösterilir (kaybolmaz).

### Masaüstü bildirimleri

- Zil listesinin üst satırındaki **Masaüstü bildirimlerini aç** düğmesine basıp tarayıcının sorusuna "İzin ver" deyin. Düğme, izin sorusu yanıtlanmadıkça (pencere kapatılsa da) görünür kalır; "Engelle" denirse tarayıcının site ayarlarından (adres çubuğundaki kilit simgesi → Bildirimler) açılabilir.
- Masaüstü bildirimine tıklanınca panel sekmesi öne gelir ve bildirimin kaydı açılır (bildirim okundu sayılır); toplu bildirimde okunmamış bildirimler sayfası açılır.
- Masaüstü bildirimi yalnız panel bir sekmede açıkken çalışır (site kapalıyken bildirim gönderilmez; bu değişmedi).

## Hatırlatma zamanlaması: 2 saat ve gün sonu 18:00

Onay bekleyen kayıtlar için iki yeni bildirim geldi. 2.3.1'deki 3 gün hatırlatması aynen sürer. Bildirimler zilde, Bildirimler sayfasında ve paneldeki hatırlatma penceresinde diğer hatırlatmalar gibi "Hatırlatma" etiketiyle görünür (pencerenin kendisi ayrı bölümde anlatılır).

**1. Kayıt 2 saattir onay bekliyorsa**

- Telegram'dan gelen bir kayıt **2 saat** içinde onaylanmazsa, o projede **onay yetkisi olan herkese** bir kez bildirim gider: "Kayıt #1203 (Ayşe K.) 2 saattir onay bekliyor." Bildirime tıklayınca kayıt açılır.
- Aynı kayıt için bu bildirim **bir kez** gider; tekrar etmez (sonraki hatırlatmayı 3 gün kuralı yapar).
- Aynı anda aynı projeden **5'ten fazla** kayıt 2 saati doldurursa tek tek bildirim yerine **tek toplu bildirim** gider: "GA: 12 kayıt en az 2 saattir onay bekliyor (#1203, #1204, #1205, …)." Tıklayınca o projenin bekleyen listesi açılır. Toplu bildirime giren kayıtlar sonradan ayrıca bildirilmez.
- Kayıt onaylanınca 2 saat bildirimi okundu olur ve zilden düşer.
- Eski Excel'den aktarılan kayıtlar bu bildirime girmez (onlar 3 gün kuralındaki proje özetiyle bildirilir).
- Süre, kaydın panele ilk geldiği andan sayılır (Telegram kaydında eklenme anı); kayıt sonradan düzenlense de sayaç baştan başlamaz.

**2. Her gün 18:00 gün sonu özeti (İstanbul saati)**

- Her gün İstanbul saatiyle **18:00'den sonraki ilk kontrolde (18:00–18:10 arasında)** her **yöneticiye** bir özet gider, örnek:
  "Gün sonu 26.11.2026: 304 kayıt onaylanmadı (GA 120, OF 80, PA 64, PP 40). Bugün eklenen 15, bugün onaylanan 9, 2 saatten uzun bekleyen 40."
- "Onaylanmadı" sayısı o an onaysız ve silinmemiş tüm kayıtlardır (eski Excel kayıtları dâhil). "Bugün" İstanbul takvim günüdür; sunucunun saati UTC olsa da doğru hesaplanır.
- Tıklayınca tüm projelerin bekleyen listesi açılır.
- Günde **bir kez** gider; panel yeniden başlasa da ikinci kez gitmez. Hiç bekleyen kayıt yoksa özet gönderilmez.
- Panel 18:00'de kapalıysa özet aynı gün panel açıldıktan yaklaşık 20 saniye sonra gider; panel ancak gece yarısından (İstanbul) sonra açılırsa o günün özeti gönderilmez. O an panele girmemiş yönetici bildirimi okunmamış olarak bir sonraki girişinde zilde/pencerede görür.
- `ONAYSIZ_GORUNUM=gizle` iken yönetici olmayan alıcıya yalnız onay yetkisi olduğu projeler sayılır; hiç onay yetkisi yoksa ona özet gitmez.

**Ayarları değiştirmek** (`/opt/kanit-paneli/.env`, ardından `systemctl restart kanit-web`):

| Ayar | Varsayılan | Anlamı |
|---|---|---|
| `HATIRLATMA_SAAT` | `2` | Kaç saat sonra bildirilsin; `0` = 2 saat bildirimi kapalı (negatif ya da hatalı değer 2 sayılır) |
| `HATIRLATMA_SAAT_TOPLU` | `5` | Aynı projeden bundan fazla kayıt aynı anda dolarsa tek toplu bildirim |
| `GUN_SONU_SAAT` | `18:00` | Gün sonu özetinin saati (İstanbul, SS:DD, ör. `17:30`; `17.30` da kabul edilir); boş ya da `0` = kapalı; hatalı yazılırsa 18:00 kullanılır ve günlüğe bir kez not düşer |
| `GUN_SONU_ALICILAR` | boş | Boşsa tüm aktif yöneticiler; doluysa yalnız buraya virgülle yazılan kullanıcı adları (yöneticilerin yerine). Olmayan ya da pasif kullanıcı atlanır ve günlüğe bir kez yazılır. Yönetici olmayan alıcı yalnız görebildiği projelerin sayılarını alır |
| `HATIRLATMA_KONTROL_DK` | `10` (önceden 30) | Kontrol sıklığı (dakika). 10 dk ile 2 saat bildirimi en geç ~10 dk gecikir, özet 18:00–18:10 arasında gider; `0` = arka plan kontrolü kapalı (yalnız komutla) |

**Hemen denemek** (18:00'i beklemeden, sunucuda):

```bash
runuser -u kanit -- /opt/kanit-paneli/.venv/bin/python -m app.cli hatirlatma-uret --gun-sonu-zorla
```

Komut önce ayrıntılı JSON raporu, en sonda kısa Türkçe özet yazar: 3 gün kuralı, 2 saat kuralı ve gün sonu özeti için kaç bildirim üretildiği. Aynı gün ikinci kez çalıştırılırsa yeni özet üretmez ("bugün zaten gönderildi").

**Dikkat:** `--gun-sonu-zorla` o günün özetini o anki sayılarla gönderir ve o günün özeti sayılır; aynı gün 18:00'de **ikinci özet gitmez**. Gerçek sunucuda denemeyi tercihen 18:00'den sonra (ya da bir test sunucusunda) yapın; sabah denerseniz yöneticiler o gün yalnız sabahki sayıları görür. `--tarih` yalnız 3 gün kuralını etkiler; 2 saat ve gün sonu adımları her zaman şimdiki saate göre çalışır.

**Teknik not:** Veritabanına yalnız bir yeni tablo eklenir (`hatirlatma_isaret`: hangi kaydın 2 saat bildiriminin kime gittiği); mevcut veriler değişmez. Bildirim anahtarları: `hatirlatma-saat:<kayıt>`, `hatirlatma-saat-ozet:<proje>:<YYYY-AA-GG SS:DD>`, `gun-sonu:<YYYY-AA-GG>`. Gün sonu satırı veritabanı kuralı gereği bir kayda bağlıdır: en kalabalık bekleyen projenin en eski bekleyen kaydı (rozet o projeyi gösterir; metin tüm dağılımı taşır). Yükseltme sonrası ilk kontrolde 2 saati çoktan geçmiş bekleyen kayıtlar da bir kez bildirilir; kalabalık projelerde bu tek toplu bildirimdir.

## Nasıl kapatılır?

- Ses: zil → **Ses** anahtarı (kişiye/tarayıcıya özel).
- Hatırlatma penceresi: **Daha sonra** (o gün için). Hatırlatmaların kendisini sunucuda kapatmak 2.3.1'deki gibi `.env` → `HATIRLATMA_KONTROL_DK=0` ve `systemctl restart kanit-web`.
- Masaüstü bildirimi: tarayıcının site ayarlarından.
- Kartlar için ayrı bir kapatma ayarı yoktur; × ile tek tek kapatılır.

## Yeni `.env` anahtarları

Pop-up/ses için yok (tercihler tarayıcıda saklanır). Hatırlatma zamanlaması için isteğe bağlı anahtarlar yukarıdaki tabloda (`HATIRLATMA_SAAT`, `HATIRLATMA_SAAT_TOPLU`, `GUN_SONU_SAAT`, `GUN_SONU_ALICILAR`, `HATIRLATMA_KONTROL_DK`).

## Testler

- Yeni: `tests/test_hatirlatma_233.py` (14 test): 2 saat eşiği ve alıcılar, toplu bildirim kuralı, 18:00 gün sonu özeti ve sayıları, UTC sunucuda İstanbul gün sınırı, `GUN_SONU_ALICILAR`, ayar doğrulama, şema geçişi, CLI `--gun-sonu-zorla`.

- Yeni: `tests/test_bildirim_popup_233.py` (4 test) ve onun çalıştırdığı `tests/bildirim_popup_tarayici.js`.
  - Şablon/statik denetimleri: kart kapsayıcısı ve hatırlatma penceresi yalnız girişli sayfalarda, Ses anahtarı, `panel.js` sözdizimi (`node --check`) ve yeni bildirimlerde tost kullanılmaması, ses kazancı ≤ 0,15, arka plan yoklaması, CSS sınıfları, koyu tema, telefon ve hareket azaltma kuralları.
  - Uçtan uca tarayıcı testi (gerçek waitress sunucusu, geçici veritabanı, Chromium): yeni kanıt kartı 2 sn içinde çıkar ve **Aç** `ac=<kayıt>` bağlantısına gidip okundu sayar; 3 bildirimde tek özet kart ve "Bildirimleri aç"; hatırlatma penceresi, odak tuzağı, üç tonlu zil; **Daha sonra** sonrası yoklamada ve sayfa yenilemede açılmaz, yeni hatırlatma yeniden açar; **Tümünü okundu say** veritabanında okundu yapar ve okunan hatırlatmaların özet kartını da kaldırır; kart düğmelerine zilden sonra birkaç Tab ile ulaşılır; Ses anahtarı yenilemeden sonra korunur ve kapalıyken ses istenmez; sayfa ilk açılışında ses yok, ses yalnız ilk tıklamadan sonra; kayıt penceresi açıkken hatırlatma ertelenir, kapanınca açılır; hatırlatma satırı kayda gider. Node + Playwright olmayan makinede bu test atlanır (üretim sunucusunda test çalıştırılmaz).
- Tüm testler: `python3 -m pytest -q tests --deselect tests/test_paket_manifesti.py` → **499 passed, 2 deselected**.
