# 2.3.5

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
