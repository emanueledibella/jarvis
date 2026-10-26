"""Application-owned phone prompts follow the conversation's initial language."""

MESSAGES = {
    "it": {
        "pin": "Sono Jarvis. Digita il tuo codice personale per continuare.",
        "verified": "Sono Jarvis. Identità verificata. Come posso aiutarti?",
        "reason": "Motivo della chiamata: {reason}",
        "dashboard": "La proposta richiede una verifica nell'interfaccia di Jarvis sul Mac.",
        "long_proposal": "La proposta è troppo lunga per la conferma telefonica. Controllala sul Mac.",
        "approval": "È richiesta la conferma per {tool}. Parametri: {arguments}. Premi uno per approvare questa azione o due per rifiutarla.",
        "pending": "Premi uno per approvare la proposta appena letta o due per rifiutarla.",
        "not_read": "Attendi la lettura completa della proposta prima di confermare, oppure controllala sul Mac.",
        "failed": "Non ho completato l'operazione. I dettagli sono disponibili nell'interfaccia di Jarvis.",
        "background": "Il lavoro continua in sottofondo. Il risultato sarà disponibile sul Mac.",
        "goodbye": "A presto.",
        "request_failed": "La richiesta vocale non è riuscita. Controlla le connessioni nelle impostazioni di Jarvis.",
        "expired": "La proposta è scaduta oppure è già stata confermata o rifiutata.",
    },
    "en": {
        "pin": "I am Jarvis. Enter your personal code to continue.",
        "verified": "I am Jarvis. Identity verified. How can I help?",
        "reason": "Reason for the call: {reason}",
        "dashboard": "The proposal requires review in the Mac dashboard.",
        "long_proposal": "The proposal is too long for phone confirmation. Review it in the dashboard.",
        "approval": "Confirmation required for {tool}. Parameters: {arguments}. Press one to approve this action or two to reject it.",
        "pending": "Press one to approve the proposal you just heard or two to reject it.",
        "not_read": "Wait for the complete proposal before confirming, or review it in the dashboard.",
        "failed": "I did not complete the operation. Details are available in the dashboard.",
        "background": "Work continues in the background. The result will be available on the Mac.",
        "goodbye": "Goodbye.",
        "request_failed": "The voice request failed. Check connections in the dashboard.",
        "expired": "This proposal has expired or has already been decided.",
    },
}


def phone_language(settings) -> str:
    language = settings.response_language
    return settings.language if language == "auto" else language


def phone_message(settings, name: str, **values) -> str:
    language = phone_language(settings).split("-")[0].lower()
    return MESSAGES.get(language, MESSAGES["en"])[name].format(**values)
