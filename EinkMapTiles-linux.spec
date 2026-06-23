# -*- mode: python ; coding: utf-8 -*-
# Build on Linux with: pyinstaller EinkMapTiles-linux.spec

a = Analysis(
    ['launch.py'],
    pathex=['src'],
    binaries=[],
    datas=[],
    hiddenimports=[
        'mapbox_vector_tile',
        'mapbox_vector_tile.decoder',
        'mapbox_vector_tile.encoder',
        'vt2geojson',
        'PIL._tkinter_finder',
        'lz4.frame',
        'lz4.block',
        'shapely',
        'pyproj',
        'urllib.request',
        'urllib.parse',
        'json',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='EinkMapTiles',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
