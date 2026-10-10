# -*- coding: utf-8 -*-
"""Yetki metni cozumleme.

Sozdizimi (virgul/noktali virgul/bosluk ile ayrilir):
  admin            -> her sey (tum projeler + bot yonetimi + kullanici yonetimi)
  *                -> tum proje sayfalari, tam yetki (oku, gorsel, kt, duzenle, sil)
  OF               -> OF sayfasi, tam yetki (takim admini)
  OF:oku           -> OF sayfasi, sadece bakar (oku + gorsel)
  OF:oku,kt        -> OF sayfasi, bakar ve KT isaretler
Eylemler: oku, gorsel, kt, duzenle, sil
"""
import re

EYLEMLER = ("oku", "gorsel", "kt", "duzenle", "sil")
TAM = set(EYLEMLER)


def coz(metin):
    """-> {'admin': bool, 'hepsi': set|None, 'projeler': {PROJE: set(eylem)}}"""
    sonuc = {"admin": False, "hepsi": None, "projeler": {}}
    if not metin:
        return sonuc
    for parca in re.split(r"[;\s]+", metin.strip()):
        if not parca:
            continue
        # "OF,PP:oku,kt" -> alanlar OF,PP ; eylemler oku,kt
        if ":" in parca:
            alan_s, eylem_s = parca.split(":", 1)
            eylemler = {e.strip().lower() for e in eylem_s.split(",") if e.strip()}
            eylemler = {e for e in eylemler if e in TAM}
            if "oku" in eylemler:
                eylemler.add("gorsel")  # bakabilen gorseli de acar
            if not eylemler:
                eylemler = {"oku", "gorsel"}
        else:
            alan_s, eylemler = parca, set(TAM)
        for alan in alan_s.split(","):
            alan = alan.strip()
            if not alan:
                continue
            if alan.lower() == "admin":
                sonuc["admin"] = True
            elif alan == "*":
                sonuc["hepsi"] = set(sonuc["hepsi"] or set()) | eylemler
            else:
                a = alan.upper()
                sonuc["projeler"][a] = sonuc["projeler"].get(a, set()) | eylemler
    if sonuc["admin"]:
        sonuc["hepsi"] = set(TAM)
    return sonuc


def izin(yk, proje, eylem):
    """yk = coz(...) ciktisi. Proje bazli izin kontrolu."""
    if yk.get("admin"):
        return True
    if yk.get("hepsi") and eylem in yk["hepsi"]:
        return True
    p = yk.get("projeler", {}).get((proje or "").upper())
    return bool(p and eylem in p)


def izinli_projeler(yk, tum_projeler):
    if yk.get("admin") or yk.get("hepsi"):
        return list(tum_projeler)
    return [p for p in tum_projeler if p in yk.get("projeler", {})]


def ozet(metin):
    """Kullanici listesinde gosterim icin kisa aciklama."""
    yk = coz(metin)
    if yk["admin"]:
        return "Super admin (her sey)"
    parcalar = []
    if yk["hepsi"]:
        parcalar.append("Tum projeler: " + ", ".join(sorted(yk["hepsi"])))
    for p, e in sorted(yk["projeler"].items()):
        parcalar.append(f"{p}: " + ("tam" if e == TAM else ", ".join(sorted(e))))
    return "; ".join(parcalar) or "(yetki yok)"
