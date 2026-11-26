# Kanıt Paneli 2.3.5 — personel kartları, kategori süzgeci, hatırlanan süzgeçler, API kullanım kılavuzu ve kategori temizliği (26 Kasım 2026)

2.3.4 üzerine `deploy/apply-update.sh` ile uygulanır (KURULUM §13, güncelleme yolu değişmedi). Veritabanı şeması ve `.env` değişmez, yeni ayar yoktur. Değişen dosyalar: `app/personel_ozeti.py`, `panel.py`, `api.py`, `cli.py`, yeni `app/api_kilavuz.py` ve `app/kategori_temizlik.py`, şablonlar (`_personel_ozet.html`, `ana.html`, `rapor_personel.html`, `kayitlar.html`, `api_anahtarlari.html`, `_api_kilavuz.html`, `katalog.html`, `kategori_temizligi.html`), `stil.css`, `rapor.js`. Bu belgede önce personel kartları, sonra API kılavuzu ve kategori temizliği anlatılır. Tarayıcı yeni dosyaları kendiliğinden alır (sürüm numaralı adresler).

## Ekip ne görür?

### Kategori süzgeci

Ana sayfadaki "Personel bazında kanıtlar" kartında ve **Rapor** sayfasında süzgeç çubuğuna **Kategori** seçimi eklendi: "Tüm kategoriler" ya da tek kategori (ör. CVPS). Listede önce seçili projelerin katalog kategorileri (katalog sırasıyla), sonra kayıtlarda geçen diğer adlar (btagsz, 30gün, S.ARK …), en sonda kategorisi boş kayıtlar için **(boş)** bulunur. Kullanıcı yalnız yetkili olduğu projelerin kategorilerini görür; proje seçiliyse liste o projeyle sınırlanır.

Kategori seçilince:

- özet çiplerinde "Kategori: CVPS" görünür, kişi/kanıt/onaylı/bekleyen sayıları yalnız o kategoriyi sayar;
- tabloda Toplam / Onaylı / Bekleyen yanında yalnız o kategori sütunu kalır (Sütun = **Tip** seçiliyse o kategorinin Sessiz / Telesekreter sayıları);
- kişi kartlarında yalnız o kategorinin kutusu görünür;
- rapor başlığına, yazdırma çıktısına, Excel'in "Bilgi" sayfasına ve dosya adına kategori eklenir (ör. `rapor-personel-of-ay-cvps-2026-11-26.xlsx`).

Büyük/küçük harf ve baştaki/sondaki boşluk, sekme ya da bölünmez boşluk fark etmez ("cvps", "CVPS " → CVPS); adın içindeki boşluklar olduğu gibi korunur ("S  ARK" ayrı bir addır). "İPTAL" ile "iptal" gibi yalnız Türkçe İ/ı harfiyle ayrılan yazımlar ayrı kutu olarak sayılır ve her kutu kendi kayıtlarını açar; Kayıtlar listesiyle aynı eşleme kullanılır, bu yüzden sayılar ile tıklanınca açılan liste birebir tutar. Listede olmayan bir ad adrese yazılırsa hata vermez, sıfır kayıt gösterir.

### Herkes için kişi kartları

"İlk 3" şeridinin yerine artık **her kişi için bir kart** vardır (tablo sırasıyla, en çok kanıt ekleyen önce). İlk üç kart altın / gümüş / bronz madalyasını korur.

- Kartta: sıra numarası, personel kodu (tıklanınca o kişinin seçili süzgeçlerdeki tüm kayıtları açılır), **N kanıt**, onaylı yüzdesi, onaylı ve bekleyen sayısı (bekleyen varsa kırmızı), kategori paylarını gösteren ince renkli çubuk.
- **Kategori kutuları:** kartın altında "CVPS 68", "ARK 8", "HGST 1" gibi küçük kutular — kategori renginde nokta, ad ve sayı. Yalnız sıfırdan büyük kategoriler, çoktan aza sıralı. **Kutuya tıklamak** Kayıtlar sayfasını o kişinin o kategorideki kayıtlarıyla açar (aynı proje, dönem ve durum; silinenler hariç) — açılan liste kutudaki sayı kadar kayıttır. "Grupla: Ekleyen" seçiliyse kutular ekleyene, "Sütun: Tip" seçiliyse tipe göredir. (boş) kutusu kategorisi boş kayıtları açar.
- İlk **6 kart** görünür. **Daha fazla göster (N kişi daha)** her basışta 12 kart daha açar (sayfa yenilenmez, düğme metni kalan kişi sayısını gösterir, klavyeyle kullanılabilir; odak ilk yeni kartın adına geçer). **Daha az göster** yeniden 6 karta döner.
- Geniş ekranda satırda 3 kart, 1100 px ve altında 2, telefonda 1 kart (kutular alt satıra sarar). Ana sayfada telefonda tablo yerine bu kartlar görünür. Koyu temada da aynı düzen.
- Yazdırmada kartlar basılmaz (rapor tablodur); kartlar da istenirse `…/rapor/personel?…&yazdir=1&kartlar=1`. `?kartlar=hepsi` tüm kartları baştan açık getirir (tarayıcıda betik kapalıysa "Tümünü göster" bağlantısı bunu kullanır).

