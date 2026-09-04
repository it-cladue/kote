"""Etiket Köprüsü.

Slack Connect kanalında düz metin "@petra" görünce @petra user group'unun üyelerine bildirim gönderir.
@petra'nın olduğu workspace'e kurulur; Socket Mode kullanır, dışa açık endpoint gerekmez.

    $env:SLACK_BOT_TOKEN = "xoxb-..."   # OAuth & Permissions > Bot User OAuth Token
    $env:SLACK_APP_TOKEN = "xapp-..."   # Basic Information > App-Level Tokens (connections:write)
    python app.py

Ayarlar: config.json (config.example.json'dan kopyala). Dosya değişince bot yeniden başlatmadan alır.

notify_mode:
  dm      -> kanala/thread'e HİÇBİR ŞEY yazılmaz; her grup üyesine "şu kanalda şu kişi sizi etiketledi,
             mesaja git" DM'i gider (Slack'in kendi "kanalda etiketlendiniz" Slackbot mesajı gibi).
  thread  -> mesajın thread'ine gerçek <!subteam^…|@petra> mention'ı yazılır.
  channel -> kanala ayrı bir mesaj olarak yazılır.
"""
import logging
import os
import sys
import threading
import time

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk.errors import SlackApiError

import bridge

BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
APP_TOKEN = os.environ.get("SLACK_APP_TOKEN")
CONFIG_PATH = os.environ.get("BRIDGE_CONFIG") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
RESOLVE_TTL = 15 * 60   # grup/kişi ID'leri: yeni grup en geç 15 dk'da görülür
MEMBERS_TTL = 5 * 60    # grup üye listesi: üye değişikliği en geç 5 dk'da görülür

logging.basicConfig(
    level=logging.DEBUG if os.environ.get("BRIDGE_DEBUG") else logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("bridge")

if not BOT_TOKEN or not APP_TOKEN:
    print("SLACK_BOT_TOKEN (xoxb-...) ve SLACK_APP_TOKEN (xapp-...) ortam değişkenleri gerekli.", file=sys.stderr)
    sys.exit(1)

app = App(token=BOT_TOKEN, logger=logging.getLogger("bolt"), token_verification_enabled=False)  # auth_test'i main() yapar
loader = bridge.ConfigLoader(CONFIG_PATH)
lock = threading.Lock()
state = {
    "config": None,
    "resolved": {"usergroups": {}, "users": {}},   # handle -> S…, email -> U…
    "resolved_at": 0.0,
    "members": {},                                  # S… -> (zaman, [U…])
    "team_url": "",
    "seen": {},                                     # "C…:ts" -> zaman (aynı event'i iki kez işlememek için)
}


def resolve_targets(client):
    """config'deki handle ve e-postaları Slack ID'lerine çevirir. Bulunamayan loglanır, bot düşmez."""
    groups = {}
    for g in client.usergroups_list(include_disabled=False).get("usergroups", []):
        groups[g["handle"].lower()] = g["id"]
    users = dict(state["resolved"]["users"])
    for targets in state["config"]["keywords"].values():
        for t in targets:
            if t["type"] == "usergroup" and t["handle"] not in groups:
                log.warning("@%s diye bir user group bu workspace'te yok (ya da devre dışı); atlanıyor.", t["handle"])
            elif t["type"] == "email" and t["email"] not in users:
                try:
                    users[t["email"]] = client.users_lookupByEmail(email=t["email"])["user"]["id"]
                except SlackApiError as e:
                    log.warning("%s bu workspace'te bulunamadı (%s); atlanıyor.", t["email"], e.response.get("error"))
    state["resolved"] = {"usergroups": groups, "users": users}
    state["resolved_at"] = time.time()
    state["members"] = {}
    log.info("Hedefler çözüldü: %d user group, %d kişi.", len(groups), len(users))


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
            log.warning("%s üyeleri alınamadı (%s).", gid, e.response.get("error"))
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
            log.warning("%s kişisine DM gönderilemedi (%s).", uid, e.response.get("error"))
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
            if e.response.get("error") != "already_reacted":
                log.warning("Emoji konulamadı (%s).", e.response.get("error"))
    log.info("%s %s: @%s -> %s.", event["channel"], event["ts"], ", @".join(hits), what)


def main():
    try:
        me = app.client.auth_test()
    except SlackApiError as e:
        print(f"Bot token geçersiz: {e.response.get('error')}", file=sys.stderr)
        sys.exit(1)
    state["team_url"] = me["url"]
    print(f"Workspace: {me['team']} ({me['team_id']})  bot: {me['user']}")
    try:
        ensure_fresh(app.client)
    except Exception as e:
        print(f"config hatası ({CONFIG_PATH}): {e}", file=sys.stderr)
        sys.exit(1)
    print("Etiket Köprüsü çalışıyor (Socket Mode). Botu kanala eklemeyi unutma: /invite @Etiket Köprüsü")
    SocketModeHandler(app, APP_TOKEN).start()


if __name__ == "__main__":
    main()
