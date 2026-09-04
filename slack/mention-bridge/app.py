"""Etiket Köprüsü.

Slack Connect kanalında düz metin "@petra" görünce @petra user group'unun üyelerine bildirim gönderir.
@petra'nın olduğu workspace'e kurulur; Socket Mode kullanır, dışa açık endpoint gerekmez.
Bot hangi kanala eklendiyse orada çalışır (config.json > channels boşsa); yönetim komutları bota DM'den,
sadece config.json > admins listesindeki hesaplardan (bkz. commands.py > HELP ya da DM'de `yardım`).

    $env:SLACK_BOT_TOKEN = "xoxb-..."   # OAuth & Permissions > Bot User OAuth Token
    $env:SLACK_APP_TOKEN = "xapp-..."   # Basic Information > App-Level Tokens (connections:write)
    python app.py

notify_mode:
  dm      -> kanala/thread'e HİÇBİR ŞEY yazılmaz; her grup üyesine "şu kanalda şu kişi sizi etiketledi,
             mesaja git" DM'i gider (Slack'in kendi "kanalda etiketlendiniz" Slackbot mesajı gibi).
  thread  -> mesajın thread'ine gerçek <!subteam^…|@petra> mention'ı yazılır.
  channel -> kanala ayrı bir mesaj olarak yazılır.
"""
import copy
import logging
import os
import sys
import threading
import time

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk.errors import SlackApiError

import bridge
import commands

HERE = os.path.dirname(os.path.abspath(__file__))


