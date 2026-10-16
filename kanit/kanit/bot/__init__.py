# -*- coding: utf-8 -*-
"""Telegram botu (python, requests ile long polling). telegram/telebot.ps1'in uye akisinin portu.

Parcalar: telegram_api (API sarmalayici), gyazo (yukleme), akis (uye akislari), komutlar (admin komutlari), calistir (dongu).
Kullanim: from kanit.bot import calistir; calistir(ayar)  ya da  python -m kanit bot
"""
from .calistir import calistir, Bot  # noqa: F401
