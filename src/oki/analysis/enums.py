from enum import StrEnum


class AnalysisStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SegmentType(StrEnum):
    SPEECH = "speech"
    MUSIC = "music"
    NOISE = "noise"
    SILENCE = "silence"


class EvidenceType(StrEnum):
    AUDIO = "audio"
    VIDEO = "video"
    TEXT = "text"
    OCR = "ocr"
