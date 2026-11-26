# Kanıt Paneli 2.4.0 — B1: Sahip rolü, IP erişim sınırı, onaylar ve İşlem Geçmişi

Bu belge 2.4.0'ın "roller ve güvenlik" parçasını anlatır. Sürüm numarası ve README/KURULUM birleştirmesi ayrıca yapılır.

## Kısaca ne değişti?

| Konu | Önce | Şimdi |
|---|---|---|
| En üst rol | Süperadmin | **Sahip** (süperadminin üstü). Süperadminler aynen çalışmaya devam eder |
| API anahtarları sayfası | Her süperadmin | **Yalnız sahip** (menüde de yalnız sahibe görünür) |
| Süperadmin hesaplarını açma / düzenleme / pasife alma / şifre sıfırlama, rol yükseltme-düşürme | Her süperadmin | **Yalnız sahip** |
| IP ile erişim sınırı | Yok (yalnız Cloudflare kuralı mümkündü, IP:18443 yolu açıktı) | **Yönetim → Erişim sınırı**: panel ve API için izin listesi, iki yolda da çalışır |
| Tehlikeli işlemler | Tek tıkla (bazılarında tarayıcı "Emin misiniz?") | Kullanıcı adını / anahtar adını **yazarak onay** (sunucu da doğrular) |
| Başlıktaki rol yazısı | Herkese "SÜPERADMIN" ya da "ADMIN" | Gerçek yetkiden: **Sahip / Süperadmin / Takım lideri / Düzenleyici / Görüntüleyici** |
| İşlem Geçmişi | Kullanıcı/işlem/anahtar araması, ham JSON ayrıntı | Kayıt no, personel, açıklama, IP ile arama; **IP sütunu**; okunur ayrıntı (+ "Ham"); **CSV indir**; Bugün / Son 7 gün / Son 30 gün / Bu ay düğmeleri |

## 1. Sahip rolü

* Sahip her şeyi yapar: süperadminin yaptığı her şey + süperadmin/sahip hesaplarını yönetme + API anahtarları + erişim sınırı.
* Süperadmin: tüm projeler, kullanıcılar (proje kullanıcıları), katalog, bot, arşiv, raporlar, çıktı, kategori temizliği — eskisi gibi.
* Mevcut hesaplar değişmez: süperadminler süperadmin kalır, veri taşıma yoktur.

### İlk kurulum: sahibi belirleme (bir kez)

Güncellemeden sonra hiç sahip yoktur. Bir süperadmin **Yönetim → Kullanıcılar** sayfasının üstündeki **"Sahip hesabını belirleyin"** kartından:

1. "Sahip olacak hesap" listesinden kendini (ya da başka bir hesabı) seçer.
2. Onay kutusuna o kullanıcı adını yazar → **Sahip yap**.

Bu yalnız etkin sahip yokken çalışır ve İşlem Geçmişi'ne **Sahip ataması** olarak yazılır. Kendini seçen oturumda kalır; başkasını seçerseniz onun açık oturumları kapanır. Sonrasında yeni sahip/süperadmin atamasını yalnız sahip yapar (hesabın **Düzenle** formunda "Sahip" seçip kullanıcı adını yazarak).

Sunucudan (SSH) da yapılabilir:

```
cd /opt/kanit-paneli
runuser -u kanit -- .venv/bin/python -m app.cli kullanici-rol admin sahip
```

`kullanici-rol <ad> sahip | admin | 'OF:oku,kt;PA:oku'` rolü değiştirir; `admin-ekle <ad> --sahip --password-env KANIT_PW` sahip hesabı açar. Son etkin sahip kapatılamaz ve rolü düşürülemez (önce başka bir hesabı sahip yapın).

### Yazılı onay isteyen işlemler

