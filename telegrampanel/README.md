# telegrampanel — Kanıt botu web paneli

Flask + SQLite tabanlı panel. Her kullanıcı kendi bilgisayarında çalıştırır (`KanitPaneli.exe`, PyInstaller); bot klasörü OneDrive ile paylaşılan `telegramkant` klasörüdür. Ayrıntılı kullanım: `OKU_BENI_PANEL.txt`.

Exe derleme: `.github/workflows/panel-exe.yml` (windows-latest + PyInstaller, `KanitPaneli.spec`). Çıktı `exe-dagitim` dalına ve bir GitHub Release'e konur.

```
telegrampanel/
  app/            Flask uygulaması (panel.py giriş noktası) + templates/ + static/
  bot_yamasi/     telebot.ps1'e eklenen "panel köprüsü" bloğu ve uygulayıcı (uygula.py)
  KUR.bat         venv + paketler + ilk süper admin
  BASLAT.bat      paneli başlatır (http://127.0.0.1:8080)
  GOREV_KUR.bat   oturum açılınca otomatik başlat (schtasks)
  KULLANICI_EKLE.bat / SIFRE_SIFIRLA.bat
  panel_ayar.ornek.json  -> panel_ayar.json olarak kopyalanır
```

Tasarım kuralları:
- Panel Excel'e **yazmaz**. İşlemler `<bot>/panel_kuyruk/<bilgisayar>.jsonl` dosyasına eklenir (her PC kendi dosyası: OneDrive çakışması olmaz); bot (`Process-PanelKuyrugu`) kendi COM bağlantısıyla uygular, sonucu `panel_kuyruk_sonuc.jsonl`'a yazar. Süper admin bot komutları da (`bot_onayla`, `bot_engelle`, `bot_bakim` …) aynı kuyruktan gider; bot klasöründeki dosyalara yalnızca bot yazar.
- Panel kullanıcıları `<bot>/panel_kullanicilar.json` içinde (hash'li); her PC aynı listeyi kullanır.
- Panel verisi exe modunda `%LOCALAPPDATA%\KanitPaneli` altında (ayar, SQLite, küçük resimler).
- Excel her `YENILEME_DK` dakikada bir kopyalanıp `openpyxl` ile okunur; OF sayfasında H sütunu 1M satır dolu olduğu için yalnızca A..G'ye bakılarak son satır bulunur.
- Yetki sözdizimi: `admin`, `*`, `OF`, `OF:oku`, `OF:oku,kt`, `OF,PP:oku GA` (`app/yetki.py`).
- Bot tarafı: `bot_yamasi/uygula.py <telebot.ps1>` dört çapaya ekleme yapar (ayar, fonksiyonlar, `Write-PanelKayit`, ana döngüde `Process-PanelKuyrugu; Write-Heartbeat`).

Komut satırı: `python -m app.panel kullanici-ekle <ad> <yetki> [sifre]`, `sifre-sifirla <ad>`, `ice-aktar`, `kullanicilar`.
