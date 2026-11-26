"""2.3.5 — API anahtarları sayfasındaki "Kullanım kılavuzu" kartının içeriği.

Uç tablosu, kopyalanabilir örnekler (curl, PowerShell, Python, Excel Power Query, Google E-Tablolar) ve örnek yanıtlar burada
tek yerde durur; şablon (_api_kilavuz.html) yalnız gösterir. Örnek yanıtlar ``tests/test_api_kilavuz_235.py`` içinde aynı veriyle
gerçek uçlar çağrılarak birebir karşılaştırılır; api.py davranışı değişirse test kırılır. Uzun başvuru: sunucu/API_KULLANIM.md."""
import json
from datetime import date

from markupsafe import escape

ANAHTAR_YER_TUTUCU = 'kp_ANAHTARINIZ'

# (yöntem, yol, amaç, ana parametreler, gereken izin)
UCLAR = (
    ('GET', '/api/v1/ozet', 'Toplam / onaylı / bekleyen; proje, kategori × tip ve ekleyen kırılımı',
     'proje, tarih1, tarih2, tarihsiz=1', ''),
    ('GET', '/api/v1/kayitlar', 'Kayıt listesi, sayfalı (kanıt tarihi yeni → eski)',
     'proje, durum (onayli | bekleyen | hepsi), kategori (harf duyarsız tam eşleşme), ekleyen, q, tarih1, tarih2, tarihsiz=1, '
     'sayfa (1…), adet (1–500, varsayılan 100)', ''),
    ('GET', '/api/v1/kayit/<id>', 'Tek kayıt ve yorumları', '—', ''),
    ('GET', '/api/v1/personel-ozet', 'Personel (ya da ekleyen) × kategori (ya da tip) sayım tablosu',
     'proje (tek), donem (bugun | hafta | gecen_hafta | ay | gecen_ay | son30 | hepsi | ozel), tarih1, tarih2, durum, grup (personel | ekleyen), '
     'sutun (kategori | tip)', ''),
    ('GET', '/api/v1/gorsel/<id>', 'Kanıt görseli (dosya olarak)', 'ikinci=1 (ikinci görsel)', 'Görsel indirme'),
    ('POST', '/api/v1/sorgu', 'Salt okunur SQL (yalnız tek SELECT; en çok 1000 satır, 5 saniye)',
     'JSON gövde: {"sql": "SELECT …", "parametreler": [ … ]}', 'SQL sorgusu'),
)

HATALAR = (
    (400, 'İstek geçersiz', 'Yanlış tarih biçimi (YYYY-AA-GG olmalı), adet 1–500 dışında, tanınmayan donem / grup / sutun değeri, '
          'tanınmayan durum (yalnız onaylı olmayan anahtarda; yalnız onaylı anahtarda durum yok sayılır ve uyari döner), '
          'personel-ozet\'te birden çok proje, SQL kuralına uymayan sorgu.'),
    (401, 'Anahtar yok ya da geçersiz', 'Authorization başlığı yok, anahtar eksik kopyalanmış, iptal edilmiş ya da süresi dolmuş. '
          'Oturum çerezi kabul edilmez.'),
    (403, 'Kapsam / izin dışı', 'Anahtarın kapsamı dışındaki proje istendi ya da anahtarda "Görsel indirme" / "SQL sorgusu" izni yok.'),
    (404, 'Bulunamadı', 'Kayıt yok ya da anahtarın kapsamında değil (ikisi aynı yanıtı alır), adres yanlış ya da API kapalı (.env: API_ACIK=0).'),
    (429, 'Çok fazla istek', 'Dakikalık sınır aşıldı; Retry-After başlığındaki saniye kadar bekleyin. Geçersiz anahtarla IP başına '
          'dakikada en çok 30 deneme; SQL ucunda aynı anda tek sorgu.'),
)