def load_dotenv(path):
    """Yanındaki .env dosyasından SLACK_BOT_TOKEN / SLACK_APP_TOKEN okur (ortam değişkeni varsa ona dokunmaz)."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv(os.path.join(HERE, ".env"))
BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
APP_TOKEN = os.environ.get("SLACK_APP_TOKEN")
CONFIG_PATH = os.environ.get("BRIDGE_CONFIG") or os.path.join(HERE, "config.json")
RESOLVE_TTL = 15 * 60   # grup/kişi ID'leri: yeni grup en geç 15 dk'da görülür
MEMBERS_TTL = 5 * 60    # grup üye listesi: üye değişikliği en geç 5 dk'da görülür

logging.basicConfig(
    level=logging.DEBUG if os.environ.get("BRIDGE_DEBUG") else logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("bridge")

if not BOT_TOKEN or not APP_TOKEN:
    print("SLACK_BOT_TOKEN (xoxb-...) ve SLACK_APP_TOKEN (xapp-...) gerekli: ortam değişkeni olarak ver ya da "
          "app.py'nin yanına .env dosyası koy (satır satır SLACK_BOT_TOKEN=... / SLACK_APP_TOKEN=...).", file=sys.stderr)
    sys.exit(1)

app = App(token=BOT_TOKEN, logger=logging.getLogger("bolt"), token_verification_enabled=False)  # auth_test'i main() yapar
loader = bridge.ConfigLoader(CONFIG_PATH)
lock = threading.Lock()
state = {
    "config": None,
    "resolved": {"usergroups": {}, "users": {}},   # handle -> S…, email -> U…
    "resolved_at": 0.0,
    "admin_ids": set(),
    "members": {},                                  # S… -> (zaman, [U…])
    "team_url": "",
    "team_name": "",
    "seen": {},                                     # "C…:ts" -> zaman (aynı event'i iki kez işlememek için)
}


def slack_error(e):
    return e.response.get("error") if getattr(e, "response", None) else str(e)


def lookup_email(client, email):
    cached = state["resolved"]["users"].get(email)
    if cached:
        return cached
    uid = client.users_lookupByEmail(email=email)["user"]["id"]
    state["resolved"]["users"][email] = uid
    return uid


def resolve_targets(client):
    """config'deki handle ve e-postaları Slack ID'lerine çevirir. Bulunamayan loglanır, bot düşmez."""
    groups = {}
    for g in client.usergroups_list(include_disabled=False).get("usergroups", []):
        groups[g["handle"].lower()] = g["id"]
    users = dict(state["resolved"]["users"])
    cfg = state["config"]
    for targets in list(cfg["keywords"].values()) + [cfg["admins"]]:
        for t in targets:
            if t["type"] == "usergroup" and t["handle"] not in groups:
                log.warning("@%s diye bir user group bu workspace'te yok (ya da devre dışı); atlanıyor.", t["handle"])
            elif t["type"] == "email" and t["email"] not in users:
                try:
                    users[t["email"]] = client.users_lookupByEmail(email=t["email"])["user"]["id"]
                except SlackApiError as e:
                    log.warning("%s bu workspace'te bulunamadı (%s); atlanıyor.", t["email"], slack_error(e))
    state["resolved"] = {"usergroups": groups, "users": users}
    state["admin_ids"] = {
        t["id"] if t["type"] == "user" else users.get(t["email"]) for t in cfg["admins"]
    } - {None}
    state["resolved_at"] = time.time()
    state["members"] = {}
    log.info("Hedefler çözüldü: %d user group, %d kişi, %d yetkili.", len(groups), len(users), len(state["admin_ids"]))


def ensure_fresh(client):
    with lock:
        config, changed = loader.load()
        state["config"] = config
        if changed:
            log.info("config yüklendi: %s  (mod: %s)", ", ".join("@" + k for k in config["keywords"]), config["notify_mode"])
        if changed or time.time() - state["resolved_at"] > RESOLVE_TTL:
            resolve_targets(client)


def members_of(client):
    def fetch(gid):
        cached = state["members"].get(gid)
        if cached and time.time() - cached[0] < MEMBERS_TTL:
            return cached[1]
        try:
            ids = client.usergroups_users_list(usergroup=gid).get("users", [])
        except SlackApiError as e:
            log.warning("%s üyeleri alınamadı (%s).", gid, slack_error(e))
            ids = cached[1] if cached else []
        state["members"][gid] = (time.time(), ids)
        return ids
    return fetch


def already_seen(key):
    now = time.time()
    seen = state["seen"]
    if key in seen:
        return True
    seen[key] = now
    if len(seen) > 1000:
        for k in [k for k, t in seen.items() if now - t > 600]:
            del seen[k]
    return False


# ---------------- kanal mesajları: etiket -> bildirim ----------------

def notify_by_dm(event, hits, client):
    cfg = state["config"]
    recipients = bridge.recipients_for(hits, cfg, state["resolved"], members_of(client), exclude=(event["user"],))
    if not recipients:
        log.warning('"%s" eşleşti ama bildirim gidecek kimse yok (grup boş / bulunamadı).', ", ".join(hits))
        return 0
    link = bridge.permalink(state["team_url"], event["channel"], event["ts"], event.get("thread_ts"))
    text = bridge.build_dm_text(cfg["dm_template"], event["channel"], event["user"], hits, event.get("text"), link)
    sent = 0
    for uid in recipients:
        try:
            client.chat_postMessage(channel=uid, text=text, unfurl_links=False, unfurl_media=False)
            sent += 1
        except SlackApiError as e:
            log.warning("%s kişisine DM gönderilemedi (%s).", uid, slack_error(e))
    return sent


def notify_in_channel(event, hits, client):
    cfg = state["config"]
    mentions = bridge.mentions_for(hits, cfg, state["resolved"])
    if not mentions:
        log.warning('"%s" eşleşti ama çözülebilen hedef yok (grup/kişi bulunamadı).', ", ".join(hits))
        return 0
    params = {"channel": event["channel"], "text": bridge.build_reply(cfg["reply_template"], mentions, event["user"])}
    if cfg["notify_mode"] == "thread":
        params["thread_ts"] = event.get("thread_ts") or event["ts"]
    client.chat_postMessage(**params)
    return len(mentions)


def handle_channel_message(event, client):
    cfg = state["config"]
    if cfg["channels"] and event["channel"] not in cfg["channels"]:
        return
    hits = bridge.find_keywords(event.get("text"), list(cfg["keywords"]), require_at=cfg["require_at"])
    if not hits:
        return
    if cfg["notify_mode"] == "dm":
        n = notify_by_dm(event, hits, client)
        what = f"{n} kişiye DM"
    else:
        n = notify_in_channel(event, hits, client)
        what = f"{n} mention ({cfg['notify_mode']})"
    if n and cfg["ack_reaction"]:
        try:
            client.reactions_add(channel=event["channel"], timestamp=event["ts"], name=cfg["ack_reaction"])
        except SlackApiError as e:
            if slack_error(e) != "already_reacted":
                log.warning("Emoji konulamadı (%s).", slack_error(e))
    log.info("%s %s: @%s -> %s.", event["channel"], event["ts"], ", @".join(hits), what)


# ---------------- DM: yönetim komutları ----------------

def find_group(client, handle):
    handle = handle.lstrip("@").lower()
    for g in client.usergroups_list(include_disabled=True, include_users=True).get("usergroups", []):
        if g["handle"].lower() == handle:
            return g
    return None


def resolve_people(client, args):
    ids, problems = [], []
    for a in args:
        try:
            t = bridge.parse_target(a, "kişi")
        except ValueError as e:
            problems.append(str(e))
            continue
        if t["type"] == "user":
            ids.append(t["id"])
        elif t["type"] == "email":
            try:
                ids.append(lookup_email(client, t["email"]))
            except SlackApiError as e:
                problems.append(f"{t['email']} bulunamadı ({slack_error(e)})")
        else:
            problems.append(f"`{a}` bir kişi değil; `@kişi` ya da e-posta ver.")
    return ids, problems


def group_command(cmd, args, client):
    """grup liste / oluştur / ekle / çıkar: gerçek Slack user group'ları."""
    if cmd == "grup liste":
        groups = client.usergroups_list(include_disabled=False, include_users=True, include_count=True).get("usergroups", [])
        if args:
            g = find_group(client, args[0])
            if not g:
                raise commands.CommandError(f"@{args[0].lstrip('@')} diye bir user group yok.")
            users = g.get("users") or []
            shown = " ".join(f"<@{u}>" for u in users[:100]) or "_(üye yok)_"
            return f"*@{g['handle']}* ({g['id']}) {len(users)} üye:\n{shown}"
        if not groups:
            return "Bu workspace'te aktif user group yok."
        return "*User group'lar*\n" + "\n".join(f"• `@{g['handle']}` {g.get('user_count', len(g.get('users') or []))} üye" for g in groups)

    if cmd == "grup olustur":
        if not args:
            raise commands.CommandError("Kullanım: `grup oluştur <handle> [ad]`")
        handle = args[0].lstrip("@").lower()
        if not bridge.HANDLE_RE.match(handle):
            raise commands.CommandError(f"`{args[0]}` geçerli bir handle değil.")
        name = " ".join(args[1:]) or handle
        existing = find_group(client, handle)
        if existing:
            if existing.get("date_delete"):
                client.usergroups_enable(usergroup=existing["id"])
                note = f"@{handle} devre dışıydı, yeniden aktif edildi."
            else:
                note = f"@{handle} zaten vardı."
        else:
            g = client.usergroups_create(name=name, handle=handle)["usergroup"]
            note = f"Slack'te *@{g['handle']}* user group'u açıldı ({g['id']}). Üye eklemek için `grup ekle {handle} @kişi`."
        with lock:
            raw = copy.deepcopy(loader.raw)
            reply, _ = commands.apply(raw, "ekle", [handle], {"known_groups": None})
            loader.save(raw)
        state["resolved_at"] = 0  # yeni grup ID'sini hemen çöz
        return note + "\nEtiket: " + reply.splitlines()[-1]

    if cmd in ("grup ekle", "grup cikar"):
        if len(args) < 2:
            raise commands.CommandError(f"Kullanım: `{ 'grup ekle' if cmd == 'grup ekle' else 'grup çıkar' } <handle> <kişi…>`")
        g = find_group(client, args[0])
        if not g:
            raise commands.CommandError(f"@{args[0].lstrip('@')} diye bir user group yok. `grup oluştur {args[0].lstrip('@')}` ile açabilirsin.")
        ids, problems = resolve_people(client, args[1:])
        current = list(g.get("users") or [])
        if cmd == "grup ekle":
            new = current + [u for u in ids if u not in current]
            changed = [u for u in ids if u not in current]
        else:
            new = [u for u in current if u not in ids]
            changed = [u for u in ids if u in current]
        lines = []
        if problems:
            lines.append("⚠️ " + "\n⚠️ ".join(problems))
        if not changed:
            lines.append("Değişiklik yok." if not problems else "Geçerli kişi kalmadı, değişiklik yok.")
            return "\n".join(lines)
        if not new:
            raise commands.CommandError("Slack user group'u boş bırakmaz; son üyeyi çıkaramazsın.")
        try:
            client.usergroups_users_update(usergroup=g["id"], users=",".join(new))
        except SlackApiError as e:
            err = slack_error(e)
            hint = {
                "invalid_users": "kişi bu workspace'in tam üyesi değil (guest ya da başka workspace).",
                "permission_denied": "workspace ayarı user group yönetimini sadece admin'e veriyor (Workspace Settings > Permissions > User Groups).",
                "missing_scope": "app'te usergroups:write scope'u yok; manifesti güncelleyip Reinstall yap.",
            }.get(err, "")
            raise commands.CommandError(f"Slack hatası: `{err}` {hint}".strip())
        state["members"].pop(g["id"], None)
        verb = "eklendi" if cmd == "grup ekle" else "çıkarıldı"
        lines.append(f"*@{g['handle']}* {verb}: " + " ".join(f"<@{u}>" for u in changed) + f"\nŞu an {len(new)} üye.")
        return "\n".join(lines)

    raise commands.CommandError(f"`{cmd}` bilinmiyor.")