| İşlem | Ne yazılır |
|---|---|
| Rol sınıfı değişikliği (proje kullanıcısı ↔ süperadmin ↔ sahip), yeni süperadmin/sahip hesabı açma | Hedef kullanıcı adı |
| Süperadmin/sahip hesabını pasife alma | Hedef kullanıcı adı |
| İlk sahip ataması | Seçilen kullanıcı adı |
| API anahtarını iptal etme | Anahtarın adı |
| Erişim listesini temizleme / dolu listeyi boşaltma | Kendi kullanıcı adınız |

Onay alanı Kullanıcılar formunda yalnız gerektiğinde açılır ve nedeni yazar ("Rol değişikliği: Proje kullanıcısı → Süperadmin"). Onay sunucuda tekrar denetlenir; büyük/küçük harf ve baştaki/sondaki boşluk önemsizdir. Hepsi İşlem Geçmişi'ne eski/yeni değerlerle yazılır.

## 2. Erişim sınırı (IP izin listesi) — işletmen kılavuzu

### Hangi yolu seçmeliyim?

Panele iki yoldan girilebiliyor: **alan adı** (Cloudflare üzerinden) ve **sunucunun IP adresi** (`https://217.156.123.36:18443`).

| Seçenek | Alan adı yolu | IP:18443 yolu | API | Not |
|---|---|---|---|---|
| (a) Yalnız Cloudflare WAF kuralı | Korunur | **Açık kalır** (kanit-ip-proxy kapatılana kadar) | Alan adından gelen API korunur | Cloudflare paneli: Security → WAF → Custom rules → "IP Source Address is not in {ofis IP}" → Block |
| (b) Panelin kendi listesi (bu sürüm) | Korunur | Korunur | Ayrı liste + anahtar başına liste | Giriş sayfası dahil her sayfa; sunucuda tek yerden |
| (c) İkisi birden | Korunur (Cloudflare'da daha erken kesilir) | Korunur | Korunur | En sıkı |

**Öneri: (b), istenirse (c).** Yalnız Cloudflare'da (a) kalırsanız IP:18443 yolu açık kalır; o yolu kapatmak için kurulum belgesindeki son adım (`systemctl disable --now kanit-ip-proxy`) gerekir.

### Panelden ayarlama (sahip)

1. **Yönetim → Erişim sınırı** sayfasını açın. "Şu anki adresiniz" kutusunda internete çıktığınız adres yazar.
2. **Panel listesine ekle** düğmesi bu adresi kutuya yazar. Gerekirse diğer adresleri ekleyin (satır başına bir tane).
3. **Kaydet**. Değişiklik hemen geçerli olur.

Yazım örnekleri: tek adres `85.105.12.34` · blok `85.105.12.0/24` (85.105.12.0–255) · geniş blok `85.0.0.0/8` · IPv6 `2a02:4780:1::/48` · açıklama `85.105.12.34  # ofis`. Boş liste = sınır yok.

* **API listesi** (sayfadaki ikinci kutu) bütün API anahtarlarına uygulanır; ayrıca **API anahtarları** sayfasında her anahtara ayrı IP listesi verilebilir (oluştururken ya da sonra "Yönet" → "IP listesini kaydet"). İkisi de doluysa istek ikisine de uymalıdır. İzinsiz adres `403` ve `"neden": "ip_izinsiz"` alır.
* Panel listesi API'yi, API listesi paneli etkilemez.

### Ofisin dış (public) IP adresini bulmak

* Ofisteki bir bilgisayardan paneli açın: **Erişim sınırı** sayfasındaki "Şu anki adresiniz" doğrudan budur (en güvenilir yol).
* Ya da Cloudflare paneli → alan adı → Analytics/Security Events'te kendi isteğinizin "Source IP" değeri.
* **Dikkat:** ev/ofis internet hatlarının çoğunda adres sabit değildir; modem yeniden başlayınca ya da sağlayıcı değiştirince değişir. Değişirse panel sizi engeller. Kalıcı çözüm: sağlayıcıdan **sabit IP** istemek. Geçici çözüm: sağlayıcınızın bloğunu yazmak (ör. `/24`); blok genişledikçe koruma zayıflar. Mobil veriden girecek kişiler için liste uygun değildir (adresleri sürekli değişir).

### Kendinizi dışarıda bırakmamak için

* Şu anki adresinizi içermeyen bir panel listesi, **"Kendi adresimi dışarıda bırakmayı anlıyorum"** işaretlenmeden kaydedilmez.
* Dolu bir listeyi tamamen boşaltmak (sınırı kaldırmak) kendi kullanıcı adınızı yazmayı ister.
* Sunucunun kendisinden doğrudan gelen istekler (127.0.0.1, ör. sağlık denetimi) sınırdan muaftır (`ERISIM_LOOPBACK_SERBEST=1`, varsayılan). `0` yapılırsa yalnız `/saglik` muaf kalır.
* `/saglik` (yalnız "OK" döndürür), sunucu kendini kendi nginx'i üzerinden (IP:18443 yolu, `X-Forwarded-For: 127.0.0.1`) denetlediğinde de muaftır; `setup-ip-https.sh` sağlık denetimi liste doluyken de çalışır.
* **Kurulum betiğini yeniden çalıştırmadan önce:** `setup-cloudflare-https.sh` 2/3 adımında alan adını sunucunun **kendi dış IP'si** üzerinden dener; panel listesi doluysa bu istek 403 alır ve betik hata verir. Betiği çalıştırmadan önce sunucunun dış IP'sini (ör. `217.156.123.36`) listeye ekleyin ya da listeyi geçici olarak boşaltın (`erisim-izin --temizle`, iş bitince yeniden doldurun). `apply-update.sh` etkilenmez (doğrudan `127.0.0.1:18080` kullanır).
* **Veritabanı okunamazsa:** liste ayarı okunamadığında (ör. anlık veritabanı kilidi) panel kapanmasın diye o istek **sınırsız geçer** ve durum `journalctl -u kanit-web` günlüğüne "Erişim sınırı okunamadı" diye yazılır. Kesin koruma isteniyorsa Cloudflare kuralını da kullanın (seçenek c).
* Engellenen kişi şu sayfayı görür: "Bu adresten erişim izinli değil (IP: …)". Bu IP'yi size iletmesi yeterlidir.

**Acil durum (SSH):**

```
cd /opt/kanit-paneli
runuser -u kanit -- .venv/bin/python -m app.cli erisim-izin --goster              # listeleri göster
runuser -u kanit -- .venv/bin/python -m app.cli erisim-izin --ekle 85.105.12.34   # panel listesine ekle (--tur api ile API'ye)
runuser -u kanit -- .venv/bin/python -m app.cli erisim-izin --temizle             # iki listeyi de boşalt (--tur panel|api)
```

Komutlar İşlem Geçmişi'ne `sunucu-cli` adıyla yazılır; yeniden başlatma gerekmez.

### TRUST_PROXY=1 şart

Panel ziyaretçi adresini nginx'in ilettiği `X-Forwarded-For` başlığından öğrenir; waitress bu başlığa yalnız `TRUST_PROXY=1` iken ve yalnız `GUVENILEN_PROXY` (127.0.0.1) adresinden gelen bağlantıda güvenir. Alan adı yolunda nginx gerçek adresi Cloudflare'ın `CF-Connecting-IP` başlığından (yalnız Cloudflare aralıklarından gelirse) alır; IP:18443 yolunda doğrudan bağlantı adresidir. İki nginx de `X-Forwarded-For $remote_addr` ile başlığı ezer, bu yüzden dışarıdan sahte başlık gönderilemez.

`TRUST_PROXY=0` iken her ziyaretçi 127.0.0.1 görünür. Bu durumda waitress `X-Forwarded-For` başlığını silmez ama uygulamaz (`clear_untrusted_proxy_headers=False`); panel böylece durumu fark eder (döngü adresi + `X-Forwarded-For`): bu durumda muafiyet uygulanmaz (liste doluysa herkes engellenir — güvenli taraf), Erişim sınırı sayfası kırmızı **"TRUST_PROXY=1 gerekli"** uyarısı gösterir ve panel listesi kaydedilemez. IP:18443 kurulum betiği (`deploy/setup-ip-https.sh`) `.env` dosyasına `TRUST_PROXY=1` yazar ve güncelleme betiği bunu denetler; `erisim-izin --goster` de değilse uyarır.

### .env ile (isteğe bağlı)

`IZINLI_IPLER=85.105.12.34,10.0.0.0/8` ve `API_IZINLI_IPLER=...` başlangıç değeri olarak okunur. Panelden ya da `erisim-izin` komutuyla bir kez kaydedildikten sonra veritabanındaki değer geçerlidir (`--temizle` bu yüzden her zaman işe yarar).

## 3. İşlem Geçmişi

* **Ara** kutusu: kayıt numarası (`1234` ya da `#1234`), kayıt anahtarı, kaydın personeli, kullanıcı, işlem, açıklama ve (yöneticilerde) IP adresi.
* **IP** sütunu yalnız süperadmin/sahipte görünür; IP'ye tıklamak o adresin işlemlerini süzer. Kullanıcı işlemleri (ekleme/güncelleme/kilit açma) artık IP ile yazılır.
* Ayrıntı sütunu rol, durum, alan değişikliklerini ve erişim listesi değişikliğini okunur yazar ("Rol: OF: oku → Süperadmin — …", "Panel listesi: (boş — sınır yok) → 85.105.12.34"). Özgün değer **Ham** düğmesinin altında.
* **CSV indir**: ekrandaki süzgecin tamamı (en çok 50.000 satır), Türkçe Excel biçiminde (UTF-8 BOM, `;`), formül enjeksiyonuna karşı güvenli. İndirme İşlem Geçmişi'ne yazılır.
* Hızlı tarih düğmeleri: Bugün, Son 7 gün, Son 30 gün, Bu ay.
* Yeni işlem adları: Sahip ataması, Erişim sınırı ayarı, Erişim engeli (IP) — dakikada IP başına en çok bir satır —, API anahtarı IP listesi, İşlem Geçmişi CSV.

## 4. Teknik notlar (geliştirici)

* `app/yetki.py`: `coz('sahip')` → `admin=True, sahip=True`; `kanonikle` eş anlamlıları (`owner`, `sistem sahibi`) `sahip`e çevirir; `rol_etiketi`, `rol_kodu`, `sahip_mi`; `SAHIP_GEREKLI_EYLEMLER` kümesi (endpoint adları). `panel.sahip_gerekli` süsleyicisi ucu kümeye ekler; `panel.before()` kümedeki uçlarda sahip olmayana 403 döner — başka modüller uç adlarını kümeye ekleyerek aynı korumayı alır.
* `app/kullanicilar.py`: `yonetim_denetimi` (Yasak → 403), `onay_gerekli`, `onay_dogru`, `sahip_ata`, son sahip koruması; `ekle/guncelle` `ip=` alır.
* `app/erisim.py`: liste ayrıştırma (IPv4/IPv6/CIDR, IPv4-eşlemeli IPv6), `ayar_oku(conn, 'panel'|'api')` / `ayar_yaz(conn, tur, metin, kim, ip)` (Ayarlar sayfası bu ikisini çağırabilir), `panel_izinli`, `api_izinli`, `red_kaydet`, `durum_ozeti`. Saklama: `ayarlar` tablosu `izinli_ipler`, `api_izinli_ipler`.
* Şema (eklemeli): `api_anahtarlari.izinli_ipler TEXT`; bayrak `core_schema_240_erisim`.
* API: genel liste anahtar doğrulamasından önce (izinsiz adres anahtar deneyemez), anahtar listesi doğrulamadan sonra, kapsam/hız denetiminden önce.
* Yeni uçlar: `/yonetim/erisim` (sahip), `/denetim.csv`.
