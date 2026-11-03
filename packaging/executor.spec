from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).parent
a = Analysis([str(root / "scripts/executor-entry.py")], pathex=[str(root / "src")],
             binaries=[], datas=[], hiddenimports=collect_submodules("keyring.backends"),
             hookspath=[], runtime_hooks=[], excludes=["torch", "tensorflow", "faster_whisper", "pytest"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="JarvisExecutor", debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="JarvisExecutor")
