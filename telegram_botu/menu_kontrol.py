# -*- coding: utf-8 -*-
"""Kullanici komut menusunun Telegram'daki CANLI durumunu gosterir; bos/eksikse kurar.

Kullanim (bot calisirken de calistirilabilir):
    Windows:  py menu_kontrol.py
    Linux:    python3 menu_kontrol.py

Ek kutuphane gerektirmez; token'i ve komut listesini config.txt icinden okur.
"""
import json
import os
import sys
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))

# config.txt'i oku (token + USER_COMMANDS)
_cfg = {}
try:
    with open(os.path.join(BASE, "config.txt"), encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                _cfg[k.strip()] = v.strip()
except OSError:
    pass

token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip() or _cfg.get("TOKEN", "")
if not token or "BURAYA" in token:
    print("HATA: TOKEN bulunamadi. config.txt icindeki TOKEN= satirini doldurun.")
    sys.exit(1)

API = f"https://api.telegram.org/bot{token}/"

def call(method, **params):
    payload = {k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
               for k, v in params.items()}
    data = urllib.parse.urlencode(payload).encode()
    with urllib.request.urlopen(API + method, data=data, timeout=20) as resp:
        out = json.load(resp)
    if not out.get("ok"):
        raise RuntimeError(f"{method}: {out}")
    return out["result"]

# Komut listesi: config.txt USER_COMMANDS satirindan (bot.py ile ayni sablon).
_DEFAULT_COMMANDS = (
    "start:🚀 Başla, menu:🏠 Ana Menü, giris:🏠 Siteye Giriş, miniapp:📱 Mini App, "
    "bonuslar:🎁 Güncel Bonuslar, yeniuye:🆕 Yeni Üye Bonusları, slot:🎰 Slot Kampanyaları, "
    "spor:⚽ Spor Bonusları, banaozel:⭐ Bana Özel Kampanyalar, turnuvalar:🏆 Turnuvalar, "
    "parayatir:💰 Para Yatır, paracek:💸 Para Çek, duyurular:📢 Duyurular, "
    "sss:❓ Sık Sorulan Sorular, destek:💬 Canlı Destek, profil:🤴 Profil, iptal:❌ İşlemi iptal et"
)

USER_CMDS = []
for parca in _cfg.get("USER_COMMANDS", _DEFAULT_COMMANDS).split(","):
    parca = parca.strip()
    if ":" in parca:
        cmd, desc = parca.split(":", 1)
        cmd, desc = cmd.strip().lstrip("/").lower(), desc.strip()
        if cmd and desc:
            USER_CMDS.append({"command": cmd, "description": desc})

try:
    me = call("getMe")
except Exception as exc:
    print(f"HATA: Telegram'a ulasilamadi: {exc}")
    sys.exit(1)

print(f"Bot: @{me.get('username')} (id {me.get('id')})")
print(f"Beklenen komut sayisi (config sablonu): {len(USER_CMDS)}")
print("-" * 44)

beklenen = [(c["command"], c["description"]) for c in USER_CMDS]
kurulum_gerekli = False
for ad, scope in (("default", {"type": "default"}), ("ozel sohbetler", {"type": "all_private_chats"})):
    mevcut = call("getMyCommands", scope=scope)
    canli = [(c.get("command", ""), c.get("description", "")) for c in mevcut]
    print(f"[{ad}] kayitli komut sayisi: {len(mevcut)}")
    for c in mevcut:
        print(f"  /{c['command']} — {c['description']}")
    if canli != beklenen:
        kurulum_gerekli = True
        print(f"  ↳ sablondan FARKLI (eksik, fazla veya sirasi bozuk) → yeniden kurulacak")

if kurulum_gerekli:
    print(f"\n{len(USER_CMDS)} komutluk liste sablondaki SIRAYLA her iki kapsama simdi kuruluyor...")
    call("setMyCommands", commands=USER_CMDS, scope={"type": "default"})
    call("setMyCommands", commands=USER_CMDS, scope={"type": "all_private_chats"})
    mevcut = call("getMyCommands", scope={"type": "all_private_chats"})
    print(f"✅ Kuruldu. Guncel liste ({len(mevcut)}):")
    for c in mevcut:
        print(f"  /{c['command']} — {c['description']}")
else:
    print("✅ Kullanici menusu Telegram'da kayitli (iki kapsamda da).")

try:
    btn = call("getChatMenuButton")
    tip = btn.get("type")
    print(f"\nSol alt menu butonu: {tip}"
          + (f" — '{btn.get('text')}'" if btn.get("text") else ""))
    if tip == "web_app":
        print("⚠️  DIKKAT: PLAY (web_app) modu aktif. Telegram bu moddayken sol altta")
        print("   ⌘ komut simgesini GOSTERMEZ — PLAY butonu ile ⌘ ayni slottadir,")
        print("   ikisi ayni anda gorunmez (BotFather'dan komut eklemek bunu degistirmez).")
        print("   Komutlar yine kayitlidir: mesaj kutusuna / yazinca liste acilir.")
        print("   ⌘ simgesini istiyorsaniz config.txt icinde MENU_BUTTON_MODE=menu")
        print("   yapip botu yeniden baslatin.")
except Exception as exc:
    print(f"\nMenu butonu okunamadi: {exc}")

print("\nNOT: Telegram istemcisi menuyu ONBELLEGE alir.")
print("Sohbeti kapatip acin; web.telegram.org icin Ctrl+F5; mobilde uygulamayi yeniden baslatin.")
print("Simge yine gorunmuyorsa mesaj kutusuna / yazin — liste geliyorsa her sey tamamdir.")
