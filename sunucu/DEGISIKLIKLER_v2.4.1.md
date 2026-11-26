# Kanıt Paneli 2.4.1 — İki adımlı doğrulama (Google Authenticator)

2.4.0 üzerine `deploy/apply-update.sh` ile uygulanır (KURULUM §13; aynı indirme + güncelleme yolu). Veritabanına yalnız
eklemeli değişiklik yapılır: `panel_kullanicilari` tablosuna dört sütun, iki yeni tablo (`iki_adim_kurtarma`,
`iki_adim_cihazlar`). Mevcut hesaplar **kapalı** başlar; kimse kurmadıkça giriş eskisi gibi yalnız kullanıcı adı ve şifreyle
yapılır. `.env` dosyasına bir şey yazmak gerekmez; iki yeni ayar Yönetim → Çalışma ayarları → **Güvenlik** bölümündedir.

API anahtarları (`/api/v1`), Telegram botu ve `/saglik` adresi etkilenmez. Cloudflare ve Erişim sınırı (IP listesi) ile
birlikte çalışır.

---

## Ekip için: Google Authenticator nasıl kurulur

1. Telefona **Google Authenticator** kurun (Android: Play Store, iPhone: App Store). Microsoft Authenticator ya da Authy de olur.
   Ücretsizdir, hesap açmak gerekmez.
2. Panelde sağ üstte adınızın altındaki **2FA: kapalı** bağlantısına basın (telefonda menü → "İki adımlı doğrulama: kapalı"; ya da **Şifre**
   sayfasının altındaki kart). **İki adımlı doğrulamayı aç** düğmesine basın.
3. Ekranda bir **QR kodu** çıkar. Uygulamada **+** → **QR kodu tara** ile okutun.
   - Paneli telefondan açtıysanız QR'ı okutamazsınız: **Uygulamada aç (telefon)** düğmesine dokunun, uygulama kendiliğinden açılır.
   - Ya da uygulamada **Kurulum anahtarı gir**'i seçin, hesap adına `Kanıt Paneli`, anahtara ekrandaki 4'lü harf gruplarını yazın,
     tür **Zamana dayalı**.
4. Uygulamada **Kanıt Paneli (kullanıcı adınız)** satırı belirir; her 30 saniyede yeni 6 haneli kod gösterir. Bu kodu paneldeki
   kutuya yazıp **Doğrula ve aç**'a basın.
5. **8 kurtarma kodu** bir kez gösterilir. **Kodları kopyala** ya da **Yazdır** ile saklayın (parola yöneticisi, kilitli not ya
   da kâğıt). Bir daha gösterilmez.

Kod kabul edilmezse: telefonun saati **otomatik** (ağdan) ayarlı olmalı. Kurulum sayfası sunucu saatini gösterir; bilgisayarın
saati 30 saniyeden fazla kaymışsa sayfa uyarır. Google Authenticator'da ⋮ → Ayarlar → **Kodlar için saat düzeltme**.

### Girişte ne değişir

Kullanıcı adı ve şifreden sonra **Doğrulama kodu** sayfası açılır: uygulamadaki 6 haneli kodu yazın. Bu adım 5 dakika içinde
tamamlanmalı; süre dolarsa şifreyle yeniden başlarsınız. Kod girilmeden panelin hiçbir sayfası açılmaz.

**"Bu cihazda 30 gün sorma"**: kendi bilgisayarınızda/telefonunuzda bu kutuyu işaretlerseniz o tarayıcı 30 gün kod istemez;
şifre yine her girişte istenir. Ortak bilgisayarda işaretlemeyin. Güvenilen cihazlarınızı İki adımlı doğrulama sayfasında
görürsünüz (tarayıcı, son kullanım, IP) ve tek tek ya da topluca kaldırabilirsiniz.

"Şifre hatırla" isteğinin güvenli karşılığı budur: tarayıcınız şifrenizi kaydedebilir (bu sizin tercihiniz); **panel şifrenizi
hiçbir zaman saklamaz**. "Bu cihazda sorma" yalnız doğrulama kodunu atlar.

### Telefon kaybolursa ya da değişirse

- **Kurtarma kodunuz varsa:** girişte kod yerine bir kurtarma kodu yazın (`abcde-fghij`; büyük/küçük harf ve tire önemsiz).
  Her kod bir kez kullanılır. İçeri girince **Yeniden kur** ile yeni telefona kurun.
- **Kurtarma kodu da yoksa:** sahibe yazın; Kullanıcılar sayfasından iki adımlı doğrulamanızı sıfırlar. Sonra yeniden kurarsınız.
- **Yeni telefon, eskisi elinizde:** İki adımlı doğrulama sayfası → **Yeniden kur** (mevcut şifre ister). Yeni kodu doğrulayana
  kadar eski telefon çalışmaya devam eder.
- **Kurtarma kodları azaldıysa** (2 ya da daha az): sayfa ve girişteki mesaj uyarır; **Yeni kurtarma kodları üret** (mevcut şifre
  ister) eskilerini geçersiz yapar.

### Kapatma

