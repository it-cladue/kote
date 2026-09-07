"""Yetkili hesabın bota DM'den yazdığı yönetim komutları (Slack'e bağlanmayan kısım).

parse(text) -> (komut, argümanlar). apply(raw, komut, args, ctx) config.json içeriğini (raw dict) değiştirir
ve yanıt metni döndürür; kaydetmeyi app.py yapar. Slack tarafı gerektiren komutlar (grup …, durum, kanallar)
app.py içinde.
"""
import re

import bridge

TR_MAP = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
MENTION_RE = re.compile(r"^<@([UW][A-Z0-9]+)(?:\|[^>]*)?>$")
CHANNEL_RE = re.compile(r"^<#([CG][A-Z0-9]+)(?:\|[^>]*)?>$")
MAILTO_RE = re.compile(r"^<mailto:([^|>]+)(?:\|[^>]*)?>$")
SUBTEAM_RE = re.compile(r"^<!subteam\^[A-Z0-9]+\|@?([^>]+)>$")
LINK_RE = re.compile(r"^<(?:https?|ftp):[^>]*>$")

TWO_ZONE_NOTE = "⚠️ İki zone'lu kurulumda bu ayar iki botta da iz bırakır (çift yanıt/emoji). İki bot varsa `mod dm` ve `emoji kapat` kalsın."

HELP = """*Etiket Köprüsü komutları* (sadece yetkililer, bu DM'den)

*Etiketler* (kanalda `@etiket` yazılınca kime bildirim gidecek)
• `liste`  tanımlı etiketler
• `ekle <etiket> [hedef…]`  etikete hedef ekler; etiket yoksa açar. Hedef: user group handle'ı (`petra`), e-posta ya da `@kişi`. Hedef verilmezse etiketle aynı adlı grup kullanılır.
• `çıkar <etiket> [hedef…]`  hedef çıkarır; hedef verilmezse etiketi siler (son etiket silinemez)

*Slack user group'ları* (gerçek gruplar; workspace ayarı user group yönetimine izin vermeli ya da `.env` içinde `SLACK_ADMIN_TOKEN` olmalı)
• `grup liste [handle]`  gruplar / bir grubun üyeleri
• `grup oluştur <handle> [ad]`  Slack'te yeni user group açar (devre dışıysa aktif eder) ve aynı adla etiket tanımlar
• `grup ekle <handle> <kişi…>`  gruba üye ekler (e-posta ya da `@kişi`)
• `grup çıkar <handle> <kişi…>`  gruptan üye çıkarır

*Ayarlar*
• `kanallar`  botun içinde olduğu kanallar ve filtre
• `kanal ekle <#kanal…>` / `kanal çıkar <#kanal…>` / `kanal temizle`  filtre boşsa bot eklendiği her kanalda çalışır
• `mod dm|thread|channel`  bildirim biçimi (iki zone'lu kurulumda `dm` kalsın)
• `emoji <ad>` / `emoji kapat`  orijinal mesaja konacak emoji (iki zone'lu kurulumda kapalı kalsın)
• `yetkili liste` / `yetkili ekle <@kişi…>` / `yetkili çıkar <@kişi…>`
• `durum`  bağlantı, son bildirim, çözülemeyen hedefler ve özet"""


class CommandError(Exception):
    pass


def norm_word(word):
    return word.strip().translate(TR_MAP).lower()


def tokenize(text):
    """Slack'in DM'de ürettiği token'ları düz değere çevirir: <@U1|ali> -> U1, <#C1|kanal> -> C1,
    <mailto:a@b.c|a@b.c> -> a@b.c, <!subteam^S1|@petra> -> petra. Linkler atılır."""
    out = []
    for tok in (text or "").split():
        m = MENTION_RE.match(tok)
        if m:
            out.append(m.group(1))
            continue
        m = CHANNEL_RE.match(tok)
        if m:
            out.append(m.group(1))
            continue
        m = MAILTO_RE.match(tok)
        if m:
            out.append(m.group(1))
            continue
        m = SUBTEAM_RE.match(tok)
        if m:
            out.append(m.group(1))
            continue
        if LINK_RE.match(tok):
            continue
        out.append(tok)
    return out


