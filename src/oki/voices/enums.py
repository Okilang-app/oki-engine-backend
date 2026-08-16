from enum import StrEnum


class VoiceMode(StrEnum):
    LICENSED_NEUTRAL_VOICE = "licensed_neutral_voice"
    CREATOR_APPROVED_CLONE = "creator_approved_clone"
    HUMAN_VOICE_ACTOR = "human_voice_actor"
