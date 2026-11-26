# Kanıt Paneli 2.3.2 — dış görsel servisleri ve API anahtarları (25 Kasım 2026)

2.3.1 üzerine `deploy/apply-update.sh` ile uygulanır (sunucuda `git pull` + güncelleme, KURULUM §13). Veritabanına yalnız iki yeni tablo eklenir (`api_anahtarlari`, `api_gunlugu`); mevcut kayıtlar ve ayarlar korunur.

## Snappark ve Teamzone görselleri panelde

- Snappark (`img.snappark.net`) ve Teamzone (`teamzone.gyazo.com`) bağlantılı kayıtların görseli artık panelin içinde açılır (küçük resim, büyütme, indir). Görsel ilk açılışta sunucu üzerinden getirilir ve `data/tmp/dis/` altına kopyalanır; sonraki açılışlar kopyadan gelir. Teamzone için sırayla `i.gyazo.com/<kimlik>.png`, `.jpg` ve Teamzone adresinin kendisi denenir; Teamzone oturum isterse görsel getirilemez.
- Güvenlik Gyazo ile aynı: yalnız bu adreslere istek, yönlendirme yalnız bu adreslere, en çok 20 MB, yalnız gerçek görsel dosyası kabul, açılamayan bağlantı 10 dakika yeniden denenmez.
- Görsel açılamadığında yer tutucu kaynağı söyler ("Görsel dış sitede (Snappark); açılamadı — Linki yeni sekmede aç"); "Yerel görsel yok" yalnız yerel dosya yolu bağlantılarında görünür.
- `gyazo-onbellekle` ve gece planı artık Gyazo + Snappark + Teamzone görsellerini kopyalar; raporda tür bazlı sayaçlar. Yeni ayar `DIS_GORSEL_PROXY` (varsayılan `GYAZO_PROXY` ile aynı; 0 = kapalı).
- Kayıt ayrıntısında yeni `link_kaynak` alanı; yeni aktarımlarda Snappark kimliği doğru okunur (mevcut kayıtlar değişmez).

## Gyazo arızasında hızlı geçiş (26 Kasım)

Sunucuda `gyazo-onbellekle` denemesinde Gyazo kaynağı çoğu görsele HTTP 503 verdi (Gyazo arızası; yalnız Cloudflare önbelleğindeki görseller açıldı) ve her bağlantıda yeniden deneme beklemesi komutu dakikalarca uzatıyordu.

