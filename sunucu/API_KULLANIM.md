# Kanıt Paneli API (2.3.2) — kullanım belgesi

Başka bir panel ya da sistem, Kanıt Paneli verisini **salt okunur** olarak bu API ile çeker. API kayıt ekleyemez,
değiştiremez, silemez; onay veremez. Tüm adresler `/api/v1/` ile başlar ve JSON döner.

Aşağıdaki örneklerde `https://panel.ornek` yerine kendi panel adresinizi, `kp_…` yerine size verilen anahtarı yazın.

## 1. Anahtar oluşturma (süperadmin)

1. Panele süperadmin hesabıyla girin.
2. Üst menü **Yönetim → API anahtarları** (`/yonetim/api-anahtarlari`).
3. **API anahtarı oluştur** formu:
   - **Ad**: anahtarı kullanacak sistem (ör. "Rapor sunucusu"). Listede ve günlükte bu ad görünür.
   - **Proje kapsamı**: *Seçili projeler* (yalnız işaretlediğiniz projeler) ya da *Tüm projeler* (sonradan eklenen projeler de dahil).
   - **Yalnız onaylı kayıtlar** (varsayılan açık): açıkken API yalnız onaylanmış kayıtları görür. Kapalıysa bekleyenler de görünür.
     Silinmiş kayıtlar hiçbir koşulda görünmez.
   - **SQL sorgusu** (varsayılan kapalı): `/api/v1/sorgu` ucunu açar.
   - **Görsel indirme** (varsayılan kapalı): `/api/v1/gorsel/<id>` ucunu ve listelerdeki `gorsel_url` alanını açar.
   - **Son kullanma tarihi** (isteğe bağlı): anahtar o günün sonuna kadar geçerlidir.
4. **Anahtar oluştur**'a basın. Anahtar (`kp_` + 40 karakter) **yalnız bir kez** gösterilir: hemen kopyalayıp karşı sistemin gizli
   ayarına yazın. Panel anahtarın kendisini saklamaz (yalnız özeti ve tanıma için ilk 8 karakteri); kaybolursa iptal edip yenisini oluşturun.
5. Listede her anahtarın kapsamı, durumu (Etkin / İptal edildi / Süresi doldu), son kullanım zamanı ve IP'si, toplam istek sayısı görünür.
   **İptal et** düğmesi anahtarı hemen geçersiz kılar. Sayfanın altında son 50 istek listelenir.
6. Oluşturma ve iptal İşlem Geçmişi'ne yazılır ("API anahtarı oluşturma", "API anahtarı iptali").

## 2. Kimlik doğrulama

Her istekte başlık:

```
Authorization: Bearer kp_…
```

- Oturum çerezi kabul edilmez; tarayıcıda panele giriş yapmış olmak API'ye erişim sağlamaz. API yanıtları çerez yazmaz.
- Yanıt başlıkları: `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`.
- İstek gövdesi en çok 64 KB.
- Anahtarı adres çubuğuna/sorgu dizesine koymayın; yalnız başlıkta gönderin. Panel HTTPS ile yayındaysa yalnız `https://` kullanın.

## 3. Uçlar

Tüm uçlarda kapsam uygulanır: anahtarın projeleri; "yalnız onaylı" açıksa yalnız onaylı kayıtlar; silinmiş kayıtlar her zaman hariç.
Ortak süzgeçler:

| Parametre | Anlamı |
|---|---|
| `proje` | Proje kodu; birden çok için tekrarlayın (`proje=OF&proje=PA`) ya da virgülle ayırın. Kapsam dışı proje → 403. Boş = anahtarın tüm projeleri. |
| `tarih1`, `tarih2` | `YYYY-AA-GG`; kanıt tarihi (`tarih`) bu aralıkta (iki uç dahil). Ters verilirse yer değiştirilir ve yanıtta `uyari` döner. |
| `tarihsiz=1` | Yalnız tarihi boş kayıtlar (tarih aralığıyla birlikte kullanılamaz). |

### 3.1 `GET /api/v1/ozet`

Parametreler: `proje`, `tarih1`, `tarih2`.

```bash
curl -s -H "Authorization: Bearer kp_…" "https://panel.ornek/api/v1/ozet?proje=OF&tarih1=2026-11-01&tarih2=2026-11-30"
```

