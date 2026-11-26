"""2.4.1 — Küçük, bağımlılıksız QR kodu üreticisi (yalnız bayt kipi, hata düzeltme düzeyi M, sürüm 1–15) ve SVG çıktısı.

İki adımlı doğrulama kurulum sayfasındaki otpauth:// bağlantısını telefonla okutmak için kullanılır; dış kütüphane, CDN ya
da JavaScript gerekmez. Uygulama ISO/IEC 18004'ü izler: veri kodlama (0100 + sayaç + bayt + sonlandırıcı + 0xEC/0x11 dolgu),
GF(256) üzerinde Reed-Solomon (ilkel polinom 0x11D), blok serpiştirme, bulucu/zamanlama/hizalama desenleri, biçim (BCH 15,5;
maske 0x5412) ve sürüm (BCH 18,6) bilgisi, zikzak yerleşim, 8 maske ve dört ceza kuralıyla maske seçimi.
Doğrulama: tests/test_v241_iki_adim.py (bilinen Reed-Solomon / biçim / sürüm vektörleri ve bağımsız bir uygulamayla birebir
matris karşılaştırması).
"""
from html import escape

# Sürüm → (blok başına hata düzeltme kod sözcüğü, [(blok sayısı, bloktaki veri kod sözcüğü), ...]) — düzey M.
_BLOKLAR_M = {
    1: (10, [(1, 16)]), 2: (16, [(1, 28)]), 3: (26, [(1, 44)]), 4: (18, [(2, 32)]), 5: (24, [(2, 43)]),
    6: (16, [(4, 27)]), 7: (18, [(4, 31)]), 8: (22, [(2, 38), (2, 39)]), 9: (22, [(3, 36), (2, 37)]),
    10: (26, [(4, 43), (1, 44)]), 11: (30, [(1, 50), (4, 51)]), 12: (22, [(6, 36), (2, 37)]),
    13: (22, [(8, 37), (1, 38)]), 14: (24, [(4, 40), (5, 41)]), 15: (24, [(5, 41), (5, 42)]),
}
_HIZALAMA = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46],
    10: [6, 28, 50], 11: [6, 30, 54], 12: [6, 32, 58], 13: [6, 34, 62], 14: [6, 26, 46, 66], 15: [6, 26, 48, 70],
}
EN_BUYUK_SURUM = max(_BLOKLAR_M)

