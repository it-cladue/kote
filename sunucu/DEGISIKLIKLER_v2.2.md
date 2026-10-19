# Kanıt Paneli 2.2 — değişiklik raporu

Bu sürüm kullanım kolaylığı ve modern görünüm güncellemesidir. Veritabanı yapısı yalnız eklemeli geçişle değişir; mevcut kayıtlar, kullanıcılar, katalog ve görseller korunur. Bağımlılık listesi (`requirements.txt`) değişmemiştir; `deploy/apply-update.sh` ile 2.1 üzerine doğrudan uygulanır.

## Görünüm ve gezinme

- Yeni görsel sistem: sakin palet, koyu üst menü, 15 px temel yazı, tutarlı 8 px aralık ölçeği, hafif gölgeli kartlar, zebra/sabit başlıklı tablolar, belirgin birincil/ikincil/tehlike düğmeleri ve odak halkaları. Koyu/açık tema düğmesi korundu.
- Üst menü yeniden düzenlendi: **Ana sayfa, Kayıtlar, Çıktı, Kanıt Kontrolü, Bildirimler, İşlem Geçmişi** ve süperadmin için **Yönetim** açılır menüsü (Proje / Kategoriler, Kullanıcılar, Bot, Arşiv). Çıktı sayfası artık menüde. Açık sayfa menüde vurgulanır.
- Yönetim menüsü tıklamayla açılır, dışarı tıklayınca veya Esc ile kapanır; üst menü tarafından kırpılmaz.
- Telefonda üst menü hamburger düğmesine katlanır; kullanıcı adı, şifre ve çıkış menünün içine taşınır. Tablolar yatay kaydırılır; kenar boşlukları 16 px.
- Kullanıcı alanında ad ve rol (Süperadmin / Admin) görünür. Her sayfanın tarayıcı sekmesi başlığı sayfaya özeldir.

## Ana sayfa

- Karşılama alanı ve hızlı arama (personel kodu, üye ID, Lead ID).
- Özet kutuları: onay bekleyen kayıt, bugün eklenen, bugün onaylanan ve size yöneltilmiş yanıtsız soru sayısı. Her kutu ilgili listeye gider.
- Proje kartlarında bekleyen/onaylı/silinen sayıları ve proje görünen adı; sayılar arka planda güncellenir.
- **Son işlemler** listesi: yetkiniz dahilindeki son 10 hareket (kim, ne yaptı, hangi proje, kayda bağlantı). Süperadmin tüm hareketleri görür.
- Sık kullanılan sayfalara kısayollar.

## Bildirimler

- Zil üzerinde okunmamış sayısı; açılır listede proje rozeti, tür, kişi, zaman, **Kaydı aç** ve tek tek **Okundu** düğmesi, **Tümünü okundu say** ve bildirim sayfasına bağlantı. Liste dışına tıklayınca veya Esc ile kapanır.
- Yeni bildirim geldiğinde küçük bir bildirim balonu gösterilir; tarayıcı izni verilmişse masaüstü bildirimi de çalışır.
- Bildirimler sayfasına proje filtresi, okunmamış sayısı ve "Yeni" etiketi eklendi.

## Projeler ve katalog

- **BETA** projesi (turuncu, `#FFA500`) güncellemeyle birlikte otomatik ve yalnız bir kez eklenir; mevcut aktif kategoriler BETA'ya bağlanır. Daha önce BETA tanımlanmışsa dokunulmaz; sonradan pasife alınır veya yeniden adlandırılırsa seed tekrar çalışmaz. PP/PA/OF/HI/VI/GA korunur.
- Panelin her yerinde (kullanıcı yetki formu, çıktı, filtreler, bot istatistiği, Excel) proje listesi ve renkleri katalogdan okunur; sabit liste kalmadı. Yeni projeyi normal adminlere açmak için Kullanıcılar ekranından yetki verin.

## Kullanıcılar ve şifre