Yanıt: `toplam`, `onayli`, `bekleyen`; `projeler` (proje bazlı toplam/onaylı/bekleyen); `kategori_tip` (kategori × tip çaprazı:
toplam, onaylı); `ekleyenler` (ekleyen bazlı ilk 50: `ekleyen_id`, `ekleyen_ad`, toplam, onaylı); `suzgec`.

### 3.2 `GET /api/v1/kayitlar`

Parametreler: `proje`, `durum` (`onayli` | `bekleyen` | `hepsi`; varsayılan `hepsi`; "yalnız onaylı" anahtarda her zaman `onayli`),
`kategori` (büyük/küçük harf duyarsız tam eşleşme), `ekleyen` (ad parçası ya da Telegram kimliği), `tarih1`, `tarih2`, `tarihsiz`,
`q` (personel, üye ID, ana üye ID, lead ID, link, açıklama, ekleyen adı, kategoride arar — Kayıtlar sayfasıyla aynı),
`sayfa` (1'den başlar), `adet` (1–500, varsayılan 100). Sıralama: kanıt tarihi yeni → eski.

```bash
curl -s -H "Authorization: Bearer kp_…" "https://panel.ornek/api/v1/kayitlar?proje=OF&durum=onayli&kategori=CVPS&tarih1=2026-11-01&adet=200&sayfa=1"
```

Yanıt: `{toplam, sayfa, adet, sayfa_sayisi, suzgec, kayitlar:[…]}`; her kayıt alanları için bkz. §4.

### 3.3 `GET /api/v1/kayit/<id>`

Tek kayıt ve yorumları (`yorumlar: [{kullanici, tur, metin, zaman}]`). Kapsam dışı ya da hiç olmayan kayıt için aynı 404 döner
(kaydın var olup olmadığı belli edilmez).

```bash
curl -s -H "Authorization: Bearer kp_…" "https://panel.ornek/api/v1/kayit/1234"
```

### 3.4 `GET /api/v1/gorsel/<id>`

Yalnız "Görsel indirme" izinli anahtarlar (aksi hâlde 403). Kaydın görselini bayt olarak döner (sunucudaki dosya ya da Gyazo önbelleği).
Görsel yoksa 404. İkinci görsel için `?ikinci=1`.

```bash
curl -s -H "Authorization: Bearer kp_…" -o kayit-1234.jpg "https://panel.ornek/api/v1/gorsel/1234"
```

### 3.5 `POST /api/v1/sorgu`

Yalnız "SQL sorgusu" izinli anahtarlar (aksi hâlde 403). Gövde JSON:

```json
{ "sql": "SELECT … WHERE personel = ?", "parametreler": ["ayse"] }
```

```bash
curl -s -H "Authorization: Bearer kp_…" -H "Content-Type: application/json" \
  -d '{"sql":"SELECT proje, count(*) AS adet FROM kayitlar GROUP BY proje"}' \
  "https://panel.ornek/api/v1/sorgu"
```

Yanıt: `{sutunlar:[…], satirlar:[[…],…], satir_sayisi, kesildi, sure_ms}`; kesildiyse ayrıca `neden: "satir"` ya da `neden: "boyut"`.

**Kurallar**

- Yalnız tek bir `SELECT` (ya da `WITH … SELECT`, `VALUES`) ifadesi. Sondaki tek `;` kabul edilir; `;` sonrasında metin (başka ifade,
  yorum) varsa 400.
- Okunabilen tablolar (anahtarın kapsamına göre süzülmüş görünümler):
  - `kayitlar`: `id, proje, kategori, kategori_code, kategori_mode, personel, uye_id, ana_uye_id, lead_id, tip, tarih, kt, kt_kim,
    kt_zaman, ekleyen_id, ekleyen_ad, link, link_turu, aciklama, kaynak, giris_tipi, ilk_gorulme, guncelleme` — silinmişler yok;
    "yalnız onaylı" anahtarda yalnız `kt=1`.
  - `yorumlar`: `id, kayit_id, kullanici, tur, metin, zaman, yanit_id` — yalnız kapsamdaki kayıtların yorumları.
  - `kategoriler`: `code, label, mode`.
  - `tg_kullanicilar`: `id, username, first_name, onayli, engelli` — tüm projeleri gören ("Tümü", yalnız onaylı olmayan) anahtarda
    tam liste; diğer anahtarlarda yalnız kapsamdaki kayıtları ekleyen Telegram kullanıcıları.
- Başka her şey reddedilir (403): panel kullanıcıları, ayarlar, işlem geçmişi, Telegram kuyrukları, `sqlite_master`, `main.` ile
  doğrudan tablo okuma, PRAGMA, ATTACH, her türlü yazma, `WITH RECURSIVE`, tablo döndüren işlevler (`json_each`, `pragma_*`),
  `sqlite_` önekli bilgi işlevleri (`sqlite_version()` vb.). İzin verilmeyen tablo var olsa da olmasa da (sütun adı yanlış olsa bile) aynı 403 döner.
- En çok **1000 satır** ve toplam **8 MB** değer döner; hangisi önce dolarsa orada kesilir, `kesildi: true` ve `neden: "satir"` ya da
  `neden: "boyut"` olur. Daha fazlası için `LIMIT`/`OFFSET` ya da `WHERE id > ?` ile sayfalayın.
- Tek bir değer (metin/blob) en çok **64 KB** olabilir; aşan değer üreten sorgu 400 `neden: "boyut"` alır.
- Sorgu en çok 5 saniye çalışır; aşarsa durdurulur (400, `neden: "sure"`).
- Sunucu genelinde aynı anda en çok `API_SORGU_ESZAMANLI` (varsayılan 2) sorgu çalışır, bir anahtarla aynı anda yalnız 1 sorgu.
  Fazlası beklemeden 429 alır (`neden: "es_zamanli"` ya da `"es_zamanli_anahtar"`, `Retry-After: 2`); birkaç saniye sonra yeniden deneyin.
- Sonuçtaki sonsuz/NaN sayılar (ör. `1e999`) JSON'da geçerli olmadığı için `null` döner.
- Parametreler `?` ile verilir (en çok 100; metin, sayı ya da null). Değerleri SQL metnine eklemek yerine parametre kullanın.
  64 bit aralığı dışındaki tam sayı, NaN/sonsuz ve geçersiz Unicode (eşi olmayan vekil karakter) 400 `neden: "girdi"` alır.
- Hata yanıtlarında `neden` alanı: `yetki`, `sure`, `sutun`, `sozdizimi`, `parametre`, `tek_ifade`, `yalniz_select`, `girdi`, `boyut`, `diger`.

**Örnek sorgular**

1. Bu personel bu ay kaç CVPS (onaylı):

```sql
SELECT count(*) AS cvps
FROM kayitlar
WHERE personel = ? AND kategori = 'CVPS' AND kt = 1
  AND tarih >= strftime('%Y-%m-01', 'now', 'localtime')
```

```bash
curl -s -H "Authorization: Bearer kp_…" -H "Content-Type: application/json" \
  -d "{\"sql\":\"SELECT count(*) AS cvps FROM kayitlar WHERE personel = ? AND kategori = 'CVPS' AND kt = 1 AND tarih >= strftime('%Y-%m-01','now','localtime')\",\"parametreler\":[\"ayse\"]}" \
  "https://panel.ornek/api/v1/sorgu"
```

2. Bu ay personel × kategori dağılımı:

```sql
SELECT personel, kategori, count(*) AS adet, sum(kt) AS onayli
FROM kayitlar
WHERE tarih >= strftime('%Y-%m-01', 'now', 'localtime')
GROUP BY personel, kategori
ORDER BY adet DESC
```

3. Sessiz / telesekreter oranı ve yorumlu kayıt sayısı (proje bazlı):

```sql
SELECT k.proje,
       sum(k.tip = 'sessiz') AS sessiz,
       sum(k.tip = 'telesekreter') AS telesekreter,
       count(DISTINCT y.kayit_id) AS yorumlu_kayit
FROM kayitlar k LEFT JOIN yorumlar y ON y.kayit_id = k.id
GROUP BY k.proje
```

### 3.6 `GET /api/v1/personel-ozet` (2.3.4)

Panelin **Rapor** sayfasındaki "Personel bazında kanıtlar" tablosu: personel (ya da ekleyen) × kategori (ya da tip) sayıları.
Silinmiş kayıtlar sayılmaz; anahtarın proje kapsamı uygulanır.

| Parametre | Değerler (varsayılan kalın) |
|---|---|
| `proje` | Tek proje kodu; boş = anahtarın tüm projeleri. Kapsam dışı → 403, birden çok proje → 400. |
| `donem` | `bugun` \| `hafta` (pazartesiden bugüne) \| **`ay`** (ayın 1'inden bugüne) \| `son30` \| `hepsi` \| `ozel` |
| `tarih1`, `tarih2` | `donem=ozel` ile `YYYY-AA-GG` (biri boş olabilir; ters verilirse yer değiştirilir, `uyari` döner). `donem` yokken tarih verilirse `ozel` sayılır. |
| `durum` | **`hepsi`** \| `onayli` \| `bekleyen`. "Yalnız onaylı" anahtarda her zaman `onayli` (başka değer istenirse `uyari` döner). |
| `grup` | **`personel`** \| `ekleyen` (Telegram'dan ekleyen kişinin adı) |
| `sutun` | **`kategori`** \| `tip` |
| `kategori` | (2.3.5) Tek kategori adı; boş = tüm kategoriler. Büyük/küçük harf ve baş/son boşluk fark etmez (katalogdaki adla eşlenir), `(boş)` ya da `__bos__` = kategorisi boş kayıtlar. `sutun=kategori` ile yanıtta yalnız o sütun döner; `sutun=tip` ile o kategorinin tip sayıları. Bilinmeyen ad hata değildir: sıfır satır döner. Yanıttaki `filtre.kategori` uygulanan adı ya da `null` verir. |

Tanınmayan değer ya da hatalı tarih → 400 (`hata` alanında hangi parametre olduğu yazar).

Örnek (2.3.5): PA projesinde bu ay kim kaç CVPS eklemiş, Sessiz/Telesekreter ayrımıyla:

```bash
curl -s -H "Authorization: Bearer kp_…" "https://panel.ornek/api/v1/personel-ozet?proje=PA&donem=ay&kategori=CVPS&sutun=tip"
```

Panelde aynı süzgeçler `/rapor/personel`, `/rapor/personel.xlsx` ve `/rapor/personel.csv` adreslerinde de geçerlidir (`kategori` dahil).
Rapor sayfasındaki sayı ve kutu bağlantıları Kayıtlar listesini şu tam eşleşen parametrelerle açar: `personel`, `ekleyen_ad`,
`tip` (harf duyarsız), `kategori` (harf duyarsız; `__bos__` = boş) ve `silinmemis=1`; boş değer için `__bos__` yazılır.

```bash
curl -s -H "Authorization: Bearer kp_…" "https://panel.ornek/api/v1/personel-ozet?proje=OF&donem=ay&durum=hepsi&grup=personel&sutun=kategori"
```

Örnek yanıt (kısaltılmış):

```json
{
  "ok": true,
  "filtre": {"proje": "OF", "projeler": ["OF"], "donem": "ay", "durum": "hepsi", "grup": "personel", "sutun": "kategori",
             "tarih1": "2026-11-01", "tarih2": "2026-11-26"},
  "donem": {"kod": "ay", "ad": "Bu ay", "tarih1": "2026-11-01", "tarih2": "2026-11-26", "etiket": "Bu ay (01.11.2026 – 26.11.2026)"},
  "sutunlar": ["ARK", "DDS", "DDT", "HGST", "PRCST", "LPST", "CVPS", "btagsz", "30gün", "S.ARK"],
  "satirlar": [
    {"personel": "ALI.K", "bos": false, "toplam": 14, "onayli": 10, "bekleyen": 4, "onay_orani": 71,
     "sutunlar": {"ARK": 2, "DDS": 5, "DDT": 0, "HGST": 7, "PRCST": 0, "LPST": 0, "CVPS": 0, "btagsz": 0, "30gün": 0, "S.ARK": 0}},
    {"personel": "(boş)", "bos": true, "toplam": 1, "onayli": 0, "bekleyen": 1, "onay_orani": 0, "sutunlar": {"ARK": 1, "DDS": 0, "…": 0}}
  ],
  "toplam": {"toplam": 15, "onayli": 10, "bekleyen": 5, "onay_orani": 67, "sutunlar": {"ARK": 3, "DDS": 5, "HGST": 7, "…": 0}},
  "kisi_sayisi": 2,
  "kayit_sayisi": 15
}
```

- `sutunlar`: sütun adları; kategoride proje kataloğu sırası, katalogda olmayan eski adlar sonda, boş kategori `"(boş)"` en sonda
  (büyük/küçük harf farkı olan adlar tek sütunda birleşir). Tipte en çok kullanılandan aza.
- `satirlar`: toplam çoktan aza, eşitse ada göre. Personeli (ya da ekleyeni) boş kayıtlar `"personel": "(boş)"`, `"bos": true`.
- "Bugün" ve dönem sınırları sunucunun takvim günüdür (panelle aynı). Tarih süzgeci kanıt tarihine (`tarih`) uygulanır; tarihsiz kayıtlar yalnız `donem=hepsi` ile sayılır.

#### 3.6.1 Durumlar: `durumlar=1` (2.3.7)

`durumlar=1` eklenirse yanıtta, panelin Rapor sayfasındaki **Durumlar** bölümüyle aynı hesapla bir `durumlar` nesnesi döner
(aynı süzgeçler: `proje`, `donem`, `tarih1`/`tarih2`, `durum`, `grup`, `sutun`, `kategori`). Ek parametre:

| Parametre | Değerler (varsayılan kalın) |
|---|---|
| `durumlar` | `1` (ya da `evet`, `true`) = ekle; boş, `0` (ya da `hayir`, `hayır`, `false`) = ekleme (yanıt 2.3.5 ile aynı). Başka değer → 400. |
| `esik` | **`50`** \| `75` \| `100` — "ortalamanın altında" sınırı (ortalamanın yüzdesi). Başka değer → 400. `durumlar=1` ile `filtre.esik` de döner. |

Kurallar (kişi = sonuçtaki satır; `grup=ekleyen` ise ekleyen):

- **Ortalama**: sütun toplamı ÷ dönemde en az bir kaydı olan kişi sayısı; genel ortalama = kayıt sayısı ÷ kişi sayısı.
- `ortalama_alti`: sütun ortalaması en az 2 iken `sayi < ortalama × esik/100`; en az 3 kişi ve birden çok dolu sütun varken toplamda da (`sutun: null`).
- `hic_eklemedi`: sütun ortalaması en az 3 iken o sütunda 0 kayıt.
- `dusus`: önceki dönemde en az 3 kayıt ve bu dönem en az %30 az; önceki dönemde kaydı olup bu dönem hiç olmayanlar (`sayi: 0`, `degisim_yuzde: -100`).
  Önceki dönem: `bugun` → dün; `hafta` → geçen haftanın aynı günleri; `ay`, `son30`, `ozel` → başlangıçtan hemen önceki eşit uzunlukta pencere;
  `hepsi` ve başlangıçsız özel aralıkta karşılaştırma yoktur (`onceki_donem: null`).
- `bekleyen`: yalnız `durum=hepsi` iken; toplam en az 5 ve bekleyen oranı en az %30 (`yuzde` = bekleyen oranı).
- `one_cikan`: toplam en az 5 ve genel ortalamanın 1,5 katı; ayrıca her sütunun en yükseği (en az 5 ve ortalamanın 2 katı).
- Kişi sayısı 2'nin altındaysa kıyaslı gruplar (`ortalama_alti`, `hic_eklemedi`, `one_cikan`) boştur ve `kiyas_notu` dolar.
- Personeli ya da kategorisi boş kayıtlar ortalamaya katılır ama ayrıca listelenmez. Sıralama en kötüden başlar.
- `yuzde`: sayının ortalamaya oranı (yüzde, tam sayı); `degisim_yuzde`: önceki döneme göre değişim (yüzde, eksi = düşüş).
- Bu liste bakılacak yerleri gösterir, bir performans değerlendirmesi değildir.

```bash
curl -s -H "Authorization: Bearer kp_…" "https://panel.ornek/api/v1/personel-ozet?proje=OF&donem=ay&durumlar=1&esik=50"
```

Örnek yanıt (yalnız `durumlar`; `donem=ozel` ile 10 günlük bir aralık, her grupta yalnız ilk öğe gösterildi, `sayi` ve `kisi_sayisi` gerçek değerdir):

```json
"durumlar": {
  "esik": 50, "kisi_sayisi": 5, "kayit_sayisi": 75, "genel_ortalama": 15.0,
  "ortalamalar": {"30gün": 0.0, "ARK": 2.0, "CVPS": 8.4, "DDS": 0.4, "DDT": 0.0, "HGST": 4.2, "LPST": 0.0, "PRCST": 0.0, "S.ARK": 0.0, "btagsz": 0.0},
  "kiyas": true, "kiyas_notu": null,
  "onceki_donem": {"tarih1": "2025-03-01", "tarih2": "2025-03-10", "kayit_sayisi": 102},
  "gruplar": [
    {"kod": "ortalama_alti", "baslik": "Ortalamanın altında", "sayi": 3, "kisi_sayisi": 2, "ogeler": [
      {"kisi": "210", "sutun": "ARK", "sayi": 0, "ortalama": 2.0, "yuzde": 0, "onceki": null, "degisim_yuzde": null,
       "aciklama": "210, ARK kategorisinde ortalamanın yarısından az kayıt ekledi (0 / ort. 2,0 · %0)"}, …]},
    {"kod": "hic_eklemedi", "baslik": "Hiç eklemedi", "sayi": 1, "kisi_sayisi": 1, "ogeler": [
      {"kisi": "273", "sutun": "HGST", "sayi": 0, "ortalama": 4.2, "yuzde": 0, "onceki": null, "degisim_yuzde": null,
       "aciklama": "273 bu dönemde hiç HGST eklemedi (ort. 4,2)"}]},
    {"kod": "dusus", "baslik": "Önceki döneme göre düşüş", "sayi": 4, "kisi_sayisi": 4, "ogeler": [
      {"kisi": "190", "sutun": null, "sayi": 0, "ortalama": null, "yuzde": null, "onceki": 12, "degisim_yuzde": -100,
       "aciklama": "190: bu dönem hiç kayıt yok (önceki dönem 12)"}, …]},
    {"kod": "bekleyen", "baslik": "Onay bekleyeni yüksek", "sayi": 2, "kisi_sayisi": 2, "ogeler": [
      {"kisi": "210", "sutun": null, "sayi": 3, "ortalama": null, "yuzde": 38, "onceki": null, "degisim_yuzde": null,
       "aciklama": "210: onay bekleyen oranı yüksek (3 / 8 · %38)"}, …]},
    {"kod": "one_cikan", "baslik": "Öne çıkanlar", "sayi": 2, "kisi_sayisi": 1, "ogeler": [
      {"kisi": "280", "sutun": "CVPS", "sayi": 20, "ortalama": 8.4, "yuzde": 238, "onceki": null, "degisim_yuzde": null,
       "aciklama": "280, CVPS kategorisinde en çok kaydı ekledi (20 / ort. 8,4 · %238)"}, …]}
  ]
}
```

Beş grup her zaman bu sırayla döner (boş grupta `ogeler: []`); bir grupta en çok 500 satır verilir, `sayi` tüm sayıdır. `ortalamalar` katalogdaki her kategoriyi içerir; dönemde kaydı olmayan kategoriler `0.0` ile döner.

## 4. Alan sözlüğü

| Alan (`/kayitlar` JSON) | SQL sütunu | Anlamı |
|---|---|---|
| `id` | `id` | Kayıt numarası (panelde `#id`). |
| `proje` | `proje` | Proje kodu (OF, PA, …). |
| `kategori` | `kategori` | Kanıt kategorisinin görünen adı: **CVPS**, DDS, DDT, HGST, PRCST, LPST, ARK, S.ARK, btagsz, 30gün … ("bu personel kaç CVPS" sorusu bu alandır). |
| — | `giris_tipi` | `resim` / `yazili` (bot), `panel` (panelden bağlantıyla eklenen kayıt). |
| — | `kategori_code`, `kategori_mode` | Kategori kodu (ör. `cvpsz`) ve soru akışı türü (`tek_uye`, `ark_ana`, `ana_only`, `sessiz_tip`). |
| `tip` | `tip` | Yalnız sessiz_tip kategorilerinde (DDS, DDT): **`sessiz`** ya da **`telesekreter`**. |
| `personel` | `personel` | Kanıtın ait olduğu personel. |
| `uye_id`, `ana_uye_id`, `lead_id` | aynı | Üye / ana üye (arkadaş kategorilerinde) / lead kimlikleri. |
| `tarih` | `tarih` | Kanıt tarihi `YYYY-AA-GG SS:DD:ss`. |
| `onayli` (true/false) | `kt` (1/0) | Onay durumu. |
| `onaylayan`, `onay_zamani` | `kt_kim`, `kt_zaman` | Onaylayan panel kullanıcısı ve zamanı. |
| `ekleyen_id`, `ekleyen_ad` | aynı | Kanıtı ekleyen Telegram kullanıcısı (kimlik ve ad). Panelden eklenen kayıtta `ekleyen_id` = `panel:<kullanıcı>`, `ekleyen_ad` = panel kullanıcı adı. |
| `kaynak` | `kaynak` | Kaydın geldiği yer: `telegram` (bot), `panel` (2.3.6: panelden **Kanıt ekle**, kategori SMS), `legacy_excel` / `excel` (eski Excel aktarımı). |
| `link`, `link_turu` | aynı | Kanıt bağlantısı ve türü (ör. gyazo). |
| `aciklama` | `aciklama` | Açıklama metni. |
| `yorum_sayisi` | — | Kayıttaki yorum sayısı. |
| `gorsel_url` | — | Yalnız görsel izinli anahtarda: `/api/v1/gorsel/<id>` (görsel yoksa null). Yerel dosya, Gyazo, Snappark ve Teamzone kayıtlarında doludur; dış sitedeki görsel ilk istekte sunucuya kopyalanır. |

## 5. Hata kodları

Tüm hatalar `{"ok": false, "hata": "<Türkçe açıklama>", "kod": <HTTP kodu>}` biçimindedir.

| Kod | Ne zaman |
|---|---|
| 400 | Geçersiz parametre (tarih, `durum`, `adet`), hatalı JSON gövde, SQL söz dizimi/süre/parametre hatası. |
| 401 | Anahtar yok, biçimi yanlış, geçersiz, iptal edilmiş ya da süresi dolmuş. |
| 403 | Kapsam dışı proje istendi; SQL ya da görsel izni yok; SQL sorgusu izin verilmeyen bir tabloya/işleme erişiyor. |
| 404 | Kayıt yok ya da kapsam dışı; görsel yok; bilinmeyen uç; API kapalı (`API_ACIK=0`). |
| 422 | Kaydın görsel dosyası bozuk ya da görsel değil (`/api/v1/gorsel`). |
| 405 | Uç bu yöntemle çağrılamaz (ör. `GET /api/v1/sorgu`). |
| 413 | Gövde 64 KB'den büyük. |
| 429 | Hız sınırı aşıldı ya da SQL sorgu kuyruğu dolu; `Retry-After` başlığı kaç saniye beklenmesi gerektiğini söyler. |
| 500 | Beklenmeyen hata; yanıttaki `kayit_no`'yu panel yöneticisine iletin. |

## 6. Hız sınırı ve günlük

- Anahtar başına dakikada en çok `API_DAKIKA_SINIRI` istek (varsayılan 120; kayan 60 saniyelik pencere). Aşılınca 429 ve `Retry-After`.
- Aynı IP'den dakikada 30'dan fazla geçersiz anahtar denemesi (64 KB'den büyük gövdeli kimliksiz istekler dahil) de 429 alır.
- `/sorgu` ucunda ayrıca eşzamanlılık sınırı vardır (bkz. §3 SQL kuralları: en çok 2 sorgu, anahtar başına 1).
- Her istek panelde günlüğe yazılır (anahtar, zaman, uç, IP, durum kodu, süre, satır sayısı); günlük 90 gün saklanır (eski satırlar
  saatte bir budanır).
- "Yalnız onaylı" anahtarda `durum=bekleyen`/`hepsi` istenirse yok sayılır ve yanıtta `uyari` alanı bunu söyler.

## 7. Sunucu ayarları (.env)

| Anahtar | Varsayılan | Anlamı |
|---|---|---|
| `API_ACIK` | `1` | `1`/`evet`/`acik`/`on`/`true`/boş: açık. Başka her değer (`0`, `kapali`, yazım hatası…) kapalı: tüm `/api/v1` adresleri 404 döner (anahtarlar silinmez). |
| `API_SORGU_ESZAMANLI` | `2` | `/api/v1/sorgu` için sunucu genelinde aynı anda çalışabilecek sorgu (1–6; geçersiz değer 2 sayılır). |
| `API_DAKIKA_SINIRI` | `120` | Anahtar başına dakikalık istek sınırı (1'den küçük ya da geçersiz değer 120 sayılır). |
