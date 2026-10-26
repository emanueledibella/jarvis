# Configurable lighting integrations

## Setup in Settings

Use **Settings → Lights and devices** to add, edit, or remove a light. Configure its spoken name, optional model label, connection method, personal/work scope, and capability profile. The model label is descriptive; the profile and adapter determine which commands are available.

Model labels accept Unicode text and punctuation, including `·` and `—`, up to 100 characters. Line breaks and control/formatting characters are rejected; surrounding whitespace is trimmed. The private registry is read and written explicitly as UTF-8 on every OS, independently of the Windows system code page.

Profiles cover fixed white with dimming, adjustable white temperature, and RGB plus white. Adjustable white has configurable minimum/maximum kelvin values. A White Ambiance profile supports white temperature, not RGB. Native Hue Bluetooth also intersects the selected profile with discovered characteristic support and its supported wire range. Unsupported changes are rejected before a write.

The default lighting feature flag is `JARVIS_LIGHTING_ENABLED=true`; it opens no radio connection and enrolls no devices. Setting it to false disables subsequent control. The same toggle is available in Settings. Device configuration is stored in private application data, independently of environment-controlled model selection.

## Hue Bluetooth without a Bridge

Select **Hue Bluetooth · no Bridge**, then **Find nearby Hue lights**. The native Mac app requests Bluetooth permission when the owner first performs discovery. A lamp being visible in the scan does not mean it accepts a new Bluetooth bond.

For a lamp already controlled by a phone, open **Hue → Settings → Voice Assistants → Amazon Alexa or Google Home → Make Discoverable** on that phone. This creates a temporary pairing window while preserving the phone's setup. Leave Hue in the background, then immediately find/select the lamp in Jarvis and use **Connect and save light**. The initial encrypted power read allows macOS to request legitimate Bluetooth pairing; confirm that system dialog if it appears. Repeat **Make Discoverable** if the window expires. Menu wording may vary with the Hue app version/language.

The Settings form includes these steps, and a failed enrollment points back to phone pairing mode. Jarvis cannot remotely enable that mode on a lamp with which it has not yet established an authenticated connection.

Discovery is limited to Hue/Signify lighting advertisements, lasts eight seconds, and returns a bounded candidate list. A discovered light is not yet registered or controllable by agent tools. Pairing verifies the Hue lighting service, reads its current state, and saves the owner's selected profile. Editing the same light can reuse its existing local association; choosing another physical light requires discovery and selection again.

Keep the lamp powered and the Mac in Bluetooth range. If the phone is holding the connection, close its Hue app before retrying. Jarvis disconnects after each operation and does not delete the phone's bond, factory-reset the lamp, rewrite its name, or change firmware/radio settings. Some firmware/pairing states may require manual vendor-guided steps; an incompatible or non-discoverable device is reported instead of being reset automatically.

The native implementation uses CoreBluetooth with no new Python Bluetooth dependencies. Only fixed power, brightness, white-temperature, and color characteristics are writable. Combined state uses a single typed TLV packet when available; otherwise settings are applied before powering on, while a requested power-off goes first. There are no flash, reset, clock, or raw-GATT tools. Commands use absolute values and read back actual state after writes.

Native Bluetooth requires macOS 14+ and the Jarvis app. Windows/Linux can use the MCP adapter; this feature does not claim native Hue Bluetooth support on those systems.

## Configurable MCP lighting services

Choose an existing MCP server, an allowed read-state tool, and an allowed set-state tool. Enable those tools in **Connections** first. Enter the constant arguments identifying the light or group. Command mappings rename the standard fields to the service's top-level parameter names; state mappings can read dotted paths from its JSON response. All fields can be configured from the GUI without changing code.

The adapter contract uses:

| Field | Meaning |
| --- | --- |
| `on` | JSON boolean |
| `brightness` | Percent from 0 to 100; a zero command means off |
| `temperature_kelvin` | White temperature in kelvin, within the chosen profile |
| `color` | RGB hex string such as `#FF8000` |

