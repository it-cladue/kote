# Kanıt Paneli 2.1 — düzeltme raporu

## Telegram ve Gyazo

“Gyazo linkine dönüştürülüyor” ara metni kaldırıldı. Dönüşüm kalıcı arka plan işi oldu; proje/kategori/soru cevapları ağ çağrısını beklemiyor ve sonuç onaydan sonra veriliyor. Aktif seçim yeni mesajla sohbetin altına geliyor, eski ekranın düğmeleri kaldırılıyor. Geri/iptal ve eski buton kurtarma korundu. Yanlış “Görünüm” menüsü kaldırıldı; Telegram’ın gerçek desteklediği native buton stilleri uygulanıyor.

Gyazo sonucu kayda gerçekten uygulanmadan başarı denmiyor. İş sırasında yerel görsel değişirse eski bağlantı yeni kanıta yazılmıyor. Kayıt bağlanmadan biten dönüşüm terminal bildirimi üretmiyor. Ağ/anahtar/erişim/belirsiz sonuçta yerel kanıt korunuyor. Gerçek Gyazo hesabının çalışması henüz canlı test edilmedi; bunun yerine sahte sağlayıcı testleri geçti.

## Yetki ve hesaplar

Normal admin yalnız süperadminin açıkça verdiği projeleri görüyor. Diğer projeler kart/filtre/renk/kategori/sayaç/profil/bildirim/görsel/rapor/API bağlamından çıkarıldı; URL/form oynama da reddediliyor. Yeni normal hesap varsayılan süperadmin olmuyor. Gelecekte eklenecek projeleri otomatik açan wildcard kaldırıldı; eski proje wildcard’ı mevcut açık listeye dönüştürülüyor. Son süperadmin ve eski form yarış korumaları sürüyor.

## Sade panel ve çalışan yönetim

Kayıt çalışma alanı, durum sekmeleri, bağlı proje/kategori filtreleri ve gelişmiş alanlar düzenlendi. Yönetim dropdownunun üst menüde kırpılması gerçek tarayıcıyla bulunup giderildi. Proje/kategori ekranı uzun açık formlar yerine kısa, katlanabilir listeler ve açık ekleme bölümleriyle yeniden düzenlendi. Eski CSS/JS önbelleğini ayırmak için sürümlü varlık bağlantısı eklendi.

Yalnız süperadmin proje kodu/adı/renk, kategori-proje bağları ve sıralı hazır/özel soru yönetiyor. Yeni aktif proje Telegram akışının tamamında destekleniyor. Her kayıt kendi sorusunu ve cevabını saklıyor; kategori değişikliği eski kaydı ezmiyor. Özel cevaplar ve Lead ID detay/düzenleme/rapora bağlandı.

## Bildirim, log ve eşzamanlı çalışma

Ayrı Bildirimler sayfası geçmiş, okunmuş/okunmamış ve tür/tarih/proje filtrelerini sunuyor. Okundu ve erişim kullanıcıya özel. İşlem Geçmişi aktör, zaman, hedef ve eylemi düzenli gösteriyor; token/parola/hash/ham giriş mesajı logda açılmıyor. Kayıt içi soru/yanıt, onaylayan ve ekleyen profili korundu.

Otomatik tam sayfa yenileme yok. Zil/sayaç arka planda güncellenir; yeni kayıt uyarısında sonuçlar kullanıcı kontrollü yenilenir. Açık yorum/filtre/düzenleme taslağı korunur. Sekiz bağımsız paralel oturum testinde bir yazma kabul edildi, yedi eski sürüm reddedildi; veri sessizce ezilmedi.

## Genel dosya kontrolü

XLSX yanında CSV/TSV, ODS ve TXT destekleniyor. TXT satır başına tek ID veya ayraçlı tablo; kodlama/ayraç/sayfa/başlık/sütun seçimleri önizlemeye bağlı. Bulundu/yok/çoklu/boş/belirsiz/kapsam dışı sonuçlar ayrılıyor; yalnız kesin yoklar eksik raporuna giriyor. Başta sıfırlar ve formül/basamak kaybı dikkate alınıyor. Rapor indirilirken güncel proje yetkisi yeniden uygulanıyor. Bu ekran kanıt eklemiyor.

## Güncelleme ve son verdiğin bilgiler

`deploy/apply-update.sh` önce dry-run, sonra kaynak/SQLite yedekli uygulama güncellemesi yapıyor. `.env`, veriler/görseller, oturum anahtarı, Plesk ve ayrı HTTPS korunuyor. Yalnız önceden aktif uygulama servisleri yeniden başlıyor; paket pip/apt veya sertifika otomasyonu kurmuyor.

Son verdiğin Telegram/Gyazo anahtarı, bot/admin parolası ve yönetici ID’si **KanitPaneli_Ozel_Sunucu_Ayarlari.env** özel dosyasına eklendi; herkese açık kod ZIP’ine konmadı. `apply-private-settings.py` bu yedi alanı mevcut `.env` ile birleştiriyor; HTTPS/port/veri yolu veya web admin parolası değişmiyor. Dosya yalnız özel transferle taşınmalıdır.

Gönderdiğin JSON yeni servisin okuduğu dosya değildir; yeni servis `.env` kullanır. `GYAZO_BAKIM=1` verdiğin haliyle tutuldu, ancak incelediğimiz kaynaklar bu alanı kullanmıyor; dönüşümü kapattığının kanıtı değildir.

**Son otomatik sonuç: 84 test geçti.** Yeni sürümün canlı sunucuna uygulanması, gerçek Gyazo dönüşümü ve verilmemiş 2 GB arşivin tamamı henüz doğrulanmış sayılmaz.
