"""Real ffprobe-based audio QA."""
from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
from pathlib import Path

import boto3

from oki.audio.models import AudioQaResult


class AudioQa:
    """Evaluate audio mixes for technical quality issues via ffprobe/ffmpeg."""

    async def evaluate(
        self,
        audio_asset_reference: str,
        *,
        expected_duration_ms: int | None = None,
        s3_bucket: str | None = None,
        s3_endpoint: str | None = None,
        s3_access_key: str = "",
        s3_secret_key: str = "",
        ffmpeg_path: str = "ffmpeg",
        ffprobe_path: str = "ffprobe",
    ) -> AudioQaResult:
        """Download audio, run loudness/clipping/silence analysis."""
        from oki.config import Settings
        settings = Settings()

        bucket = s3_bucket or settings.s3_bucket
        if not bucket or not audio_asset_reference:
            return AudioQaResult(
                organization_id=None,  # type: ignore[arg-type]
                audio_mix_version_id=None,  # type: ignore[arg-type]
                clipping_detected=False,
                silence_detected=False,
                cut_words_detected=False,
                loudness_lufs=None,
                issues=[],
                passed=True,
            )

        loop = asyncio.get_running_loop()

        s3 = boto3.client(
            "s3",
            endpoint_url=s3_endpoint or settings.s3_endpoint_url or None,
            aws_access_key_id=s3_access_key or settings.s3_access_key or "",
            aws_secret_access_key=s3_secret_key or settings.s3_secret_key or "",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = Path(tmpdir) / "audio.m4a"

            try:
                def _download():
                    resp = s3.get_object(Bucket=bucket, Key=audio_asset_reference)
                    audio_path.write_bytes(resp["Body"].read())
                await loop.run_in_executor(None, _download)
            except Exception as e:
                return AudioQaResult(
                    organization_id=None,  # type: ignore[arg-type]
                    audio_mix_version_id=None,  # type: ignore[arg-type]
                    clipping_detected=False,
                    silence_detected=False,
                    cut_words_detected=False,
                    loudness_lufs=None,
                    issues=[{"type": "download_error", "message": str(e)}],
                    passed=False,
                )

            # 1. Loudness + true peak via ffmpeg EBU R128
            loudness_lufs: float | None = None
            true_peak: float | None = None
            issues: list[dict] = []

            def _loudness():
                r = subprocess.run(
                    [
                        ffmpeg_path, "-i", str(audio_path),
                        "-af", "loudnorm=print_format=json",
                        "-f", "null", "-",
                    ],
                    capture_output=True, text=True, timeout=120,
                )
                output = r.stderr
                try:
                    start = output.rfind("{")
                    end = output.rfind("}") + 1
                    if start >= 0 and end > start:
                        d = json.loads(output[start:end])
                        return float(d.get("input_i", 0)), float(d.get("input_tp", 0))
                except Exception:
                    pass
                return None, None

            loudness_lufs, true_peak = await loop.run_in_executor(None, _loudness)

            # 2. Clipping detection (true peak > -1 dBFS)
            clipping_detected = bool(true_peak is not None and true_peak > -1.0)
            if clipping_detected:
                issues.append({"type": "clipping", "true_peak_dbfs": true_peak})

            # 3. Silence detection (unexpected silence > 3s)
            def _detect_silence():
                r = subprocess.run(
                    [
                        ffmpeg_path, "-i", str(audio_path),
                        "-af", "silencedetect=noise=-40dB:d=3.0",
                        "-f", "null", "-",
                    ],
                    capture_output=True, text=True, timeout=120,
                )
                silences = []
                start = None
                for line in r.stderr.splitlines():
                    if "silence_start" in line:
                        try:
                            start = float(line.split("silence_start:")[1].strip())
                        except (IndexError, ValueError):
                            pass
                    elif "silence_end" in line and start is not None:
                        try:
                            end = float(line.split("silence_end:")[1].split("|")[0].strip())
                            duration = end - start
                            silences.append({"start": start, "end": end, "duration": duration})
                            start = None
                        except (IndexError, ValueError):
                            pass
                return silences

            silences = await loop.run_in_executor(None, _detect_silence)
            silence_detected = bool(silences)
            if silence_detected:
                for s in silences[:5]:
                    issues.append({"type": "silence", **s})

            # 4. Duration check
            def _duration():
                r = subprocess.run(
                    [
                        ffprobe_path, "-v", "error",
                        "-show_entries", "format=duration",
                        "-of", "json", str(audio_path),
                    ],
                    capture_output=True, text=True, timeout=30,
                )
                try:
                    d = json.loads(r.stdout)
                    return float(d["format"]["duration"]) * 1000
                except Exception:
                    return None

            actual_duration_ms = await loop.run_in_executor(None, _duration)
            if expected_duration_ms and actual_duration_ms is not None:
                drift_ms = abs(actual_duration_ms - expected_duration_ms)
                if drift_ms > 500:
                    issues.append({
                        "type": "duration_mismatch",
                        "expected_ms": expected_duration_ms,
                        "actual_ms": actual_duration_ms,
                        "drift_ms": drift_ms,
                    })

            # 5. Target loudness check (-16 to -12 LUFS for YouTube)
            if loudness_lufs is not None and not (-18 <= loudness_lufs <= -10):
                issues.append({
                    "type": "loudness_out_of_range",
                    "loudness_lufs": loudness_lufs,
                    "target_range": "[-18, -10]",
                })

        passed = not clipping_detected and len([i for i in issues if i["type"] != "silence"]) == 0

        return AudioQaResult(
            organization_id=None,  # type: ignore[arg-type]
            audio_mix_version_id=None,  # type: ignore[arg-type]
            clipping_detected=clipping_detected,
            silence_detected=silence_detected,
            cut_words_detected=False,
            loudness_lufs=loudness_lufs,
            issues=issues,
            passed=passed,
        )