For example, a service might accept `power` and `level` instead of `on` and `brightness`, and return `status.power` and `status.level`. Configure those mappings and a synthetic target such as `{"entity_id":"light.example"}`. Credentials belong in the existing MCP connection configuration. Target arguments and mappings are kept in the private light registry and are not returned to the model's light-listing tool.

This is a defined adapter contract, not automatic compatibility with every MCP tool shape. Separate on/off tools, alternate units, or non-JSON state responses need a normalizing MCP service. The selected service remains responsible for correctly identifying and controlling its configured target. Server/tool allowlists and the task's network profile are rechecked on every call.

## Commands and permissions

The agent has `lights_list`, `light_state`, and `light_set`. It chooses only registered lights in the task's scope; an omitted target works only when exactly one light exists there. Models do not receive native Bluetooth identifiers and cannot discover, enroll, rename, or grant access to devices through these tools.

An owner can explicitly enable **Allow direct voice control** for each light. This permits reversible lighting changes without a new dashboard approval for each command. Without that grant, the existing dashboard approval flow applies. A previous grant does not allow web pages, documents, or other untrusted tool content to authorize lighting effects. Other tool risks and approval rules remain unchanged.

Useful Italian/English requests include “accendi la lampada”, “luminosità al 30%”, “bianco caldo a 2700 kelvin”, and “turn off the light”. RGB requests require a color-capable profile. A positive dimming/color command turns the light on unless the request explicitly keeps it off; zero brightness or black maps to off.

Each mutation passes through the common effect ledger. Success is reported only after state readback confirms the requested setting, with bounded brightness/temperature and color-coordinate tolerance. Timeouts or inconsistent readback remain unconfirmed, rather than being silently replayed. An already issued physical write cannot be undone by closing a voice response.

Native operations carry an ephemeral, exact-payload authorization checked immediately before the Mac claims the action. Registry edits/removal/grant changes invalidate queued authorizations. Disable and emergency stop block new operations; native settings updates also stop pending Bluetooth work. Private tasks keep their dialogue/effect result out of persistent logs. The private registry intentionally retains the owner's device configuration until they remove it.

MCP output is reduced to typed state values. Arbitrary text and raw remote exceptions never enter the trusted light-state result. Model text is not evidence that a lamp changed.

## Verification and sources

Regression tests exercise typed commands, unsupported-model controls, opaque discovery handles, private storage, scope separation, direct grants, approval/resume, effect deduplication, revocation before native claim, disabled/emergency-stop paths, MCP policy/mapping, malformed state/error redaction, private tasks, and editing an existing association. Pure Swift tests verify Hue packet values and reject raw/reset/conflicting operations. These tests use synthetic devices and do not scan or change an actual lamp.

Hardware discovery, first pairing, coexistence with the phone, and actual power/dimming/temperature require an owner's device check. The public repository contains no device inventory, radio identifiers, personal model selections, or pairing records.

Primary references consulted:

- [Home Assistant Hue BLE pairing prerequisites](https://www.home-assistant.io/integrations/hue_ble/#alexagoogle-pairing-mode), including the phone's non-destructive **Make Discoverable** flow.
- [Philips Hue: connecting without a Bridge](https://www.philips-hue.com/en-us/explore-hue/faq/controls/how-to-connect-philips-hue-without-a-bridge) for Bluetooth operation and product limitations.
- [HueBLE](https://github.com/flip-dots/HueBLE), [hue-ble-mcp](https://github.com/jonnyblankinship/hue-ble-mcp), and [OpenHue](https://github.com/dw2lam/OpenHue) for the community-documented Hue lighting GATT profile. Jarvis uses its own bounded CoreBluetooth adapter; these projects are not installed or executed by setup.
- [CoreBluetooth pairing/permission behavior documented by Bleak](https://bleak.readthedocs.io/en/latest/backends/macos.html), including the required application usage description and OS-owned pairing dialog.
