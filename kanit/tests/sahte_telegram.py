# -*- coding: utf-8 -*-
"""Sahte Telegram Bot API + Gyazo sunucusu (localhost, thread). Dis ag yok.

Kullanim:
    s = SahteSunucu(token="TEST"); ayar["TELEGRAM_API"] = s.url; ayar["GYAZO_API"] = s.url
    s.mesaj(111, "merhaba"); s.foto(111, "foto1"); s.geri_arama(111, "proje_pp", msg_id)
    bot.tur()  -> s.cagrilar: [(metod, govde), ...]; s.metinler(): gonderilen/duzenlenen metinler; s.gyazo_yuklemeler
Hata enjeksiyonu: s.getupdates_hatasi = (409, "Conflict") (bir kez), s.hata_429 = 2 (ilk 2 sendMessage 429), s.gyazo_hata = True.
"""
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs


def kucuk_jpeg(renk=(200, 30, 30), boyut=(48, 32)):
    try:
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", boyut, renk).save(buf, "JPEG", quality=80)
        return buf.getvalue()
    except Exception:
        return b"\xff\xd8\xff\xe0" + b"\x00" * 200 + b"\xff\xd9"


def kucuk_png(renk=(30, 30, 200), boyut=(40, 40)):
    try:
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", boyut, renk).save(buf, "PNG")
        return buf.getvalue()
    except Exception:
        return b"\x89PNG\r\n\x1a\n" + b"\x00" * 200


