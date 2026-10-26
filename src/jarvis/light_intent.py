"""Conservative, whole-request matching for an owner's explicit lighting command."""

from __future__ import annotations

import re
import unicodedata


def words(value: str) -> str:
    return " ".join(value.casefold().replace("’", "'").split())


def requested_light_change(prompt: str, wake_phrase: str = "Jarvis") -> tuple[str, dict] | None:
    # Quoted/document instructions, multiple requests, and ambiguous language
    # keep the normal approval policy. Never extract commands from a passage.
    if len(prompt) > 240 or any(unicodedata.category(c) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for c in prompt):
        return None
    text = words(prompt).rstrip(".!? ")
    if wake_phrase.strip():
        text = re.sub(r"^" + re.escape(words(wake_phrase)) + r"(?:[,.:!?]\s*|\s+)", "", text)
    text = re.sub(r"^(?:per favore|please)[, ]+", "", text)
    text = re.sub(r"^(?:puoi|potresti|can you|could you|would you)\s+", "", text)
    text = re.sub(r",?\s+(?:per favore|please|grazie|thanks)$", "", text)

    power = re.fullmatch(r"(accendi|accendere|spegni|spegnere)\s+(.+)", text)
    if power:
        return power[2], {"on": power[1] in {"accendi", "accendere"}}
    power = re.fullmatch(r"(?:turn|switch)\s+(on|off)\s+(.+)", text)
    if power:
        return power[2], {"on": power[1] == "on"}
    power = re.fullmatch(r"(?:turn|switch)\s+(.+?)\s+(on|off)", text)
    if power:
        return power[1], {"on": power[2] == "on"}

    text = re.sub(r"^(?:imposta|metti|porta|regola|set|dim|brighten)\s+", "", text)
    setting = re.fullmatch(r"(.+?)\s+(?:al|a|to)\s+(\d{1,5})\s*(%|percento|per cento|percent|kelvin|k)", text)
    if setting:
        target, number, unit = setting.groups()
        field = "brightness" if unit in {"%", "percento", "per cento", "percent"} else "temperature_kelvin"
        return target, {field: int(number)}
    color = re.fullmatch(r"(.+?)\s+(?:a|to)\s+(#[0-9a-f]{6})", text)
    if color:
        return color[1], {"color": color[2].upper()}
    return None


def matches_light_target(target: str, name: str, *, only_light: bool) -> bool:
    def clean(value):
        return re.sub(r"^(?:la|il|lo|the|my)\s+", "", words(value))

    target, name = clean(target), clean(name)
    nouns = {"luce", "lampada", "light", "lamp"}
    if only_light and target in nouns | {"luci", "lights"}:
        return True
    aliases = {name}
    for noun in nouns:
        aliases.add(f"{noun} {name}")
        for preposition in ("di", "della", "del", "in", "of", "in the"):
            aliases.add(f"{noun} {preposition} {name}")
    return target in aliases
