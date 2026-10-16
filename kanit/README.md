# Kanıt Merkezi — sunucu sürümü (kanit/)

Telegram botu + web paneli + tek veritabanı. Excel yok: veri SQLite'ta (WAL), "Excel" istendiğinde üretilen bir rapordur.
Windows sürümü (`telegram/telebot.ps1` + `telegrampanel/`) geçiş tamamlanana kadar olduğu gibi durur.

## Yerleşim

```
kanit/
  requirements.txt
  kanit/__init__.py      SURUM
  kanit/ayar.py          .env (/opt/kanit/.env) + ortam değişkenleri -> dict (VERI, DB, GORSELLER, ONBELLEK, TELEGRAM_TOKEN, GYAZO_TOKEN, BOT_PASSWORD, ADMIN_IDS, PORT, DINLE ...)
  kanit/db.py            ŞEMA + ORTAK YAZMA İŞLEMLERİ (tek sözleşme; aşağıya bak)
  kanit/normalle.py      Türkçe normalizasyon (normalle / kucuk / buyuk / metin)
  kanit/yetki.py         yetki kısaltmaları: admin, *, OF, OF:oku,kt  (coz / izin / izinli_projeler / ozet)
  kanit/gorsel.py        gorsel deposu: kaydet / tam_yol / kucuk / dosya_adi / link_turu_ve_kimlik / gyazo_url / jpeg_yap
  kanit/bot/             Telegram botu (python, requests ile long polling)         -> kanit.bot
  kanit/web/             Flask paneli (templates/, static/)                          -> kanit.web
  kanit/ice_aktar.py     Excel + bot durum dosyaları + görsel klasörleri -> veritabanı (önce deneme raporu)
  kanit/disa_aktar.py    tam kitap Excel çıktısı (proje başına sayfa, A..J düzeni)
  kanit/__main__.py      komut satırı: python -m kanit web | bot | ice-aktar | yedekle | kullanici-ekle | sifre-sifirla | disa-aktar
  tests/                 test_db.py (temel), test_web.py, test_bot.py, test_ice_aktar.py
deploy/                  kur.sh, guncelle.sh, yedekle.sh, kanit-web.service, kanit-bot.service, nginx örneği, env.ornek, ISLETME.md
```

## Sözleşme (herkes buna uyar)

1. `kayitlar` tablosuna yalnızca `db.kayit_ekle / kayit_guncelle / kt_ayarla / kayit_sil / kayit_geri_al` ile yazılır.
   Bu fonksiyonlar arşivi (`arsiv`, dokunulmaz), denetimi (`denetim`) ve bildirimleri (`bildirimler`) kendileri yazar.
   Doğrudan `UPDATE kayitlar` YASAK.
2. Yorumlar: `db.yorum_ekle / yorum_duzenle / yorum_sil / yorum_okundu / okunmamis_yorumlar`.
3. Telegram üyeleri: `db.tg_*` (onayla, onay_kaldir, engelle, engel_kaldir, tam_sifirla, deneme, kayit_sayaci); oturumlar `db.oturum_*`.
4. Panel kullanıcıları: `db.kullanici_*`; giriş `db.kullanici_dogrula(conn, ad, sifre, kaynak_ip)`.
5. Çalışma zamanı ayarları (`bakim_modu`, `gyazo_bakim`, `telegram_offset`, `bot_nabiz`, `son_degisiklik`) `db.ayar_al / ayar_yaz`.
6. Şema değişikliği gerekirse `db.SEMA`'ya ekleme + `db._goc` içinde `ALTER TABLE` adımı + `SEMA_SURUMU` artışı; var olan sütun/tablo adları değişmez.
7. Python kaynak dosyaları ASCII (Türkçe karakter yalnızca `\u` kaçışıyla); şablonlar/JS tam Türkçe.
8. Zaman damgaları yerel `yyyy-MM-dd HH:mm:ss` metin (TZ=Europe/Istanbul). Karşılaştırmalar `normalle.normalle` ile, SQLite `upper/LIKE` ile değil.
9. Görseller `VERI/gorseller/<PROJE>/<dosya>`; kayıtta göreli yol (`gorsel_dosya`). Dışarıdan gelen yol/ad asla doğrudan kullanılmaz.
10. Testler `cd kanit && python3 tests/test_db.py` gibi tek dosya olarak çalışır (pytest de olur); dış ağ yok, gerçek Telegram/Gyazo yok (sahte sunucu).

## Çalıştırma (geliştirme)

```
cd kanit
python3 -m pip install -r requirements.txt
KANIT_VERI=/tmp/kanit-veri python3 -m kanit web      # http://127.0.0.1:8080
KANIT_VERI=/tmp/kanit-veri python3 -m kanit bot
```

Sunucu kurulumu: `deploy/ISLETME.md`.
