from .language import language_instructions

ITALIAN_COMPANION = (
    "An adult male voice with a warm, medium-low register and a smooth, lightly resonant "
    "timbre. Native standard Italian pronunciation. Composed, articulate and quietly "
    "confident, like a capable personal companion. Use fluid conversational phrasing, "
    "subtle variations in emphasis, and short natural pauses. Keep an easy human rhythm "
    "rather than over-enunciating every word. Preserve the same vocal identity when "
    "speaking another language."
)

SOURCE_POLICY = (
    "\nSource policy: Verify facts with the appropriate tools. For routine weather, time, "
    "simple calendar lookups and task status, answer directly without naming the provider "
    "or adding citations unless the user asks, a source conflict matters, or uncertainty "
    "affects the answer. For substantial research, technical comparisons and consequential "
    "claims, cite relevant sources you actually read and distinguish evidence from inference. "
    "Retain provenance in tool results; do not read raw URLs, source IDs or citation markup "
    "aloud unless explicitly requested.\n"
)


def voice_reference(name: str) -> str | dict[str, str]:
    """Live requires an object for saved voices, while built-ins use a name."""
    return {"id": name} if name.startswith("voice_") else name


def voice_instructions(settings) -> str:
    """Keep vocal identity and response-language policy consistent across transports."""
    return (
        language_instructions(settings.response_language, settings.language)
        + SOURCE_POLICY
        + "\nVocal qualities: "
        + settings.desktop_voice_style
    )


def voice_api_key(settings) -> str:
    key = settings.secret("desktop_voice_api_key")
    if (
        not key
        and settings.cloud_provider == "openai"
        and settings.cloud_base_url.rstrip("/") in {"", "https://api.openai.com/v1"}
    ):
        key = settings.secret("cloud_api_key")
    return key