### Hatırlanan süzgeçler (takım liderleri için)

Rapor sayfasında **Uygula**'ya basıldığında ya da bir seçim değiştiğinde süzgeçler bu tarayıcıda, kullanıcıya özel olarak hatırlanır. Menüden **Rapor**'a (süzgeçsiz adres) gelindiğinde son kullanılan süzgeçler kendiliğinden uygulanır ve başlığın altında "Son kullandığınız süzgeçler uygulandı. **Varsayılana dön**" notu görünür (× ile kapanır). **Varsayılana dön** hatırlananı siler. Ör. yalnız PA'dan sorumlu takım lideri bir kez "PA · Bu ay · CVPS" seçer, sonraki girişlerde rapor doğrudan bu seçimle açılır.

- Adreste herhangi bir süzgeç varsa (yer imi, paylaşılan bağlantı) hatırlanan uygulanmaz.
- Artık yetkisi olmayan bir proje hatırlanmışsa sayfa hata vermez: varsayılan görünüm açılır ve hatırlanan silinir.
- Hatırlama tarayıcıya özeldir (başka bilgisayarda varsayılanla açılır); sunucuda bir şey saklanmaz.
- Ana sayfa kartı her zaman varsayılanla açılır; kartta süzgeç seçildiyse "Tüm tablo ve rapor →" o seçimle, seçilmediyse hatırlanan süzgeçlerle açılır.

### Kayıtlar ve API

- Kayıtlar sayfası `kategori=__bos__` ile kategorisi boş kayıtları listeler (seçimde "(boş) — kategorisi olmayanlar" yazar). `tip` süzgeci 2.3.4'ten beri vardır.
- `GET /api/v1/personel-ozet` yeni `kategori` parametresini alır; yanıttaki `filtre.kategori` uygulanan adı (ya da `null`) gösterir (`API_KULLANIM.md` §3.6). Excel/CSV çıktıları da `kategori` parametresini taşır: Excel dosyasının bilgi satırında ve dosya adında kategori yazar; CSV tablo olarak içe aktarılabilsin diye ek satır almaz, seçilen kategori dosya adından anlaşılır (ör. `rapor-personel-of-ay-cvps-2026-11-26.csv`).

## Test

Yeni `tests/test_personel_kartlari_235.py` (9 test) ve tarayıcı senaryosu `tests/personel_kartlari_tarayici.js`: kategori süzgecinin tüm proje/dönem (özel tarih aralığı dahil)/durum/grup/sütun birleşimlerinde bağımsız SQL ile karşılaştırılması, sonunda sekme / bölünmez boşluk ya da içinde çift boşluk olan eski kategoriler ile "İPTAL" / "iptal" gibi Türkçe harf biçimlerinde sayı ile listenin birebir tutması, kart kutusu ve ad bağlantılarının Kayıtlar listesiyle birebir tutması, kategori seçeneklerinin yetkiyle sınırlanması, 6 kart / 12'şer açma / geri kapama / odak, betik kapalıyken `?kartlar=hepsi`, hatırlanan süzgeçler (yönlendirme, not, sıfırlama, yetkisi kalkan proje, döngü koruması), Excel/CSV/API ve 1280 px, koyu tema, 390 px telefon ekran görüntüleri. 2.3.4 testleri "İlk 3" yerine kişi kartlarına uyarlandı.

## Panelde API kullanım kılavuzu

**Yönetim → API anahtarları** sayfasına **Kullanım kılavuzu** kartı eklendi (başlıktaki "Kullanım kılavuzu" düğmesi karta götürür).
Kart, karşı sistemi kuracak kişiye `API_KULLANIM.md` dosyasını göndermeden çalışmaya başlaması için yeterli bilgiyi verir:

1. **Uçlar ve parametreler**: `/api/v1/ozet`, `/api/v1/kayitlar` (`kategori` süzgeci dahil), `/api/v1/kayit/<id>`,
   `/api/v1/personel-ozet`, `/api/v1/gorsel/<id>`, `POST /api/v1/sorgu`; hangi ucun hangi izni istediği.
