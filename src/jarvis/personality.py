"""Shared conversational preferences for chat and Live voice."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

Score = Annotated[int, Field(ge=0, le=100)]


class PersonalityProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    enabled: bool = False
    humor: Score = 20
    irony: Score = 10
    professionalism: Score = 70
    warmth: Score = 60
    conciseness: Score = 70


def personality_instructions(profile: PersonalityProfile, *, spoken: bool = False) -> str:
    if not profile.enabled:
        return ""

    return (
        "\nConversation style for replies to the owner. Each preference is on a 0–100 scale.\n"
        f"- Humor {profile.humor}/100: from no jokes to playful humor where it fits.\n"
        f"- Irony {profile.irony}/100: from literal phrasing to dry wit and understatement.\n"
        f"- Professionalism {profile.professionalism}/100: from casual to formal and structured.\n"
        f"- Warmth {profile.warmth}/100: from matter-of-fact to friendly and expressive.\n"
        f"- Conciseness {profile.conciseness}/100: from developed explanations to essentials first.\n"
        "Follow the owner's explicit style requests. Use humor and irony only when the context suits "
        "them. Keep urgent or sensitive replies, progress updates and approval prompts direct. "
        "Preserve accuracy, evidence, required detail and exact readbacks. For drafts and code, follow "
        "the requested audience and format.\n"
        + (
            "Express the selected style with natural pacing and emphasis within the chosen vocal identity.\n"
            if spoken
            else ""
        )
    )
