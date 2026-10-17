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

## Güncelleme notu

Sürüm `2.2.0`. `bash deploy/apply-update.sh --dry-run` sonra `bash deploy/apply-update.sh`. Betik başlığı 2.1 → 2.2 olarak güncellendi; mantığı değişmedi. Tarayıcıda eski CSS/JS önbelleğini atlatmak için varlık bağlantıları `v=2.2.0` ile sürümlenir.
