# Süperadmin yönetim karşılıkları

Panelde `admin` yetkisi süper admindir. Takım admini (`OF`, `OF:oku,kt` gibi) kendi kanıtlarını kontrol eder/onaylar/yorumlar; bot ve hesap yönetimine giremez. Yeni kanıt yalnız Telegram’dan eklenir. Şifre ve token panelde gösterilmez.

| Eski Telegram komutu | Site karşılığı |
|---|---|
| `/durum` | Bot yönetimi üst durum şeridi; heartbeat, bakım ve duraklatma |
| `/istatistik`, `/kayit_raporu` | Bot yönetimi → İstatistik ve kayıt raporu; proje sayıları ve en çok ekleyenler |
| `/son_kullanicilar`, `/kullanici_ara`, `/engelliler` | Telegram kullanıcıları → ID/ad araması, son 1/2/24 saat, 7/30 gün ve durum filtreleri |
| `/kullanici_durum` | Kullanıcı ID bağlantısı → onay, engel, deneme ve açık oturum detayı |
| `/engelle`, `/engel_kaldir` | Kullanıcı formu / Engeli kaldır; mevcut onay korunur |
| `/engel_kaldir_sifirla` | Tam sıfırla; onay, engel, deneme ve oturum temizlenir |
| `/onayli_sil` | Onayı kaldır; yeniden parola gerekir |
| `/oturumlar`, `/oturum_temizle` | Açık oturum listesi; kullanıcı veya tüm oturumları temizle |
| `/kategori_liste`, `/kategori_bilgi`, `/kategori_akislari` | Kategori akışları tablosu ve sorulan alan açıklaması |
| `/kategori_ekle`, `/kategori_sil`, `/kategori_yayinla` | Kategori ekle/düzenle/kaldır/yayınla; yeni seçimlere anında yansır |
| `/yedekle` | SQLite yedeği al; medya ayrıca yedeklenmeli |
| `/bakim_ac`, `/bakim_kapat` | Bakım aç/kapat |
| `/son_hatalar` | Hatalar ve başarısız güncellemeler; düzelince tekrar dene |
| `/kapat` | Botu güvenli duraklat; süreç/sunucu çalışsa da mesaj işlemez. Site üzerinden Sürdür ile açılır |
| `/admin_cikis` | Web hesabından Çıkış; Telegram admin oturumu ayrı kalır |
| `/excel_mod`, `/excel_son_satir` | Emekli: canlı Excel yok. Veritabanı kayıt sayıları ve ayrı Excel Kontrol ekranı kullanılır |

Telegram’da `/yardim_admin` yeni komut listesini gösterir. Bot duraklatılmışken Telegram’dan devam komutu alınamaz; site üzerinden Sürdür seçilmelidir. İşlemler denetim kaydına yazılır. Ağ hataları ve kalıcı gelen/giden kuyruk, kanıt kayıtlarını çoğaltmadan yeniden denemeyi destekler.

## Excel Check

Excel Kontrol’den XLSX yükle, çalışma sayfasını seç, alanları Excel sütunlarına bağla ve karşılaştırılacak kutuları işaretle. Örneğin Proje + Kategori + Personel + Üye ID. En az bir kimlik alanı gerekir. İstersen projeyi ve KT durumunu sabitle. Kriterlerin tümü aynı kayıtta tutmalıdır; benzer metin tahmini yapılmaz.

Sonuçta bulundu, yok, birden çok eşleşme ve eksik alan/erişim kapsamı sayıları gösterilir. Bulunanların kalıcı sistem ID’leri (`#123`) kayıt detayına götürür. Çoklu eşleşmeler tek bir kanıt seçilmiş gibi sunulmaz. Boş/formül sonucu olmayan değerler kesin eksik kanıt sayılmaz. Yetkisiz projede kanıt olup olmadığı açıklanmaz.

Tam rapor veya yalnız **yok** olanlar indirilebilir. Bu yükleme kayıt eklemez; Excel sadece karşılaştırma girdisidir. Başlık 1. satırdır, XLSX en fazla 12 MB HTTP yüklemesi/128 MB açılmış içerik ve 20.000 ilgili satırla sınırlıdır. Baştaki sıfır önemliyse hücreyi Excel’de metin olarak tut; sayı hücresinden kaybolmuş sıfırlar tahminle geri eklenmez.

## Kayıt biçimi, Gyazo ve tema

Görsel sonrası bot kayıt biçimini sorar. Doğrudan görsel seçimi Gyazo'ya istek göndermez. Gyazo seçimi görüntüyü dış servise yükler ve bağlantıyı bilenlerin görmesini sağlayabilir; bunu kullanıcıya açıkça anlatır. Dönüşüm başarısızsa yerel dosya her durumda korunur. Sitede de mevcut kayıtta KT/görsel yetkisi olan admin için isteğe bağlı dönüşüm düğmesi bulunur; yeni kanıt eklenmez. Elinde görüntü dosyası yokken yalnız bozuk linkten 'görsel kaydedildi' sonucu çıkarılmaz.

Telegram tema düğmesi veya `/tema` renkli/sade tercihini kullanıcı bazında saklar. Telegram'ın native buton renkleri mavi/yeşil/kırmızıyla sınırlıdır; diğer proje renkleri işaretlerle ayrılır. Site koyu modu varsayılandır, sağ üstteki açık/koyu tema düğmesi tarayıcıda saklanır. Eski global onaylı listesi yeni bot kimliğinde ilk parola girişini atlamaz; her fotoğrafta yeniden değil, bu bota ilk güvenli girişte şifre gerekir.
