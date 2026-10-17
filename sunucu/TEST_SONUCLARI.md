# Kanıt Paneli 2.1 — test sonuçları

17 Ekim 2026 son kaynak koşusu: `python3 -m pytest -q tests` → **84 passed**, 19,71 saniye. Tek uyarı, kötü niyetli/bozuk ZIP kontrolü testinde bilerek oluşturulan yinelenen `content.xml` üyesinden gelir; bu dosya reddi test edilir. Python, JavaScript ve güncelleme Bash sözdizimleri doğrulandı.

## Doğrulanan kapsam

| Alan | Sonuç |
|---|---|
| Bot | İlk giriş, görsel/belge ve yazılı Lead; sıralı eski/yeni sorular; aktif ekranın sohbet altına gelmesi; eski/yanlış callback kurtarma; onay, geri/iptal ve kayıt tekrarının önlenmesi |
| Gyazo | Kalıcı iş kuyruğu, arka plan yükleme, kayıt bağlanmadan bildirim üretmeme, belirsiz sonuç koruması; görsel değişirse linkin uygulanmaması ve yanlış başarı söylememesi |
| Dinamik katalog | Yeni aktif proje seçim/callback/final kaydına kadar işler; proje-kategori üyeliği, sıralı hazır/özel soru ve değişmez eski soru görüntüsü korunur |
| Panel | CSRF, oturum/parola güvenliği, sürüm çatışması, onay/düzenleme/silme/geri alma, görünür onaylayan/geçmiş ve Lead ID/özel cevapların detay/raporda korunması |
| Proje yetkisi | Kart, filtre, kategori, renk, profil, bildirim, görsel ve rapor kapsamı; değiştirilmiş proje/ID/form reddi; eski wildcard’ın gelecekteki projeleri açmaması |
| Bildirim ve konuşma | Kullanıcıya özel geçmiş, okunmuşluk ve yeni proje yetkisi; kayıt içi soru/yanıt/yorum, aktör/tarih ve karşı taraf bildirimi |
| Dosya kontrolü | XLSX, CSV/TSV, ODS, TXT ID/tablo; ayraç/kodlama/sayfa/başlık değişimi, gerçek kimlik eşleştirme, sıfırlar, eksik/boş/belirsiz/çoklu sonuç, kapsam ve indirme yetkisi |
| Eşzamanlı kullanım | Sekiz bağımsız oturum aynı kayıt sürümünü paralel düzenledi: yalnız bir yazma kabul edildi, yedi eski-sürüm isteği 409 ile reddedildi; kayıp güncelleme oluşmadı |
| Özel ayar | Sahte anahtarlarla ayar birleştirme; HTTPS/port/oturum değeri korunması, yinelenen satır temizliği ve açık izinli özel dosyanın reddi |
| Aktarım/arşiv | Önceki Excel aktarımının tekrar güvenliği, boş uzantılar, tahmini sahiplik, ikinci görsel, izinli kök ve belirsiz arşiv eşlemesi regresyonları |

## Gerçek tarayıcı kontrolü

Üretim anahtarı ve verileri kullanılmadan ayrı test paneli açıldı. Yönetim dropdownunda üst `overflow:auto` nedeniyle kırpılma gerçek DOM ölçümüyle doğrulandı; `overflow:visible` düzeltmesinden sonra menüden katalog sayfasına tıklamayla geçildi. Yeni kategori bölümü açıldı; hazır şablon soruları, özel soru ekleme ve yukarı taşıma gerçek istemciyle doğrulandı. Katalog iki sütunlu grid ve proje seçimi flex düzeni ölçüldü. Eski CSS önbelleğini ayırmak için teslim varlıklarına sürüm parametresi eklendi.

Tam sayfa otomatik yenileme kaldırılmıştır. Bildirim/sayaç yoklaması sürer; açık filtre ve yorum/düzenleme taslağı zorla silinmez. Arka plan Gyazo sonucu açık çalışma taslağını yenilemeyle ezmez.

## Dış doğrulamalar ve sınırlamalar

Bu 2.1 revizyonu henüz kullanıcının canlı sunucusuna uygulanmadı. Gerçek verilen Gyazo access token ile bu revizyonda yükleme yapılmadı; sağlayıcı testleri sahte HTTP/Telegram ile çalıştı. Dönüşümün canlı başarısı özel ayar birleştirilip sunucu botunda seçim yapılarak doğrulanacak. Önceki 2.0 gerçek Telegram #4361 kaydı bu yeni arayüzün canlı onayı sayılmaz.

Gerçek 2 GB görsel arşivi geliştirme ortamına verilmedi; tüm gerçek arşivin eşleşme sayısı bilinmiyor. Sekiz oturumluk doğrulama kapasite/yük garantisi değildir. Sunucu kaynakları ve gerçek trafik ayrıca ölçülmelidir.

Güncelleme Plesk/Nginx/Apache veya HTTPS sertifika yenilemesini değiştirmez. Özel anahtarlar, parolalar ve kullanıcı verileri herkese açık kaynak ZIP’inde değildir; özel ayar ayrı teslim edilir. Otomatik IP sertifika yenilemesi kullanıcı isteğiyle hâlâ ertelenmiştir.
