# Kanıt Paneli 2.3.1 — bildirim ve onay görünürlüğü (24 Kasım 2026)

2.3.0 kurulumunun üzerine `deploy/apply-update.sh` ile uygulanır; veritabanı yapısı değişmez, mevcut kayıtlar, kullanıcılar ve ayarlar korunur. Yalnız `kanit-web` yeniden başlar; bot etkilenmez.

## Hatırlatma bildirimleri

- Onay bekleyen bir kayıt **3 günü** geçince (`HATIRLATMA_GUN`) o projede onay yetkisi olan herkese "Bu ID'nin kontrolü N gündür bekliyor." bildirimi düşer; onaylanmadıkça aynı kayıt için **3 günde bir** (`HATIRLATMA_TEKRAR_GUN`) yinelenir.
- Kullanıcı başına **günde en çok 50** kayıt hatırlatması (`HATIRLATMA_GUNLUK_SINIR`); fazlası o günün proje özetine katlanır ve sonraki günlerde sırayla (en uzun süredir hatırlatılmamış önce) bildirilir. Sık kontrol gün içinde yeni bildirim üretmez.
- Eski Excel'den aktarılan onaysız kayıtlar (gerçek veride 300) kişi başına yüzlerce bildirim üretmez: proje başına tek özet gelir ("GA: 126 kayıt 3 günden uzun süredir onay bekliyor (eski Excel'den)."); özetteki sayı, tıklayınca açılan listeyle aynıdır.
- Onaylanan ya da silinen kaydın eski hatırlatması zilden düşer ve okundu sayılır.
- Üretim web sürecinde 30 dakikada bir yapılır (`HATIRLATMA_KONTROL_DK`; 0 = kapalı, en çok 7 gün); anında üretmek için `python -m app.cli hatirlatma-uret` (`--tarih` yalnız bugün ya da geçmiş bir gün olabilir).
- Ana sayfadaki proje kartlarında "3 gündür bekleyen: X" sayacı; Kayıtlar → Gelişmiş filtrelerde "En az … gündür bekleyen".

## Onaysız kayıtların raporlama ekibine görünümü

`ONAYSIZ_GORUNUM` ayarı, projede **onay yetkisi olmayan** kullanıcılar için geçerlidir (takım liderleri her şeyi görür):