# Gerçek çağrıdan alınmış örnekler (test aynı veriyle tohumlayıp birebir karşılaştırır):
# kayıt 1: OF, CVPS, P123, onaylı (admin), ekleyen ahmet; kayıt 2: OF, DDS, P124, bekliyor, ekleyen zeynep.
ORNEK_OZET = {
    'ok': True, 'toplam': 2, 'onayli': 1, 'bekleyen': 1,
    'projeler': [{'proje': 'OF', 'toplam': 2, 'onayli': 1, 'bekleyen': 1}],
    'kategori_tip': [{'kategori': 'CVPS', 'tip': 'Sessiz', 'toplam': 1, 'onayli': 1},
                     {'kategori': 'DDS', 'tip': 'Telesekreter', 'toplam': 1, 'onayli': 0}],
    'ekleyenler': [{'ekleyen_id': '5551234', 'ekleyen_ad': 'ahmet', 'toplam': 1, 'onayli': 1},
                   {'ekleyen_id': '5559876', 'ekleyen_ad': 'zeynep', 'toplam': 1, 'onayli': 0}],
    'suzgec': {'proje': [], 'durum': 'hepsi', 'tarih1': '', 'tarih2': ''},
}
ORNEK_KAYIT = {
    'id': 1, 'proje': 'OF', 'kategori': 'CVPS', 'personel': 'P123', 'uye_id': '445566', 'ana_uye_id': None, 'lead_id': None,
    'tip': 'Sessiz', 'tarih': '2026-11-20 14:05:00', 'onayli': True, 'onaylayan': 'admin', 'onay_zamani': '2026-11-20 15:10:00',
    'ekleyen_id': '5551234', 'ekleyen_ad': 'ahmet', 'link': 'https://gyazo.com/abc123', 'link_turu': 'gyazo', 'aciklama': None, 'kaynak': 'telegram',
    'yorum_sayisi': 0,
}
ORNEK_KAYITLAR = {
    'ok': True, 'toplam': 1, 'sayfa': 1, 'adet': 100, 'sayfa_sayisi': 1,
    'suzgec': {'proje': [], 'durum': 'onayli', 'tarih1': '', 'tarih2': '', 'kategori': '', 'q': '', 'ekleyen': ''},
    'kayitlar': [ORNEK_KAYIT],
}
ORNEK_KAYITLAR_YOLU = '/api/v1/kayitlar?durum=onayli'


def _json(veri):
    # Panelin JSON çıktısıyla aynı sıra (Flask anahtarları alfabetik sıralar).
    return json.dumps(veri, ensure_ascii=False, indent=2, sort_keys=True)


