# telegram/ — Telegram kanıt botu: ekran görüntülerini geri alma ve saklama

Bot (`telebot.ps1`) her kanıtı Gyazo'ya yükleyip Excel'e link yazıyor; görselin kendisini yerelde
tutmuyordu. **Gyazo'da eski linklerin görselleri artık açılmıyor**, o yüzden görselleri
Gyazo'dan değil **doğrudan Telegram'dan** geri alıyoruz.

| Dosya | Ne işe yarar | Kaynak |
|---|---|---|
| `Gorselleri-Cek.ps1` | **TEK DOSYA, sıfır ayar**: sağ tık → "PowerShell ile çalıştır". Bot klasörünü kendisi bulur, son 2 ayı Telegram'dan PNG olarak çeker. | **Telegram** |
| `Recover-TelegramGorselleri.ps1` | **Geriye dönük** (son 2 ay): eski görselleri Telegram'dan geri indirir. | **Telegram** |
| `telebot.ps1` | **İleriye dönük**: botun yamalı hali. Bundan sonra her kayıtta görseli yerele de kaydeder. | Telegram |
| `Export-GyazoGorselleri.ps1` | Opsiyonel: Gyazo linki hâlâ açılan kayıtları Gyazo'dan indirir (tam adlandırma, Telegram'a hiç dokunmadan). | Gyazo |
| `1_ONCE_TARA.bat`, `2_INDIR.bat`, `3_GYAZO_OPSIYONEL.bat`, `OKU_BENI.txt` | Çift tıkla çalıştırma. Bot klasörüne kopyalayıp sırayla çalıştırın; parametre yazmak gerekmez. | – |

