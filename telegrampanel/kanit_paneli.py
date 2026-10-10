# -*- coding: utf-8 -*-
"""Exe giris noktasi (PyInstaller). Kaynaktan calistirmak icin: python -m app.panel"""
import os, sys

if __name__ == "__main__":
    if "--surum" in sys.argv:
        from app.panel import SURUM
        print("KanitPaneli", SURUM)
        sys.exit(0)
    if "--kendini-sina" in sys.argv:
        # Derleme sonrasi duman testi: kutuphaneler ve exe icindeki sablon/statik dosyalar yerinde mi?
        import tempfile
        os.environ["PANEL_VERI"] = tempfile.mkdtemp(prefix="kanitpaneli-sina-")
        import waitress, openpyxl, PIL.Image, sqlite3, werkzeug.security  # noqa: F401
        from app import panel
        c = panel.app.test_client()
        r1 = c.get("/saglik"); r2 = c.get("/kurulum")
        print("saglik", r1.status_code, "kurulum", r2.status_code, "statik", c.get("/static/stil.css").status_code)
        assert r1.status_code == 200 and r1.headers.get("X-Kanit-Paneli") == panel.SURUM
        assert r2.status_code == 200 and "Kurulum" in r2.get_data(as_text=True)
        assert c.get("/static/stil.css").status_code == 200 and c.get("/static/panel.js").status_code == 200
        assert werkzeug.security.check_password_hash(werkzeug.security.generate_password_hash("x"), "x")
        print("KanitPaneli kendini-sina: OK")
        sys.exit(0)
    from app.panel import calistir
    calistir()