def ornekler(taban, bugun=None):
    """Kopyalanabilir örnek blokları. ``taban``: panelin dış adresi (request.url_root), sonunda '/' olsun ya da olmasın."""
    taban = str(taban or '').rstrip('/')
    bugun = bugun or date.today()
    ay_basi = bugun.replace(day=1).isoformat()
    k = ANAHTAR_YER_TUTUCU
    ozet_url = taban + '/api/v1/ozet'
    liste_url = taban + '/api/v1/kayitlar?durum=onayli&tarih1=' + ay_basi + '&adet=100&sayfa=1'
    po_url = taban + '/api/v1/personel-ozet?donem=ay&grup=personel&sutun=kategori'
    curl = '\n'.join([
        '# Özet (toplam / onaylı / bekleyen)',
        'curl -s -H "Authorization: Bearer %s" "%s"' % (k, ozet_url),
        '',
        '# Bu ayın onaylı kayıtları, ilk 100',
        'curl -s -H "Authorization: Bearer %s" "%s"' % (k, liste_url),
        '',
        '# Bu ay personel × kategori tablosu',
        'curl -s -H "Authorization: Bearer %s" "%s"' % (k, po_url),
    ])
    powershell = '\n'.join([
        '$basliklar = @{ Authorization = "Bearer %s" }' % k,
        '',
        '# Özet',
        '$ozet = Invoke-RestMethod -Uri "%s" -Headers $basliklar' % ozet_url,
        '$ozet.toplam',
        '',
        '# Bu ayın onaylı kayıtları, tablo olarak',
        '$liste = Invoke-RestMethod -Uri "%s" -Headers $basliklar' % liste_url,
        '$liste.kayitlar | Select-Object id, proje, kategori, personel, onayli, tarih | Format-Table',
        '',
        '# CSV dosyasına kaydet (Excel ile açılır)',
        '$liste.kayitlar | Export-Csv -Path kayitlar.csv -NoTypeInformation -Encoding UTF8',
    ])
    python = '\n'.join([
        'import requests',
        '',
        'TABAN = "%s"' % taban,
        'BASLIK = {"Authorization": "Bearer %s"}' % k,
        '',
        'ozet = requests.get(TABAN + "/api/v1/ozet", headers=BASLIK, timeout=30)',
        'ozet.raise_for_status()',
        'print("Toplam:", ozet.json()["toplam"])',
        '',
        '# Bütün onaylı kayıtları sayfa sayfa çek (sayfa başına en çok 500)',
        'kayitlar, sayfa = [], 1',
        'while True:',
        '    r = requests.get(TABAN + "/api/v1/kayitlar", headers=BASLIK, timeout=60,',
        '                     params={"durum": "onayli", "adet": 500, "sayfa": sayfa})',
        '    r.raise_for_status()',
        '    veri = r.json()',
        '    kayitlar += veri["kayitlar"]',
        '    if sayfa >= veri["sayfa_sayisi"]:',
        '        break',
        '    sayfa += 1',
        'print(len(kayitlar), "kayıt")',
    ])
    excel = '\n'.join([
        'let',
        '    // Her istek en çok 500 kayıt verir; bu sorgu sayfa_sayisi kadar sayfayı çekip birleştirir.',
        '    Taban = "%s",' % taban,
        '    Baslik = [Authorization = "Bearer %s"],' % k,
        '    Sayfa = (n as number) => Json.Document(Web.Contents(Taban, [',
        '        RelativePath = "api/v1/kayitlar",',
        '        Query = [durum = "onayli", adet = "500", sayfa = Number.ToText(n)],',
        '        Headers = Baslik',
        '    ])),',
        '    Ilk = Sayfa(1),',
        '    Sayfalar = List.Generate(() => 1, each _ <= Ilk[sayfa_sayisi], each _ + 1,',
        '        each if _ = 1 then Ilk else Sayfa(_)),',
        '    Kayitlar = List.Combine(List.Transform(Sayfalar, each _[kayitlar])),',
        '    Tablo = Table.FromRecords(Kayitlar)',
        'in',
        '    Tablo',
    ])
    sheets = '\n'.join([
        'function kanitKayitlariniGetir() {',
        '  var anahtar = "%s";' % k,
        '  var taban = "%s";' % taban,
        '  // Her istek en çok 500 kayıt verir; sayfa_sayisi kadar sayfa çekilip birleştirilir.',
        '  var kayitlar = [], sayfaNo = 1, veri;',
        '  do {',
        '    var yanit = UrlFetchApp.fetch(taban + "/api/v1/kayitlar?durum=onayli&adet=500&sayfa=" + sayfaNo, {',
        '      headers: { Authorization: "Bearer " + anahtar },',
        '      muteHttpExceptions: true',
        '    });',
        '    if (yanit.getResponseCode() !== 200) throw new Error(yanit.getContentText());',
        '    veri = JSON.parse(yanit.getContentText());',
        '    kayitlar = kayitlar.concat(veri.kayitlar);',
        '    sayfaNo++;',
        '  } while (sayfaNo <= veri.sayfa_sayisi);',
        '  var alanlar = ["id", "proje", "kategori", "personel", "uye_id", "tarih", "onayli"];',
        '  var satirlar = [alanlar].concat(kayitlar.map(function (k) {',
        '    return alanlar.map(function (a) { return k[a] === null ? "" : k[a]; });',
        '  }));',
        '  var tablo = SpreadsheetApp.getActiveSpreadsheet();',
        '  var sayfa = tablo.getSheetByName("Kanıtlar") || tablo.insertSheet("Kanıtlar");',
        '  sayfa.clearContents();',
        '  sayfa.getRange(1, 1, satirlar.length, alanlar.length).setValues(satirlar);',
        '}',
    ])
    return [
        dict(kimlik='curl', baslik='curl (Linux / Mac / Windows 10+ curl.exe)', dil='bash', metin=curl,
             notlar=['Windows PowerShell\'de <code>curl</code> yazınca başka bir komut (Invoke-WebRequest) çalışır; aynı satırları '
                     '<code>curl.exe</code> diye yazın ya da Komut İstemi (cmd) kullanın.',
                     'Çıktıyı dosyaya kaydetmek için sona <code>-o ozet.json</code> ekleyin.']),
        dict(kimlik='powershell', baslik='Windows PowerShell', dil='powershell', metin=powershell,
             notlar=['Windows PowerShell 5.1 ve PowerShell 7 ile çalışır. Eski Windows\'ta TLS hatası alırsanız önce: '
                     '<code>[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12</code>',
                     'Hata ayrıntısı için: <code>try { … } catch { $_.ErrorDetails.Message }</code>']),
        dict(kimlik='python', baslik='Python (requests)', dil='python', metin=python,
             notlar=['Kurulum: <code>pip install requests</code>. Dakikalık istek sınırına takılmamak için büyük listelerde <code>adet=500</code> kullanın.']),
        dict(kimlik='excel', baslik='Excel Power Query', dil='powerquery', metin=excel,
             notlar=['Kolay yol: <b>Veri → Veri Al → Diğer Kaynaklardan → Web\'den</b> → <b>Gelişmiş</b>. URL bölümlerine '
                     '<code>%s/api/v1/kayitlar?durum=onayli&amp;adet=500</code> yazın; <b>HTTP istek üst bilgisi</b> olarak '
                     '<code>Authorization</code> seçip değerine <code>Bearer %s</code> girin. Erişim türü sorulursa <b>Anonim</b> seçin, '
                     'açılan kayıtları <b>Tabloya Dönüştür</b> ile tabloya çevirin. <b>Dikkat:</b> bu kolay yol yalnız ilk 500 kaydı getirir '
                     '(yanıttaki <code>toplam</code> ve <code>sayfa_sayisi</code>\'na bakın); hepsi için aşağıdaki sorguyu kullanın ya da '
                     '<code>tarih1</code> / <code>tarih2</code> / <code>proje</code> ile daraltın.' % (escape(taban), k),
                     'Tek istekte en çok 500 kayıt gelir; yukarıdaki sorgu <code>sayfa_sayisi</code> kadar sayfayı otomatik çekip birleştirir.',
                     'Ya da <b>Veri Al → Boş Sorgu → Gelişmiş Düzenleyici</b>\'ye yukarıdaki kodu yapıştırın. Yenile düğmesi veriyi yeniden çeker.',
                     'Anahtar Excel dosyasının içinde saklanır: dosyayı yalnız anahtarı görmesi gereken kişilerle paylaşın.']),
        dict(kimlik='sheets', baslik='Google E-Tablolar (Apps Script)', dil='javascript', metin=sheets,
             notlar=['<b>Uzantılar → Apps Script</b>\'e yapıştırın, kaydedin, <b>Çalıştır</b>\'a basın ve izin verin; '
                     '"Kanıtlar" sayfası dolar. Düzenli yenileme için Apps Script\'te <b>Tetikleyiciler</b> ekleyin.',
                     'Tek istekte en çok 500 kayıt gelir; kod <code>sayfa_sayisi</code> kadar sayfayı sırayla çekip birleştirir.',
                     '<code>IMPORTDATA</code> / <code>IMPORTJSON</code> gibi formüller başlık (Authorization) gönderemez; bu API ile çalışmaz.',
                     'Google sunucuları panelinize internetten ulaşabilmelidir (panel yalnız iç ağdaysa çalışmaz). Anahtarı kodda değil '
                     '<b>Proje Ayarları → Komut dosyası özellikleri</b>\'nde saklamak daha güvenlidir.']),
    ]


def kilavuz(taban, dakika_siniri, bugun=None):
    taban = str(taban or '').rstrip('/')
    return dict(taban=taban, uclar=[dict(yontem=a, yol=b, amac=c, parametreler=d, izin=e) for a, b, c, d, e in UCLAR],
                ornekler=ornekler(taban, bugun), hatalar=[dict(kod=a, ad=b, aciklama=c) for a, b, c in HATALAR],
                ornek_ozet=_json(ORNEK_OZET), ornek_kayitlar=_json(ORNEK_KAYITLAR), ornek_kayitlar_yolu=ORNEK_KAYITLAR_YOLU,
                ornek_hata=_json({'ok': False, 'kod': 401, 'hata': 'API anahtarı geçersiz. Anahtarı eksiksiz kopyaladığınızdan emin olun.'}),
                dakika_siniri=dakika_siniri, anahtar=ANAHTAR_YER_TUTUCU)
