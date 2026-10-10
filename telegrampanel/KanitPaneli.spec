# -*- mode: python ; coding: utf-8 -*-
# PyInstaller tarifi: tek dosya KanitPaneli.exe (sablonlar ve statik dosyalar iceride).
a = Analysis(
    ["kanit_paneli.py"],
    pathex=["."],
    binaries=[],
    datas=[("app/templates", "app/templates"), ("app/static", "app/static")],
    hiddenimports=["waitress", "openpyxl", "PIL", "PIL.Image", "jinja2.ext"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pydoc", "doctest", "test"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="KanitPaneli",
    debug=False,
    strip=False,
    upx=False,
    console=True,
    icon=None,
)
