"""Hatchet task stubs for analysis pipeline.

TODO: wire to actual Hatchet worker decorators once the Hatchet SDK is integrated.
"""

from uuid import UUID


async def transcription_task(job_id: UUID, asset_id: UUID) -> dict:
    """Run audio transcription for an asset.

    TODO: call OpenAITranscriptionClient.
    """
    return {
        "task": "transcription",
        "job_id": str(job_id),
        "asset_id": str(asset_id),
        "status": "pending",
    }


async def diarization_task(job_id: UUID, asset_id: UUID) -> dict:
    """Run speaker diarization for an asset.

    TODO: integrate speaker diarization model.
    """
    return {
        "task": "diarization",
        "job_id": str(job_id),
        "asset_id": str(asset_id),
        "status": "pending",
    }


async def scene_detection_task(job_id: UUID, asset_id: UUID) -> dict:
    """Run visual scene detection for an asset.

    TODO: integrate scene/chapter detection model.
    """
    return {
        "task": "scene_detection",
        "job_id": str(job_id),
        "asset_id": str(asset_id),
        "status": "pending",
    }


async def ocr_task(job_id: UUID, asset_id: UUID) -> dict:
    """Run OCR for on-screen text in an asset.

    TODO: integrate OCR engine.
    """
    return {
        "task": "ocr",
        "job_id": str(job_id),
        "asset_id": str(asset_id),
        "status": "pending",
    }


async def sponsor_candidate_detection_task(job_id: UUID, asset_id: UUID) -> dict:
    """Run sponsor candidate detection from transcript and audio cues.

    TODO: integrate StubSponsorDetector or real detection pipeline.
    """
    return {
        "task": "sponsor_candidate_detection",
        "job_id": str(job_id),
        "asset_id": str(asset_id),
        "status": "pending",
    }
