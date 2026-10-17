# Kanıt Paneli 2.2 — test sonuçları

17 Ekim 2026 kaynak koşusu: `python3 -m pytest -q tests` → **94 passed**, yaklaşık 25 saniye (2.1'deki 84 teste 2.2 için 10 yeni test eklendi: `tests/test_genel_v22.py`). Tek uyarı, kötü niyetli/bozuk ZIP kontrolü testinde bilerek oluşturulan yinelenen `content.xml` üyesinden gelir; bu dosyanın reddi test edilir. Python (`ast`), JavaScript (`node --check`) ve güncelleme Bash (`bash -n`) sözdizimleri doğrulandı.

## 2.2 ile eklenen doğrulamalar

| Alan | Sonuç |
|---|---|
| Menü ve sürüm | Süperadmin menüsünde Ana sayfa / Kayıtlar / Çıktı / Kanıt Kontrolü / Bildirimler / İşlem Geçmişi / Yönetim bağlantıları; normal adminde yönetim bağlantılarının bulunmaması; sayfa başlıkları, `aria-current`, hamburger ve zil kutusu, `v=2.2.0` varlık sürümü, `/saglik` başlığı `2.2.0` |
| BETA projesi | Yeni kurulumda ve BETA'sız 2.1 veritabanında bir kez eklenir (renk `#FFA500`, aktif, aktif kategoriler bağlı); admin pasife alır/yeniden adlandırırsa sonraki bağlantılar geri getirmez; mevcut proje satırları değişmez; kullanıcı formu, çıktı ve bot istatistiğinde katalogdan görünür |
| Şifre kuralı | 7 karakter reddi, 8 karakter kabulü (hesap ekleme, güncelleme, `/sifre`, yönetim formu); `minlength="8"` ipuçları |
| CLI | `admin-ekle --password-env`, `sifre-sifirla --password-env` (ilk girişte değişim) ve `--kalici` (kalıcı parola, hesap aktif); kısa parola ve boş ortam değişkeni hataları |
| Hata sayfaları | 404'te başlık, açıklama ve **Geri dön**; tarayıcı isteğinde HTML, `fetch` isteğinde JSON (`ok:false, hata`); CSRF hatasının özel metni; 500'de "Beklenmeyen hata, kayıt no …", ham hata metninin kullanıcıya sızmaması, `sunucu_hata` denetim satırı ve JSON karşılığı |
| Ana sayfa | KPI sayıları (bekleyen, bugün eklenen, bugün onaylanan, açık soru) ve **Son işlemler** listesi yalnız yetkili projeleri kapsar; yetkisiz projenin kodu, kişisi veya kaydı HTML'de yer almaz; süperadmin tüm hareketleri görür; yanıtlanan soru sayaçtan düşer |
| Diğer sayfalar | Bildirimler, İşlem Geçmişi, Arşiv, Bot, Telegram kullanıcı durumu, ekleyen profili, Kanıt Kontrolü, Çıktı, Katalog, Kullanıcılar ve Şifre sayfaları 200 döner; sayfaya özel `<title>`, üst etiket + `h1` düzeni; satır içi `onclick` yok; giriş sayfası yeni kart düzeni |

2.1 kapsamı (bot, Gyazo, katalog, yetki, bildirim/konuşma, dosya kontrolü, eşzamanlı sürüm çatışması, özel ayar, aktarım/arşiv) değişmeden geçmektedir; `test_katalog` içindeki aktif proje sayısı BETA nedeniyle 6 → 7 olarak güncellendi.

## Gerçek tarayıcı kontrolü (Playwright / Chromium)

Geçici SQLite, örnek kayıtlar ve üç hesapla panel `waitress` üzerinde başlatıldı; masaüstü (1366×900) ve telefon (390×844) görünümlerinde açık ve koyu tema için giriş, ana sayfa, kayıtlar, çıktı, kanıt kontrolü, bildirimler, işlem geçmişi, katalog, kullanıcılar, bot, arşiv, şifre, 404 ve ekleyen profili sayfalarının ekran görüntüleri alındı. Yönetim açılır menüsünün tıklamayla açılıp ekran dışına taşmadığı ve Esc ile kapandığı, zil kutusunun açıldığı, telefonda hamburger menünün yönetim bağlantılarını gösterdiği ve kayıt ayrıntı penceresinin açıldığı gerçek DOM ölçümüyle doğrulandı. Telefonda yatay sayfa kaydırması yok. Konsolda yalnız bilerek açılan 404 sayfasının kendi "404" kaynağı görüldü; başka JavaScript hatası veya başarısız istek yok.

## Dış doğrulamalar ve sınırlamalar

Bu 2.2 paketi henüz kullanıcının canlı sunucusuna uygulanmadı; `deploy/apply-update.sh` mantığı 2.1 ile aynıdır (yalnız başlık metni güncellendi). Gerçek Gyazo erişimi, gerçek Telegram botu ve 2 GB görsel arşivi geliştirme ortamında yoktur; ilgili testler sahte sağlayıcılarla çalışır. Tarayıcı kontrolü örnek veriyle yapıldı; canlı kurulumda eski CSS önbelleği için Ctrl+F5 gerekebilir (varlıklar `v=2.2.0` ile sürümlenmiştir).
