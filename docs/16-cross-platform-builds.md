# Cross-platform builds and portable preview

October 25, 2026. The owner extended the original Mac-only scope to Windows/Linux compilation, configuration, and downloadable packages. The native Swift host still supplies macOS-specific capabilities. The portable distribution launches the Python service and opens its authenticated React dashboard in the system browser.

## Supported surfaces

The service, agent framework, local/cloud model clients, web tools, MCP, Second Brain, schedules, SQLite persistence, and workspace tools use the same implementation on all three operating systems. The frontend reports configured systems using platform metadata from `/api/status`.

Windows/Linux portable builds use text conversation. They do not include the Apple wake recognizer, native desktop audio, EventKit, Keychain, global voice shortcut, or native login-item registration. Phone audio can use configured OpenAI/carrier services; the Apple `say`/`afconvert` fallback reports an explicit unsupported-platform error. No other microphone implementation is silently substituted.

The initial binaries target Windows x86-64 and Linux x86-64/glibc 2.35+. A native build is required for another OS/architecture. Linux desktop integration, Windows signing, Linux ARM/musl, and native voice parity need their own work; the preview does not claim them.

## Runtime paths and controls

| Item | macOS | Windows | Linux |
| --- | --- | --- | --- |
| Private data | `~/Library/Application Support/Jarvis` | `%LOCALAPPDATA%/Jarvis` | `$XDG_DATA_HOME/Jarvis` or `~/.local/share/Jarvis` |
| User-private protection | POSIX modes | Protected Windows DACL for the current user, SYSTEM and administrators | POSIX modes |
| Process exclusion | `flock` | Nonblocking `msvcrt` byte lock | `flock` |
| Approved command shell | zsh without startup files | Windows PowerShell without profiles, encoded command | `/bin/sh` with a restricted environment |
| Confinement | Existing macOS sandbox | Explicitly unavailable | Explicitly unavailable |

Confinement requests never fall back to host execution. Strict-local command execution therefore remains unavailable on Windows/Linux; other local tools can still be used. Commands in connected profiles retain the existing proposal/approval policy. Provider credentials are not inherited by command or MCP child processes. Windows process cleanup terminates the worker tree on cancellation/timeout.

Windows workspace I/O uses `CreateFileW` handles that reject reparse points and pin ancestor directories against rename/delete. Device aliases, alternate data streams, ambiguous trailing dots/spaces, excluded secrets and external junctions are rejected. Existing-file replacement uses `ReplaceFileW` to retain its destination ACL. POSIX keeps the existing descriptor-relative operations. The native test suite exercises the host implementation, rather than merely mocking an OS name.

Windows commands use explicit UTF-8 output, closed standard input, system module discovery and no user profiles. Their working environment retains required Windows variables without inheriting provider keys. The frozen-app test also preserves `SYSTEMROOT` case-insensitively: Python normalizes Windows environment names to uppercase, and omitting this variable prevents Winsock/asyncio initialization.

Frozen builds find UI assets under their bundle resource directory, choose no workspace folders by default, and keep all mutable data outside the extracted application. Their default `.env` is in private application data. `--env-file` and `JARVIS_ENV_FILE` select another file; source checkouts retain the repository `.env` default. GUI settings and env precedence remain unchanged. Existing Mac data is not migrated or rewritten by the packaging process.

## Launcher and packaging

The executable defaults to `desktop`; `serve`, `doctor`, `config`, `open`, and other CLI commands remain available. Double-clicking `Jarvis.exe` starts a local service and opens the dashboard. The console owns that process; Ctrl+C stops it. Closing the browser does not terminate tasks, and no auto-start registration is performed.

The portable launcher authenticates any listener already using the configured port with a nonce/HMAC bound to the port before giving the browser its bearer token. An unrelated listener receives no bearer token. A second genuine instance opens the existing service instead of taking ownership or launching another database writer.

