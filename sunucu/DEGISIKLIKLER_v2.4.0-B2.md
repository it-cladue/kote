# 2.4.0 — İşletim (B2): yedekler, sistem durumu, çalışma ayarları

Bu bölüm sunucuyu yöneten kişi içindir. Üç yenilik var: geri yüklenebilir yedekler ve yedek listesi, ana sayfada
"Sistem durumu" kartı, .env'e dokunmadan değiştirilebilen "Çalışma ayarları" sayfası.

## Güncellemeden sonra bir kez yapın

```
cd /opt/kanit-paneli && sudo bash deploy/setup-backup.sh
```

Bu komut yeni yedek betiğini ve zamanlayıcı birimini kurar (gece çalışması artık `--zamanlayici` ile çağrılır). Yapılmazsa
eski betik çalışmaya devam eder; yedek alınır ama panel son yedeği ve listeyi göremez (kartta "Son yedek" kırmızı kalır).

## 1. Yedekler

**Nerede?**

| Tür | Klasör | Dosya adı | Saklama |
|---|---|---|---|
| Gece (otomatik, 03:17) | `/var/backups/kanit-paneli/gunluk/` (yalnız root) | `panel-YYYYAAGG.db.gz` | 14 gün |
| Sunucuda elle | aynı klasör | `panel-YYYYAAGG-SSDDSS.db.gz` | son 10 |
| Panelden ("Yedek al") | `/opt/kanit-paneli/data/yedekler/` | `panel-YYYYAAGG-SSDDSS.db.gz` | son 10 |

- Elle ya da panelden alınan yedek **gece dosyasının üzerine yazmaz** (adında saat vardır). Eskiden aynı gün elle alınan yedek
  o günün gece dosyasını eziyordu.
- Panelin düğmesi artık **"Yedek al (geri yüklenebilir)"** adını taşır ve gece yedeğiyle **aynı biçimde** (`.db.gz`, bütünlük
  denetimli) yazar. Eski "SQLite yedeği al" dosyası (`.sqlite3`) `--geri-yukle` ile açılmıyordu; bu sorun kalktı.
- Panel yedekleri veri klasöründedir, çünkü web servisi güvenlik gereği yalnız oraya yazabilir. Gece yedekleri root'a ait
  klasörde kalır; panel ele geçirilse bile onları silemez.
- Her yedekten sonra betik `data/son_yedek.json` (son yedek) ve `data/yedekler.json` (liste özeti: ad, boyut, tarih, kayıt sayısı)
  yazar; panel bunları okur. Her yedek klasöründe `MANIFEST.tsv` vardır (kayıt sayısı buradan gelir).
- Gece (zamanlayıcı) yedeği ayrıca `data/son_gece_yedegi.json` yazar. Sistem durumu kartındaki "Son yedek" rengi **yalnız gece
  yedeğine** bakar: panelden ya da sunucuda elle alınan yedek satırda ek bilgi olarak görünür ama satırı yeşile çevirmez
  (gece işi bozulduysa bunu gizlemesin; panel yedekleri ayrıca panelin silebileceği veri diskindedir).
- Telegram'daki `/yedekle` komutu bu sürümde eski biçimde kalır (bot ekibinin işi); panel düğmesini kullanın.

**Listeleme**

- Panel: Yönetim menüsü → Bot sayfası → "Yedekler" bölümü (son 5) ya da `/yonetim/yedekler` (tamamı). Ana sayfadaki Sistem durumu
  kartında da "Yedekler" düğmesi var.
- Sunucu: `sudo /usr/local/sbin/kanit-yedek.sh --liste` (tablo) ya da `--liste --json`.

**Geri yükleme — adım adım**

1. Sunucuya SSH ile bağlanın.
2. Listeden yedeği seçin (panelde her satırın yanında komut ve "Kopyala" düğmesi var).
3. Önce deneyin (hiçbir şeye dokunmaz):
   `sudo /usr/local/sbin/kanit-yedek.sh --geri-yukle panel-20261126-101500.db.gz --dry-run`
   (yalnız dosya adı yeterli; betik gece ve panel klasörlerinde arar. Tam yol da verilebilir.)
