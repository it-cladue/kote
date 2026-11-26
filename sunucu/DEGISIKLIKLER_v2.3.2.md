# Kanıt Paneli 2.3.2 — dış görsel servisleri ve API anahtarları (25 Kasım 2026)

2.3.1 üzerine `deploy/apply-update.sh` ile uygulanır (sunucuda depodan taze kopya + güncelleme, KURULUM §13). Veritabanına yalnız iki yeni tablo eklenir (`api_anahtarlari`, `api_gunlugu`); mevcut kayıtlar ve ayarlar korunur.

## Snappark ve Teamzone görselleri panelde

- Snappark (`img.snappark.net`) ve Teamzone (`teamzone.gyazo.com`) bağlantılı kayıtların görseli artık panelin içinde açılır (küçük resim, büyütme, indir). Görsel ilk açılışta sunucu üzerinden getirilir ve `data/tmp/dis/` altına kopyalanır; sonraki açılışlar kopyadan gelir. Teamzone için sırayla `i.gyazo.com/<kimlik>.png`, `.jpg` ve Teamzone adresinin kendisi denenir; Teamzone oturum isterse görsel getirilemez.
- Güvenlik Gyazo ile aynı: yalnız bu adreslere istek, yönlendirme yalnız bu adreslere, en çok 20 MB, yalnız gerçek görsel dosyası kabul, açılamayan bağlantı 10 dakika yeniden denenmez.
- Görsel açılamadığında yer tutucu kaynağı söyler ("Görsel dış sitede (Snappark); açılamadı — Linki yeni sekmede aç"); "Yerel görsel yok" yalnız yerel dosya yolu bağlantılarında görünür.
- `gyazo-onbellekle` ve gece planı artık Gyazo + Snappark + Teamzone görsellerini kopyalar; raporda tür bazlı sayaçlar. Yeni ayar `DIS_GORSEL_PROXY` (varsayılan `GYAZO_PROXY` ile aynı; 0 = kapalı).
- Kayıt ayrıntısında yeni `link_kaynak` alanı; yeni aktarımlarda Snappark kimliği doğru okunur (mevcut kayıtlar değişmez).

## Gyazo arızasında hızlı geçiş (26 Kasım)

Sunucuda `gyazo-onbellekle` denemesinde Gyazo kaynağı çoğu görsele HTTP 503 verdi (Gyazo arızası; yalnız Cloudflare önbelleğindeki görseller açıldı) ve her bağlantıda yeniden deneme beklemesi komutu dakikalarca uzatıyordu. Gyazo silinmiş görsellere de HTTP 503 verir; gece planında önbellekte olmayanların çoğu zaten silinmiş eski bağlantılardır. Bu yüzden iki ayrı kural vardır:

