# -*- coding: utf-8 -*-
"""Telegram Bot API sarmalayicisi (requests).

Botun Send-Json / Send-Message / Edit-Message / Answer-Callback / Delete-Message kalibi:
  - her cagri 3 deneme, aralarda 0.3*i sn geri cekilme,
  - 429 Too Many Requests: Telegram'in verdigi retry_after kadar bekler,
  - 409 Conflict (ayni token ile ikinci poller): CakismaHatasi firlatir, dongu bunu gurultulu loglar,
  - metinler HTML parse_mode ile gider; kullanici metni html_kacir ile kacirilir (Escape-Html),
  - klavyeler JSON (inline_keyboard) olarak gonderilir.
Taban adres ayarlanabilir (ayar 'TELEGRAM_API'); testler sahte sunucuya yonlendirir.
"""
import logging
import time
import requests

log = logging.getLogger("kanit.bot")
VARSAYILAN_TABAN = "https://api.telegram.org"


class CakismaHatasi(Exception):
    """409 Conflict: baska bir bot sureci ayni token ile getUpdates cekiyor."""


class GorselBuyuk(ValueError):
    """Dosya MAX_GORSEL_MB sinirini asiyor."""


def html_kacir(s):
    """Escape-Html: & < > \" kacirilir (parse_mode HTML icin)."""
    if s is None:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def klavye(satirlar):
    """[[(metin, callback_data), ...], ...] -> {'inline_keyboard': [[{'text','callback_data'}]]}"""
    return {"inline_keyboard": [[{"text": str(m), "callback_data": str(d)} for (m, d) in satir] for satir in satirlar]}


