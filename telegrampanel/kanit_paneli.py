# -*- coding: utf-8 -*-
"""Exe giris noktasi (PyInstaller). Kaynaktan calistirmak icin: python -m app.panel"""
import sys
from app.panel import calistir

if __name__ == "__main__":
    if "--surum" in sys.argv:
        from app.panel import SURUM
        print("KanitPaneli", SURUM)
        sys.exit(0)
    calistir()
