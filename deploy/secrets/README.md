Mount server-side APNs and FCM credentials here only when enabling push.
Use owner-only permissions readable by container UID 10001. No real credential
belongs in Git, an image, a companion binary or a build artifact. Set paths in
deploy/.env, such as /run/secrets/apns.p8 or /run/secrets/fcm.json.
