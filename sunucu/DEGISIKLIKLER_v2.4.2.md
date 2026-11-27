# Kanıt Paneli 2.4.2 — Yeni hesaplarda iki adımlı doğrulama varsayılan olarak zorunlu

2.4.1 üzerine `deploy/apply-update.sh` ile uygulanır (KURULUM §13; aynı indirme + güncelleme yolu, `.env` değişmez).
Veritabanına yalnız bir sütun eklenir (`panel_kullanicilari.iki_adim_zorunlu`). Mevcut hesaplar **"Politikaya göre"**
kalır; yani güncellemeden sonra hiçbir mevcut hesabın girişi değişmez.

## Ne değişti

İstek: "Yeni kullanıcı oluştururken 2FA zorunlu otomatik seçili olsun; zorunluluğu kaldırmak isteğe bağlı olsun ve yalnız
süperadmin kaldırabilsin — herkesinkini." Artık her hesabın kendi zorunluluk ayarı var ve yeni hesaplar zorunlu açılır.

### Yeni kullanıcı formu

Yönetim → Kullanıcılar → **Yeni kullanıcı** formunda yeni bir kutu var, **her zaman işaretli** gelir:

> ☑ İki adımlı doğrulama zorunlu (ilk girişte kurulum ister)

- Kutu **işaretli** kalırsa hesap zorunludur — genel politika "Kapalı" olsa bile. Kişi ilk girişte geçici şifresini
  değiştirir, sonra Google Authenticator kurulum sayfasına yönlenir; kurmadan panelin başka sayfası açılmaz.
- Kutuyu **kaldırırsanız** hesap zorunlu tutulmaz — genel politika "Herkes" olsa bile. Kişi isterse kendisi kurar.
- Bu formu yalnız süperadmin ve sahip görür; yani zorunluluğu kaldırmak da yalnız onlara açıktır.

### Hesap başına zorunluluk: üç durum

Her hesabın **Düzenle** satırının altında "İki adımlı doğrulama zorunluluğu" seçimi ve **Zorunluluğu kaydet** düğmesi vardır:

| Seçim | Anlamı |
|---|---|
| **Zorunlu** | Bu hesap için her durumda zorunlu. Kurmamışsa bir sonraki tıklamada kurulum sayfasına yönlenir (oturumu kapanmaz). Formdan açılan yeni hesaplar böyle başlar. |
| **Zorunlu değil** | Politika bu hesabı zorlamaz. Kurulu 2FA kapanmaz; yalnız zorunluluk kalkar ve hemen etkili olur. |
| **Politikaya göre** | Genel politika (`IKI_ADIM_ZORUNLU`) karar verir. 2.4.2 öncesinden kalan hesaplar ve sunucu komutuyla açılan hesaplar böyledir. |

Kısaca: **hesap ayarı politikadan önce gelir**; genel politika yalnız "Politikaya göre" olan hesaplar için karar verir.

**Kim değiştirebilir?** Yalnız **süperadmin** ve **sahip** — ve bunlar **herkesinkini** değiştirebilir: proje
kullanıcıları, diğer süperadminler, sahip ve kendi hesapları. (Süperadmin, sahibin satırında başka bir şeyi düzenleyemese de
bu seçim orada da vardır.) Başka hiçbir rol değiştiremez; kullanıcı kendi zorunluluğunu "2FA" ya da "Şifre" sayfasından
kaldıramaz. Her değişiklik İşlem Geçmişi'ne "Kullanıcı güncelleme" olarak, kimin yaptığı ve "2FA zorunluluğu: zorunlu →
zorunlu değil" gibi eski → yeni değerle yazılır.

### Kullanıcılar sayfası

- 2FA sütunu yine `açık` / `yok` / `zorunlu, bekliyor` gösterir. Hesabın kendi ayarı varsa altında küçük bir not çıkar:
  "hesap ayarı: zorunlu" ya da "hesap ayarı: zorunlu değil" (telefonda Durum hücresinde). "Politikaya göre" hesaplarda not yoktur.
- "Henüz kurmayan: …" satırı yalnız gerçekten zorunlu olup kurmamış etkin hesapları sayar.
- Listenin üstünde: "yeni hesaplar varsayılan olarak zorunlu; hesap ayarı politikadan önce gelir".

### Sunucu komutu

```
cd /opt/kanit-paneli
sudo runuser -u kanit -- .venv/bin/python -m app.cli 2fa-zorunlu KULLANICI_ADI evet       # zorunlu
sudo runuser -u kanit -- .venv/bin/python -m app.cli 2fa-zorunlu KULLANICI_ADI hayir      # zorunlu değil
sudo runuser -u kanit -- .venv/bin/python -m app.cli 2fa-zorunlu KULLANICI_ADI politika   # politikaya göre
sudo runuser -u kanit -- .venv/bin/python -m app.cli 2fa-durum                            # yeni "HESAP AYARI" sütunu
```

`2fa-zorunlu` İşlem Geçmişi'ne `sunucu-cli` adıyla yazılır. `2fa-durum --json` çıktısında her hesap için `hesap_ayari`
alanı vardır.

## Değişen / eklenen dosyalar

- `app/db.py` — `iki_adim_zorunlu` sütunu (`core_schema_242_iki_adim_hesap`, eklemeli ve tekrarlanabilir geçiş)
- `app/iki_adim.py` — `zorunlu_mu()` önce hesap ayarına bakar; `hesap_ayari()`, `hesap_ayari_degeri()`
- `app/kullanicilar.py` — `ekle(..., iki_adim_zorunlu=None)`, `guncelle` alanı ve denetim açıklaması
- `app/panel.py`, `app/templates/kullanicilar.html`, `app/static/stil.css` — işaretli kutu, satır başına zorunluluk formu
  (yalnız süperadmin/sahip, her hesap), notlar
- `app/cli.py` — `2fa-zorunlu`, `2fa-durum` sütunu; `app/ayarlar.py` — `IKI_ADIM_ZORUNLU` yardım metni
- `tests/test_v242_iki_adim_hesap.py` (yeni), `tests/iki_adim_tarayici.js` (2.4.2 adımları)
