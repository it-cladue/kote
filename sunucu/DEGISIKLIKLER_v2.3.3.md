# Kanıt Paneli 2.3.3 — bildirimler artık pop-up ve sesli (26 Kasım 2026)

2.3.2 üzerine `deploy/apply-update.sh` ile uygulanır (sunucuda depodan taze kopya + güncelleme, KURULUM §13). Yalnız panel ekranı (şablon, `panel.js`, `stil.css`) değişir; veritabanı, bot, ayarlar ve `.env` aynı kalır. Tarayıcı yeni dosyaları kendiliğinden alır (sürüm numaralı adresler), Ctrl+F5 gerekmez.

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
- Ne zaman açılır: (a) panel sayfası açıldığında okunmamış hatırlatma varsa (tarayıcı kuralı gereği sayfa açılışında henüz tıklama olmadığı için bu açılış sessizdir); (b) panel açıkken yeni hatırlatma gelince (hatırlatma sesiyle birlikte).
- Alt düğmeler:
  - **Daha sonra**: pencereyi kapatır ve **o gün** aynı hatırlatmalar için yeniden açmaz (sayfa yenilense de). Gün içinde **yeni** bir hatırlatma gelirse yine açılır. Ertesi gün okunmamış hatırlatma kaldıysa yeniden açılır. Seçim o tarayıcıda, kişiye göre saklanır.
  - **Tümünü okundu say**: listedeki hatırlatmaları okundu sayar ve pencereyi kapatır (kayıtların onay durumu değişmez).
  - **Kapat** (ya da Esc): yalnız bu sayfada kapatır; başka bir sayfaya geçince okunmamış hatırlatma varsa yeniden açılır.
  - **Tüm hatırlatmalar**: Bildirimler sayfasını okunmamış hatırlatmalar süzgeciyle açar.
- Kayıt ayrıntı penceresi ya da görsel büyütme açıkken veya kullanıcı bir alana (arama kutusu, yorum, düzenleme) yazarken pencere **açılmaz**; kayıt penceresi kapanınca ya da yazma alanından çıkıldıktan sonraki yoklamada (en geç 10 sn) açılır. Yazı yazan kişinin imleci alınmaz.
- Klavye: pencere açılınca odak ilk "Aç" düğmesine gelir, Tab pencere içinde döner, Esc kapatır ve odak önceki yere döner.

### Arka plandaki sekme

- Panel sekmesi arka plandayken de bildirimler kontrol edilir (10 sn yerine 30 sn'de bir). Yeni bildirim gelince ses (izin varsa) ve masaüstü bildirimi hemen çıkar; kartlar ve hatırlatma penceresi sekmeye dönünce gösterilir (kaybolmaz).

### Masaüstü bildirimleri

- Zil listesinin üst satırındaki **Masaüstü bildirimlerini aç** düğmesine basıp tarayıcının sorusuna "İzin ver" deyin. Düğme, izin sorusu yanıtlanmadıkça (pencere kapatılsa da) görünür kalır; "Engelle" denirse tarayıcının site ayarlarından (adres çubuğundaki kilit simgesi → Bildirimler) açılabilir.
- Masaüstü bildirimine tıklanınca panel sekmesi öne gelir ve bildirimin kaydı açılır (bildirim okundu sayılır); toplu bildirimde okunmamış bildirimler sayfası açılır.
- Masaüstü bildirimi yalnız panel bir sekmede açıkken çalışır (site kapalıyken bildirim gönderilmez; bu değişmedi).

## Nasıl kapatılır?

- Ses: zil → **Ses** anahtarı (kişiye/tarayıcıya özel).
- Hatırlatma penceresi: **Daha sonra** (o gün için). Hatırlatmaların kendisini sunucuda kapatmak 2.3.1'deki gibi `.env` → `HATIRLATMA_KONTROL_DK=0` ve `systemctl restart kanit-web`.
- Masaüstü bildirimi: tarayıcının site ayarlarından.
- Kartlar için ayrı bir kapatma ayarı yoktur; × ile tek tek kapatılır.

## Yeni `.env` anahtarı

Yok. Tüm tercihler tarayıcıda saklanır.

## Testler

- Yeni: `tests/test_bildirim_popup_233.py` (4 test) ve onun çalıştırdığı `tests/bildirim_popup_tarayici.js`.
  - Şablon/statik denetimleri: kart kapsayıcısı ve hatırlatma penceresi yalnız girişli sayfalarda, Ses anahtarı, `panel.js` sözdizimi (`node --check`) ve yeni bildirimlerde tost kullanılmaması, ses kazancı ≤ 0,15, arka plan yoklaması, CSS sınıfları, koyu tema, telefon ve hareket azaltma kuralları.
  - Uçtan uca tarayıcı testi (gerçek waitress sunucusu, geçici veritabanı, Chromium): yeni kanıt kartı 2 sn içinde çıkar ve **Aç** `ac=<kayıt>` bağlantısına gidip okundu sayar; 3 bildirimde tek özet kart ve "Bildirimleri aç"; hatırlatma penceresi, odak tuzağı, üç tonlu zil; **Daha sonra** sonrası yoklamada ve sayfa yenilemede açılmaz, yeni hatırlatma yeniden açar; **Tümünü okundu say** veritabanında okundu yapar ve okunan hatırlatmaların özet kartını da kaldırır; kart düğmelerine zilden sonra birkaç Tab ile ulaşılır; Ses anahtarı yenilemeden sonra korunur ve kapalıyken ses istenmez; sayfa ilk açılışında ses yok, ses yalnız ilk tıklamadan sonra; kayıt penceresi açıkken hatırlatma ertelenir, kapanınca açılır; hatırlatma satırı kayda gider. Node + Playwright olmayan makinede bu test atlanır (üretim sunucusunda test çalıştırılmaz).
- Tüm testler: `python3 -m pytest -q tests --deselect tests/test_paket_manifesti.py` → **499 passed, 2 deselected**.