# GF(256) üs/log tabloları (ilkel polinom x^8+x^4+x^3+x^2+1 = 0x11D).
_US = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _US[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _US[_i] = _US[_i - 255]


def _carp(a, b):
    return 0 if a == 0 or b == 0 else _US[_LOG[a] + _LOG[b]]


def _uretec(n):
    """(x - α^0)(x - α^1)…(x - α^(n-1)); katsayılar en yüksek dereceden başlar."""
    poli = [1]
    for i in range(n):
        yeni = [0] * (len(poli) + 1)
        for j, k in enumerate(poli):
            yeni[j] ^= k
            yeni[j + 1] ^= _carp(k, _US[i])
        poli = yeni
    return poli


def reed_solomon(veri, n):
    """Veri kod sözcükleri için n hata düzeltme kod sözcüğü (polinom bölümünden kalan)."""
    gen = _uretec(n)
    kalan = list(veri) + [0] * n
    for i in range(len(veri)):
        katsayi = kalan[i]
        if katsayi:
            for j in range(1, len(gen)):
                kalan[i + j] ^= _carp(gen[j], katsayi)
    return kalan[len(veri):]


def _veri_sozcuk_sayisi(surum):
    return sum(adet * boy for adet, boy in _BLOKLAR_M[surum][1])


def surum_sec(uzunluk):
    """Bu kadar baytın sığdığı en küçük sürüm; sığmazsa ValueError."""
    for surum in sorted(_BLOKLAR_M):
        sayac_bit = 8 if surum <= 9 else 16
        if 4 + sayac_bit + 8 * uzunluk <= 8 * _veri_sozcuk_sayisi(surum):
            return surum
    raise ValueError('QR için metin çok uzun.')


def kod_sozcukleri(veri, surum):
    """Serpiştirilmiş son kod sözcüğü dizisi (veri + hata düzeltme)."""
    toplam = _veri_sozcuk_sayisi(surum)
    sayac_bit = 8 if surum <= 9 else 16
    bitler = []

    def koy(deger, uzunluk):
        for i in range(uzunluk - 1, -1, -1):
            bitler.append((deger >> i) & 1)
    koy(0b0100, 4)
    koy(len(veri), sayac_bit)
    for b in veri:
        koy(b, 8)
    if len(bitler) > toplam * 8:
        raise ValueError('QR için metin çok uzun.')
    koy(0, min(4, toplam * 8 - len(bitler)))
    while len(bitler) % 8:
        bitler.append(0)
    sozcukler = [int(''.join(map(str, bitler[i:i + 8])), 2) for i in range(0, len(bitler), 8)]
    dolgu = (0xEC, 0x11)
    ilk = len(sozcukler)
    while len(sozcukler) < toplam:
        sozcukler.append(dolgu[(len(sozcukler) - ilk) % 2])
    ec_n, gruplar = _BLOKLAR_M[surum]
    bloklar, ec_bloklar, konum = [], [], 0
    for adet, boy in gruplar:
        for _ in range(adet):
            blok = sozcukler[konum:konum + boy]
            konum += boy
            bloklar.append(blok)
            ec_bloklar.append(reed_solomon(blok, ec_n))
    sonuc = []
    for i in range(max(len(b) for b in bloklar)):
        for b in bloklar:
            if i < len(b):
                sonuc.append(b[i])
    for i in range(ec_n):
        for b in ec_bloklar:
            sonuc.append(b[i])
    return sonuc


def _bch(veri, uretec, uretec_bit):
    d = veri << (uretec_bit - 1)
    while d.bit_length() >= uretec_bit:
        d ^= uretec << (d.bit_length() - uretec_bit)
    return (veri << (uretec_bit - 1)) | d


def bicim_bitleri(maske):
    """Düzey M (00) + maske numarası → 15 bitlik biçim bilgisi (BCH(15,5), 0x5412 ile XOR)."""
    return _bch((0b00 << 3) | maske, 0x537, 11) ^ 0x5412


def surum_bitleri(surum):
    """Sürüm 7+ için 18 bitlik sürüm bilgisi (BCH(18,6), üreteç 0x1F25)."""
    return _bch(surum, 0x1F25, 13)


_MASKELER = (
    lambda i, j: (i + j) % 2 == 0,
    lambda i, j: i % 2 == 0,
    lambda i, j: j % 3 == 0,
    lambda i, j: (i + j) % 3 == 0,
    lambda i, j: (i // 2 + j // 3) % 2 == 0,
    lambda i, j: (i * j) % 2 + (i * j) % 3 == 0,
    lambda i, j: ((i * j) % 2 + (i * j) % 3) % 2 == 0,
    lambda i, j: ((i * j) % 3 + (i + j) % 2) % 2 == 0,
)


def _iskelet(surum):
    """İşlev desenleri yerleşmiş matris: True/False sabit modül, None veri alanı."""
    n = 17 + 4 * surum
    m = [[None] * n for _ in range(n)]
    for sat, sut in ((0, 0), (n - 7, 0), (0, n - 7)):
        for r in range(-1, 8):
            for c in range(-1, 8):
                y, x = sat + r, sut + c
                if 0 <= y < n and 0 <= x < n:
                    m[y][x] = (0 <= r <= 6 and c in (0, 6)) or (0 <= c <= 6 and r in (0, 6)) or (2 <= r <= 4 and 2 <= c <= 4)
    konumlar = _HIZALAMA[surum]
    for y in konumlar:
        for x in konumlar:
            if m[y][x] is not None:
                continue
            for r in range(-2, 3):
                for c in range(-2, 3):
                    m[y + r][x + c] = max(abs(r), abs(c)) != 1
    for i in range(8, n - 8):
        if m[6][i] is None:
            m[6][i] = i % 2 == 0
        if m[i][6] is None:
            m[i][6] = i % 2 == 0
    # Biçim ve sürüm alanları ayrılır (değerleri maske seçilince yazılır).
    for i in range(9):
        if m[8][i] is None:
            m[8][i] = False
        if m[i][8] is None:
            m[i][8] = False
    for i in range(8):
        m[8][n - 1 - i] = False
        m[n - 1 - i][8] = False
    m[n - 8][8] = True  # karanlık modül
    if surum >= 7:
        for i in range(18):
            m[i // 3][i % 3 + n - 11] = False
            m[i % 3 + n - 11][i // 3] = False
    return m


def _bilgileri_yaz(m, surum, maske):
    n = len(m)
    bits = bicim_bitleri(maske)
    for i in range(15):
        b = bool((bits >> i) & 1)
        if i < 6:                       # dikey kopya: sol üst sütun 8, sonra sol alt
            m[i][8] = b
        elif i < 8:
            m[i + 1][8] = b
        else:
            m[n - 15 + i][8] = b
        if i < 8:                       # yatay kopya: sağ üst satır 8, sonra sol üst
            m[8][n - i - 1] = b
        elif i < 9:
            m[8][15 - i] = b
        else:
            m[8][14 - i] = b
    m[n - 8][8] = True
    if surum >= 7:
        vb = surum_bitleri(surum)
        for i in range(18):
            b = bool((vb >> i) & 1)
            m[i // 3][i % 3 + n - 11] = b
            m[i % 3 + n - 11][i // 3] = b


def _yerlestir(iskelet, sozcukler, maske):
    n = len(iskelet)
    m = [satir[:] for satir in iskelet]
    bitler = [(s >> (7 - k)) & 1 for s in sozcukler for k in range(8)]
    indeks = 0
    yon = -1
    y = n - 1
    x = n - 1
    fonk = _MASKELER[maske]
    while x > 0:
        if x == 6:
            x -= 1
        while True:
            for c in (0, 1):
                xx = x - c
                if iskelet[y][xx] is None:
                    koyu = bool(bitler[indeks]) if indeks < len(bitler) else False
                    indeks += 1
                    m[y][xx] = koyu != fonk(y, xx)
            y += yon
            if y < 0 or y >= n:
                y -= yon
                yon = -yon
                break
        x -= 2
    return m


def ceza(m):
    """ISO/IEC 18004 maske ceza puanı (N1=3, N2=3, N3=40, N4=10)."""
    n = len(m)
    puan = 0
    for satirlar in (m, [list(s) for s in zip(*m)]):
        for satir in satirlar:
            uzunluk = 1
            for i in range(1, n):
                if satir[i] == satir[i - 1]:
                    uzunluk += 1
                else:
                    if uzunluk >= 5:
                        puan += uzunluk - 2
                    uzunluk = 1
            if uzunluk >= 5:
                puan += uzunluk - 2
            metin = ''.join('1' if v else '0' for v in satir)
            for desen in ('10111010000', '00001011101'):
                bas = metin.find(desen)
                while bas != -1:
                    puan += 40
                    bas = metin.find(desen, bas + 1)
    for y in range(n - 1):
        for x in range(n - 1):
            if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                puan += 3
    koyu = sum(sum(1 for v in s if v) for s in m)
    puan += 10 * (abs(koyu * 100 // (n * n) - 50) // 5)
    return puan


def matris(metin, maske=None, surum=None):
    """Metnin QR matrisi (satır listesi, True = koyu). maske verilmezse en düşük cezalı maske seçilir."""
    veri = metin.encode('utf-8') if isinstance(metin, str) else bytes(metin)
    surum = surum or surum_sec(len(veri))
    sozcukler = kod_sozcukleri(veri, surum)
    iskelet = _iskelet(surum)
    adaylar = [maske] if maske is not None else range(8)
    en_iyi = None
    for mk in adaylar:
        m = _yerlestir(iskelet, sozcukler, mk)
        _bilgileri_yaz(m, surum, mk)
        p = ceza(m) if maske is None else 0
        if en_iyi is None or p < en_iyi[0]:
            en_iyi = (p, m)
    return en_iyi[1]


def svg(metin, modul=6, kenar=4, baslik='QR kodu'):
    """Satır içi kullanılabilir SVG (beyaz zemin, siyah modüller; koyu temada da okunur). Boyut CSS ile değiştirilebilir."""
    m = matris(metin)
    n = len(m)
    boy = n + 2 * kenar
    parcalar = []
    for y, satir in enumerate(m):
        x = 0
        while x < n:
            if satir[x]:
                bas = x
                while x < n and satir[x]:
                    x += 1
                parcalar.append('M%d %dh%dv1h-%dz' % (bas + kenar, y + kenar, x - bas, x - bas))
            else:
                x += 1
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" role="img" '
            'aria-label="%s" shape-rendering="crispEdges" class="qr-svg"><title>%s</title><rect width="100%%" height="100%%" fill="#fff"/>'
            '<path fill="#000" d="%s"/></svg>') % (boy, boy, boy * modul, boy * modul, escape(baslik), escape(baslik), ''.join(parcalar))
