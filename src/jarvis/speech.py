import re


def speech_text(markdown: str, limit: int = 1500) -> str:
    """Produce a spoken view without asking a second model to rewrite facts."""
    text = re.sub(r"```[\s\S]*?```", " Il codice è disponibile nella dashboard. ", markdown)
    text = re.sub(r"\[([^\]]+)\]\(https?://[^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "riferimento nella dashboard", text)
    text = re.sub(r"(?m)^\s{0,3}(?:#{1,6}|[-*])\s+", "", text)
    text = re.sub(r"[`*_]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        cutoff = text.rfind(".", 0, limit)
        text = (
            text[: cutoff + 1 if cutoff > limit // 2 else limit].rstrip()
            + " Trovi il dettaglio nella dashboard."
        )
    return text
