# Kanıt Paneli 2.3.7 — personel raporunda "Durumlar" (26 Kasım 2026)

2.3.5 üzerine `deploy/apply-update.sh` ile uygulanır (KURULUM §13, güncelleme yolu değişmedi). Veritabanı şeması ve `.env` değişmez, yeni ayar yoktur. Değişen dosyalar: `app/personel_ozeti.py`, `app/panel.py` (yalnız personel raporu ve Excel çıktısı), `app/api.py` (`/api/v1/personel-ozet`), şablonlar `_personel_ozet.html` ve `rapor_personel.html`, `static/rapor.js`, `static/stil.css` (po-* bölümü). Tarayıcı yeni dosyaları kendiliğinden alır (sürüm numaralı adresler).

## Ekip ne görür?

**Rapor** sayfasında özet sayıların (kişi / kanıt / onaylı / bekleyen) hemen altında, kişi kartlarından önce **Durumlar** bölümü vardır. Bölüm, ekranda seçili süzgeçlerle (proje, kategori, dönem, durum, gruplama, sütun) hesaplanan aynı tablo üzerinden, takım liderinin bakması gereken yerleri kısa cümlelerle listeler. Her satır bir bağlantıdır; tıklanınca Kayıtlar sayfası o kişinin ilgili kayıtlarıyla açılır.

Beş grup vardır (boş grup gösterilmez, başlıktaki rozet satır sayısıdır):

| Grup | Örnek satır | Ne zaman |
|---|---|---|
| **Ortalamanın altında** | 210, CVPS kategorisinde ortalamanın yarısından az kayıt ekledi (3 / ort. 8,4 · %36) | Kişinin o kategorideki sayısı eşiğin altında. En az 3 kişi varsa toplam için de: "210 toplamda ortalamanın yarısından az kayıt ekledi (8 / ort. 15,0 · %53)". |
| **Hiç eklemedi** | 273 bu dönemde hiç HGST eklemedi (ort. 4,2) | Kişi başına ortalaması en az 3 olan bir kategoride hiç kaydı yok. |
| **Önceki döneme göre düşüş** | 171: önceki döneme göre %61 düşüş (31 → 12) · 190: bu dönem hiç kayıt yok (önceki dönem 12) | Önceki dönemde en az 3 kaydı vardı ve bu dönem en az %30 az; ya da önceki dönemde kaydı vardı, bu dönem hiç yok. |
| **Onay bekleyeni yüksek** | 255: onay bekleyen oranı yüksek (12 / 40 · %30) | En az 5 kaydın en az %30'u onay bekliyor (yalnız Durum = Tümü iken). |
| **Öne çıkanlar** | 280 ortalamanın üstünde (32 / ort. 15,0 · %213) · 280, CVPS kategorisinde en çok kaydı ekledi (20 / ort. 8,4 · %238) | En az 5 kayıt ve ortalamanın 1,5 katı; ya da bir kategoride en çok kayıt (en az 5 ve ortalamanın 2 katı). |

Her grupta ilk 8 satır görünür; **Daha fazla göster (N satır daha)** kalanları açar, **Daha az göster** geri kapatır (sayfa yenilenmez, klavyeyle kullanılır). Hiç satır yoksa "Bu dönemde dikkat çeken bir durum yok." yazar.

### Kurallar sade dille