VERBS = {
    "yardim": "yardim", "help": "yardim", "?": "yardim",
    "liste": "liste", "list": "liste",
    "ekle": "ekle", "cikar": "cikar", "sil": "cikar",
    "grup": "grup", "kanal": "kanal", "kanallar": "kanallar",
    "mod": "mod", "emoji": "emoji", "yetkili": "yetkili", "durum": "durum",
}
SUBVERBS = {
    "grup": {"liste": "liste", "list": "liste", "olustur": "olustur", "ac": "olustur", "ekle": "ekle", "cikar": "cikar", "sil": "cikar"},
    "kanal": {"ekle": "ekle", "cikar": "cikar", "sil": "cikar", "temizle": "temizle"},
    "yetkili": {"liste": "liste", "list": "liste", "ekle": "ekle", "cikar": "cikar", "sil": "cikar"},
}


def is_command(text):
    """Metin bilinen bir komutla mı başlıyor? (Yetkisiz kişilerin 'teşekkürler' gibi DM'lerini ayırt etmek için.)"""
    tokens = tokenize(text)
    return bool(tokens) and norm_word(tokens[0]) in VERBS


def parse(text):
    """-> ("ekle", ["petra", "ali@firma.com"]) | ("grup olustur", [...]) | ... CommandError bilinmeyende."""
    tokens = tokenize(text)
    if not tokens:
        raise CommandError("Boş komut.")
    verb = VERBS.get(norm_word(tokens[0]))
    if not verb:
        raise CommandError(f"`{tokens[0]}` diye bir komut yok.")
    if verb in SUBVERBS:
        if len(tokens) < 2:
            raise CommandError(f"`{tokens[0]}` komutunun alt komutu eksik: " + ", ".join(sorted(set(SUBVERBS[verb].values()))))
        sub = SUBVERBS[verb].get(norm_word(tokens[1]))
        if not sub:
            raise CommandError(f"`{tokens[0]} {tokens[1]}` diye bir komut yok.")
        return f"{verb} {sub}", tokens[2:]
    return verb, tokens[1:]


# ---- config.json (raw dict) üzerinde çalışan komutlar ----

def _keyword(arg):
    raw = arg.strip()
    if bridge.USER_ID_RE.match(raw) or bridge.CHANNEL_ID_RE.match(raw) or bridge.EMAIL_RE.match(raw):
        raise CommandError("Etiket adı bir kişi, kanal ya da e-posta olamaz; düz bir ad yaz (ör. `petra`). Kişiler hedef olarak verilir: `ekle petra @Ali`.")
    key = bridge.fold(raw.lstrip("@"))
    if not key or not bridge.HANDLE_RE.match(key):
        raise CommandError(f"`{arg}` geçerli bir etiket adı değil (harf, rakam, nokta, tire, alt çizgi).")
    if key.startswith("_"):
        raise CommandError("Etiket adı `_` ile başlayamaz.")
    return key


def _targets(args, keyword):
    out = []
    for a in args:
        try:
            t = bridge.parse_target(a, keyword)
        except ValueError as e:
            raise CommandError(str(e))
        out.append(t)
    return out


def _target_str(t):
    if t["type"] == "usergroup":
        return t["handle"]
    if t["type"] == "email":
        return t["email"]
    return t["id"]


def _target_show(t):
    if t["type"] == "usergroup":
        return "@" + t["handle"]
    if t["type"] == "email":
        return t["email"]
    return f"<@{t['id']}>"


def _canon(value, keyword):
    return _target_str(bridge.parse_target(value, keyword))


def _keywords_raw(raw):
    """keywords sözlüğünü kanonik hale getirir: anahtarlar küçük harf ve @'sız, değerler liste, çakışanlar birleşik."""
    kws = raw.setdefault("keywords", {})
    canon = {}
    for k, v in list(kws.items()):
        if k.startswith("_"):
            canon[k] = v
            continue
        key = bridge.fold(k.strip().lstrip("@"))
        items = list(v) if isinstance(v, list) else [v]
        if key in canon and isinstance(canon[key], list):
            for t in items:
                if t not in canon[key]:
                    canon[key].append(t)
        else:
            canon[key] = items
    kws.clear()
    kws.update(canon)
    return kws


def _tag_keys(kws):
    return [k for k in kws if not k.startswith("_")]


def cmd_liste(raw, args, ctx):
    kws = _keywords_raw(raw)
    keys = _tag_keys(kws)
    if not keys:
        return "Tanımlı etiket yok. `ekle <etiket> [hedef…]` ile ekle."
    lines = []
    for k in keys:
        shown = ", ".join(_target_show(bridge.parse_target(t, k)) for t in kws[k])
        lines.append(f"• `@{k}` → {shown}")
    return "*Etiketler*\n" + "\n".join(lines)