- Kullanıcılar sayfası: solda hesap listesi (rol, proje rozetleri ve işlem kapsamı, aktif/pasif, son giriş), satırda **Düzenle** ile açılan düzenleme alanı, sağda yeni kullanıcı formu. Rol seçimi kart biçiminde; proje başına onay/düzenleme/silme kutuları okunaklı.
- Şifre kuralı **en az 8 karakter** oldu (panel, CLI ve formlardaki ipuçları aynı). Geçici şifre üretme düğmesi düzenleme alanında.
- Sunucu komutları: `admin-ekle` ve `sifre-sifirla` artık `--password-env` ile ortam değişkeninden parola alır; `--kalici` ile parola kalıcı olur (ilk girişte değiştirme zorunluluğu konmaz). Örnek:

```bash
cd /opt/kanit-paneli && KANIT_PW=telecc123 .venv/bin/python -m app.cli sifre-sifirla admin --password-env KANIT_PW --kalici
```

## Hata sayfaları

- 400/403/404/409/413/429 için anlaşılır Türkçe açıklama, **Geri dön** ve ana sayfa bağlantıları.
- Beklenmeyen sunucu hatasında (500) kullanıcıya "Beklenmeyen hata, kayıt no …" gösterilir; tam ayrıntı sunucu günlüğüne yazılır ve İşlem Geçmişi'nde `sunucu_hata` satırı oluşur. Kayıt numarası destek için paylaşılabilir.
- Sayfa içinden fetch ile çağrılan uç noktalar hata sayfası yerine JSON hata mesajı döndürür; böylece düğmelerde "silly" HTML hataları yerine okunur mesaj çıkar.

## Diğer sayfalar

- Bildirimler, İşlem Geçmişi, Arşiv, Bot, Telegram kullanıcı durumu, ekleyen profili, Kanıt Kontrolü (adım numaralı 1-2-3-4 akış), Çıktı, Katalog, Kullanıcılar, Giriş ve Şifre ekranları aynı başlık düzenine (etiket + başlık + kısa açıklama + eylemler), aynı kart/tablo/düğme diline getirildi. Giriş sayfası ortalanmış kart ve "Kanıt Paneli" logosu ile yeniden düzenlendi.
- İşlem Geçmişi'nde işlem adları Türkçe açıklamalı, sonuç durum etiketli, kayıt hedefleri tıklanabilir.
- Durum etiketleri (Onaylı / Bekliyor / Silinen / Aktif / Pasif) tüm sayfalarda aynı.

## Kayıtlar sayfası ve kanıt görseli

