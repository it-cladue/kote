# Kanıt Paneli 2.3.2 — dış görsel servisleri ve API anahtarları (25 Kasım 2026)

2.3.1 üzerine `deploy/apply-update.sh` ile uygulanır (sunucuda `git pull` + güncelleme, KURULUM §13). Veritabanına yalnız iki yeni tablo eklenir (`api_anahtarlari`, `api_gunlugu`); mevcut kayıtlar ve ayarlar korunur.

## Snappark ve Teamzone görselleri panelde

- Snappark (`img.snappark.net`) ve Teamzone (`teamzone.gyazo.com`) bağlantılı kayıtların görseli artık panelin içinde açılır (küçük resim, büyütme, indir). Görsel ilk açılışta sunucu üzerinden getirilir ve `data/tmp/dis/` altına kopyalanır; sonraki açılışlar kopyadan gelir. Teamzone için sırayla `i.gyazo.com/<kimlik>.png`, `.jpg` ve Teamzone adresinin kendisi denenir; Teamzone oturum isterse görsel getirilemez.
- Güvenlik Gyazo ile aynı: yalnız bu adreslere istek, yönlendirme yalnız bu adreslere, en çok 20 MB, yalnız gerçek görsel dosyası kabul, açılamayan bağlantı 10 dakika yeniden denenmez.
- Görsel açılamadığında yer tutucu kaynağı söyler ("Görsel dış sitede (Snappark); açılamadı — Linki yeni sekmede aç"); "Yerel görsel yok" yalnız yerel dosya yolu bağlantılarında görünür.
- `gyazo-onbellekle` ve gece planı artık Gyazo + Snappark + Teamzone görsellerini kopyalar; raporda tür bazlı sayaçlar. Yeni ayar `DIS_GORSEL_PROXY` (varsayılan `GYAZO_PROXY` ile aynı; 0 = kapalı).
- Kayıt ayrıntısında yeni `link_kaynak` alanı; yeni aktarımlarda Snappark kimliği doğru okunur (mevcut kayıtlar değişmez).

## API anahtarları: dış sistemler için salt okunur erişim

- Yönetim → **API anahtarları** (yalnız süperadmin): ad, proje kapsamı (tümü ya da seçim), yalnız onaylı kayıtlar (varsayılan açık), SQL sorgu izni ve görsel indirme izni (varsayılan kapalı), isteğe bağlı son kullanma tarihi. Anahtar (`kp_…`) bir kez gösterilir; sunucuda yalnız özeti saklanır. İptal, son kullanım zamanı/IP, istek sayısı ve son 50 istek sayfada görünür; oluşturma/iptal İşlem Geçmişi'ne yazılır.
- Uçlar (`Authorization: Bearer kp_…`, yalnız HTTPS üzerinden kullanın): `GET /api/v1/ozet`, `GET /api/v1/kayitlar`, `GET /api/v1/kayit/<id>`, `GET /api/v1/gorsel/<id>`, `POST /api/v1/sorgu`. Oturum çerezi API'de geçmez, anahtar panel sayfalarında geçmez. Yanıtlar Türkçe JSON hata alanıyla; anahtar başına dakikada 120 istek (`API_DAKIKA_SINIRI`) ve `Retry-After`; geçersiz anahtar denemesi IP başına dakikada 30; gövde en çok 64 KB; her istek günlüğe yazılır.
- `POST /api/v1/sorgu`: tek `SELECT`, salt okunur bağlantı ve SQLite yetkilendiricisiyle kilitli; yalnız anahtarın kapsamına göre süzülmüş `kayitlar`, `yorumlar`, `kategoriler`, `tg_kullanicilar` görünümleri; yazma, PRAGMA, ATTACH, şema tabloları, panel kullanıcıları ve ayarlar her koşulda reddedilir; 5.000 satır ve 5 saniye sınırı. Kullanım ve örnekler: `API_KULLANIM.md`.
- Yeni ayarlar: `API_ACIK` (varsayılan 1; 0 = API kapalı), `API_DAKIKA_SINIRI` (120).

## Yeni `.env` anahtarları (hepsi isteğe bağlı)

| Anahtar | Varsayılan | Anlam |
|---|---|---|
| `DIS_GORSEL_PROXY` | `GYAZO_PROXY` değeri | Snappark/Teamzone görsellerini sunucu üzerinden getir ve kopyala |
| `API_ACIK` | `1` | 0 ise tüm `/api/v1` uçları kapalı (404) |
| `API_DAKIKA_SINIRI` | `120` | Anahtar başına dakikalık istek sınırı |