class SahteSunucu:
    def __init__(self, token="TEST"):
        self.token = token
        self.kilit = threading.Lock()
        self.kuyruk = []            # bekleyen guncellemeler (Telegram gibi: offset'ten kucukler atilir)
        self.cagrilar = []          # (metod, govde) basarili cagrilar
        self.denemeler = {}         # metod -> HTTP deneme sayisi (429 dahil)
        self.dosyalar = {"foto1": kucuk_jpeg(), "foto2": kucuk_jpeg((20, 200, 20)), "png1": kucuk_png(), "buyuk": b"\xff\xd8\xff" + b"\x00" * (9 * 1024 * 1024)}
        self.dosya_boyutu_bildir = True
        self.sonraki_update = 1
        self.sonraki_mesaj = 1000
        self.getupdates_hatasi = None   # (kod, metin) bir kez
        self.hata_429 = 0
        self.gyazo_hata = False
        self.gyazo_yuklemeler = []      # yuklenen bayt sayilari
        self.gyazo_sayac = 0
        self.son_mesajlar = {}          # chat_id -> botun o sohbete gonderdigi son mesajin id'si (temizle() ile silinmez)
        self.kullanicilar = {}          # uid -> (first_name, username): gercek Telegram her guncellemede ayni 'from' bilgisini yollar
        sunucu = self

        class Istek(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _govde(self):
                n = int(self.headers.get("Content-Length") or 0)
                ham = self.rfile.read(n) if n else b""
                tip = self.headers.get("Content-Type") or ""
                if "json" in tip:
                    try:
                        return json.loads(ham.decode("utf-8")), ham
                    except ValueError:
                        return {}, ham
                return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}, ham

            def _json(self, kod, nesne):
                veri = json.dumps(nesne, ensure_ascii=False).encode("utf-8")
                self.send_response(kod)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(veri)))
                self.end_headers()
                self.wfile.write(veri)

            def do_GET(self):
                self.do_POST()

            def do_POST(self):
                yol = urlparse(self.path).path
                if yol == "/api/upload":
                    return self._gyazo()
                if yol.startswith(f"/file/bot{sunucu.token}/"):
                    return self._dosya(yol[len(f"/file/bot{sunucu.token}/"):])
                on_ek = f"/bot{sunucu.token}/"
                if not yol.startswith(on_ek):
                    return self._json(404, {"ok": False, "error_code": 404, "description": "Not Found"})
                metod = yol[len(on_ek):]
                veri, _ = self._govde()
                with sunucu.kilit:
                    sunucu.denemeler[metod] = sunucu.denemeler.get(metod, 0) + 1
                    return getattr(self, "m_" + metod, self.m_bilinmeyen)(metod, veri)

            def m_bilinmeyen(self, metod, veri):
                self._json(404, {"ok": False, "error_code": 404, "description": f"Not Found: {metod}"})

            def m_getUpdates(self, metod, veri):
                if sunucu.getupdates_hatasi:
                    kod, metin = sunucu.getupdates_hatasi
                    sunucu.getupdates_hatasi = None
                    return self._json(kod, {"ok": False, "error_code": kod, "description": metin})
                offset = int(veri.get("offset") or 0)
                sunucu.kuyruk = [u for u in sunucu.kuyruk if u["update_id"] >= offset]
                limit = int(veri.get("limit") or 100)
                sunucu.cagrilar.append((metod, dict(veri)))
                self._json(200, {"ok": True, "result": [dict(u) for u in sunucu.kuyruk[:limit]]})

            def m_sendMessage(self, metod, veri):
                if sunucu.hata_429 > 0:
                    sunucu.hata_429 -= 1
                    return self._json(429, {"ok": False, "error_code": 429, "description": "Too Many Requests", "parameters": {"retry_after": 0}})
                if str(veri.get("chat_id")) == "404404":
                    return self._json(403, {"ok": False, "error_code": 403, "description": "Forbidden: bot was blocked by the user"})
                sunucu.sonraki_mesaj += 1
                kayit = dict(veri)
                kayit["_message_id"] = sunucu.sonraki_mesaj
                sunucu.cagrilar.append((metod, kayit))
                sunucu.son_mesajlar[str(veri.get("chat_id"))] = sunucu.sonraki_mesaj
                self._json(200, {"ok": True, "result": {"message_id": sunucu.sonraki_mesaj, "chat": {"id": veri.get("chat_id")}, "text": veri.get("text")}})

            def m_editMessageText(self, metod, veri):
                sunucu.cagrilar.append((metod, dict(veri)))
                self._json(200, {"ok": True, "result": {"message_id": veri.get("message_id"), "text": veri.get("text")}})

            def m_answerCallbackQuery(self, metod, veri):
                sunucu.cagrilar.append((metod, dict(veri)))
                self._json(200, {"ok": True, "result": True})

            def m_deleteMessage(self, metod, veri):
                sunucu.cagrilar.append((metod, dict(veri)))
                self._json(200, {"ok": True, "result": True})

            def m_getFile(self, metod, veri):
                fid = str(veri.get("file_id") or "")
                if fid not in sunucu.dosyalar:
                    return self._json(400, {"ok": False, "error_code": 400, "description": "Bad Request: file not found"})
                sunucu.cagrilar.append((metod, dict(veri)))
                uz = ".png" if sunucu.dosyalar[fid][:4] == b"\x89PNG" else ".jpg"
                sonuc = {"file_id": fid, "file_unique_id": "u" + fid, "file_path": f"photos/{fid}{uz}"}
                if sunucu.dosya_boyutu_bildir:
                    sonuc["file_size"] = len(sunucu.dosyalar[fid])
                self._json(200, {"ok": True, "result": sonuc})

            def _dosya(self, yol):
                fid = yol.rsplit("/", 1)[-1].rsplit(".", 1)[0]
                veri = sunucu.dosyalar.get(fid)
                if veri is None:
                    return self._json(404, {"ok": False, "description": "file not found"})
                with sunucu.kilit:
                    sunucu.cagrilar.append(("dosya_indir", {"file_id": fid}))
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(veri)))
                self.end_headers()
                self.wfile.write(veri)

            def _gyazo(self):
                _, ham = self._govde()
                yetki = self.headers.get("Authorization") or ""
                with sunucu.kilit:
                    if sunucu.gyazo_hata:
                        return self._json(500, {"message": "sunucu hatasi"})
                    if not yetki.startswith("Bearer ") or b'name="imagedata"' not in ham:
                        return self._json(401, {"message": "unauthorized"})
                    sunucu.gyazo_sayac += 1
                    kimlik = ("%032x" % sunucu.gyazo_sayac)
                    sunucu.gyazo_yuklemeler.append(len(ham))
                    sunucu.cagrilar.append(("gyazo_upload", {"bayt": len(ham)}))
                self._json(200, {"image_id": kimlik, "permalink_url": f"https://gyazo.com/{kimlik}", "url": f"https://i.gyazo.com/{kimlik}.jpg", "type": "jpg"})

        self.sunucu = ThreadingHTTPServer(("127.0.0.1", 0), Istek)
        self.sunucu.daemon_threads = True
        self.port = self.sunucu.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.sunucu.serve_forever, daemon=True)
        self.thread.start()

    def kapat(self):
        self.sunucu.shutdown()
        self.sunucu.server_close()

    # ---- guncelleme uretimi ----
    def ekle(self, icerik):
        with self.kilit:
            g = {"update_id": self.sonraki_update}
            g.update(icerik)
            self.sonraki_update += 1
            self.kuyruk.append(g)
            return g["update_id"]

    def _from(self, uid, ad, username):
        if ad is None or username is None:
            eski = self.kullanicilar.get(str(uid)) or ("Ali", None)
            ad = eski[0] if ad is None else ad
            username = eski[1] if username is None else username
        self.kullanicilar[str(uid)] = (ad, username)
        d = {"id": int(uid), "is_bot": False, "first_name": ad}
        if username:
            d["username"] = username
        return d

    def mesaj(self, uid, metin=None, ad=None, username=None, chat_tipi="private", tarih=1760000000, ek=None):
        """Metin mesaji (ya da ek sozlugu ile photo/document). ad/username verilmezse o kullanicinin son bilinen kimligi. -> message_id"""
        with self.kilit:
            self.sonraki_mesaj += 1
            mid = self.sonraki_mesaj
        m = {"message_id": mid, "from": self._from(uid, ad, username), "chat": {"id": int(uid), "type": chat_tipi}, "date": tarih}
        if metin is not None:
            m["text"] = metin
        if ek:
            m.update(ek)
        self.ekle({"message": m})
        return mid

    def foto(self, uid, file_id="foto1", **k):
        return self.mesaj(uid, None, ek={"photo": [{"file_id": file_id + "_kucuk", "width": 10, "height": 10}, {"file_id": file_id, "width": 48, "height": 32}]}, **k)

    def belge(self, uid, file_id="png1", mime="image/png", **k):
        return self.mesaj(uid, None, ek={"document": {"file_id": file_id, "file_name": "ekran.png", "mime_type": mime}}, **k)

    def geri_arama(self, uid, data, msg_id=None, ad=None, username=None):
        """Buton tiklamasi; msg_id None ise botun bu kullaniciya gonderdigi son mesaj."""
        if msg_id is None:
            msg_id = self.son_mesaj_id(uid)
        self.ekle({"callback_query": {"id": f"cb{self.sonraki_update}", "from": self._from(uid, ad, username), "data": data,
                                      "message": {"message_id": msg_id, "chat": {"id": int(uid), "type": "private"}}}})

    # ---- kayit okuma ----
    def son_mesaj_id(self, uid):
        """Bota ait, bu sohbete gonderilen son sendMessage'in message_id'si (butonlar bu mesaja baglidir; temizle() etkilemez)."""
        return self.son_mesajlar.get(str(uid))

    def mesaj_idleri(self, uid):
        return [v["_message_id"] for metod, v in self.cagrilar if metod == "sendMessage" and str(v.get("chat_id")) == str(uid)]

    def liste(self, metod, uid=None):
        return [v for m, v in self.cagrilar if m == metod and (uid is None or str(v.get("chat_id")) == str(uid))]

    def metinler(self, uid=None):
        return [v.get("text") or "" for m, v in self.cagrilar if m in ("sendMessage", "editMessageText") and (uid is None or str(v.get("chat_id")) == str(uid))]

    def son_metin(self, uid=None):
        m = self.metinler(uid)
        return m[-1] if m else ""

    def son_klavye(self, uid=None):
        for m, v in reversed(self.cagrilar):
            if m in ("sendMessage", "editMessageText") and (uid is None or str(v.get("chat_id")) == str(uid)):
                return v.get("reply_markup")
        return None

    def klavye_metinleri(self, uid=None):
        kb = self.son_klavye(uid) or {}
        return [[b["text"] for b in satir] for satir in kb.get("inline_keyboard", [])]

    def klavye_verileri(self, uid=None):
        kb = self.son_klavye(uid) or {}
        return [b["callback_data"] for satir in kb.get("inline_keyboard", []) for b in satir]

    def temizle(self):
        with self.kilit:
            self.cagrilar = []
            self.denemeler = {}