def cmd_ekle(raw, args, ctx):
    if not args:
        raise CommandError("Kullanım: `ekle <etiket> [hedef…]`")
    key = _keyword(args[0])
    targets = _targets(args[1:], key) if len(args) > 1 else [{"type": "usergroup", "handle": key}]
    kws = _keywords_raw(raw)
    current = kws.setdefault(key, [])
    existing = {_canon(t, key) for t in current}
    added, warn = [], []
    for t in targets:
        s = _target_str(t)
        if s in existing:
            continue
        current.append(s)
        existing.add(s)
        added.append(_target_show(t))
        if t["type"] == "usergroup" and ctx.get("known_groups") is not None and t["handle"] not in ctx["known_groups"]:
            warn.append(f"@{t['handle']} diye bir user group bu workspace'te yok; `grup oluştur {t['handle']}` ile açabilirsin.")
    reply = f"`@{key}` → " + ", ".join(_target_show(bridge.parse_target(t, key)) for t in current)
    reply = ("Eklendi: " + ", ".join(added) + "\n" if added else "Zaten vardı, değişiklik yok.\n") + reply
    if warn:
        reply += "\n⚠️ " + "\n⚠️ ".join(warn)
    return reply


def cmd_cikar(raw, args, ctx):
    if not args:
        raise CommandError("Kullanım: `çıkar <etiket> [hedef…]`")
    key = _keyword(args[0])
    kws = _keywords_raw(raw)
    if key not in kws:
        raise CommandError(f"`@{key}` diye bir etiket yok.")

    def delete_tag():
        if len(_tag_keys(kws)) <= 1:
            raise CommandError("Son etiketi silemezsin; önce başka bir etiket ekle.")
        del kws[key]

    if len(args) == 1:
        delete_tag()
        return f"`@{key}` etiketi silindi. (İki zone'lu kurulumda diğer zone'un botunda da silinmesi gerekir.)"
    remove = {_target_str(t) for t in _targets(args[1:], key)}
    before = list(kws[key])
    kws[key] = [t for t in before if _canon(t, key) not in remove]
    gone = [t for t in before if t not in kws[key]]
    if not gone:
        raise CommandError("Bu hedefler zaten etikette yok.")
    if not kws[key]:
        delete_tag()
        return f"Çıkarıldı: {', '.join(gone)}. Hedef kalmadığı için `@{key}` etiketi silindi."
    return f"Çıkarıldı: {', '.join(gone)}\n`@{key}` → " + ", ".join(kws[key])


def _channel_ids(args):
    ids = []
    for a in args:
        if not bridge.CHANNEL_ID_RE.match(a):
            raise CommandError(f"`{a}` bir kanal değil. Kanalı `#` ile seçerek yaz (Slack otomatik tamamlasın).")
        ids.append(a)
    if not ids:
        raise CommandError("En az bir kanal ver: `kanal ekle #kanal`")
    return ids


def cmd_kanal_ekle(raw, args, ctx):
    ids = _channel_ids(args)
    chans = raw.setdefault("channels", [])
    for c in ids:
        if c not in chans:
            chans.append(c)
    return ("Filtre: " + ", ".join(f"<#{c}>" for c in chans) + "\nBot artık sadece bu kanallarda çalışır. "
            "(Bot zaten yalnızca eklendiği kanallarda çalışır; iki zone'lu kurulumda filtreyi boş bırakmak daha güvenlidir.)")


def cmd_kanal_cikar(raw, args, ctx):
    ids = _channel_ids(args)
    chans = raw.setdefault("channels", [])
    raw["channels"] = [c for c in chans if c not in ids]
    if not raw["channels"]:
        return "Filtre boş: bot eklendiği her kanalda çalışır."
    return "Filtre: " + ", ".join(f"<#{c}>" for c in raw["channels"])


def cmd_kanal_temizle(raw, args, ctx):
    raw["channels"] = []
    return "Filtre temizlendi: bot eklendiği her kanalda çalışır."