- Aynı servisten art arda 10 HTTP 5xx gelince komut **arıza moduna** geçer: kalan bağlantılar bekleme ve yeniden deneme olmadan hızla "açılamayan" olarak işaretlenir, günlüğe "muhtemelen Gyazo arızası" uyarısı düşer, sonuçta `ariza` listesi yer alır. Açılamayanlar bir sonraki çalıştırmada (gece planı) yeniden denenir; kalıcı kayıp yoktur.
- Arıza sayacı artık yalnız HTTP 5xx'i değil, **ağ hatalarını** da sayar (Gyazo'nun yanıt vermeden asılı kaldığı, bağlantının ancak 15 sn okuma zaman aşımında bittiği durum; bağlantı kurulamaması, DNS hatası). 404/410, 429 ve diğer "görsel yok" sonuçları sayılmaz; tek bir başarılı indirme sayacı sıfırlar. Günlük satırı: "Gyazo art arda 10 bağlantıda yanıt veremedi (son durum: …); muhtemelen Gyazo arızası".
- Aynı servisin **25** bağlantısı arada hiç başarılı indirme olmadan **hiç yanıt vermezse** (zaman aşımı ya da bağlantı hatası) o servisin kalan bağlantıları bu çalıştırmada **hiç istenmez**; CSV raporunda sebep "Gyazo arızası sürüyor (… bu çalıştırmada denenmedi, sonraki çalıştırmada yeniden denenir)" olur. Diğer servisler (Snappark/Teamzone ya da Gyazo) sürer; denenmeyen bağlantılar gecelik 900 sınırından düşmez. Sonuçta `ariza_denenmedi` = {servis: sayı} yer alır. **Düz HTTP 503 bunu tetiklemez**: Gyazo silinmiş görsellere de 503 verdiği için, başta 25'ten fazla silinmiş görsel olsa bile sonraki canlı bağlantılar her gece denenir (503'lerde yalnız hızlı geçiş olur, 503 yanıtı zaten hızlıdır). Aradaki hızlı 503/404 yanıtları ise sayacı sıfırlamaz: arızada bağlantıların bir kısmı asılı kalıp bir kısmı hızlı 503 alsa da asılılar birikir ve servis yine bırakılır. Sayacı yalnız başarılı indirme sıfırlar (429 beklemesinden sonra gelen başarı dahil).
- Ön kontrol (deneme isteği) yanıt alamazsa 1 sn sonra bir kez daha denenir (tek seferlik zaman aşımı çalıştırmayı durdurmaz). İkisi de yanıtsızsa komut yaklaşık yarım dakikada `GYAZO_ONBELLEK_YARIM: Gyazo'ya ulaşılamıyor …` ile durur (çıkış kodu 1): buradan Gyazo'nun asılı olduğu ile sunucunun dış HTTPS erişiminin (ör. güvenlik duvarı) engellendiği ayırt edilemez; mesajdaki `curl` satırı bir HTTP kodu yazarsa erişim vardır, Gyazo arızalıdır. Gece planı sonraki gece yeniden dener.
- Süre: Gyazo yanıt vermeden asılı kalan bir bağlantıda tek deneme ~20 sn sürer (bağlantı 5 sn + okuma 15 sn; gövde yavaş gelirse en çok ~30 sn). İlk 10 hatalı bağlantı bir kez daha denendiği için her biri ~40 sn'ye (en kötü ~1 dk) kadar sürebilir, sonrakiler tek denemedir. Ön kontrol geçip görseller asılı kalırsa `--en-cok 20` denemesi bu yüzden ~10 dakikaya kadar sürebilir (25 sınırına varmaz); düz 503'lerde birkaç saniyede biter.
- Komut sonunda arıza varsa `GYAZO_ONBELLEK_TAMAM` satırından önce bir bilgi satırı çıkar, örn. "ARIZA: Gyazo yanıt vermiyor (muhtemelen Gyazo arızası); 180 bağlantı açılamadı, 700 bağlantı denenmedi. Sonraki çalıştırmada (gece planı kuruluysa kendiliğinden) yeniden denenir." Bu satır ve iki arıza günlük satırı ("art arda 10 …", "art arda 25 …") gece planının günlüğünde (`journalctl -u kanit-gyazo`) de görünür; bağlantı başına 503 satırları gece günlüğüne yazılmaz. Çıkış kodu ve `GYAZO_ONBELLEK_TAMAM` aynı kalır (gece planı bozulmaz).
- Geçici hatada yeniden deneme beklemesi 5 sn → 1 sn.
- HTTP 503 açıklaması: "Gyazo yanıt vermiyor (HTTP 503: Gyazo arızası ya da silinmiş görsel; sonraki çalıştırmada yeniden denenir)". Ön kontrolde var olmayan kimlik için 503/404 normal sayılır.
- `t.gyazo.com` hem Gyazo hem Teamzone için izinli ana makine (Teamzone bağlantıları buraya yönlendiriyor; önceden "izinli olmayan ana makine" ile reddediliyordu).

## API anahtarları: dış sistemler için salt okunur erişim

