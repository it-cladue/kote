# -*- coding: utf-8 -*-
"""Tek normalizasyon: bot yazarken, aktarici okurken, arama ve liste kontrolu karsilastirirken AYNI fonksiyon.
SQLite'in upper()/LIKE'i ASCII'dir; 'I/i/İ/ı' ve 'ş/ğ/ç/ö/ü' icin burada kucuk harfe cevrilir ve *_norm sutunlarina yazilir."""
import re

_BOSLUK = re.compile(r"\s+")
_URL = re.compile(r"^(https?://)?(www\.)?", re.I)
_TR = str.maketrans({"I": "ı", "İ": "i"})


def kucuk(s):
    """Turkce dogru kucuk harf: I -> ı, İ -> i, sonra casefold."""
    return str(s or "").translate(_TR).lower()


def metin(v):
    """Hucre/alan degeri -> temiz metin (None -> '', float 123.0 -> '123', bool -> 'TRUE'/'FALSE')."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return _BOSLUK.sub(" ", str(v)).strip()


def normalle(v):
    """Karsilastirma anahtari: kirp, Turkce kucuk harf, ic bosluklar tek bosluk; yalniz rakamsa bastaki sifirlar atilir;
    link ise http(s)://, www., sondaki / ve sorgu/parca kismi atilir."""
    s = kucuk(metin(v))
    if not s:
        return ""
    if s.isdigit():
        return s.lstrip("0") or "0"
    if s.startswith(("http://", "https://", "www.")):
        s = _URL.sub("", s).split("?", 1)[0].split("#", 1)[0].rstrip("/")
    return s


def buyuk(s):
    """Turkce dogru buyuk harf (i -> İ, ı -> I)."""
    return str(s or "").replace("i", "İ").replace("ı", "I").upper()