- **Ortalama** = dönemde en az bir kaydı olan kişi başına düşen kayıt. Ör. CVPS'te 5 kişinin toplam 42 kaydı varsa CVPS ortalaması 42 ÷ 5 = 8,4'tür. Hiç CVPS eklemeyen ama başka kategoride kaydı olan kişi de bu 5 kişiye dahildir. Genel ortalama = tüm kayıtlar ÷ kişi sayısı. Bölümün üstündeki açıklama satırı bu sayıları gösterir.
- **Eşik** (%50 / %75 / %100) "ortalamanın altında" sınırıdır: %50 = ortalamanın yarısının altı (varsayılan), %75 = dörtte üçünün altı, %100 = ortalamanın altı. Eşik yalnız bu grubu etkiler. Seçim adreste `esik=75` olarak durur ve diğer süzgeçlerle birlikte hatırlanır.
- Çok küçük kategoriler (kişi başına 2'den az) "ortalamanın altında" sayılmaz; "hiç eklemedi" için ortalama en az 3 olmalıdır.
- **Önceki dönem**, seçili dönemle aynı uzunlukta ve hemen öncesindeki aralıktır, süzgeçler aynıdır: *Bugün* → dün; *Bu hafta* → geçen haftanın pazartesisinden aynı güne; *Bu ay* → ayın 1'inden önceki aynı sayıda gün (ör. 1–26 Kasım için 6–31 Ekim); *Son 30 gün* → ondan önceki 30 gün; *Özel aralık* → başlangıçtan önceki aynı uzunlukta aralık (yalnız başlangıç verilmişse bitiş bugün sayılır). *Tümü*'nde ve başlangıcı olmayan aralıkta karşılaştırma yapılmaz. Açıklama satırı önceki dönemin tarihlerini yazar.
- Kişi sayısı 2'nin altındaysa kıyas yapılmaz ("Kıyas için en az 2 kişi gerekir."); düşüş ve bekleyen yine gösterilir.
- Kategori seçiliyken yalnız o kategori karşılaştırılır (toplam satırları yinelenmesin diye çıkmaz). Sütun = Tip seçiliyse tipler ("Sessiz tipinde …"), Grupla = Ekleyen seçiliyse ekleyenler karşılaştırılır.
- Personeli ya da kategorisi boş kayıtlar ortalamaya katılır, ayrıca listelenmez. Sıralama en kötüden başlar (en düşük yüzde, en büyük düşüş).
- **Bu liste bir yargı değildir**: izinli, yeni başlayan ya da başka işte çalışan kişi de listede görünebilir. Amaç takım liderine nereye bakacağını göstermektir.

### Bağlantılar

Satırdaki ilk sayı ile tıklanınca açılan liste aynıdır: kategori satırı o kişinin o kategorideki kayıtlarını, toplam/düşüş/öne çıkan satırı kişinin dönemdeki tüm kayıtlarını, bekleyen satırı yalnız onay bekleyenlerini, "bu dönem hiç kayıt yok" satırı önceki dönemdeki kayıtlarını açar. Sayının 0 olduğu satırlar (hiç eklemedi) kişinin dönemdeki diğer kayıtlarını açar.

### Ana sayfa, çıktılar, API

- Ana sayfadaki "Personel bazında kanıtlar" kartında özet sayıların altında tek satır: "Durumlar: 5 kişi ortalamanın altında · 2 kişi bazı kategorilerde hiç eklemedi · 1 düşüş · … Rapor →". Bağlantı kartın süzgeçleriyle Rapor sayfasının Durumlar bölümünü açar. Dikkat çeken bir şey yoksa satır görünmez. Ana sayfada eşik varsayılan olarak %50'dir; adreste `esik` verilirse o kullanılır.
- **Excel**: ikinci sayfa "Durumlar" (Grup, Kişi, Kategori/Sütun, Sayı, Ortalama, Yüzde/Değişim, Açıklama; tüm satırlar). "Bilgi" sayfasına eşik, ortalama ve önceki dönem yazılır. **CSV değişmedi** (tek tablo).
- **Yazdır**: bölüm özet sayılardan sonra sıkışık basılır (iki sütun, grup başına ilk 8 satır ve "… N satır daha (tümü Excel'in Durumlar sayfasında)" notu). Rapor alt başlığında "Durumlar eşiği: %50" yazar.
- **API**: `GET /api/v1/personel-ozet?…&durumlar=1&esik=50` yanıta `durumlar` nesnesini ekler (`API_KULLANIM.md` §3.6.1). `durumlar` verilmezse yanıt eskisiyle aynıdır.

## Test

Yeni `tests/test_rapor_durumlar_237.py` (15 test) ve tarayıcı senaryosu `tests/rapor_durumlar_tarayici.js` (Node + Playwright yoksa atlanır; ekran görüntüleri `/tmp/claude-0/p237/`). `tests/test_personel_ozet_234.py`'de Excel sayfa listesi Özet / Durumlar / Bilgi olarak güncellendi.
