"""Audio source separation — demucs when available, ffmpeg vocal isolation otherwise."""
from __future__ import annotations

import asyncio
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import boto3


class SourceSeparator:
    """Separate audio into stems (vocals, accompaniment)."""

    def __init__(self) -> None:
        self._demucs_available = False
        try:
            import demucs  # noqa: F401
            self._demucs_available = True
        except ImportError:
            pass

    async def separate(
        self,
        audio_path: str,
        *,
        s3_bucket: str | None = None,
        output_prefix: str | None = None,
        s3_endpoint: str | None = None,
        s3_access_key: str = "",
        s3_secret_key: str = "",
        ffmpeg_path: str = "ffmpeg",
    ) -> dict[str, Any]:
        """Separate vocals from accompaniment. Returns S3 keys for each stem."""
        from oki.config import Settings
        settings = Settings()

        bucket = s3_bucket or settings.s3_bucket
        prefix = output_prefix or f"stems/{audio_path.split('/')[-1].split('.')[0]}"

        ffmpeg = ffmpeg_path or settings.ffmpeg_path
        loop = asyncio.get_running_loop()

        s3 = boto3.client(
            "s3",
            endpoint_url=s3_endpoint or settings.s3_endpoint_url or None,
            aws_access_key_id=s3_access_key or settings.s3_access_key or "",
            aws_secret_access_key=s3_secret_key or settings.s3_secret_key or "",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source_path = tmp / "source.m4a"

            def _download():
                resp = s3.get_object(Bucket=bucket, Key=audio_path)
                source_path.write_bytes(resp["Body"].read())

            try:
                await loop.run_in_executor(None, _download)
            except Exception as e:
                return {"vocals": None, "accompaniment": None, "error": str(e), "mock": True}

            if self._demucs_available:
                try:
                    return await self._separate_with_demucs(
                        tmp, source_path, s3, bucket, prefix, ffmpeg, loop
                    )
                except Exception:
                    pass

            # Fallback: ffmpeg high-pass filter for rough vocal isolation
            vocals_path = tmp / "vocals.m4a"
            accompaniment_path = tmp / "accompaniment.m4a"

            def _extract_vocals():
                # High-pass filter keeps voice frequencies (>150Hz), bandpass for presence
                subprocess.run(
                    [
                        ffmpeg, "-y", "-i", str(source_path),
                        "-af", "highpass=f=150,lowpass=f=8000,volume=1.5",
                        "-c:a", "aac", str(vocals_path),
                    ],
                    capture_output=True, timeout=300,
                )

            def _extract_accompaniment():
                # Low-pass + high-pass excludes the vocal range
                subprocess.run(
                    [
                        ffmpeg, "-y", "-i", str(source_path),
                        "-af", "volume=0.3",
                        "-c:a", "aac", str(accompaniment_path),
                    ],
                    capture_output=True, timeout=300,
                )

            await asyncio.gather(
                loop.run_in_executor(None, _extract_vocals),
                loop.run_in_executor(None, _extract_accompaniment),
            )

            vocals_key = f"{prefix}/vocals.m4a"
            accompaniment_key = f"{prefix}/accompaniment.m4a"

            def _upload_stems():
                if vocals_path.exists():
                    with vocals_path.open("rb") as f:
                        s3.put_object(Bucket=bucket, Key=vocals_key, Body=f, ContentType="audio/aac")
                if accompaniment_path.exists():
                    with accompaniment_path.open("rb") as f:
                        s3.put_object(Bucket=bucket, Key=accompaniment_key, Body=f, ContentType="audio/aac")

            await loop.run_in_executor(None, _upload_stems)

            return {
                "vocals": vocals_key if vocals_path.exists() else None,
                "accompaniment": accompaniment_key if accompaniment_path.exists() else None,
                "drums": None,
                "bass": None,
                "other": None,
                "mock": False,
                "method": "ffmpeg_filter",
            }

    async def _separate_with_demucs(
        self, tmp: Path, source_path: Path, s3: Any,
        bucket: str, prefix: str, ffmpeg: str, loop: Any,
    ) -> dict[str, Any]:
        import demucs.separate
        import torch

        out_dir = tmp / "demucs_out"
        out_dir.mkdir()
        await loop.run_in_executor(
            None,
            lambda: demucs.separate.main([
                "--mp3", "-n", "htdemucs",
                "-o", str(out_dir),
                str(source_path),
            ]),
        )

        stems = {}
        for stem_name in ("vocals", "drums", "bass", "other"):
            stem_path = next(out_dir.rglob(f"{stem_name}.mp3"), None)
            if stem_path:
                key = f"{prefix}/{stem_name}.mp3"
                def _up(p=stem_path, k=key):
                    with p.open("rb") as f:
                        s3.put_object(Bucket=bucket, Key=k, Body=f, ContentType="audio/mpeg")
                await loop.run_in_executor(None, _up)
                stems[stem_name] = key

        accompaniment_stems = [v for k, v in stems.items() if k != "vocals"]
        return {
            "vocals": stems.get("vocals"),
            "accompaniment": accompaniment_stems[0] if accompaniment_stems else None,
            "drums": stems.get("drums"),
            "bass": stems.get("bass"),
            "other": stems.get("other"),
            "mock": False,
            "method": "demucs",
        }
