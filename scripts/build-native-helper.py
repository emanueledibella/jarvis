"""Build the optional macOS capability adapter; Windows uses cloud calendars."""
import platform
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
output = root / "dist/native-helper"
output.mkdir(parents=True, exist_ok=True)
if sys.platform != "darwin":
    (output / "README.txt").write_text("Apple EventKit and the macOS window picker are available only on macOS.\n")
else:
    architecture = "arm64" if platform.machine() == "arm64" else "x86_64"
    subprocess.run(["swiftc", "-O", "-parse-as-library", "-target", architecture + "-apple-macos14.0",
        str(root / "native/RemoteNativeHelper.swift"), str(root / "native/CalendarBridge.swift"),
        str(root / "native/ScreenContext.swift"), str(root / "native/DocumentOCR.swift"),
        "-Xlinker", "-sectcreate", "-Xlinker", "__TEXT", "-Xlinker", "__info_plist", "-Xlinker", str(root / "native/RemoteNativeHelper.Info.plist"),
        "-o", str(output / "JarvisNativeHelper")], check=True)
    subprocess.run(["codesign", "--force", "--sign", "-", str(output / "JarvisNativeHelper")], check=True)
