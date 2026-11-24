# Kanıt Paneli 2.3.1 — bildirim ve onay görünürlüğü (24 Kasım 2026)

2.3.0 kurulumunun üzerine `deploy/apply-update.sh` ile uygulanır; veritabanı yapısı değişmez, mevcut kayıtlar, kullanıcılar ve ayarlar korunur. Yalnız `kanit-web` yeniden başlar; bot etkilenmez.

## Hatırlatma bildirimleri

- Onay bekleyen bir kayıt **3 günü** geçince (`HATIRLATMA_GUN`) o projede onay yetkisi olan herkese "Bu ID'nin kontrolü N gündür bekliyor." bildirimi düşer; onaylanmadıkça **3 günde bir** (`HATIRLATMA_TEKRAR_GUN`) yinelenir, aynı kayıt için günde en çok bir.
- Eski Excel'den aktarılan onaysız kayıtlar (gerçek veride 300) kişi başına yüzlerce bildirim üretmez: proje başına tek özet gelir ("GA: 126 kayıt 3 günden uzun süredir onay bekliyor (eski Excel'den)."). Ayrıca kullanıcı başına günde en çok 50 kayıt hatırlatması (`HATIRLATMA_GUNLUK_SINIR`); fazlası özete katlanır.
- Üretim web sürecinde 30 dakikada bir yapılır (`HATIRLATMA_KONTROL_DK`; 0 = kapalı); anında üretmek için `python -m app.cli hatirlatma-uret`.
- Ana sayfadaki proje kartlarında "3 gündür bekleyen: X" sayacı; Kayıtlar → Gelişmiş filtrelerde "En az … gündür bekleyen".

## Onaysız kayıtların raporlama ekibine görünümü

`ONAYSIZ_GORUNUM` ayarı, projede **onay yetkisi olmayan** kullanıcılar için geçerlidir (takım liderleri her şeyi görür):

- `uyar` (varsayılan): listede ve kartlarda kırmızı "ONAY YOK — raporlamada kullanmayın" rozeti; kayıt ayrıntısının üstünde kırmızı şerit; arama yalnız onaysız kayıt döndürüyorsa listenin üstünde uyarı kutusu; Excel çıktısında "Takım lideri onayı" sütunu (Onaylı / YOK) ve dosya adında onaysız sayısı.
- `gizle`: onaysız ve silinmiş kayıtlar liste, arama, ayrıntı (403 "Bu kaydın onayı yok; yalnız onaylı kayıtlar gösterilir."), ekleyen profili, Kanıt Kontrolü ve çıktıda hiç görünmez; durum sekmelerinde yalnız Onaylı kalır.
- Çıktı sayfasındaki onay durumu seçenekleri: **Hepsi / Onaylılar / Onaysızlar (onay bekleyen) / Silinenler**.

## Bildirime tıklayınca doğrudan hedefe gitme

- Zil listesi ve Bildirimler sayfasındaki her satır tıklanınca ilgili kayıt doğrudan açılır (yeni kanıt, onay, hatırlatma).
- Yorum, soru ve yanıt bildirimlerinde kayıt açılır, Konuşma bölümü genişler, ilgili yorum satırına kaydırılır ve 3 saniye vurgulanır.
- Hatırlatma özeti projenin "bekleyen, 3 günden eski" listesini açar. Telefonda da aynı şekilde çalışır; okundu işaretleme korunur.

## Ekleyen profili özeti

- Telegram ekleyen profilinde tarih aralığı (Son 7 gün / Son 30 gün / Bu ay / Tümü ya da elle) ve seçili aralık için özet: Toplam / Onaylı / Bekleyen / Silinen; kategori × tip (sessiz, telesekreter, diğer) çapraz tablosu; aynı görünümü Excel'e aktaran bağlantı. "Bu kişi bu ay kaç CVPS, kaç sessiz ekledi?" sorusu tek bakışta cevaplanır.

## Yeni `.env` anahtarları (hepsi isteğe bağlı)

| Anahtar | Varsayılan | Anlam |
|---|---|---|
| `ONAYSIZ_GORUNUM` | `uyar` | Onay yetkisi olmayan kullanıcı için onaysız kayıt: `uyar` ya da `gizle` |
| `HATIRLATMA_GUN` | `3` | Hatırlatma eşiği (gün) |
| `HATIRLATMA_TEKRAR_GUN` | `3` | Aynı kayıt için tekrar aralığı (gün) |
| `HATIRLATMA_KONTROL_DK` | `30` | Web sürecinde kontrol sıklığı (dakika); `0` = kapalı, yalnız CLI |
| `HATIRLATMA_GUNLUK_SINIR` | `50` | Kullanıcı başına günlük kayıt hatırlatması üst sınırı |