2. **Hazır örnekler** (her birinde **Kopyala** düğmesi): curl (Linux/Mac; Windows'ta `curl.exe` notu), Windows PowerShell
   (`Invoke-RestMethod -Headers`, CSV'ye kaydetme), Python (`requests`, sayfa sayfa çekme), Excel Power Query (Veri → Web'den →
   Gelişmiş, `Authorization` üst bilgisi; Gelişmiş Düzenleyici kodu), Google E-Tablolar (Apps Script `UrlFetchApp`; `IMPORTDATA`
   başlık gönderemediği için çalışmaz notu). Tek istek en çok 500 kayıt verdiği için Python, Excel ve E-Tablolar örnekleri
   `sayfa_sayisi` kadar sayfayı sırayla çekip birleştirir (Excel'in "kolay yol" notu yalnız ilk 500 kaydı getirdiğini söyler). Örneklerdeki adres panelin gerçek dış adresidir (isteğin geldiği adres; vekil arkasında
   `TRUST_PROXY=1` ile `X-Forwarded-*` dikkate alınır), anahtar yerine `kp_ANAHTARINIZ` yazar.
3. **Örnek yanıtlar**: `/api/v1/ozet` ve `/api/v1/kayitlar?durum=onayli` (onay alanlarıyla). Testte aynı veriyle gerçek uç
   çağrılıp birebir karşılaştırılır.
4. **Hatalar ve istek sınırı**: 400/401/403/404/429 tablosu, hata gövdesi biçimi, `API_DAKIKA_SINIRI` (sayfada o anki değer).
5. **Güvenlik**: anahtar paroladır, yalnız başlıkta gönderilir, HTTPS, her sisteme ayrı anahtar, sızınca **İptal et**.

Uzun başvuru belgesi yine `sunucu/API_KULLANIM.md`'dir. Yeni ayar, şema değişikliği yok. Kod: `app/api_kilavuz.py`,
`app/templates/_api_kilavuz.html`.

## Kategori temizliği

Kayıtlardaki kategori metni serbest yazıdır (eski Excel içe aktarımı her yazımı olduğu gibi taşıdı); canlı veride 33 farklı değer var
(`30GÜN` / `30 GÜN`, `BTAGSZ` / `BTAGSIZ`, `CD` / `cd`, `WP kanıt telegrama  eklenmiştir`, …). Yeni araç bunları katalogdaki
kategorilerde birleştirir.

- **Yönetim → Proje / Kategoriler → Kategori temizliği** (`/yonetim/katalog/kategori-temizligi`, yalnız süperadmin). Her farklı değer
  baş/son boşluksuz ve büyük/küçük harf duyarsız gruplanır; grubun yazımları ve sayıları, toplam / onaylı / bekleyen / silinmiş,
  projeler, katalogda olup olmadığı ("Katalogda var", "Kodu eşleşiyor") ve **Kayıtlarda gör** bağlantısı görünür.
- Her grup için **Şuna dönüştür**: etkin katalog kategorileri, **— değiştirme —** (varsayılan) ya da **(boş) yap**. Katalog adıyla
  eşleşen gruplar kendi kategorisine önceden seçilidir; yazım farkı varsa (ör. katalog adı `cd` iken kayıtta `CD`) kayıtlar katalogdaki
  yazıma çekilir, fark yoksa hiçbir şey değişmez.
- **Önizle** hiçbir şey yazmaz; grup başına kaç kaydın değişeceğini (onaylı / bekleyen / silinmiş) gösterir. **Uygula** tek
  transaction'dır; önizlemeden sonra etkilenecek kayıtlar değiştiyse (yeni kayıt, düzenleme, onaylama/silme/geri alma) hiçbir şey yazmadan reddeder ve yeniden
  önizleme gösterir.
- Yazılan değer, botun yazdığıyla aynıdır: `kategori` = katalogdaki **görünen ad**, `kategori_code` = katalog **kodu** ((boş) yapılınca
  `''` ve boş kod). `kategori_mode` ve sorulan soruların anlık görüntüsü tarihî bilgi olduğu için değişmez. Değişen kayıtların sürüm
  sayacı artar (açık düzenleme penceresi eski kategoriyi geri yazamaz). Metni zaten hedef yazımında olan kayıtlara dokunulmaz
  (onların `kategori_code`'u da olduğu gibi kalır; panel, rapor ve süzgeç yalnız `kategori` metnine bakar).
- Silinmiş kayıtlar da dönüştürülür (geri alınınca tutarlı kalsınlar) ve sonuçta ayrı sayılır.
- Değişen her grup için İşlem Geçmişi'ne bir **Kategori birleştirme** (`kategori_birlestir`) satırı yazılır: eski yazımlar ve
  sayıları, yeni değer, kayıt sayısı, kaç tanesinin silinmiş olduğu.
- Aynı dönüşümü tekrar uygulamak hiçbir kaydı değiştirmez ve yeni satır yazmaz.
- **Katalog sayfası**: her kategorinin yanında kayıt sayısı (adı o yazımla eşleşen silinmemiş kayıtlar) ve not: "Pasif yapınca bot yeni
  kanıt için sunmaz; eski kayıtlar etiketini korur".
- **Sunucu komutu** (aynı işlem, aynı İşlem Geçmişi satırları; `--kim` ile kullanıcı adı, varsayılan `sunucu-cli`):

  ```bash
  cd /opt/kanit-paneli && runuser -u kanit -- .venv/bin/python -m app.cli kategori-temizle --listele
  runuser -u kanit -- .venv/bin/python -m app.cli kategori-temizle --donustur "30 GÜN=30gün" --donustur "BTAGSIZ=btagsz" --donustur "WP kanıt telegrama  eklenmiştir=(boş)" --onizle
  runuser -u kanit -- .venv/bin/python -m app.cli kategori-temizle --donustur "30 GÜN=30gün" --donustur "BTAGSIZ=btagsz" --donustur "WP kanıt telegrama  eklenmiştir=(boş)"
  ```

  stdout JSON, stderr Türkçe tablo/özet. `YENI` katalog kodu ya da görünen adıdır; boşaltmak için `(boş)`. Çıkış kodu: **0** başarı
  (hiçbir şey değişmese de), **1** hata (geçersiz/pasif hedef, yanlış biçim, aynı değere iki hedef; hiçbir şey yazılmaz).

### Operatör için adım adım

1. **Hangi kategoriler kalacak?** Ekip gerçekte hangilerini kullanıyorsa (Telegram'da seçtikleri) onlar kalır. Kategori temizliği
   sayfasındaki sayılar yardımcı olur: çok kayıtlı olanlar gerçek kategorilerdir; 1-2 kayıtlı tuhaf yazılar (`MEVCUT ÜYE`,
   `2667965 LEAD`, `R.Cumada Görüşme mevcuttur.`) büyük olasılıkla yanlışlıkla kategori sütununa yazılmış notlardır.
2. **Kullanılmayanları pasif yapın:** Yönetim → Proje / Kategoriler → kategoriyi açın → **Aktif** işaretini kaldırın → Kaydet.
   Bot onu artık sunmaz; eski kayıtlar etiketini korur. Hiçbir şey silinmez, istediğiniz an yeniden işaretleyebilirsiniz.
3. **Yazımı katalogda düzeltin** (gerekirse): ör. görünen adı `cd` yerine `CD` olsun istiyorsanız önce katalogda düzeltin; temizlik
   kayıtları katalogdaki yazıma çeker.
4. **Yedek alın:** sunucuda `sudo /usr/local/sbin/kanit-yedek.sh` çalıştırın; çıktıdaki `YEDEK_DOGRULANDI: panel-YYYYMMDD.db.gz`
   satırındaki dosya adını not edin (`/var/backups/kanit-paneli/gunluk/` altındadır). Bot sayfasındaki **SQLite yedeği al**
   başka klasöre `.sqlite3` olarak yazar ve `--geri-yukle` onu kabul etmez; bu iş için onu kullanmayın.
5. **Birleştirin:** Kategori temizliği sayfasında her tuhaf değer için **Şuna dönüştür** seçin (emin değilseniz **— değiştirme —**
   bırakın) → **Önizle** → sayıları kontrol edin → **Uygula**. Sonuç kartında kaç kaydın değiştiği yazar; İşlem Geçmişi'nde
   "Kategori birleştirme" satırları görünür. Rapor sayfasındaki sütunlar ve Kayıtlar süzgeci hemen birleşmiş değeri gösterir.
6. **Geri almak:** tek yol yedekten geri yüklemektir:
   `sudo /usr/local/sbin/kanit-yedek.sh --geri-yukle /var/backups/kanit-paneli/gunluk/panel-YYYYMMDD.db.gz --dry-run` ile planı görün,
   sonra `--dry-run` olmadan çalıştırın (README §11). Yedekten sonra gelen yeni kayıtlar da geri gider; bu yüzden temizliği yedeği
   aldıktan hemen sonra yapın.

Şema değişikliği ve yeni ayar yok. Kod: `app/kategori_temizlik.py`, `app/templates/kategori_temizligi.html`, `app/cli.py`
(`kategori-temizle`). Testler: `tests/test_kategori_temizlik_235.py` (8), `tests/test_api_kilavuz_235.py` (8).
