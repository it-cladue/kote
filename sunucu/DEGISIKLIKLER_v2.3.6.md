# Kanıt Paneli 2.3.6 — Panelden kanıt ekleme (SMS kategorisi) (26 Kasım 2026)

2.3.5 üzerine `deploy/apply-update.sh` ile uygulanır (KURULUM §13, güncelleme yolu değişmedi). `.env` dosyasına bir şey yazmak gerekmez. Veritabanına yalnız bir **ekleme** yapılır: katalogda **SMS** kategorisi yoksa ilk açılışta oluşturulur; mevcut kayıtlara, kategorilere ve projelere dokunulmaz. Değişen dosyalar: `app/panel.py`, `app/katalog.py`, `app/db.py`, `app/api.py`, `app/api_kilavuz.py`, `app/settings.py`, yeni şablonlar `_kanit_ekle.html` ve `kayit_yeni.html`, `kayitlar.html`, `ana.html`, `giris.html`, `panel.js`, `kayit.css`. Tarayıcı yeni dosyaları kendiliğinden alır (sürüm numaralı adresler).

## Ne değişti?

Şimdiye kadar kanıt yalnız Telegram botundan eklenebiliyordu. 2.3.6 ile **yetkili kullanıcılar kanıtı doğrudan panelden** ekler: Gyazo (ya da Snappark / Teamzone) bağlantısını yapıştırır, personel ve diğer bilgileri doldurur. Bu kayıtların kategorisi her zaman **SMS**'tir ve Kayıtlar sayfasında Telegram kayıtlarıyla aynı biçimde görünür.

## Kim ekleyebilir?

- **Süperadmin:** tüm etkin projelere.
- **Proje yetkisi olan kullanıcı:** yalnız **onay** (takım lideri) ya da **düzenleme** yetkisi olduğu etkin projelere. Sadece "görüntüleme" yetkisi olan kullanıcı ekleyemez; bu kullanıcılar yeni bir düğme görmez.
- Yetkisi olmayan projeye gönderim reddedilir ("Bu projeye kanıt ekleme yetkiniz yok"). Pasif projelere ekleme yapılmaz.

Yetkiler değişmedi; mevcut **Yönetim → Kullanıcılar** ekranındaki proje izinleri kullanılır.

## Nasıl eklenir?

1. **Kayıtlar** sayfasının üstündeki mavi **Kanıt ekle** düğmesine basın (ana sayfadaki **Kanıt ekle** düğmesi aynı formu ayrı sayfada açar: `/kayit/yeni`).
2. **Proje**: yalnız ekleme yetkiniz olan projeler listelenir. Tek projeniz varsa ya da Kayıtlar listesinde tek proje seçiliyse o proje hazır gelir.
3. **Görsel bağlantısı** (zorunlu): Gyazo bağlantısını olduğu gibi yapıştırın, ör. `https://gyazo.com/0123…` (32 karakterlik kimlik). Kabul edilen adresler: `gyazo.com`, `i.gyazo.com`, `t.gyazo.com`, `img.snappark.net`, `snappark.net`, `teamzone.gyazo.com`. Bağlantı `https://` ile başlamalıdır; `http://`, başka siteler, içinde `@`, boşluk ya da Türkçe karakter olan bağlantılar reddedilir. İsterseniz **2. görsel bağlantısı** da girilebilir (aynı kurallar).
4. **Personel** (zorunlu, en çok 100 karakter), **Üye ID**, **Ana üye ID**, **Lead ID** (isteğe bağlı), **Sessiz / Telesekreter** (— / Sessiz / Telesekreter; botla aynı değerler), **Açıklama** (isteğe bağlı, en çok 500 karakter).
5. **Kategori** seçilmez: formda sabit **SMS** rozeti görünür.
6. **Onaylı olarak ekle**: yalnız seçilen projede **onay yetkiniz** varsa görünür ve **işaretli gelir** (takım lideri kendi eklediği kanıtı aynı anda onaylamış olur; onaylayan olarak adınız ve zamanı yazılır). İşareti kaldırırsanız kayıt "Onay bekleyen" listesine düşer. Onay yetkiniz yoksa kutu görünmez ve kayıt onaysız eklenir.
7. **Kanıtı ekle**: "Kayıt #N eklendi" iletisi çıkar, liste yenilenir ve yeni kaydın ayrıntısı açılır.