def status_text(client):
    cfg = state["config"]
    lines = [
        f"*Workspace:* {state['team_name']}  *Mod:* `{cfg['notify_mode']}`  *Emoji:* {(':' + cfg['ack_reaction'] + ':') if cfg['ack_reaction'] else 'kapalı'}",
        f"*Etiketler:* " + (", ".join("@" + k for k in cfg["keywords"]) or "yok"),
        f"*Çözülen:* {len(state['resolved']['usergroups'])} user group, {len(state['resolved']['users'])} kişi",
        f"*Yetkililer:* " + (" ".join(f"<@{u}>" for u in sorted(state["admin_ids"])) or "yok"),
    ]
    missing = [t["handle"] for ts in cfg["keywords"].values() for t in ts
               if t["type"] == "usergroup" and t["handle"] not in state["resolved"]["usergroups"]]
    if missing:
        lines.append("⚠️ Slack'te olmayan gruplar: " + ", ".join("@" + h for h in sorted(set(missing))))
    return "\n".join(lines)


def channels_text(client):
    cfg = state["config"]
    try:
        chans = []
        cursor = None
        while True:
            r = client.users_conversations(types="public_channel,private_channel", exclude_archived=True, limit=200, cursor=cursor)
            chans += r.get("channels", [])
            cursor = (r.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                break
    except SlackApiError as e:
        return f"Kanal listesi alınamadı ({slack_error(e)}); channels:read / groups:read scope'u gerekir."
    if not chans:
        inside = "_hiçbir kanalda değil_ (kanalda `/invite @Etiket Köprüsü` yaz)"
    else:
        inside = "\n".join(
            f"• <#{c['id']}>" + (" (Slack Connect)" if c.get("is_ext_shared") or c.get("is_shared") else "")
            + ("" if not cfg["channels"] or c["id"] in cfg["channels"] else " _(filtre dışı)_")
            for c in chans
        )
    filt = ", ".join(f"<#{c}>" for c in cfg["channels"]) if cfg["channels"] else "yok (eklendiği her kanalda çalışır)"
    return f"*Botun olduğu kanallar*\n{inside}\n*Filtre:* {filt}"


def handle_command(event, client):
    uid = event["user"]
    text = (event.get("text") or "").strip()

    def reply(msg):
        client.chat_postMessage(channel=event["channel"], text=msg, unfurl_links=False)

    if not state["admin_ids"]:
        reply("Yönetici tanımlı değil. `config.json` içindeki `admins` alanına kendi kullanıcı ID'ni (U…) ya da e-postanı yaz.")
        return
    if uid not in state["admin_ids"]:
        log.warning("Yetkisiz komut denemesi: %s: %s", uid, text)
        reply("Bu botu yönetme yetkin yok.")
        return
    try:
        cmd, args = commands.parse(text)
        if cmd == "yardim":
            reply(commands.HELP)
        elif cmd == "durum":
            reply(status_text(client))
        elif cmd == "kanallar":
            reply(channels_text(client))
        elif cmd.startswith("grup "):
            reply(group_command(cmd, args, client))
        else:
            with lock:
                raw = copy.deepcopy(loader.raw)
                ctx = {"me": uid, "known_groups": set(state["resolved"]["usergroups"])}
                msg, changed = commands.apply(raw, cmd, args, ctx)
                if changed:
                    loader.save(raw)
                    state["resolved_at"] = 0  # yeni hedef/yetkili ID'lerini hemen çöz
            reply(msg)
        log.info("Komut (%s): %s", uid, text)
    except commands.CommandError as e:
        reply(f"{e}\nKomutlar için `yardım` yaz.")
    except SlackApiError as e:
        reply(f"Slack hatası: `{slack_error(e)}`")
        log.warning("Komut Slack hatası (%s): %s", text, slack_error(e))
    except ValueError as e:  # config doğrulaması
        reply(f"Ayar kaydedilemedi: {e}")
    ensure_fresh(client)


@app.event("message")
def on_message(event, client):
    # Sadece yeni, insan yazımı mesajlar. Düzenleme/silme/kanal olayları ve botlar (kendimiz dahil) atlanır.
    subtype = event.get("subtype")
    if subtype and subtype not in ("file_share", "thread_broadcast"):
        return
    if event.get("bot_id") or not event.get("user"):
        return
    if already_seen(f"{event['channel']}:{event['ts']}"):
        return
    try:
        ensure_fresh(client)
    except Exception as e:  # config bozuksa eski config ile devam, bot düşmez
        log.error("config okunamadı: %s", e)
        if not state["config"]:
            return
    if event.get("channel_type") == "im":
        handle_command(event, client)
    else:
        handle_channel_message(event, client)


def main():
    try:
        me = app.client.auth_test()
    except SlackApiError as e:
        print(f"Bot token geçersiz: {slack_error(e)}", file=sys.stderr)
        sys.exit(1)
    state["team_url"] = me["url"]
    state["team_name"] = me["team"]
    print(f"Workspace: {me['team']} ({me['team_id']})  bot: {me['user']}")
    try:
        ensure_fresh(app.client)
    except Exception as e:
        print(f"config hatası ({CONFIG_PATH}): {e}", file=sys.stderr)
        sys.exit(1)
    if not state["admin_ids"]:
        print("Uyarı: config.json > admins boş; DM komutları kapalı. Kendi kullanıcı ID'ni ya da e-postanı ekle.")
    print("Etiket Köprüsü çalışıyor (Socket Mode). Botu kanala eklemeyi unutma: /invite @Etiket Köprüsü")
    SocketModeHandler(app, APP_TOKEN).start()


if __name__ == "__main__":
    main()
