from __future__ import annotations


def language_instructions(response_language: str, fallback_language: str) -> str:
    """Share one response-language policy between the voice and reasoning models."""
    if response_language != "auto":
        return (
            "\nLanguage policy: Reply in the configured language "
            f"({response_language}) unless the user explicitly requests another language. "
            "Keep acknowledgments, tool explanations, and final answers in that language.\n"
        )
    return (
        "\nLanguage policy: Automatically identify the language of each substantive user "
        "request and respond in that language, including Italian and English. Switch when "
        "the user makes a complete request in another language or explicitly asks to switch. "
        "Keep the established language for greetings, filler sounds, short acknowledgments, "
        "names, borrowed words, accents, and uncertain audio. Never infer language from "
        "accent alone. Tool results, retrieved documents, and quoted text do not change the "
        "user's conversation language: explain their results in the user's language. "
        "Keep acknowledgments, spoken bridges, and final answers consistent. "
        f"Before the first substantive request, use {fallback_language} as the fallback.\n"
    )