Hatalı alanlar kırmızıyla işaretlenir ve altında Türkçe açıklama yazar; düzeltip yeniden gönderin (girilen bilgiler kaybolmaz). Pencere **Esc** ya da **Kapat** ile kapanır; kapattığınızda doldurduğunuz alanlar bir sonraki açılışa kadar korunur. Telefonda form tam ekran açılır.

**Çift kayıt olmaz:** düğmeye iki kez basmak, yavaş bağlantıda tekrar basmak ya da sayfayı yenileyip formu yeniden göndermek ikinci bir kayıt açmaz; aynı form yalnız bir kayıt üretir ("Bu form zaten gönderildi; Kayıt #N yeniden oluşturulmadı").

## Ekip ne görür?

- **Kayıtlar listesi:** kategori sütununda **SMS**, Ekleyen sütununda "kullanıcıadı **(panel)**". Kategori süzgecinde **SMS** seçilerek yalnız bu kayıtlar listelenebilir.
- **Kayıt ayrıntısı:** başlıkta SMS rozeti; **Kaynak: Panel**, **Giriş tipi: Panel (bağlantı)**, **Ekleyen: kullanıcıadı (panel)**; işlem geçmişinde "Panelden eklendi". Görsel, Telegram'daki Gyazo bağlantılı kayıtlar gibi sunucu üzerinden gösterilir (gece Gyazo kopyalama işi bu kayıtları da kopyalar).
- **Bildirimler:** onaysız eklenen kayıt için projede onay yetkisi olan herkese (ekleyen hariç) Telegram kayıtlarındaki gibi "Yeni kanıt" bildirimi gider. Onaylı eklenen kayıt için onay bildirimi gitmez.
- **Hatırlatmalar:** onaysız panel kaydı Telegram kaydı gibi 2 saat / 3 gün / gün sonu hatırlatmalarına girer.
- **Ana sayfa "Son işlemler" ve İşlem Geçmişi:** "Panelden kanıt ekledi" satırı (kim, hangi proje, kayıt numarası, onaylı mı).
- **Kayıtlar listesi:** tablo ve kart görünümünde kategori SMS rozetiyle, ekleyen "kullanıcıadı (panel)" olarak görünür; galeri kartında "· Panel" yazar.
- **Bot yönetimi sayfası ve `/kayit_raporu`:** "En çok kanıt ekleyenler" listesinde panel kullanıcısı "kullanıcıadı (panel)" olarak, Telegram ID sütunu boş (—) ve bağlantısız görünür.
- **Excel çıktısı:** **Kaynak** sütununda `Panel`, **Giriş tipi** sütununda `Panel (bağlantı)`. "Ekleyen Telegram ID" sütununun adı eski çıktılarla uyum için değişmedi; panel kayıtlarında bu hücrede Telegram ID yerine `panel:kullanıcıadı` yazar.
- **Personel raporu:** diğer kayıtlar gibi sayılır; SMS ayrı bir kategori sütunudur.
- **API:** `/api/v1/kayitlar` ve `/api/v1/kayit/<id>` yanıtına `kaynak` alanı eklendi (`telegram`, `panel`, eski Excel için `legacy_excel` / `excel`). SQL ucundaki `kayitlar` görünümünde `kaynak='panel'`, `giris_tipi='panel'`, `kategori_code='sms'`.

## SMS kategorisi

