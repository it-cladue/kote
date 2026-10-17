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

## Güncelleme notu

Sürüm `2.2.0`. `bash deploy/apply-update.sh --dry-run` sonra `bash deploy/apply-update.sh`. Betik başlığı 2.1 → 2.2 olarak güncellendi; mantığı değişmedi. Tarayıcıda eski CSS/JS önbelleğini atlatmak için varlık bağlantıları `v=2.2.0` ile sürümlenir.
