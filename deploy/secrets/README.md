Mount server-side APNs and FCM credentials here only when enabling push.
Use owner-only permissions readable by container UID 10001. No real credential
belongs in Git, an image, a companion binary or a build artifact. Set paths in
`deploy/.env`, such as `/run/secrets/apns.p8` or `/run/secrets/fcm.json`.

`JARVIS_APNS_PRIVATE_KEY` and `JARVIS_FCM_SERVICE_ACCOUNT` in that Compose file
are paths, not inline keys. Compose maps them to the core's
`JARVIS_REMOTE_APNS_PRIVATE_KEY` and `JARVIS_REMOTE_FCM_SERVICE_ACCOUNT` options.
Only the core mounts this directory; the isolated document worker does not.
Back up these mounted credentials separately from the core's age snapshot.
See [server push setup](../README.md#voce-e-notifiche) and
[the complete option reference](../../docs/12-configurazione-env.md#remote-server-options).