Politika zorunlu kılmıyorsa İki adımlı doğrulama sayfasının altında **Kapat**: mevcut şifre + uygulamadaki kod (ya da bir
kurtarma kodu) ister. Kapatınca kurtarma kodları ve güvenilen cihazlar silinir. Kurtarma kodları yalnız bir kez gösterilir:
o sayfayı yenilerseniz yeni kod çıkmaz, "zaten açık" uyarısı görünür; gerekirse "Yeni kurtarma kodları üret"i kullanın.

---

## Operatör / sahip için

### Zorunlu kılma

Yönetim → Çalışma ayarları → Güvenlik → **İki adımlı doğrulama zorunlu mu** (`IKI_ADIM_ZORUNLU`):

| Değer | Kimler için zorunlu |
|---|---|
| `kapali` (varsayılan) | Kimse; isteyen kendi açar. |
| `yonetici` | Sahip, süperadminler ve herhangi bir projede **onay (kt)** yetkisi olan herkes. |
| `hepsi` | Bütün panel kullanıcıları. |

Bekleme süresi yoktur: kaydettiğiniz anda geçerli olur. Zorunlu olup henüz kurmamış kişi giriş yapabilir ama kurulumu bitirene
kadar **yalnız kurulum sayfasını** görür (menü gizlenir, sayfanın üstünde Türkçe açıklama ve Çıkış düğmesi vardır). Geçici
şifreyle giren kişi önce şifresini değiştirir, sonra kuruluma yönlenir. **Siz de kurmadıysanız** kaydettiğiniz anda kurulum
sayfasına yönlenirsiniz; kendi kurulum sayfanız her zaman açıktır, yani politika sizi dışarıda bırakamaz.

Kimin kurmadığı **Kullanıcılar** sayfasındaki yeni **2FA** sütununda görünür: `açık` / `yok` / `zorunlu, bekliyor`; listenin
üstünde "Henüz kurmayan: …" satırı ve geçerli politika yazar.

### Sıfırlama ve güvenilen cihazları iptal

Kullanıcılar → hesabın **Düzenle** satırı → **İki adımlı doğrulama** bölümü (yalnız sahip görür ve yapar):

- **İki adımlı doğrulamayı sıfırla:** kullanıcı adını yazarak onaylanır (sunucu da denetler). Anahtar, kurtarma kodları ve
  güvenilen cihazlar silinir, kişinin açık oturumları kapanır. Politika zorunlu kılıyorsa bir sonraki girişte yeniden kurar.
- **Güvenilen cihazları iptal et (N):** kişinin "bu cihazda sorma" işaretli bütün tarayıcıları bir sonraki girişte yeniden kod ister.

Her işlem İşlem Geçmişi'ne yazılır: `2fa_ac` (açtı / yeniden kurdu), `2fa_kapat`, `2fa_kurtarma_kullanildi`, `2fa_sifirla`,
`2fa_cihaz_guven`, `2fa_cihaz_kaldir`, `2fa_kurtarma_yenile`, `2fa_hata` (hatalı kod) ve `giris` satırının açıklamasında
"iki adımlı doğrulama: uygulama kodu / kurtarma kodu" ya da "güvenilen cihaz".

### Güvenilen cihaz süresi

Çalışma ayarları → Güvenlik → **"Bu cihazda sorma" süresi (gün)** (`IKI_ADIM_GUVEN_GUN`, varsayılan 30, 0–365). **0** özelliği
kapatır: kutu girişte görünmez ve daha önce güvenilen cihazlar da kodu atlatamaz. Süreyi **kısaltırsanız** (ör. 30 → 7)
önceden güvenilen cihazlar da yeni süreye uyar: cihazın oluşturma tarihinden 7 gün geçmişse bir sonraki girişte kod istenir
(uzatma eski cihazları uzatmaz). Şifre değişikliği, rol değişikliği, hesabın
pasife alınması, iki adımlı doğrulamanın kapatılması ya da sıfırlanması kişinin bütün güvenilen cihazlarını iptal eder.

### Acil durum (sunucudan)

Sahibin telefonu kaybolduysa ya da politika yüzünden kimse giremiyorsa, sunucuda (kanit hesabıyla):

```bash
cd /opt/kanit-paneli && sudo runuser -u kanit -- .venv/bin/python -m app.cli 2fa-durum
cd /opt/kanit-paneli && sudo runuser -u kanit -- .venv/bin/python -m app.cli 2fa-sifirla KULLANICI_ADI
# politikayı kapatmak için:
cd /opt/kanit-paneli && sudo runuser -u kanit -- .venv/bin/python -m app.cli ayar IKI_ADIM_ZORUNLU kapali
```

`2fa-durum` politika, güven süresi ve her hesabın durumunu (açık / yok / zorunlu-bekliyor, kalan kurtarma kodu, cihaz sayısı)
yazar; `--json` ile JSON. `2fa-sifirla` İşlem Geçmişi'ne `sunucu-cli` adıyla yazılır.

---

## Güvenlik ayrıntıları

