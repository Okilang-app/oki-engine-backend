"""Asset validation service: virus scan, media probe, codec allow-list."""

import hashlib
import logging
from pathlib import Path
from typing import Any
from uuid import UUID

from oki.assets.enums import ValidationStatus
from oki.media.clamav import ClamAVScanner
from oki.media.ffprobe import ALLOWLISTED_AUDIO_CODECS, ALLOWLISTED_CONTAINERS, MediaProbe

logger = logging.getLogger(__name__)

VALIDATION_ERROR_CODES = {
    "container_not_allowed",
    "audio_codec_not_allowed",
    "video_codec_not_allowed",
    "missing_audio_stream",
    "clamav_threat_found",
    "clamav_unavailable",
    "ffprobe_failed",
    "sha256_mismatch",
    "file_too_small",
}


class AssetValidationService:
    """Run the full validation pipeline on a local file path."""

    def __init__(
        self,
        scanner: ClamAVScanner | None = None,
        probe: MediaProbe | None = None,
    ) -> None:
        self._scanner = scanner or ClamAVScanner()
        self._probe = probe or MediaProbe()

    async def validate(
        self,
        path: Path | str,
        *,
        expected_sha256: str | None = None,
        require_audio: bool = True,
    ) -> dict[str, Any]:
        """Run validation and return a structured result dict.

        Steps:
        1. ClamAV scan
        2. SHA-256 computation
        3. ffprobe media inspection
        4. Codec allow-list check
        5. Audio stream requirement
        """
        path = Path(path)
        errors: list[str] = []
        details: dict[str, Any] = {}

        # 1. Virus scan
        try:
            scan_result = await self._scanner.scan(path)
            if not scan_result.get("clean", True):
                errors.append("clamav_threat_found")
                details["threats"] = scan_result.get("threats", [])
        except Exception as exc:
            logger.warning("ClamAV scan failed: %s", exc)
            errors.append("clamav_unavailable")

        # 2. SHA-256
        computed_sha256 = ""
        try:
            computed_sha256 = self._compute_sha256(path)
            details["sha256_computed"] = computed_sha256
            if expected_sha256 is not None:
                if computed_sha256.lower() != expected_sha256.lower():
                    errors.append("sha256_mismatch")
        except Exception as exc:
            logger.warning("SHA-256 computation failed: %s", exc)
            errors.append("sha256_mismatch")

        # 3. Media probe
        probe_data: dict[str, Any] | None = None
        try:
            probe_data = await self._probe.probe(path)
            details["probe"] = self._probe.parse_container(probe_data)
            details["streams"] = self._probe.parse_streams(probe_data)
        except Exception as exc:
            logger.warning("ffprobe failed: %s", exc)
            errors.append("ffprobe_failed")

        # 4. Codec validation
        if probe_data is not None:
            codec_result = self._probe.validate_codecs(probe_data, require_audio=require_audio)
            details["codec_validation"] = codec_result
            if not codec_result["valid"]:
                errors.extend(codec_result["errors"])

        status = ValidationStatus.PASSED if not errors else ValidationStatus.FAILED
        return {
            "status": status,
            "sha256_computed": computed_sha256,
            "error_codes": errors,
            "details": details,
        }

    @staticmethod
    def _compute_sha256(path: Path) -> str:
        """Stream-hash a file with SHA-256."""
        h = hashlib.sha256()
        with path.open("rb") as f:
            while chunk := f.read(8192):
                h.update(chunk)
        return h.hexdigest()