**Hazır paket:** bu klasördeki iki script + üç `.bat` + `OKU_BENI.txt` bot klasörüne (bot_log.txt, telegram_cache.txt,
config.json'un olduğu yere) kopyalanır, `1_ONCE_TARA.bat` sonra `2_INDIR.bat` çift tıklanır. Çıktı **PNG**'dir
(`-Format jpg` ile JPEG). Bir dosya PNG'ye çevrilemezse `.jpg` kalır ve `indeks.csv`'de `indirildi_jpg` yazar.

Üçünde de dosya adı aynı düzendedir; boş alanlar atlanır:

```
2026-09-15_16-01-18_Dilek-Office_OF_CVPS_P263_U490241154.png
2026-07-18_11-10-43_galabeyza_GA_ARK_P275_U435686089_A435422754.png
```
`P` = personel kodu, `U` = üye ID, `A` = ana üye ID. Türkçe karakter ve boşluklar sadeleştirilir
(`Dilek Office` → `Dilek-Office`).

---

## 1. Geriye dönük — `Recover-TelegramGorselleri.ps1` (ANA YÖNTEM)

### Neden Telegram?

Excel'de/logda Telegram dosya kimliği (file_id) tutulmamış. Elimizdeki tek Telegram izi
`telegram_cache.txt`: her satır `<kullanıcıID>:<mesajID>` (özel sohbette **sohbet ID'si = kullanıcı
ID'sidir**, yani kaydı ekleyen kişiyi kesin biliriz).

Telegram Bot API bir botun eski mesajı ID ile "okumasına" izin vermez; ama mesajı başka bir sohbete
**yönlendirmeye** (`forwardMessage`) izin verir ve yönlendirme sonucu mesajın kendisini (fotoğraf +
orijinal tarih) döner. Script her cache kaydını bir "dökme" sohbetine yönlendirir, fotoğrafsa en büyük
boyutu indirir, sonra yönlendirilen kopyayı siler.

**Adlandırma:** orijinal gönderim tarihi + kullanıcı (ikisi de Telegram'dan, kesin). Ek olarak script
`bot_log.txt` + Excel ile eşleştirip (aynı kullanıcı + yakın zaman) **proje / kategori / personel / üye
ID**'yi de dosya adına ekler. Eşleşme bulunamazsa ad yine `tarih_kullanıcı` olarak yazılır (kayıp yok).

### ÖNEMLİ — çalıştırmadan önce

1. **Botu durdurun.** Script canlı bot token'ını kullanır; bot çalışırken ikisi aynı anda Telegram'a
   giderse çakışır. `config.json`'daki `TELEGRAM_TOKEN` otomatik okunur, hiçbir yere yazılmaz.
2. **Bir "dökme" sohbeti açın (önerilir).** Yönlendirme her mesajı bir an için `-HedefChatId` sohbetine
   düşürür (script hemen siler). Bildirim yağmuru olmasın diye: Telegram'da **botun yönetici olduğu boş
   bir grup/kanal** açın, ID'sini `-HedefChatId` verin. Vermezseniz `config.json`'daki ilk `ADMIN_IDS`
   kullanılır (yönetici hesabına anlık bildirimler gelir). `.bat` ile çalıştırıyorsanız `config.json`'a
   `"KURTARMA_HEDEF_CHAT_ID": "-100..."` satırı ekleyerek de verebilirsiniz.
3. Bot silinmiş mesajları (akıştaki personel/üye ID yazıları bot tarafından silinir) yönlendiremez;
   bunlar `mesaj_yok` diye atlanır. **Fotoğraf mesajları silinmediği için kurtarılır.** Kullanıcı sohbeti
   sildiyse/botu engellediyse (`erisim_yok`) o kişinin görselleri gelmez.

### Kullanım

```powershell
# 1) Önce dene: son 2 ayı TARA (indirme yok), ne kadar fotograf var gör
.\Recover-TelegramGorselleri.ps1 -BotKlasoru "C:\...\telegramkant" -HedefChatId -1002345678901 -SadeceTara

# 2) Son 2 ayi indir. Kesilirse tekrar calistir; inmis olanlar atlanir.
.\Recover-TelegramGorselleri.ps1 -BotKlasoru "C:\...\telegramkant" -HedefChatId -1002345678901

# Belirli tarih araligi
.\Recover-TelegramGorselleri.ps1 -BotKlasoru "C:\...\telegramkant" -HedefChatId -1002345678901 -Baslangic 2026-08-01 -Bitis 2026-08-31
```

Script bot klasörünün içindeyse `-BotKlasoru` gerekmez. Çalıştırma engeli varsa:
`powershell -ExecutionPolicy Bypass -File .\Recover-TelegramGorselleri.ps1 ...`

**Verimlilik:** `telegram_cache.txt` kronolojiktir. `-SonAy 2` ile script cache'i **sondan (en yeni) başa**
tarar ve tarih aralığından yeterince eskiye inince durur (`-EskiDurma`), böylece tüm geçmişi
yönlendirmez.

Çıktı `<BotKlasoru>\telegram_gorseller\` altında proje klasörleri + `indeks.csv` (`;` ayraçlı, UTF-8):

| Sütun | Anlamı |
|---|---|
| `KullaniciAdi`, `KullaniciId` | Kaydı ekleyen (Telegram sohbet ID'sinden, kesin) |
| `Zenginlik` | `eslesti` (proje/kategori/personel bulundu) / `sadece_kullanici_tarih` |
| `Durum` | `indirildi` / `indirildi_jpg` (PNG'ye çevrilemedi, .jpg kaldı) / `zaten_var` / `tarandi` (-SadeceTara) / `getfile_hata:...` |

Diğer parametreler: `-SonAy 3`, `-AdSablonu "{proje}_{personel}_{tarih}"`
(alanlar: `tarih kullanici kullaniciid proje kategori personel uyeid anaid tip mesajid`),
`-Zenginlestir:$false` (log/Excel eşlemesini kapat), `-Yeniden`, `-KopyaBirak` (yönlendirilen kopyayı
silme), `-Format jpg`, `-BeklemeMs 350`, `-EskiDurma 400`.

### Bilinen sınırlar (dürüstçe)

- Kategori/personel/üye ID **her zaman garanti değildir**: bunlar Telegram'da yoktur, log+Excel eşleşmesiyle
  eklenir (kaydın %97,7'sinde kullanıcı doğru eşleşiyor). Eşleşmezse ad `tarih_kullanıcı` olur.
- `telegram_cache.txt`'de sohbet ID'si olmayan çok eski kayıtlar (bot'un ilk sürümünden) yönlendirilemez;
  atlanır ("eski/sohbetsiz").
- Bu script buradan (sunucu ortamı) canlı Telegram ile **test edilemedi**; tüm mantık gerçek log/Excel
  verisiyle ve sahte bir Telegram API'siyle uçtan uca sınandı. İlk kez `-SadeceTara` ile çalıştırıp
  `indeks.csv`'ye bakın.

---

## 2. İleriye dönük — `telebot.ps1` yaması

Bundan sonra her onaylanan kayıtta, Telegram'dan zaten inen görselin bir kopyası yerele kaydedilir; Gyazo'ya
bağımlı değildir. Orijinal `telebot.ps1` (17.08.2026) üzerine değişiklikler:

1. **Ayarlar:** `GORSEL_KLASOR` (varsayılan `<bot>\ekran_goruntuleri`), `GORSEL_KAYDET` (`"false"` ile kapat),
   `GORSEL_AD_SABLONU`. Üçü de `config.json`'dan okunur; zorunlu değil.
2. **`Get-GyazoFromFileId`**: Telegram'dan inen geçici dosya, Gyazo yüklemesi başarılıysa silinmez;
   `$global:SonGorselTemp`'te tutulur.
3. **Yeni fonksiyonlar** `ConvertTo-GuvenliAd` / `Get-GorselDosyaAdi` / `Save-YerelGorsel`. Adlandırma
   `Recover-TelegramGorselleri.ps1` ile aynı.
4. **`Process-Callback` → `onayla`**: `Add-ExcelRow` başarılıysa görsel `ekran_goruntuleri\<PROJE>\` altına
   taşınır ve loga `Gorsel kaydedildi -> ...` yazılır.
5. Açılış logunda `Gorsel : <klasör>` satırı.

**Not:** Kararınıza göre Gyazo yüklemesi başarısız olursa botun davranışı **değiştirilmedi** (eskisi gibi
"tekrar dene" der, kayıt oluşmaz). Görsel yerele yalnızca kayıt Excel'e yazıldığında konur.

Kurulum: botu durdur, `telebot.ps1`'i bu dosyayla değiştir, botu başlat. `config.json`'a ek gerekmez.

> Güvenlik notu: Bu depodaki `telebot.ps1`'de `ADMIN_PASSWORD` varsayılanı `BURAYA_ADMIN_SIFRE`
> yer tutucusuyla değiştirildi; gerçek şifre `config.json`'dan gelir.

---

## 3. Opsiyonel — `Export-GyazoGorselleri.ps1` (Gyazo)

Gyazo linki **hâlâ açılan** kayıtları Gyazo'dan indirir; kategori/personel dâhil tam adlandırma verir,
Telegram'a hiç dokunmaz. Gyazo'nun sildiği eski görselleri kurtaramaz (`indeks.csv`'de `gyazo_silinmis`).

```powershell
.\Export-GyazoGorselleri.ps1 -BotKlasoru "C:\...\telegramkant" -SadeceListele   # once listele
.\Export-GyazoGorselleri.ps1 -BotKlasoru "C:\...\telegramkant"                  # son 2 ayi indir
```

Kullanıcı eşlemesi `kesin` / `tahmini` / `belirsiz` olarak `indeks.csv`'de işaretlenir. (`kesin` eşleme,
aynı projede saniyeler içinde iki kayıt bittiğinde yanlış kişiyi seçmesin diye düzeltildi.)

Her üç script de Windows PowerShell 5.1 ve PowerShell 7 ile çalışır; Excel kurulu olması gerekmez.
