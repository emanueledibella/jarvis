JARVIS - PORTABLE DASHBOARD PREVIEW

Extract this entire archive. Keep Jarvis.exe (Windows) or Jarvis (Linux)
together with the _internal directory. No separate Python or Node install
is needed to run this package. A modern web browser is required.

Windows: double-click Jarvis.exe.
Linux: open a terminal in this directory and run ./Jarvis.

The launcher opens an authenticated dashboard on 127.0.0.1. Keep the console
open while using Jarvis; Ctrl+C stops its service. Closing the browser tab
does not stop the service. Nothing is installed for automatic login startup.

First use: configure a model in Settings. Ollama/LM Studio must be installed
separately for local models. Provider keys are entered locally, never included
in a download. Enable workspace folders explicitly before using file tools.

Private data locations:
  Windows: %LOCALAPPDATA%\Jarvis
  Linux: $XDG_DATA_HOME/Jarvis, or ~/.local/share/Jarvis
An explicit --env-file can be supplied before the command. In a frozen build,
the default .env is inside that private data directory, not the launch folder.

Examples:
  Jarvis.exe --help
  Jarvis.exe config validate
  Jarvis.exe --env-file C:\path\jarvis.env desktop
  ./Jarvis --env-file /path/jarvis.env desktop --no-browser

These Windows/Linux builds include the service, agents, dashboard, local/cloud
model clients, workspace tools, MCP, memory, web tools and scheduling.
Apple wake recognition, native microphone/desktop speech, EventKit, global
voice shortcut and the macOS sandbox require the separate native Mac app.
Use text on the portable dashboard. Telephony requires separately configured
carrier/OpenAI credentials. Local faster-whisper is not bundled.

Host commands require an explicit approval; confinement mode fails closed
where the macOS sandbox is unavailable. There is no silent fallback.

These are unsigned preview builds. Follow your organization's execution policy;
do not disable system protections. Verify the archive's SHA256 against the
published checksum. Full instructions and platform limits:
https://github.com/emanueledibella/jarvis#build-and-run-on-windows-or-linux
