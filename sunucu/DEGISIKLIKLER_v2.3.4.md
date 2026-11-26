# Kanıt Paneli 2.3.4 — personel bazında kanıt özeti ve rapor (26 Kasım 2026)

2.3.3 üzerine `deploy/apply-update.sh` ile uygulanır (KURULUM §13, güncelleme yolu değişmedi). Veritabanı şeması ve `.env` değişmez, yeni ayar yoktur. Değişen dosyalar: panel ekranı (`ana.html`, yeni `rapor_personel.html` ve `_personel_ozet.html`, `base.html` menüsü, `kayitlar.html`), `stil.css`, yeni `rapor.js`, yeni `app/personel_ozeti.py`, `panel.py`, `api.py`. Tarayıcı yeni dosyaları kendiliğinden alır (sürüm numaralı adresler).

## Ekip ne görür?

### Ana sayfada "Personel bazında kanıtlar" kartı

"Proje bazında iş yükü" kartlarının hemen altında, "Son işlemler"den önce yeni bir kart vardır: hangi temsilci (personel) hangi kategoriden kaç kanıt eklemiş.

- **Süzgeç çubuğu:** Proje (tek proje ya da tüm yetkili projeler), Dönem (**Bugün · Bu hafta · Bu ay · Son 30 gün · Tümü**; hafta pazartesi başlar, "bugün" sunucunun takvim günüdür — ana sayfadaki "Bugün eklenen" sayacıyla aynı), Durum (Tümü / Onaylı / Bekleyen), Grupla (**Personel** ya da **Ekleyen** = kanıtı Telegram'dan ekleyen kişi). Seçim değişince sayfa kendiliğinden yenilenir; seçimler adreste kalır (yer imi olarak kaydedilebilir). Varsayılan: Bu ay, Tümü, Personel.
- **Özet çipleri:** kişi sayısı, kanıt sayısı, onaylı, bekleyen ve seçili dönemin tarih aralığı.
- **İlk 3:** en çok kanıtı olan üç kişi için küçük kartlar (altın / gümüş / bronz şerit): ad, toplam, onaylı yüzdesi, kategori paylarını gösteren ince renkli çubuk ve en çok üç kategori ("ARK 2 · DDS 2 …").
- **Tablo:** ilk 10 kişi; satırda Toplam, Onaylı (yüzdesiyle), Bekleyen ve her kategori için sayı. Hücreler değer büyüdükçe koyulaşan açık mavi tonla boyanır (sayı her zaman yazılıdır). En altta **Toplam** satırı (tüm kişiler). Kartta yalnız seçili dönemde en az bir kaydı olan kategoriler gösterilir.
- **Sayıya tıklamak** Kayıtlar sayfasını o personel + o kategori + aynı proje, dönem ve durumla açar (sıfır hücreler bağlantı değildir). Kişi adına tıklamak o kişinin tüm kayıtlarını, toplam satırındaki sayılar tüm kişileri açar.
- **"Tüm tablo ve rapor →"** aynı seçimle rapor sayfasına gider.
- Telefonda (900 px ve altı) tablo yerine kişi başına kart gösterilir: ad, toplam, onaylı/bekleyen, pay çubuğu ve kategori rozetleri (rozete dokunmak o kayıtları açar). İlk 3 kartı yan yana küçük görünür.

### Rapor sayfası (üst menü → **Rapor**)

Üst menüye eklenen **Rapor** öğesi 1280 px dizüstü ekranda menüyü ikinci satıra taşırmasın diye 901–1365 px arasında menü öğeleri biraz sıklaştırıldı.

En az bir projesi olan her kullanıcı görür (`/rapor/personel`).

- Aynı süzgeç çubuğu, ek olarak **Özel aralık** (başlangıç / bitiş tarihi, **Uygula** ile) ve **Sütun** seçimi: **Kategori** ya da **Tip** (Sessiz / Telesekreter …).
- Tüm kişilerin tam tablosu: başlık satırı ve ad sütunu kaydırırken sabit kalır, toplam satırı tablonun altında sabittir, satırlar zebra desenli, hücreler ısı tonlu. **Sütun başlığına tıklamak** o sütuna göre sıralar (tekrar tıklamak yönü çevirir; Personel başlığı A→Z).
- Başlıkta seçimin özeti ("Tüm yetkili projeler · Bu ay (01.11.2026 – 26.11.2026) · Durum: Tümü · …") ve oluşturma zamanı yazılır.
- **Excel'e aktar:** `rapor-personel-<proje|tum>-<dönem>-<tarih>.xlsx`. "Özet" sayfası tablonun aynısıdır (koyu başlık satırı, dondurulmuş başlık ve ad sütunu, kalın toplam satırı, sütun genişlikleri içeriğe göre); "Bilgi" sayfasında proje, dönem, durum, gruplama, kişi/kanıt sayısı, oluşturma zamanı ve oluşturan yazar.
- **CSV:** aynı tablo; Türkçe Excel'in doğrudan açtığı biçimde (UTF-8 BOM, `;` ayırıcı).
- **Yazdır:** tarayıcının yazdırma penceresini açar; çıktıda menü, süzgeçler ve düğmeler gizlenir, sayfa A4 yatay düzenlenir, başlıkta seçim ve oluşturma zamanı kalır. Koyu temada da çıktı beyaz zeminlidir. `…/rapor/personel?…&yazdir=1` adresi yazdırma penceresini kendiliğinden açar.
- Excel ve CSV indirmeleri İşlem Geçmişi'ne "Personel raporunu indirdi" olarak yazılır.
- Telefonda süzgeçler alt alta, tablo kartın içinde yatay kaydırılır (ad sütunu sabit); sayfa yatay kaymaz.

### Kurallar

- Yalnız **silinmemiş** kayıtlar sayılır. Personeli boş kayıtlar "(boş)" satırında, kategorisi boş kayıtlar "(boş)" sütununda toplanır (kategorisi boş hücre Kayıtlar'a bağlanmaz).
- Kategori adları büyük/küçük harf farkı gözetmeden birleştirilir ("cvps" ve "CVPS" tek sütun) ve proje kataloğundaki sırayla gösterilir; katalogda olmayan eski adlar sona eklenir.
- Herkes yalnız yetkili olduğu projeleri görür. `ONAYSIZ_GORUNUM=gizle` iken onay yetkisi olmayan projelerde onay bekleyen kayıtlar sayılmaz (Kayıtlar sayfasıyla aynı kural); tüm projelerinde onay yetkisi yoksa Durum "Onaylı"ya sabitlenir.
- Yetkisiz proje istenirse 403; tanınmayan dönem/durum/grup/sütun ya da hatalı tarih varsayılana döner ve sayfada uyarı yazılır.
- Sıralama: toplam çoktan aza, eşitse ada göre.

### Kayıtlar sayfasına eklenenler

Hücre bağlantılarının "tam olarak o kayıtları" açması için Kayıtlar listesine (ve "Excel (bu görünüm)" çıktısına) yeni adres süzgeçleri eklendi: `personel`, `ekleyen_ad`, `tip` (tam eşleşme; `__bos__` = boş değer) ve `silinmemis=1` (Tümü sekmesinde silinenleri dışarıda bırakır). Kategori süzgeci artık kayıttaki kategorinin baş/son boşluklarını yok sayar; böylece eski Excel'den `HGST ` gibi boşluklu gelmiş kayıtlar raporda ayrı sütun olmaz, `HGST` sütununda sayılır ve hücre bağlantısı aynı kayıtları açar. Bu süzgeçlerle gelindiğinde sonuç sayısının üstünde "Rapordan gelen süzgeç: Personel: … · Silinenler hariç — kaldır" satırı görünür. Arama kutusu (`q`) değişmedi.

Düzeltme: Kayıtlar ve API'deki **başlangıç tarihi** süzgeci artık saatsiz eski Excel tarihlerini de o günden sayar (önceden ayın 1'i gibi başlangıç gününe düşen eski Excel kaydı listede görünmüyordu).

İnceleme düzeltmeleri (baskı, telefon, klavye): yazdırılan / PDF raporda sütun başlıkları (Personel, Toplam, Onaylı, Bekleyen, kategori adları) her sayfada yazılı tekrarlanır (önceden 3. sayfadan itibaren yalnız renkli noktalar çıkıyordu); tablo kartı sayfalara bölünür, ilk sayfa boş kalmaz, satır ortadan bölünmez, toplam satırı yalnız sonda bir kez basılır; kâğıtta personel adları kısaltılmaz, gerekirse alt satıra sarılır. 480 px'ten dar telefonda "İlk 3" kartları alt alta dizilir ve adlar tam görünür. Dönem / Grupla / Sütun düğmelerinde ok tuşları her basışta sayfayı yenilemez: seçim Enter / Boşluk ile, gruptan çıkınca ya da son ok tuşundan yaklaşık 0,6 saniye sonra uygulanır; fare ve dokunmayla seçim eskisi gibi hemen uygulanır.

## Hatırlatma penceresi artık her sayfada açılmaz

Önceden "Bekleyen kontroller hatırlatması" penceresi **Kapat** ya da Esc ile kapatılsa bile her sayfa geçişinde (Kayıtlar → Ana sayfa …) yeniden açılıyordu. Artık:

- Pencere her hatırlatma için günde en çok **bir kez** kendiliğinden açılır. Hangi hatırlatmaların gösterildiği o tarayıcıda, kişiye ve güne göre saklanır.
- **Kapat** (ya da Esc, pencere dışına tıklamak, satırdaki **Aç**, **Tümünü okundu say**): bu hatırlatmalar için pencere bir daha kendiliğinden açılmaz; yeni hatırlatma gelirse açılır (o zaman tüm okunmamış hatırlatmalar listelenir).
- **Daha sonra**: bugün pencere bir daha kendiliğinden açılmaz; yeni hatırlatmalar kart ve zil olarak gelir (hatırlatma kartı ekranda kalır, ses çalar, zil sayısı artar).
- Ertesi gün okunmamış kalan hatırlatmalar için pencere bir kez daha açılır.
- Pencereyi istediğiniz zaman açmak için: zil (Bildirimler) → listenin üst satırındaki **Hatırlatmalar (N)** düğmesi. Yalnız okunmamış hatırlatma varken görünür; "Daha sonra" denmiş olsa da pencereyi açar.
- Kayıt penceresi / görsel büyütme açıkken, bir alana yazılırken ya da sekme arka plandayken pencere eskisi gibi bekletilir; bekletilip hiç gösterilmeyen pencere "gösterildi" sayılmaz.
- Değişen dosyalar: `panel.js`, `base.html`. Sunucu tarafı ve veritabanı değişmedi.

## API

`GET /api/v1/personel-ozet` — aynı tablo JSON olarak (parametreler `proje`, `donem`, `durum`, `grup`, `sutun`, `tarih1`, `tarih2`). Anahtarın proje kapsamı uygulanır; "yalnız onaylı" anahtarda durum her zaman `onayli`. Geçersiz parametre 400, kapsam dışı proje 403. Hız sınırı ve API günlüğü diğer uçlarla aynı. Ayrıntı ve örnek: `API_KULLANIM.md` §3.6.

## Teknik notlar

- Tek veri işlevi `app/personel_ozeti.py::personel_ozeti()` ana sayfa kartı, rapor sayfası, Excel/CSV ve API tarafından kullanılır; tek `GROUP BY` sorgusu, bağlı parametreler. Mevcut `kayitlar(tarih)` ve `kayitlar(proje,silindi,kt)` indeksleri ~7.000 kayıtta yeterli; yeni indeks eklenmedi.
- Excel/CSV hücreleri formül sayılmaz: `=`, `+`, `-`, `@` ile başlayan metinlerin başına `'` eklenir.
- Grafik kütüphanesi yok; pay çubukları ve ısı tonları CSS ile çizilir. Yeni bağımlılık yok.

## Testler

Yeni `tests/test_personel_ozet_234.py` (12 test): her dönem × durum × grup × sütun birleşiminin bağımsız bir hesapla karşılaştırılması, harf duyarsız kategori birleştirme ve katalog sırası, eski Excel tarihleri; ana sayfa kartında ilk 10 / ilk 3 / rapor bağlantısı ve süzgeç durumu; rapor ve kart hücre bağlantılarının Kayıtlar listesinde tam olarak aynı sayıyı vermesi; yetki kapsamı (yalnız-okuma + `gizle`, onay yetkili kullanıcı, 403); Excel (openpyxl ile açılıp tabloyla karşılaştırma, başlık biçimi, dondurma, formül koruması), CSV (BOM, `;`), yazdır; geçersiz parametrelerde 500 olmaması; API (401, proje kapsamı, yalnız onaylı, JSON biçimi, 400); belgeler; Node + Playwright ile açık / koyu / 390 px telefon görünümünde ekran görüntüleri, yatay taşma, sıralama, özel aralık, yazdırma (baskıda başlık etiketleri, bölünebilen tablo kartı, kısaltılmayan adlar; A4 yatay PDF çıktısı), telefonda alt alta ilk 3 ve klavyeyle dönem seçimi denetimi (`tests/personel_ozet_tarayici.js`; Node veya Playwright yoksa atlanır).