- **Hızlı geçiş (10):** Aynı servisten art arda 10 bağlantıda HTTP 5xx ya da ağ hatası (bağlantı/okuma zaman aşımı, DNS, bağlantı reddi, 30 sn toplam süre) gelince o servisin kalan bağlantılarında 1 sn'lik "geçici hata" yeniden denemesi yapılmaz. Başka hiçbir şey değişmez: bağlantılar arası bekleme sürer (800 silinmiş bağlantılık 503 birikiminde Gyazo'nun hız sınırına, 429'a düşmemek için), arıza ilan edilmez. Günlüğe bir kez şu satır düşer: "Gyazo art arda 10 bağlantıda hata verdi (son durum: …); kalan Gyazo bağlantıları bir kez daha denenmeden geçilir. Silinmiş görseller de HTTP 503 verir, Gyazo arızası da olabilir; açılamayanlar sonraki çalıştırmada yeniden denenir." (Snappark/Teamzone için satır o servisin adını taşır.) Sonuçta `hizli_gecis` listesi yer alır. 404/410, 429 ve diğer "görsel yok" sonuçları sayacı değiştirmez; tek bir başarılı indirme sayacı sıfırlar.
- **Arıza (son 30 bağlantının 25'i):** Bir servisin **son 30 denenen bağlantısının en az 25'inde hiç yanıt alınamazsa** (bağlantı ya da okuma zaman aşımı, bağlantı hatası) o servisin kalan bağlantıları bu çalıştırmada **hiç istenmez**. Günlük satırı: "Gyazo art arda 25 bağlantının 25'inde hiç yanıt alınamadı (zaman aşımı / bağlantı hatası); muhtemelen Gyazo arızası. Kalan Gyazo bağlantıları bu çalıştırmada denenmeyecek, …". CSV raporunda sebep "Gyazo arızası sürüyor (… bu çalıştırmada denenmedi, sonraki çalıştırmada yeniden denenir)" olur; denenmemiş bir görselin başka bir satırdaki tekrarı da aynı sebebi taşır ve "denenmedi" sayılır. Diğer servisler sürer; denenmeyen bağlantılar gecelik 900 sınırından düşmez. Sonuçta `ariza` listesi ve `ariza_denenmedi` = {servis: sayı} yer alır. HTTP yanıtı alınan her bağlantı (503, 404 …) "yanıt var" sayılır; tek bir başarılı indirme bu sayımı sıfırdan başlatır (429 beklemesinden sonra gelen başarı dahil). Gövdesi 30 sn'de bitmeyen indirme (yanıt başlığı gelmiştir) arızaya sayılmaz, yalnız hızlı geçişe sayılır.
  - Tamamen asılı Gyazo 25 bağlantıda bırakılır (35 istek: ilk 10'u bir kez daha denenir).
  - Asılıların arasına hızlı 503/404 karışsa da (örn. %90 asılı, %10 hızlı yanıt) servis bırakılır.
  - Bilinçli ödünleşim: bağlantıların yarısı asılı, yarısı hızlı 503 alıyorsa servis bırakılmaz (yalnız hızlı geçiş); asılı bağlantı başına ~20 sn harcanır, gece penceresi ve gecelik sınır süreyi yine sınırlar.
  - **Olağan gece** (silinmiş görsellerin 503 birikimi, arada tek seferlik zaman aşımları) **bırakmaya yol açmaz ve `ARIZA:` satırı çıkarmaz**; sondaki canlı bağlantılar her gece denenir ve iner. Günlükte yalnız hızlı geçiş satırı görülebilir, bu bir arıza bildirimi değildir.
- Ön kontrol (deneme isteği) yanıt alamazsa 1 sn sonra bir kez daha denenir (tek seferlik zaman aşımı çalıştırmayı durdurmaz). İkisi de yanıtsızsa komut yaklaşık yarım dakikada `GYAZO_ONBELLEK_YARIM: Gyazo'ya ulaşılamıyor …` ile durur (çıkış kodu 1): buradan Gyazo'nun asılı olduğu ile sunucunun dış HTTPS erişiminin (ör. güvenlik duvarı) engellendiği ayırt edilemez. Mesajdaki `curl` satırını çalıştırın: çıktı 000 ise sunucu Gyazo'dan hiç yanıt alamadı (dış erişim engelli ya da Gyazo asılı); 200/403/503 gibi üç basamaklı başka bir sayı yazarsa erişim var, Gyazo arızalıdır. Gece planı sonraki gece yeniden dener.
- Süre: Gyazo yanıt vermeden asılı kalan bir bağlantıda tek deneme ~20 sn sürer (bağlantı 5 sn + okuma 15 sn). Hızlı geçişten önceki ilk 10 hatalı bağlantı bir kez daha denendiği için her biri ~40 sn sürer, sonrakiler tek denemedir (~20 sn). Gövdesi yavaş gelen bir indirme en çok 30 sn sürer ve yeniden denenmez. Ön kontrol geçip görseller asılı kalırsa `--en-cok 20` denemesi bu yüzden ~10 dakikaya kadar sürebilir (25 sınırına varmaz); düz 503'lerde birkaç saniyede biter.
- Komut sonunda **yalnız bir servis bırakıldıysa** (arıza) `GYAZO_ONBELLEK_TAMAM` satırından önce bir bilgi satırı çıkar, örn. "ARIZA: Gyazo yanıt vermiyor (muhtemelen Gyazo arızası); 26 bağlantı açılamadı, 9 bağlantı denenmedi. Sonraki çalıştırmada (gece planı kuruluysa kendiliğinden) yeniden denenir." Yalnız hızlı geçiş olduysa ek satır çıkmaz (özet ve durum satırı yeterlidir). `ARIZA:` satırı, hızlı geçiş satırı, bırakma satırı ve ön kontrolün `Gyazo erişimi: …` satırı gece planının günlüğünde (`journalctl -u kanit-gyazo`) de görünür; bağlantı başına 503/403 satırları gece günlüğüne yazılmaz. Çıkış kodu ve `GYAZO_ONBELLEK_TAMAM` aynı kalır (gece planı bozulmaz).
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