class TelegramAPI:
    def __init__(self, token, taban=None, uyku=None, deneme=3):
        self.token = token or ""
        self.taban = (taban or VARSAYILAN_TABAN).rstrip("/")
        self.uyku = uyku or time.sleep
        self.deneme = max(1, int(deneme))
        self.oturum = requests.Session()
        self.son_hata = ""
        self.deneme_sayisi = 0  # toplam HTTP denemesi (test/istatistik)

    def _url(self, metod):
        return f"{self.taban}/bot{self.token}/{metod}"

    def cagir(self, metod, veri=None, zaman_asimi=12, sessiz=False):
        """Bir API metodu. -> result (dict/list/bool) | None (hata; son_hata dolu). 409 -> CakismaHatasi."""
        for i in range(1, self.deneme + 1):
            self.deneme_sayisi += 1
            try:
                r = self.oturum.post(self._url(metod), json=veri or {}, timeout=zaman_asimi)
                if r.status_code == 409:
                    raise CakismaHatasi(f"{metod}: 409 Conflict - {r.text[:200]}")
                try:
                    j = r.json()
                except ValueError:
                    j = None
                if r.status_code == 429:
                    bekle = 1
                    if isinstance(j, dict):
                        bekle = (j.get("parameters") or {}).get("retry_after", 1)
                    try:
                        bekle = min(float(bekle), 60.0)
                    except (TypeError, ValueError):
                        bekle = 1.0
                    log.warning("! Telegram 429 (%s): %.1f sn bekleniyor", metod, bekle)
                    self.uyku(bekle)
                    continue
                if isinstance(j, dict) and j.get("ok"):
                    return j.get("result", True)
                aciklama = (j or {}).get("description") if isinstance(j, dict) else None
                self.son_hata = f"{metod}: {aciklama or ('HTTP %s' % r.status_code)}"
                if r.status_code in (400, 401, 403, 404):
                    # kalici hata (gecersiz chat, bot engellenmis, bozuk istek): tekrar denemenin anlami yok
                    if not sessiz:
                        log.warning("! API hatasi: %s", self.son_hata)
                    return None
                log.warning("! API hatasi (%s/%s): %s", i, self.deneme, self.son_hata)
            except CakismaHatasi:
                raise
            except requests.RequestException as e:
                self.son_hata = f"{metod}: {e}"
                log.warning("! API hatasi (%s/%s): %s", i, self.deneme, self.son_hata)
            if i < self.deneme:
                self.uyku(0.3 * i)
        return None

    # ---- mesajlar ----
    def mesaj_gonder(self, chat_id, metin, klavye_=None):
        """Send-Message -> message_id | None"""
        veri = {"chat_id": chat_id, "text": metin, "parse_mode": "HTML", "disable_web_page_preview": True}
        if klavye_:
            veri["reply_markup"] = klavye_
        r = self.cagir("sendMessage", veri)
        if isinstance(r, dict):
            return r.get("message_id")
        return None

    def mesaj_duzenle(self, chat_id, mesaj_id, metin, klavye_=None):
        """Edit-Message (mesaj_id yoksa yeni mesaj gonderir). -> message_id | None"""
        if not mesaj_id:
            return self.mesaj_gonder(chat_id, metin, klavye_)
        veri = {"chat_id": chat_id, "message_id": mesaj_id, "text": metin, "parse_mode": "HTML", "disable_web_page_preview": True}
        if klavye_:
            veri["reply_markup"] = klavye_
        r = self.cagir("editMessageText", veri, sessiz=True)
        if r is None:
            # "message is not modified" ya da mesaj silinmis: yeni mesajla devam et
            if "not modified" in (self.son_hata or ""):
                return mesaj_id
            log.warning("! Mesaj duzenlenemedi (%s); yeni mesaj gonderiliyor", self.son_hata)
            return self.mesaj_gonder(chat_id, metin, klavye_)
        return mesaj_id

    def geri_arama_yanitla(self, cb_id, metin=None):
        veri = {"callback_query_id": cb_id}
        if metin:
            veri["text"] = metin
        try:
            self.cagir("answerCallbackQuery", veri, zaman_asimi=5, sessiz=True)
        except CakismaHatasi:
            pass

    def mesaj_sil(self, chat_id, mesaj_id):
        try:
            return bool(self.cagir("deleteMessage", {"chat_id": chat_id, "message_id": mesaj_id}, zaman_asimi=5, sessiz=True))
        except CakismaHatasi:
            return False

    def guncellemeler(self, offset, zaman_asimi=25, limit=100):
        """getUpdates (long polling). -> list | None (hata)"""
        r = self.cagir("getUpdates", {"offset": offset, "timeout": zaman_asimi, "limit": limit}, zaman_asimi=zaman_asimi + 10)
        if isinstance(r, list):
            return r
        return None

    # ---- dosyalar ----
    def dosya_bilgisi(self, file_id):
        return self.cagir("getFile", {"file_id": file_id}, zaman_asimi=15)

    def dosya_indir(self, file_path, en_fazla_bayt):
        """file/bot<token>/<file_path> akisini indirir; sinir asilirsa GorselBuyuk."""
        url = f"{self.taban}/file/bot{self.token}/{file_path}"
        r = self.oturum.get(url, timeout=30, stream=True)
        r.raise_for_status()
        parcalar, toplam = [], 0
        for parca in r.iter_content(65536):
            if not parca:
                continue
            toplam += len(parca)
            if toplam > en_fazla_bayt:
                r.close()
                raise GorselBuyuk(f"{toplam} bayt > {en_fazla_bayt}")
            parcalar.append(parca)
        return b"".join(parcalar)

    def gorsel_indir(self, file_id, en_fazla_bayt):
        """getFile + indirme, boyut siniri. -> bytes. Hata: RuntimeError / GorselBuyuk."""
        bilgi = self.dosya_bilgisi(file_id)
        if not isinstance(bilgi, dict) or not bilgi.get("file_path"):
            raise RuntimeError("getFile basarisiz: " + (self.son_hata or "yanit yok"))
        boyut = bilgi.get("file_size")
        if boyut and int(boyut) > en_fazla_bayt:
            raise GorselBuyuk(f"{boyut} bayt > {en_fazla_bayt}")
        return self.dosya_indir(bilgi["file_path"], en_fazla_bayt)
