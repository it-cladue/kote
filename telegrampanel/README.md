# telegrampanel — Kanıt botu web paneli

Flask + SQLite tabanlı, botla aynı bilgisayarda çalışan panel. Ayrıntılı kullanım: `OKU_BENI_PANEL.txt`.

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
- Panel Excel'e **yazmaz**. İşlemler `<bot>/panel_kuyruk.jsonl` dosyasına eklenir; bot (`Process-PanelKuyrugu`) kendi COM bağlantısıyla uygular, sonucu `panel_kuyruk_sonuc.jsonl`'a yazar.
- Excel her `YENILEME_DK` dakikada bir kopyalanıp `openpyxl` ile okunur; OF sayfasında H sütunu 1M satır dolu olduğu için yalnızca A..G'ye bakılarak son satır bulunur.
- Yetki sözdizimi: `admin`, `*`, `OF`, `OF:oku`, `OF:oku,kt`, `OF,PP:oku GA` (`app/yetki.py`).
- Bot tarafı: `bot_yamasi/uygula.py <telebot.ps1>` dört çapaya ekleme yapar (ayar, fonksiyonlar, `Write-PanelKayit`, ana döngüde `Process-PanelKuyrugu; Write-Heartbeat`).

Komut satırı: `python -m app.panel kullanici-ekle <ad> <yetki> [sifre]`, `sifre-sifirla <ad>`, `ice-aktar`, `kullanicilar`.