def cmd_mod(raw, args, ctx):
    if len(args) != 1 or norm_word(args[0]) not in bridge.NOTIFY_MODES:
        raise CommandError("Kullanım: `mod dm` | `mod thread` | `mod channel`")
    raw["notify_mode"] = norm_word(args[0])
    desc = {"dm": "kanala hiçbir şey yazılmaz, üyelere DM gider",
            "thread": "mesajın thread'ine gerçek mention yazılır",
            "channel": "kanala ayrı mesaj yazılır"}[raw["notify_mode"]]
    out = f"Mod: `{raw['notify_mode']}` ({desc})."
    if raw["notify_mode"] != "dm":
        out += "\n" + TWO_ZONE_NOTE
    return out


def cmd_emoji(raw, args, ctx):
    if len(args) != 1:
        raise CommandError("Kullanım: `emoji bell` | `emoji kapat`")
    name = args[0].strip(":")
    if norm_word(name) in ("kapat", "kapali", "yok", "off"):
        raw["ack_reaction"] = ""
        return "Emoji kapatıldı: orijinal mesaja iz bırakılmaz."
    if not re.match(r"^[a-z0-9_+-]+$", name):
        raise CommandError(f"`{args[0]}` geçerli bir emoji adı değil (ör. `bell`, `eyes`, `white_check_mark`).")
    raw["ack_reaction"] = name
    return f"Emoji: :{name}: (etiket yakalanınca orijinal mesaja konur).\n" + TWO_ZONE_NOTE


def _admins_raw(raw):
    """admins listesini kanonik hale getirir (e-postalar küçük harf, tekrarlar atılır)."""
    admins = raw.setdefault("admins", [])
    canon = []
    for a in admins:
        try:
            s = _canon(a, "admins")
        except ValueError:
            s = str(a)
        if s not in canon:
            canon.append(s)
    admins[:] = canon
    return admins


def cmd_yetkili_liste(raw, args, ctx):
    admins = _admins_raw(raw)
    if not admins:
        return "Yetkili tanımlı değil."
    return "*Yetkililer*\n" + "\n".join("• " + _target_show(bridge.parse_target(a, "admins")) for a in admins)


def cmd_yetkili_ekle(raw, args, ctx):
    if not args:
        raise CommandError("Kullanım: `yetkili ekle @kişi` (ya da e-posta)")
    admins = _admins_raw(raw)
    added = []
    for t in _targets(args, "admins"):
        if t["type"] == "usergroup":
            raise CommandError(f"`{_target_str(t)}` bir kişi değil; `@kişi` ya da e-posta ver.")
        s = _target_str(t)
        if s not in admins:
            admins.append(s)
            added.append(_target_show(t))
    return ("Yetkili eklendi: " + ", ".join(added)) if added else "Zaten yetkili."


def cmd_yetkili_cikar(raw, args, ctx):
    if not args:
        raise CommandError("Kullanım: `yetkili çıkar @kişi`")
    admins = _admins_raw(raw)
    remove = {_target_str(t) for t in _targets(args, "admins")}
    remaining = [a for a in admins if a not in remove]
    if not remaining:
        raise CommandError("Son yetkiliyi çıkaramazsın; önce başka bir yetkili ekle.")
    me_keys = {k for k in (ctx.get("me"), (ctx.get("me_email") or "").lower()) if k}
    if me_keys and not (me_keys & set(remaining)):
        raise CommandError("Kendini yetkiden çıkaramazsın; bunu başka bir yetkili yapmalı.")
    gone = [a for a in admins if a in remove]
    if not gone:
        raise CommandError("Bu kişiler zaten yetkili değil.")
    raw["admins"] = remaining
    return "Yetkiden çıkarıldı: " + ", ".join(gone)


CONFIG_COMMANDS = {
    "liste": cmd_liste,
    "ekle": cmd_ekle,
    "cikar": cmd_cikar,
    "kanal ekle": cmd_kanal_ekle,
    "kanal cikar": cmd_kanal_cikar,
    "kanal temizle": cmd_kanal_temizle,
    "mod": cmd_mod,
    "emoji": cmd_emoji,
    "yetkili liste": cmd_yetkili_liste,
    "yetkili ekle": cmd_yetkili_ekle,
    "yetkili cikar": cmd_yetkili_cikar,
}
READ_ONLY = {"liste", "yetkili liste"}


def apply(raw, cmd, args, ctx=None):
    """raw'ı yerinde değiştirir, yanıt döndürür. Değişiklik yapmayan komutlar için changed=False."""
    fn = CONFIG_COMMANDS.get(cmd)
    if not fn:
        raise CommandError(f"`{cmd}` bu katmanda işlenmez.")
    reply = fn(raw, args, ctx or {})
    return reply, cmd not in READ_ONLY