- `uyar` (varsayılan): listede ve kartlarda kırmızı "ONAY YOK — raporlamada kullanmayın" rozeti; kayıt ayrıntısının üstünde kırmızı şerit; arama yalnız onaysız kayıt döndürüyorsa listenin üstünde uyarı kutusu; Excel çıktısında "Takım lideri onayı" sütunu (Onaylı / YOK / Silindi; eski 0/1 değerli `KT` sütununun yerine, KT'ye bağlı formüller bu sütuna göre güncellenmeli) ve dosya adında onaysız sayısı; uyarı kutusu yalnız aramanın hiçbir sekmede onaylı sonucu yoksa çıkar, onaylısı başka sekmedeyse bağlantılı bilgi notu verilir.
- `gizle`: onaysız ve silinmiş kayıtlar liste, arama, ayrıntı (403 "Bu kaydın onayı yok; yalnız onaylı kayıtlar gösterilir."), ekleyen profili, Kanıt Kontrolü, çıktı, İşlem Geçmişi, ana sayfadaki "Son işlemler" ve sayaçlar, bildirim akışı ve kategori listesinde hiç görünmez; durum sekmelerinde yalnız Onaylı kalır ve "Onay bekleyen kayıtlar size gösterilmez" notu çıkar.
- Çıktı sayfasındaki onay durumu seçenekleri: **Hepsi / Onaylılar / Onaysızlar (onay bekleyen) / Silinenler**.

## Bildirime tıklayınca doğrudan hedefe gitme

- Zil listesi ve Bildirimler sayfasındaki her satır tıklanınca ilgili kayıt doğrudan açılır (yeni kanıt, onay, hatırlatma).
- Yorum, soru ve yanıt bildirimlerinde kayıt açılır, Konuşma bölümü genişler, ilgili yorum satırına kaydırılır ve 3 saniye vurgulanır.
- Hatırlatma özeti projenin "bekleyen, 3 günden eski" listesini açar. Telefonda da aynı şekilde çalışır; okundu işaretleme korunur.

## Ekleyen profili özeti

- Telegram ekleyen profilinde tarih aralığı (Son 7 gün / Son 30 gün / Bu ay / Tümü kısayolları ya da elle) ve seçili aralık için "Bu aralıkta ne eklemiş?" özeti: Toplam / Onaylı / Bekleyen / Silinen; kategori × tip (Sessiz / Telesekreter / Diğer) çapraz tablosu, birden fazla projede proje alt toplamları; "Bu görünümü Excel'e aktar" bağlantısı Çıktı formunu aynı koşullarla (ekleyen, tarih, proje, durum) doldurur. Onay yetkisi olmayan kullanıcı `gizle` modundaysa özet de yalnız onaylıları sayar. "Bu kişi bu ay kaç CVPS, kaç sessiz ekledi?" sorusu tek bakışta cevaplanır.

## Gyazo kopyalama: gece planı ve görünür ilerleme

- `gyazo-onbellekle` artık başta Gyazo'ya tek bir deneme isteği atar; ulaşılamıyorsa hiçbir bağlantı denemeden anlaşılır bir mesajla durur (daha önce sessizce beklerdi). Küçük denemelerde (`--en-cok 100` ve altı) ya da `--ayrintili` ile her bağlantı için satır yazar; hız sınırında "30 sn bekleniyor" der.
- Gece planı: `--yeni-en-cok N` (bir çalıştırmada en çok N yeni indirme) ve `--pencere 22:30-07:30` (yalnız bu saatlerde çalış, bitişte dur; `--saat-dilimi` varsayılan Europe/Istanbul). Pencere dışında başlatılırsa hiçbir şey yapmadan çıkar. Çıkış satırları: `GYAZO_ONBELLEK_TAMAM`, `GYAZO_ONBELLEK_DEVAM` (kalan sayısıyla), `GYAZO_ONBELLEK_YARIM` (hız sınırı ya da erişim yok).
- `deploy/setup-gyazo-gece.sh`: `kanit-gyazo.service` + `kanit-gyazo.timer` kurar (kanit kullanıcısı, sertleştirilmiş birim, her gece 22:30 TR + 5 dk rastgele, gecede 900, bitiş 07:30); 6.000 bağlantı yaklaşık 7 geceye yayılır, iş bitince gecelik çalışma saniyeler içinde "yeni yok" der ve bottan gelen yeni Gyazo bağlantılarını da aynı pencerede alır.
- Güncellemeler GitHub'dan: sunucu her sürümde depodan taze kopya alır (`.git` geçmişi sunucuda tutulmaz), sonra `apply-update.sh` (KURULUM §13).

## Bot mesajı

- Kanıt kaydedilince ekleyene artık bağlantı gönderilmez; mesaj "✅ Kanıtınız panele işlendi, teşekkürler." + kayıt numarasıdır (Gyazo dönüşümü bitince gelen mesaj da aynı; bağlantı yalnız panelde görünür).

## Yeni `.env` anahtarları (hepsi isteğe bağlı)

| Anahtar | Varsayılan | Anlam |
|---|---|---|
| `ONAYSIZ_GORUNUM` | `uyar` | Onay yetkisi olmayan kullanıcı için onaysız kayıt: `uyar` ya da `gizle` |
| `HATIRLATMA_GUN` | `3` | Hatırlatma eşiği (gün) |
| `HATIRLATMA_TEKRAR_GUN` | `3` | Aynı kayıt için tekrar aralığı (gün) |
| `HATIRLATMA_KONTROL_DK` | `30` | Web sürecinde kontrol sıklığı (dakika); `0` = kapalı, yalnız CLI |
| `HATIRLATMA_GUNLUK_SINIR` | `50` | Kullanıcı başına **günde** en çok kayıt hatırlatması; 0 ya da negatif değer varsayılana döner |

Statik dosyalar artık `?v=<sürüm>` ile sürümlenir; yükseltmeden sonra tarayıcıda Ctrl+F5 gerekmez. Bu sürüm, dört bağımsız inceleyicinin (güvenlik, hatırlatma mantığı, arayüz, yükseltme uyumu) bulgularıyla düzeltilerek yayımlandı; ayrıntı `TEST_SONUCLARI.md`.
