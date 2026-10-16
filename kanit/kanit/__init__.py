# -*- coding: utf-8 -*-
"""Kanit Merkezi - sunucu surumu.

Telegram botu + web paneli + tek veritabani (SQLite, WAL). Excel yok; "Excel" artik istendiginde uretilen bir rapordur.
Paketler: kanit.db (sema + ortak yazma islemleri + arsiv), kanit.ayar (ayarlar), kanit.normalle (Turkce normalizasyon),
kanit.yetki (yetki kisaltmalari), kanit.gorsel (gorsel deposu), kanit.bot (Telegram botu), kanit.web (Flask paneli),
kanit.ice_aktar (Excel / durum dosyasi / gorsel aktarici), kanit.disa_aktar (tam kitap Excel ciktisi).
"""
SURUM = "2.0.0"