- **Detay penceresi artık hata vermiyor.** Eski Excel kaydı, görseli olmayan lead kaydı, silinmiş kayıt, dosyası sunucuda bulunmayan görsel, bozuk görsel, ikinci görseli olmayan kayıt: hepsi sorunsuz açılır; sorun olursa anlaşılır Türkçe uyarı çıkar, "Kayıt okunamadı (500)" gibi ham kodlar yok.
- **Proje seçimi:** "Tüm yetkili projeler" kutusu kaldırıldı. Projeler katalogdaki renkleriyle çip olarak görünür; **Tümü** çipi var. Hiç çip seçilmemişse tüm yetkili projeler listelenir; çipe tıklayınca filtre anında uygulanır, kategori listesi seçilen projelere göre gelir. Filtre çubuğu sayfa kaydırılınca üstte sabit kalır. Kategori filtresi küçük/karışık harfli kategori adlarında da seçimi korur.
- **Satıra veya karta tıklamak detayı açar.** Klavyede ← → ile kayıtlar arasında gezilir, Esc kapatır; bildirimlerden gelen `?ac=<id>` bağlantıları adres çubuğunda kalır (paylaşılabilir), kapatınca temizlenir.
- **Görsel deneyimi:** detay penceresinde büyük görsel alanı; **Büyüt** veya görsele tıklayınca tam ekran görüntüleyici (+ / − düğmeleri, fare tekerleği ile yakınlaştırma, sürükleyerek kaydırma, telefonda iki parmakla yakınlaştırma, "Yeni sekmede aç", "İndir", ← → ile kayıtlar arasında geçiş). İkinci görsel küçük resim olarak gösterilir. Tablo küçük resimleri büyütüldü; galeri kareleri eşit boyda.
- **Eski Gyazo bağlantıları:** sunucuda yerel dosyası olmayan ama Gyazo linki bulunan kayıtlarda görsel sunucu üzerinden getirilip önbelleğe alınır (yalnız gyazo.com, 15 sn, 20 MB sınırı). Açılamayan linklerde "Görsel yok (eski Gyazo linki açılamadı)" yazısı ve linkin kendisi gösterilir. `.env` içine `GYAZO_PROXY=0` yazılırsa bu özellik kapanır.
- **Bozuk veya eksik görsel:** listelerde boş hücre yerine "Görsel açılamadı" / "Dosya sunucuda bulunamadı" yer tutucusu; ham bozuk dosya tarayıcıya gönderilmez.
- **Detay içeriği:** üstte proje/kategori/durum rozetleri, iki sütunlu bilgi alanı, onay satırı (onaylayan/zaman), eylem düğmeleri (Onayla / Onayı kaldır / Düzenle / Sil — silme nedeni sorulur / Geri al / Gyazo'ya dönüştür), "Konuşma" ve "İşlem geçmişi" açılır bölümler. "İşlem hatası" bayraklı kayıtta hata metni pencerede görünür; silinmiş kayıtta veya yetki yoksa düğmelerin neden olmadığı yazar; kaydedilmemiş düzenleme varsa kapatmadan önce sorulur.
- **Düzenleme:** kategori serbest metin değil, projeye tanımlı kategorilerden seçilir; alan doğrulama mesajları satır içinde. Aynı kayıt bu arada başkası tarafından değiştirilmişse gerçek mesaj ve **Yenile** düğmesi çıkar; girilen değerler kaybolmaz.
- **Gyazo'ya dönüştür:** işin durumu (bekliyor / tekrar denenecek / hata), deneme sayısı ve hata metni pencerede görünür; **Gyazo'yu tekrar dene** düğmesi var. Gyazo anahtarı tanımlı değilse düğmenin altında açıklama yazar.
- **Toplu onay:** tabloda ve kart görünümünde seçim kutuları, "Sayfadakileri seç", **Seçilenleri onayla (n)** / **Onayı kaldır (n)** (yalnız onay yetkisi olanlara); sonuç özeti bildirim olarak görünür. Onayla/Sil sonrası satır durumu ve sekme sayaçları anında güncellenir.
- **Araç çubuğu:** "Excel (bu görünüm)" düğmesi her zaman görünür (boş görünümde pasif); sonuç sayısı; sayfa başına 24 / 48 / 96 seçimi; arama kutusu açıklama, ekleyen ve kategori içinde de arar; ana sayfadan gelen aramada "Arama: …" rozeti ve "Aramayı temizle" bağlantısı. Ters tarih aralığı sayfa içinde uyarı olarak gösterilir.
- **Telefon (390 px):** tablo görünümü yatay kaydırmasız kart listesine dönüşür, Detay düğmesi ve tüm dokunma hedefleri ekran içinde (≥ 40 px), detay penceresi tam ekran ve eylem çubuğu altta sabit. Uzun personel/üye değerleri diğer sütunlara taşmaz.
- **Arşiv:** "Kayıtla ilişkilendir" yanlış kayıt numarasında veya kayıtta zaten görsel varken hata sayfası yerine arşiv sayfasında açıklayıcı mesaj gösterir ("Değiştirmek için 'Varsa mevcut görsel bağını değiştir' kutusunu işaretleyin").
- Olmayan kayıt için 403 "yetkiniz yok" yerine 404 "kayıt bulunamadı"; küçük resim önbellek klasörü silinse bile küçük resimler yeniden üretilir.

## Düzeltmeler (2.2 düzeltme turu — genel)

- **Bot sayfası:** `?sure=` için tanınmayan değer 500 hatası vermez; "Tüm zamanlar" kabul edilip bir not gösterilir. Onayla / Engelle / Tam sıfırla artık üç ayrı küçük kart; her kartın kendi Telegram ID alanı var. Onaylarken ad boş bırakılırsa kişinin Telegram'daki adı korunur, sayısal ID artık ada yazılmaz; girilen ad yalnız görünen ada gider. Bot durumu "Çalışıyor · son sinyal 20 sn önce", "Bot son 12 dakikadır sinyal vermedi" veya "Bot henüz sinyal göndermedi" biçiminde; kırmızı yalnız gerçekten sinyal kesilince.
- **Arşiv taraması:** sonuç ham JSON yerine "Arşiv tarandı: 3 dosya tarandı, 2 dosya indekslendi, 1 görsel kayıtla eşleşti." cümlesiyle gösterilir.
- **Giriş yönlendirmesi:** giriş sonrası dönülen adres sorgu dizesini (durum, proje, filtre) korur; yalnız site içi hedef kabul edilir.
- **Oturum düşmesi:** süperadmin bir hesabın yetkisini/şifresini değiştirince o kullanıcı "Oturumunuz sona erdi; yetkileriniz güncellendi veya şifreniz değişti…" mesajıyla giriş sayfasına gönderilir. Açık pencerede yapılan işlemler 400 (CSRF) yerine JSON 401 "Oturumunuz sona erdi, sayfayı yenileyin." alır; zil yoklaması da bunu yakalayıp kullanıcıyı giriş sayfasına taşır.
- **Çıktı (Excel):** başlangıç > bitiş olan tarih aralığı tam sayfa "Hata 400" yerine formun içinde uyarı olarak gösterilir, form değerleri korunur (tarayıcıda göndermeden önce de kontrol edilir). Seçime uyan kayıt yoksa boş dosya inmez; "Seçime uyan kayıt yok" uyarısı ve istenirse "Yine de boş dosyayı indir" bağlantısı gösterilir. Düğme/alan adları sadeleştirildi ("Excel dosyasını indir", "Onay durumu", "Ekleyen kişi").
- **İşlem Geçmişi:** proje kaydı artık "Kayıt #BETA" değil "Proje: BETA"; kategori kaydı "Kategori: …"; kayıt tablosunda bulunmayan eski hedefler "Kayıt anahtarı: …". Katalog ve bot işlemlerinin Türkçe adları eklendi.
- **/saglik:** sağlık denetimi ve statik dosyalar oturum çerezi üretmez.
- **Bildirim zili:** her öğede "#12 · PERSONEL KATEGORİ · Yeni kanıt eklendi" satırı; listede en çok 15 öğe, fazlası için "N bildirim daha · Tümünü gör" bağlantısı. `bildirim.json` öğelerinde `kayit_id`, `personel`, `kategori` alanları.
- **Kullanıcılar:** üretilen geçici şifre, sayfanın üstünde kopyala düğmeli bir kutuda görünür ve sayfa yenilenene kadar kalır (yalnız bir kez gösterilir). Kullanıcı düzenleme formunun 500 hatası (görünen ad alanının `ad` parametresiyle çakışması) giderildi. Kullanıcı adı / şifre / Telegram ID desen hatalarında tarayıcının İngilizce uyarısı yerine Türkçe açıklama.
- **Kanıt Kontrolü:** TXT okuma notu nötr mavi bilgi kutusu; sayfadaki tüm düğme ve alan metinleri sade Türkçe ("Dosyayı yükle", "Önizlemeyi yenile", "Kayıtlarla karşılaştır", "Yalnız bu projede ara", "Onay durumu", "Tüm sonucu Excel olarak indir").
- **Arama kapsamı:** ana sayfa ve kayıtlar aramasında açıklama, ekleyen adı ve kategori de aranır; ana sayfadaki kutunun altında kapsam ipucu. Çıktı sayfasındaki arama alanı da aynı kapsamı kullanır.
- **Telefon (390 px):** Bot, Bot/kullanıcı, İşlem Geçmişi, Kullanıcılar, Arşiv, Bildirimler, Çıktı ve Kanıt Kontrolü sayfalarında sayfa genişlemesi yok; tablolar kendi sarıcısında kaydırılır, kullanıcı listesi sarmalanır, Bot işlem kartları alt alta dizilir.

## Düzeltmeler (son QA turu)

Genel ekran düzeltmeleri:

- **İşlem Geçmişi:** silme nedeni "Ayrıntı" sütununda "Sebep: …" olarak görünür; onay/silme satırlarında "Önceki: 0 / Yeni: 1" yerine "Onay: bekliyor → onaylı", "Silindi", "Geri alındı" gibi okunur metin. Ters tarih aralığı formun içinde uyarı olarak gösterilir.
- **İşlem adları:** bildirim okuma, Telegram (kanıt ekleme, şifreyle giriş, engelleme, eski/yanlış düğme), bot yönetimi (bakım modu, onay, engel, sıfırlama, yedek…), katalog ve Gyazo işlemleri ana sayfada ve İşlem Geçmişi'nde Türkçe adla yazılır; sözlükte olmayan kod ham haliyle iki kez basılmaz. Kullanıcının kendi "bildirim okundu" hareketleri ana sayfadaki "Son işlemler" akışını doldurmaz.
- **Bildirimler:** başlangıç > bitiş olan tarih aralığı tam sayfa "400" yerine formda satır içi uyarı; seçimler korunur. Uzun personel değerinde telefonda sayfa genişlemez.
- **Tablolar:** Telegram ekleyen profili ve diğer tablolarda uzun personel/üye ID değerleri komşu sütunlara taşmaz (hücre içinde sarılır; tam değer ipucu olarak görünür).
- **Kanıt Kontrolü:** sonuç adımındaki iki indirme düğmesi telefonda alt alta sarılır (≥ 40 px); adım 3 eşleştirme tablosu telefonda satır satır sarmalanır, geniş ekranda yana kaydırma ipucu; "Kontrol zamanı" hem sayfada hem indirilen "Kontrol bilgisi" sayfasında yerel saatle "gg.aa.yyyy ss:dd" biçiminde.
- **Oturum düşmesi (iki sekme):** yetki/şifre değişince düşme bilgisi yeni giriş yapılana kadar korunur; her sekme "Oturumunuz sona erdi; yetkileriniz güncellendi veya şifreniz değişti…" açıklamasını görür. Oturumu olmayan her gönderim CSRF kontrolünden önce JSON 401 "Oturumunuz sona erdi, sayfayı yenileyin." (XHR) ya da açıklamalı giriş sayfası (form) alır; panel eski sekmedeki "Geçersiz CSRF" 400'ünde de giriş sayfasına yönlendirir ve giriş sonrası aynı sayfaya döner.
- **Proje / Kategoriler:** proje kodu, kategori kodu ve soru anahtarı alanlarında tarayıcının İngilizce uyarısı yerine Türkçe açıklama ("Proje kodu yalnız BÜYÜK harf, rakam ve alt çizgi (en çok 24).").
- **Kullanıcılar:** kapsam özeti ve rozet ipucu "HI: Onay, Düzenleme, Silme" biçiminde Türkçe ve sabit sırada; "Süperadmin" etiketi tek satır, "tüm projeler" altında. Ana sayfada "Proje bazında iş yükü" başlığı telefonda notun üstünde tam genişlikte.
- **Telefon dokunma hedefleri:** menü altındaki Şifre / Çıkış / Koyu tema, zil listesindeki "Kaydı aç" / "Okundu", Çıktı proje çipleri, Kanıt Kontrolü indirme düğmeleri ve Arşiv "Kayıtla ilişkilendir" ≥ 40 px.
- **Hamburger menü:** yönetim sayfasındayken menü açılınca "Yönetim" alt listesi açık ve aktif sayfa vurgulu gelir; hamburger dokunuşu alt menüyü kapatmaz.
- Statik dosya sürüm etiketi `v=2.2.3` (eski görünüm kalırsa Ctrl+F5).

Kayıtlar sayfası düzeltmeleri (K1–K8):

- **K1 – Toplu onay araç çubuğu:** "Yenile" / "Sonuçları yenile" sonrasında seçim yapılınca çubuk yeniden görünür ve toplu onay çalışır; yenileme sonrası seçim sıfırlanır.
- **K2 – Kayıt penceresi "İşlem geçmişi":** silme sebebi "Silindi · admin · Sebep: …" olarak görünür; onay satırları "Onaylandı" / "Onay kaldırıldı".
- **K3 – Kayıp görsel dosyası:** dosyası sunucuda bulunmayan kayıt, hiç görseli olmayan kayıttan ayrılır: pencerede turuncu "Görsel dosyası sunucuda bulunamadı… Arşiv'den yeniden ilişkilendirebilirsiniz." uyarısı; listede/kartta "Dosya yok" işareti.
- **K4 – "Sonuçları yenile" şeridi:** kullanıcının kendi onay/silme/toplu işleminden sonra gereksiz yere çıkmaz.
- **K5 – Boş yorum:** "Gönder ve bildir" boş kutuyla basılınca Türkçe "Göndermeden önce bir yorum yazın." uyarısı.
- **K6 – Doğrudan açılan adresler:** /gorsel, /kucuk, /kayit adresleri tarayıcıda açılınca ham JSON yerine Türkçe hata sayfası; JSON yanıtlarında Türkçe karakterler okunur.
- **K7 – Yetkisiz / olmayan kayıt bağlantısı:** `?ac=` ile açılınca pencere yarım kalmaz: "Kayıt açılamadı" başlığı, yalnız açıklama ve Kapat; proje kodu biliniyorsa söylenir.
- **K8 – Telefon:** Kayıtlar filtre alanları (Kategori, Ara) ve Düzenle formundaki seçim/giriş alanları ≥ 40 px.

Veri ve sunucu tarafı (son tur):

- **Çıktı sayımı:** "kaç kayıt indirilecek" ön kontrolü artık satırları çekmeden sayar; birkaç kullanıcı aynı anda Excel alırken yavaşlama kalktı.
- **Proje çipleri:** veritabanına elle girilmiş küçük harfli/bilinmeyen proje kodları ayrı bir çip olarak görünmez; büyük harfe çevrilip tekilleştirilir.
- **Sunucu komutları (`app.cli`):** yardım ve hata metinleri Türkçe ("bilinmeyen komut", "eksik değer"); her komutun açıklaması var; terminal olmadan (betik/boru içinden) parola istenirse ham Python hatası yerine `--password-env` kullanmanız söylenir.
- Paket manifesti `DOSYA_DOGRULAMA.sha256` 2.2 dosyalarıyla yeniden üretildi (`sha256sum -c DOSYA_DOGRULAMA.sha256` ile doğrulanabilir); ZIP içinde `__pycache__` / `.pytest_cache` yok.

- **Alan adı kurulumu:** yeni `deploy/setup-domain-https.sh` betiği; Plesk ekranı kullanılmadan, mevcut siteye dokunmadan panel alan adını Plesk nginx'ine ekler, Let's Encrypt sertifikası alır ve IP + alan adı sertifikaları için otomatik yenileme zamanlayıcısı kurar (README 1a).

## Güncelleme notu

Sürüm `2.2.0`. `bash deploy/apply-update.sh --dry-run` sonra `bash deploy/apply-update.sh`. Betik başlığı 2.1 → 2.2 olarak güncellendi; mantığı değişmedi. Tarayıcıda eski CSS/JS önbelleğini atlatmak için varlık bağlantıları `v=2.2.3` ile sürümlenir. Tema varsayılanı artık cihazın açık/koyu tercihine uyar (tercih yoksa açık tema); daha önce seçilmiş tema tarayıcıda korunur.