4. Plan doğruysa `--dry-run` olmadan çalıştırın. Betik yedeği açıp doğrular (bozuksa durur), paneli ve botu durdurur, mevcut
   veritabanını `/root/kanit-onceki/<zaman>/` altına kopyalar, yedeği yerine koyar, servisleri başlatır.
5. Çıktının sonunda `GERI_YUKLEME_TAMAM` yazar. Yedekten sonra eklenen kayıtlar geri gelmez.

**Kategori temizliği:** sayfanın üstünde "Önce yedek al" düğmesi var; yedek alınır, aynı sayfaya dönülür, dosya adı ve geri
yükleme komutu üstte yazar. (Düğme başka sayfalara da eklenebilir: `templates/_yedek_dugmesi.html`.)

## 2. Sistem durumu kartı (ana sayfa, yalnız süperadmin)

Her satır yeşil (normal), sarı (dikkat), kırmızı (sorun) ya da gri (bilgi yok) olur. Sarı/kırmızı satırın altında kısa açıklama ve
sunucuda çalıştırılacak komut (kopyalama düğmesiyle) yazar.

| Satır | Yeşil | Sarı | Kırmızı |
|---|---|---|---|
| Web sunucusu | sürüm ve çalışma süresi | — | — |
| Telegram botu | son sinyal < 2 dk | < 10 dk, ya da bot duraklatılmış | ≥ 10 dk ya da hiç sinyal yok |
| Son yedek (gece yedeği) | < 26 saat | < 50 saat | daha eski, hiç gece yedeği yok ya da bütünlük bozuk (panel yedeği sayılmaz) |
| Gece görsel işi | son 36 saatte başarılı | daha eski (< 7 gün), hız sınırı ya da servis arızası | erişim hatası / hata / 7 günden eski (hiç çalışmadıysa gri) |
| Hatırlatma işi | son çalışma < 20 dk (aralık 10 dk iken) | < 60 dk | daha eski (aralık 0 ise gri: kapalı) |
| Disk | < %80 dolu | < %90 | ≥ %90 |
| Veritabanı boyutu | bilgi | — | — |
| Bot kuyruğu | işlenemeyen yok, bekleyen < 20 | işlenemeyen var ya da bekleyen ≥ 20 | bekleyen ≥ 200 |

- Kırmızı satır için süperadminlere **günde bir, satır başına bir** "Sistem" bildirimi gider (zil + Bildirimler sayfasında "Sistem"
  türü; proje rozeti yoktur, düğme "Sistem durumunu aç"). Tıklayınca ana sayfadaki kart açılır. Bildirim, panelin 10 dakikalık hatırlatma işiyle üretilir.
- JSON: `/yonetim/sistem-durumu.json`. Sunucuda: `cd /opt/kanit-paneli && sudo runuser -u kanit -- .venv/bin/python -m app.cli durum` (kırmızı satır varsa çıkış kodu 1; `--json`, `--uyar`).
  (Not: eski `/durum.json` adresi aynen duruyor; yeni kart onu kullanmaz.)

## 3. Çalışma ayarları (`/yonetim/ayarlar`)

Hatırlatma, bildirim, görünürlük, API ve görsel ayarları artık panelden değiştirilebilir. Gizli anahtarlar, parolalar, dosya
yolları ve port **listede yoktur** ve buradan hiçbir şekilde yazılamaz.

**Hangi değer geçerli? (öncelik)**

1. Panelde kaydedilen değer (sayfada **DB** etiketi),
2. yoksa `.env` dosyasındaki değer (**.env**),
3. o da yoksa varsayılan (**varsayılan**).

"Varsayılana dön" yalnız panel değerini siler; `.env`'de değer varsa o geçerli olur. `.env`'deki değer geçersizse sayfa bunu
kırmızıyla yazar ve **okuyucunun gerçekte kullandığı değeri** gösterir (eskiden sessizce varsayılana düşüyordu): geçersiz
yazım → varsayılan; bazı üst sınırlar kırpılır (ör. `BEKLEYEN_OZET_SAAT=30` → 24); bazı sınır dışı değerler olduğu gibi kullanılır
(ör. `HATIRLATMA_GUN=500`). "Şu an geçerli değer" sütunu ve `ayar --listele` bu gerçek değeri yazar. `DIS_GORSEL_PROXY` .env'de
yoksa `GYAZO_PROXY` değeri geçerlidir (sayfada not olarak yazar).

