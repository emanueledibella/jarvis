"""Safe, human-readable telephony requirements, without configuration values."""

LABELS = {
    "telephony_account_id": ("Twilio account SID", "SID account Twilio"),
    "telephony_auth_token": ("Twilio auth token", "Token di autenticazione Twilio"),
    "telephony_from_number": ("Caller number, E.164", "Numero chiamante, E.164"),
    "telephony_from_number_e164": ("Caller number in E.164 format (+country code and number)", "Numero chiamante in formato E.164 (+prefisso e numero)"),
    "owner_phone_number": ("Your verified number, E.164", "Il tuo numero verificato, E.164"),
    "owner_phone_number_e164": ("Your verified number in E.164 format (+country code and number)", "Il tuo numero verificato in formato E.164 (+prefisso e numero)"),
    "phone_pin": ("Personal PIN, 6–8 digits", "PIN personale di 6–8 cifre"),
    "phone_pin_6_to_8_digits": ("Personal PIN, 6–8 digits", "PIN personale di 6–8 cifre"),
    "phone_api_key": ("OpenAI audio API key", "Chiave API OpenAI per l’audio"),
    "desktop_voice_api_key": ("OpenAI key for the shared voice", "Chiave OpenAI per la voce condivisa"),
    "extra_voice": ("Local speech recognition dependency (voice extra)", "Dipendenza per il riconoscimento vocale locale (extra voice)"),
    "telephony_public_base_url": ("Public HTTPS telephony URL", "URL HTTPS pubblico per la telefonia"),
    "public_https_url": ("A public HTTPS URL for telephony", "Un URL HTTPS pubblico per la telefonia"),
    "telephony_tunnel": ("Active telephony connection", "Connessione telefonica attiva"),
}


def requirement_labels(missing: list[str], language: str) -> list[str]:
    index = 1 if language == "it" else 0
    return list(dict.fromkeys(LABELS.get(field, (field, field))[index] for field in missing))


def configuration_error(missing: list[str], language: str) -> ValueError:
    # Installed companions recognize this prefix as a translatable validation
    # error; a pretranslated message would be hidden under technical details.
    return ValueError("Invalid fields: " + ", ".join(requirement_labels(missing, language)) + ".")
