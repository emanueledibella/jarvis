# Build with scripts/build-desktop.py on the destination operating system.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules, copy_metadata

root = Path(SPECPATH).parent
datas = [(str(root / "web/dist"), "web/dist")]
datas += copy_metadata("jarvis-personal", recursive=True)
for package in ("deepagents", "fastmcp", "dateparser", "jsonschema_specifications", "tzdata"):
    datas += collect_data_files(package)
hidden = collect_submodules("jarvis") + collect_submodules("tiktoken_ext")
hidden += ["langchain_openai", "langchain_ollama", "langchain_anthropic", "langgraph.checkpoint.sqlite.aio", "uvicorn.logging", "uvicorn.loops.asyncio", "uvicorn.protocols.http.h11_impl", "uvicorn.protocols.websockets.websockets_impl", "uvicorn.lifespan.on"]
analysis = Analysis(
    [str(root / "packaging/entrypoint.py")],
    pathex=[str(root / "src")],
    binaries=collect_dynamic_libs("sqlite_vec"),
    datas=datas,
    hiddenimports=hidden,
    excludes=["pytest", "ruff", "faster_whisper", "tkinter"],
)
archive = PYZ(analysis.pure)
executable = EXE(
    archive, analysis.scripts, [], exclude_binaries=True,
    name="Jarvis", console=True, upx=False,
    icon=str(root / "assets/jarvis-icon.png") if sys.platform == "win32" else None,
)
bundle = COLLECT(executable, analysis.binaries, analysis.datas, name="Jarvis", upx=False)