- **Algoritma:** RFC 6238 (TOTP) / RFC 4226 (HOTP), HMAC-SHA1, 6 hane, 30 saniye; yalnız Python standart kütüphanesi.
  160 bit rastgele anahtar (base32). Doğrulama ±1 adım (±30 sn) kabul eder; aynı kod (ya da daha eskisi) ikinci kez
  kullanılamaz (son kullanılan sayaç saklanır); karşılaştırma sabit zamanlı. Saat kaynağı sunucu saatidir.
- **Kurulum:** anahtar, uygulamadan geçerli bir kod girilene kadar hesaba yazılmaz (15 dakika geçerli bekleyen anahtar).
  QR kodu sunucuda SVG olarak üretilir (`app/qr_svg.py`, ISO/IEC 18004 bayt kipi, hata düzeltme M); dış kütüphane, CDN ya da
  JavaScript yok. `otpauth://totp/Kan%C4%B1t%20Paneli:<kullanıcı>?secret=…&issuer=Kan%C4%B1t%20Paneli&digits=6&period=30&algorithm=SHA1`.
- **Ön işaret:** parola doğru olunca tam oturum açılmaz; oturum çerezinde yalnız rastgele bir numara, sunucuda 5 dakikalık,
  tek kullanımlık bir satır bulunur. Kod doğrulanınca satır silinir ve yeni oturum (yeni CSRF) açılır; aynı işaretle ikinci kez
  giriş yapılamaz. Parola adımından sonra hesap değişirse (şifre, rol, sıfırlama) işaret geçersiz olur.
- **Deneme sınırı:** hesap başına 5 dakikada 5 hatalı kod → hesap parola akışındaki gibi 15 dakika kilitlenir (`giris_kilit`);
  hatalı kodlar IP başına 15 dakikalık 20 deneme sınırına da sayılır. Kilit denetimi, sayım ve kod denetimi tek veritabanı
  işleminde yapılır; aynı anda gönderilen çok sayıda istek de sınırı aşamaz. Aynı sınır, ayarlardaki **Kapat** formundaki kod
  için de geçerlidir: hesap kilitliyken doğru kod girilse bile iki adımlı doğrulama kapatılmaz.
- **Kurulum bekleyen hesap:** politika zorunlu kılıp hesap henüz kurmadıysa yalnız kurulum sayfası ve çıkış açılır; Şifre
  sayfası da kurulum bitene kadar kapalıdır (geçici şifreli hesap önce şifresini değiştirir, sonra kurar).
- **Telefonda kod alanı:** giriş adımındaki ve Kapat formundaki kod alanı harf klavyesi açar; kurtarma kodları (harfli)
  telefondan rahatça yazılır. Kullanıcılar sayfasında telefonda 2FA durumu "Durum" hücresinin altında gösterilir.
- **Kurtarma kodları:** 8 adet, 10 karakter (karışan 0/o/1/l/i yok), parola karmasıyla (werkzeug) saklanır, tek kullanımlık.
- **Güvenilen cihaz:** rastgele belirteç ayrı bir çerezde (`__Host-kanit_cihaz`, HTTPS'te; HttpOnly, Secure, SameSite=Lax);
  veritabanında yalnız SHA-256 özeti, kullanıcı, oluşturma, bitiş, son IP ve kısa tarayıcı özeti (ör. "Chrome · Android").
- **Anahtarın saklanması (dürüst not):** TOTP anahtarı veritabanında **düz metin** (base32) durur; şifreleme iddiası yoktur.
  Güven sınırı veritabanı dosyasıdır: dosya yalnız `kanit` hesabınca okunabilir (kurulumdaki izinler) ve yedekler
  (`/var/backups/kanit-paneli`) aynı özenle saklanmalıdır. Veritabanını ele geçiren biri kodları üretebilir; bu yüzden yedekleri
  paylaşmayın.

## Değişen / eklenen dosyalar

- `app/iki_adim.py` (yeni): TOTP, kurtarma kodları, ön işaret, güvenilen cihazlar, politika.
- `app/qr_svg.py` (yeni): bağımlılıksız QR → SVG.
- `app/panel.py`: giriş akışı (`/giris` → `/giris/dogrulama`), `/profil/iki-adim`, zorunlu kılma yönlendirmesi, Kullanıcılar
  sütunu ve sahip işlemleri, İşlem Geçmişi adları.
- `app/db.py`: eklemeli şema (`core_schema_241_iki_adim`). `app/kullanicilar.py`: şifre/rol/etkinlik değişince güvenilen cihazlar
  silinir. `app/ayarlar.py`: Güvenlik grubu (`IKI_ADIM_ZORUNLU`, `IKI_ADIM_GUVEN_GUN`). `app/cli.py`: `2fa-sifirla`, `2fa-durum`.
- Şablonlar: `giris_kod.html`, `iki_adim.html` (yeni); `base.html` (başlıkta adın altında "2FA: açık/kapalı", zorunlu kurulumda sade başlık),
  `kullanicilar.html`, `sifre.html`. `static/stil.css`.
- Testler: `tests/test_v241_iki_adim.py`, `tests/iki_adim_tarayici.js`, `tests/qr_karsilastir.js`.
