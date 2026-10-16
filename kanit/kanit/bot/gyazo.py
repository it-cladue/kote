# -*- coding: utf-8 -*-
"""Gyazo yukleme (botun Upload-ToGyazo'su): POST <GYAZO_API>/api/upload, Bearer token, multipart 'imagedata'.
Donen permalink_url (https://gyazo.com/<id>) kayda link olarak yazilir. Taban adres ayar 'GYAZO_API' ile degisir (test icin)."""
import logging
import requests

log = logging.getLogger("kanit.bot")
VARSAYILAN_API = "https://upload.gyazo.com"


def yukle(token, baytlar, api=None, zaman_asimi=30):
    """-> permalink_url | None (hata loglanir)"""
    url = (api or VARSAYILAN_API).rstrip("/") + "/api/upload"
    try:
        r = requests.post(url, headers={"Authorization": f"Bearer {token or ''}"},
                          files={"imagedata": ("img.jpg", baytlar, "image/jpeg")}, timeout=zaman_asimi)
        if r.status_code != 200:
            log.warning("! Gyazo hatasi: HTTP %s %s", r.status_code, r.text[:200])
            return None
        j = r.json()
        link = j.get("permalink_url") or j.get("url")
        if not link:
            log.warning("! Gyazo yaniti linksiz: %s", str(j)[:200])
            return None
        return str(link)
    except Exception as e:  # ag hatasi, bozuk JSON
        log.warning("! Gyazo hatasi: %s", e)
        return None
