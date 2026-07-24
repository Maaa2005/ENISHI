from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules


project_dir = Path(SPECPATH)
datas = [
    (str(project_dir / "alembic.ini"), "."),
    (str(project_dir / "alembic_migrations"), "alembic_migrations"),
    (
        str(project_dir / "enishi_core" / "protocol" / "negotiation-message.schema.json"),
        "enishi_core/protocol",
    ),
]
hiddenimports = []

# database.pyはAlembicをimportlibで遅延ロードするため明示的に同梱する。
hiddenimports += collect_submodules("alembic", filter=lambda name: ".testing" not in name)

# keyringはmacOSバックエンドを実行時ロードするため、プラグイン一式を収集する。
keyring_datas, keyring_binaries, keyring_hiddenimports = collect_all("keyring")
datas += keyring_datas
hiddenimports += keyring_hiddenimports

a = Analysis(
    [str(project_dir / "enishi_core" / "sidecar.py")],
    pathex=[str(project_dir)],
    binaries=keyring_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="enishi-core",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