- İlk açılışta katalogda **SMS** (kod `sms`) yoksa oluşturulur: etkin, tüm etkin projelere bağlı, "tek üye" soru şablonuyla (Personel + Üye ID). Bu yüzden SMS Telegram botunun kategori listesinde de görünür. Botta görünmesini istemiyorsanız **Yönetim → Proje / Kategoriler** ekranında SMS'in proje bağlarını kaldırabilirsiniz; panelden ekleme yine çalışır.
- SMS kategorisini katalogda **pasif** yaparsanız panelden kanıt ekleme durur: form "kategori pasif; panelden kanıt ekleme kapalı" uyarısıyla kayıt açmaz. Yeniden etkinleştirince ekleme açılır.
- Panel formunda yalnız **Personel** zorunludur; Üye ID boş bırakılabilir. Kayda yazılan soru anlık görüntüsü bunu yansıtır (Üye ID "isteğe bağlı"); katalogdaki soru tanımı değişmez, Telegram botu kendi kuralıyla sormaya devam eder.
- Görünmez biçim karakterleri (sıfır genişlikli boşluk, yazı yönünü çeviren karakterler vb.) panel formundaki alanlardan sessizce atılır.
- Katalogda zaten `sms` kodlu bir kategori varsa (elle açılmış) **hiç değiştirilmez**: adı, aktifliği, proje bağları korunur ve panel kayıtları onun adıyla yazılır.
- SMS'in adını katalogdan değiştirirseniz (ör. "SMS kanıt") yeni panel kayıtları yeni adla yazılır; eski kayıtlar eski adını korur.

### Ayar (isteğe bağlı): `PANEL_EKLEME_KATEGORI`

Panel kayıtlarının kategorisi varsayılan olarak **SMS**'tir. Başka bir ad isterseniz `.env` dosyasına yazın ve servisi yeniden başlatın:

```
PANEL_EKLEME_KATEGORI=SMS
```

Yazılan ad katalogda varsa (harf büyüklüğü fark etmez) o kategori kullanılır; yoksa ilk açılışta SMS gibi oluşturulur (kod addan türetilir, ör. "Kısa Mesaj" → `kisa_mesaj`). Eski kategori silinmez.

## Teknik notlar

- Kayıt alanları: `anahtar='panel:<uuid>'`, `kaynak='panel'`, `giris_tipi='panel'`, `ekleyen_id='panel:<kullanıcı>'`, `ekleyen_ad=<kullanıcı>`, `ekleyen_guven='panel'`, `kategori`/`kategori_code`/`kategori_mode` katalogdan, `link_turu` botla aynı sınıflandırma (`gyazo` / `snappark` / `teamzone`), `tarih=guncelleme=` ekleme anı, `ilk_gorulme` boş (bot gibi), `surum=1`. Onaylı eklemede `kt=1`, `kt_kaynak='panel'`, `kt_kim`, `kt_zaman`. Soru anlık görüntüsü (`soru_anlik_json`, `cevaplar_json`) bot kayıtları gibi yazılır; düzenleme ekranı aynı çalışır.
- Görsel dosyası yüklenmez (yalnız bağlantı). Bağlantı doğrulaması görsel vekilinin kullandığı kuralla aynıdır: yalnız `https`, host izin listesiyle **tam** eşleşmeli, kullanıcı adı/parola (`kim@host`) ve port kabul edilmez.
- Tek işlemde (transaction) kayıt + bildirim + İşlem Geçmişi satırı (`panel_kanit_ekle`) + değişiklik damgası yazılır. Çift gönderim koruması: her form açılışı oturuma tek kullanımlık bir form kimliği yazar; kayıt anahtarı bu kimlikten üretildiği için veritabanındaki benzersizlik kuralı ikinci kaydı engeller.
- Uçlar: `GET /kayit/yeni` (form sayfası), `GET /kayit/yeni.json` (pencere için form kimliği ve proje listesi), `POST /kayit/yeni` (CSRF zorunlu; XHR'a JSON `{ok, id, mesaj}`, düz gönderime kayda yönlendirme). Yetkisiz kullanıcıya 403.

## Güncellemeden sonra kontrol

1. Süperadmin olarak **Kayıtlar** → **Kanıt ekle**; proje seçip bir Gyazo bağlantısı ve personel kodu girin, **Kanıtı ekle**.
2. "Kayıt #N eklendi" iletisi ve açılan ayrıntıda **SMS**, **Kaynak: Panel**, **Ekleyen: … (panel)** görünmeli.
3. Yalnız görüntüleme yetkili bir kullanıcıyla girildiğinde **Kanıt ekle** düğmesi görünmemeli.