Discovery allows up to five seconds for the TCP connection and two seconds for a response. Windows can delay rejection of a closed loopback port beyond one second, so a one-second connect deadline caused false startup failures. The native source suite includes a real unused-port regression. A timeout against an occupied/unresponsive port still stops launch without sending credentials.

`packaging/jarvis.spec` includes only application modules, required libraries/metadata, and the built frontend. `scripts/build-desktop.py` adds public branding, a sanitized example env, instructions, and build metadata. Archives preserve the executable plus `_internal` together. No source checkout, venv, runtime data, credentials, OAuth cache, or model weights are copied. `uv.lock` supplies one universal dependency resolution.

PyInstaller requires a build on the destination platform. CI uses pinned official GitHub actions, a read-only repository token, Python 3.12 and Node 22. Uploads are permitted only after source tests, frontend compilation, and frozen-app checks pass. Files are accompanied by SHA256 checksums and source/lockfile identifiers; checksums provide integrity, not a publisher code signature.

## Verification procedure

`scripts/smoke-desktop.py` starts the actual frozen application from a temporary directory with private temporary data, a different port, no cloud key, no microphone, and a local HTTP model fixture. It checks bearer enforcement, rejected foreign Origin, bundle UI assets, no implicit workspace grant, OS/distribution metadata, and a real Deep Agents task that calls `current_time` and persists a checkpoint. The model fixture answers twice over loopback; no OpenAI request is made.

Source tests additionally exercise OS-specific paths, exclusive process ownership, environment filtering, command execution and timeout, filesystem revisions, Windows ACLs/junctions, and the existing privacy/tool boundaries. Native Swift scenarios remain macOS-specific. Headless CI does not certify an interactive voice conversation or every Linux desktop/browser integration.

Build and launch commands for each OS are in the [README](../README.md#build-and-run-on-windows-or-linux).

## Verification results

The current preview was built from `0e403738272ebfe6cb13b02e380bf4f6efed7bd8`; [native CI and frozen-app checks](https://github.com/emanueledibella/jarvis/actions/runs/40289020296) passed on all three systems. The [security gate](https://github.com/emanueledibella/jarvis/actions/runs/40289020314) passed independently.

The release executable records its source revision in `BUILD-INFO.json`. CI evidence is available in the repository’s Portable builds workflow.

| Host | Python tests | Frontend | Executable validation |
| --- | --- | --- | --- |
| Windows Server 2022, x86-64 | 118 passed, one macOS-only skip | TypeScript/Vite passed | Native PyInstaller EXE, isolated frozen-app smoke test |
| Ubuntu 22.04, x86-64 | 117 passed, two platform-specific skips | TypeScript/Vite passed | Native PyInstaller ELF, isolated frozen-app smoke test |
| macOS, ARM64 | 117 passed, two platform-specific skips; 40 Swift scenarios passed | TypeScript/Vite passed | Native Swift bundle compiled and ad-hoc signature verified locally |

Release archives are additionally checked for their SHA256, executable format, bundled frontend, source/lockfile identifiers, and absence of private runtime filenames. No production service restart or microphone activation is needed for this verification. No paid model request is made.

The lockfile fingerprint covers the bytes in the build checkout. Git checks out CRLF line endings on the Windows runner and LF on Linux, so those fingerprints differ; both were verified against the same Git lockfile with the corresponding line endings. The source revision pins its repository contents.

Primary references: [PyInstaller platform requirements](https://pyinstaller.org/en/stable/requirements.html), [bundle runtime paths](https://pyinstaller.org/en/stable/runtime-information.html), [uv universal lockfile](https://docs.astral.sh/uv/concepts/projects/layout/#the-lockfile), [CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew), [Windows PowerShell environment](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_environment_variables?view=powershell-5.1), [GitHub workflow artifacts](https://docs.github.com/en/actions/concepts/workflows-and-actions/workflow-artifacts).