- Her alan kaydedilirken denetlenir; hatalı değerde Türkçe açıklama alanın yanında çıkar, girilen değer kaybolmaz.
- Her değişiklik İşlem Geçmişi'ne eski ve yeni değerle yazılır ("Çalışma ayarını değiştirdi").
- Yeniden başlatma gerekmez: değer bir sonraki istekte (görünürlük, API) ya da hatırlatma işinin bir sonraki turunda geçerli olur.
  İstisnalar sayfada "Not" olarak yazar: Gyazo/Snappark görsel ayarları panel görünümü için `sudo systemctl restart kanit-web`
  ister (gece işi bir sonraki çalışmada uygular); hatırlatma işi sunucu açılırken 0 (kapalı) idiyse açmak için bir kez restart.
- Değiştirme yetkisi **sahip** hesabındadır; süperadmin sayfayı salt okunur görür. (Sahip rolü aynı sürümde ayrıca geliyor;
  o gelene kadar süperadmin değiştirebilir.)
- Sunucudan (kanit hesabıyla; root olarak çalıştırmayın, veritabanı yan dosyaları root sahipli kalır):
  `cd /opt/kanit-paneli && sudo runuser -u kanit -- .venv/bin/python -m app.cli ayar --listele`,
  `… ayar BEKLEYEN_OZET_SAAT 3`, `… ayar BEKLEYEN_OZET_SAAT --sil`.

Gruplar ve ayarlar: **Hatırlatmalar** (HATIRLATMA_GUN, HATIRLATMA_TEKRAR_GUN, HATIRLATMA_GUNLUK_SINIR, HATIRLATMA_KONTROL_DK,
HATIRLATMA_SAAT, HATIRLATMA_SAAT_TOPLU), **Bildirimler** (BEKLEYEN_OZET_SAAT, BEKLEYEN_OZET_PENCERE, BEKLEYEN_OZET_YONETICI,
GUN_SONU_SAAT, GUN_SONU_ALICILAR), **Görünürlük** (ONAYSIZ_GORUNUM, PANEL_EKLEME_KATEGORI), **API** (API_ACIK, API_DAKIKA_SINIRI),
**Görseller** (GYAZO_PROXY, DIS_GORSEL_PROXY).

## Teknik özet (geliştirici / koordinatör)

- Yeni: `app/ayarlar.py` (katman + kayıt listesi), `app/durum.py`, `app/yedek.py`, `app/isletim.py` (blueprint; panel.py sonunda
  kaydedilir), şablonlar `ayarlar.html`, `yedekler.html`, `_sistem_durumu.html`, `_yedekler_tablo.html`, `_yedek_dugmesi.html`,
  `static/isletim.css`. Şema değişikliği yok (mevcut `ayarlar` tablosu: `ayar:<AD>`, `is:hatirlatma`, `is:gece_gorsel`).
- Okuyucular katmana bağlandı: `hatirlatma.ayarlar(ayar, conn)`, `panel._onaysiz_modu/_hatirlatma_gun`, `api.acik_mi/dakika_siniri`,
  `katalog.panel_kategori_etiketi(conn)`, `cli gyazo-onbellekle`, panel açılışındaki görsel çözücü.
- `kanit-yedek.sh`: `--zamanlayici`, `--liste [--json]`, ad ile `--geri-yukle`, her yedekte `YEDEK_DOGRULANDI` satırı, MANIFEST,
  işaretler; elle/gece yedekleri ayrı saklanır. `kanit-yedek.service` `--zamanlayici` ile çalışır.
- Sahip kapısı: `isletim.sahip_gerekli` / `_sahip_mi()` — B1'in `panel.sahip_gerekli`, `panel.sahip_mi` ya da `g.yk['sahip']`
  alanı varsa onu kullanır; yoksa süperadmin (TODO B1). `durum._alicilar` şu an yetkisi `admin` olanları alır; sahip rolü ayrı
  bir yetki metniyle gelirse oraya eklenmeli.
- Menü için tek satır (base.html, Yönetim açılır menüsü, "API anahtarları" satırının altına):
  `<a href="{{ url_for('isletim.ayarlar') }}" class="{{ 'aktif' if ep in ('isletim.ayarlar','isletim.yedekler') }}">Çalışma ayarları / Yedekler</a>`