- Yönetim → **API anahtarları** (yalnız süperadmin): ad, proje kapsamı (tümü ya da seçim), yalnız onaylı kayıtlar (varsayılan açık), SQL sorgu izni ve görsel indirme izni (varsayılan kapalı), isteğe bağlı son kullanma tarihi. Anahtar (`kp_…`) bir kez gösterilir; sunucuda yalnız özeti saklanır. İptal, son kullanım zamanı/IP, istek sayısı ve son 50 istek sayfada görünür; oluşturma/iptal İşlem Geçmişi'ne yazılır.
- Uçlar (`Authorization: Bearer kp_…`, yalnız HTTPS üzerinden kullanın): `GET /api/v1/ozet`, `GET /api/v1/kayitlar`, `GET /api/v1/kayit/<id>`, `GET /api/v1/gorsel/<id>`, `POST /api/v1/sorgu`. Oturum çerezi API'de geçmez, anahtar panel sayfalarında geçmez. Yanıtlar Türkçe JSON hata alanıyla; anahtar başına dakikada 120 istek (`API_DAKIKA_SINIRI`) ve `Retry-After`; geçersiz anahtar denemesi IP başına dakikada 30; gövde en çok 64 KB; her istek günlüğe yazılır.
- `POST /api/v1/sorgu`: tek `SELECT`, salt okunur bağlantı ve SQLite yetkilendiricisiyle kilitli; yalnız anahtarın kapsamına göre süzülmüş `kayitlar`, `yorumlar`, `kategoriler`, `tg_kullanicilar` görünümleri; yazma, PRAGMA, ATTACH, şema tabloları, panel kullanıcıları ve ayarlar her koşulda reddedilir; 5.000 satır ve 5 saniye sınırı. Kullanım ve örnekler: `API_KULLANIM.md`.
- Yeni ayarlar: `API_ACIK` (varsayılan 1; 0 = API kapalı), `API_DAKIKA_SINIRI` (120).

## Bağımsız inceleme sonrası düzeltmeler

Birleşik 2.3.2 kodu dört bağımsız inceleyiciden geçti (SQL ucu saldırgan gözüyle, anahtar yönetimi, dış görsel çözümleyici, yükseltme uyumu). Yetkilendirici aşılamadı; bulunan altı orta/yüksek bulgu kapatıldı:

- SQL sorgu ucu: yanıt en çok **1.000 satır ve toplam 8 MB**, tek değer en çok 64 KB; sınır dolunca `kesildi: true` ve `neden` (`satir`/`boyut`) döner (önceden tek sorgu sunucu belleğini GB'larca şişirebiliyordu). Sunucu genelinde aynı anda en çok 2 sorgu (`API_SORGU_ESZAMANLI`), anahtar başına 1; fazlası 429 ve `Retry-After: 2`. `tg_kullanicilar` görünümü yalnız "tüm projeler" kapsamlı anahtarda tam listedir. Bilgi işlevleri (`sqlite_version()` vb.) kapalı; sonsuz sayılar `null`.
- API: Snappark/Teamzone kayıtlarında `gorsel_url` artık dolu; bozuk görsel dosyası 422; `API_ACIK` yalnız açık anlamlı değerlerde (1/evet/acik/on/true) açıktır, başka her değer kapatır; istek günlüğü saatte bir budanır.
- Dış görseller: yönlendirmeler yalnız izinli hostlara (tam eşleşme, yalnız https/443) izlenir; `@`, ters bölü, boşluk ya da port içeren adresler reddedilir; bağlanmadan önce hostun iç ağ adresine çözülmediği denetlenir (Gyazo yolu dahil). Tek bir bozuk ya da asılı Snappark bağlantısı gece kopyasının tamamını durdurmaz; servis yalnız art arda 3 bağlantıda bağlantı kurulamazsa o gece atlanır. Snappark hız sınırı yalnız Snappark'ı durdurur.
- Liste ve galeri küçük resimleri dış siteyi beklemez: ilk açılışta "Görsel hazırlanıyor" yer tutucusu görünür, görsel arka planda kopyalanır (aynı anda en çok 2), ayrıntı görünümü en çok 10 sn bekler. Yavaş bir dış servis artık paneli diğer kullanıcılar için kilitlemez.
- Yeni testler: `test_inceleme_232.py` (83); toplam 471.

## Yeni `.env` anahtarları (hepsi isteğe bağlı)

| Anahtar | Varsayılan | Anlam |
|---|---|---|
| `DIS_GORSEL_PROXY` | `GYAZO_PROXY` değeri | Snappark/Teamzone görsellerini sunucu üzerinden getir ve kopyala |
| `API_ACIK` | `1` | 0 ise tüm `/api/v1` uçları kapalı (404) |
| `API_DAKIKA_SINIRI` | `120` | Anahtar başına dakikalık istek sınırı |
| `API_SORGU_ESZAMANLI` | `2` | `/api/v1/sorgu` için aynı anda en çok sorgu (1-6) |
