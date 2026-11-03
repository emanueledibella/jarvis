# Managed telephony connection

In **Settings → Telephony**, choose **Connection management → Managed by Jarvis**.
Fill in the carrier, numbers, PIN when required, and audio settings, then click
**Activate telephony**. Activation saves pending settings and starts a private
Caddy proxy and a Cloudflare Quick Tunnel. It does not place a call.

Caddy and `cloudflared` must already be installed. On macOS they can be installed
with `brew install caddy cloudflared`. Jarvis also searches the standard Homebrew
locations when launched from Finder. The application does not install services
or register these tools to start at login.

Activation shows progress until a signed public challenge proves that the new
tunnel reaches this Jarvis instance. The generated HTTPS address is used for
webhook signatures, call callbacks, PIN redirects and WSS audio. It stays in
memory; an old manually configured proxy URL is preserved separately. No call
or carrier budget reservation is needed to verify the connection.
Jarvis waits for Cloudflare to register the connection and tolerates delayed
DNS availability, including macOS caching of an initial negative DNS answer.

When incoming calls are enabled, activation also updates the configured Twilio
number's voice and status webhooks to the new address. This requires access to
that incoming number in the configured account and a valid incoming PIN. An
account, number, connection or webhook error closes both child processes and
shows an error. Activation never creates or purchases a phone number.

**Deactivate telephony** closes the tunnel and proxy, then stops active calls.
It can also cancel an activation in progress. The same cleanup runs during an
emergency stop, a switch to `local_strict`, relevant phone configuration changes,
or backend shutdown. Lifetime-pipe guardians terminate the native children even
if the backend is killed. Unexpected exit of either child closes its companion;
startup and shutdown are bounded and repeated activation does not duplicate
processes. A new Jarvis session requires explicit activation again.

The generated proxy binds to a free loopback port. It forwards only POST
`/telephony/voice`, POST `/telephony/status`, and GET `/telephony/media`, retaining
the body, connection and timeout limits of the external proxy example. Other
paths return 404. Provider credentials and local API tokens are not inherited by
the children. Raw child output is drained without retaining request logs.

Existing installations retain **External proxy** mode by default. Set
`JARVIS_TELEPHONY_TUNNEL_MODE=managed` before launch to select managed mode, or
leave it unset to select the mode in Settings. Do not lock
`JARVIS_TELEPHONY_ENABLED=false` through the environment if activation should be
controlled in the dashboard. A locked configuration never prevents stopping an
already managed tunnel.

External mode keeps the previous proxy URL and enabled setting. Jarvis stops
only processes it created. Close any old manually started Caddy/cloudflared
commands once when migrating; unrelated listeners are never terminated.

[Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)
assign a temporary address on every activation and have no uptime guarantee.
The computer must stay awake and the Jarvis backend must remain running.

Outbound reminder calls announce the notification body, falling back to the title
when no body is supplied. The announcement replaces the generic offer of help;
incoming calls retain the normal assistant greeting. PIN verification, when
enabled, happens before any reminder content is disclosed. OpenAI Live receives
the complete opening in its initial session input, so it can announce the reminder
before listening without a second greeting or a delayed, truncated readback.

For outbound calls with the PIN disabled, a verified answer from Twilio starts
preparing that same Live voice while the carrier finishes connecting. A call
requiring a PIN can prepare only after verification. The first audio packet waits
in memory until the authenticated media stream attaches, then playback uses the
already running session. Preparation expires after 15 seconds without a media
connection and closes on hangup, shutdown or privacy/authorization changes; it
uses the existing voice budget reservation and includes preparation in usage.
Duplicate callbacks reuse one session, and a failed or expired preparation falls
back to normal startup. `call.voice_started` records preparation and the wait from
media attachment to the first outgoing audio packet, without retaining audio or
reminder contents.
The preparation sends only locally generated silence to keep Live's audio clock
running before the carrier attaches. Startup output silence is discarded with a
bounded 100 ms lead-in retained to preserve the opening of the first spoken word.

Verification includes concurrent activation, cancellation, failed startup,
lost children, emergency/shutdown cleanup, no automatic restart, authenticated
controls, current-URL signatures, inbound webhook updates with a fake carrier,
real lifetime-pipe cleanup after parent death, and a real Caddy routing check
when installed. Public carrier calls and paid audio are outside these tests.

The October 28 verification also exercised a real supervised Caddy/Cloudflare
tunnel with a separate local Jarvis instance and synthetic credentials. Its
signed public challenge succeeded, private paths returned 404, unsigned webhooks
returned 403, and deactivation stopped both children and closed the proxy port.
The dashboard Activate/Deactivate flow was checked in a real browser with a fake
Cloudflare child, including a 390 px viewport without horizontal overflow.
