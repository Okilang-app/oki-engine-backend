"""Real ffmpeg-based audio mixer."""
from __future__ import annotations

import asyncio
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import boto3


class AudioMixer:
    """Execute audio mix via ffmpeg: replace speech track, preserve music/ambience."""

    def __init__(self, output_bucket: str, s3_endpoint: str | None = None) -> None:
        self._output_bucket = output_bucket
        self._s3_endpoint = s3_endpoint

    async def mix_async(
        self,
        *,
        dialogue_key: str,
        source_key: str,
        output_key: str,
        music_keys: list[str] | None = None,
        target_loudness_lufs: float = -14.0,
        dialogue_gain_db: float = 0.0,
        ambient_volume: float = 0.2,
        s3_access_key: str = "",
        s3_secret_key: str = "",
        ffmpeg_path: str = "ffmpeg",
    ) -> dict[str, Any]:
        """Download stems, mix with ffmpeg, upload master audio."""
        from oki.config import Settings
        settings = Settings()

        s3 = boto3.client(
            "s3",
            endpoint_url=self._s3_endpoint or None,
            aws_access_key_id=s3_access_key or settings.s3_access_key or "",
            aws_secret_access_key=s3_secret_key or settings.s3_secret_key or "",
        )

        loop = asyncio.get_running_loop()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            dialogue_path = tmp / "dialogue.m4a"
            source_path = tmp / "source.mp4"
            output_path = tmp / "mixed.m4a"

            def _dl_dialogue():
                resp = s3.get_object(Bucket=self._output_bucket, Key=dialogue_key)
                dialogue_path.write_bytes(resp["Body"].read())

            def _dl_source():
                resp = s3.get_object(Bucket=self._output_bucket, Key=source_key)
                source_path.write_bytes(resp["Body"].read())

            await asyncio.gather(
                loop.run_in_executor(None, _dl_dialogue),
                loop.run_in_executor(None, _dl_source),
            )

            # Extract ambient/music track from source (everything except vocals)
            ambient_path = tmp / "ambient.m4a"
            has_separate_music = bool(music_keys)

            # No ambient bed is built from the source here. The source track is
            # the full original mix, dialogue included, so laying it under the
            # dub just replays the original speech beneath the translation —
            # only a real instrumental stem (music_keys) may be bedded.

            # Mix dialogue + ambient with loudness normalization
            import math as _math
            d_vol = 10 ** (dialogue_gain_db / 20.0) if dialogue_gain_db != 0.0 else 1.0
            _limiter = "alimiter=limit=0.841:level=0:attack=5:release=50"

            if has_separate_music and music_keys:
                music_path = tmp / "music.m4a"
                def _dl_music():
                    resp = s3.get_object(Bucket=self._output_bucket, Key=music_keys[0])
                    music_path.write_bytes(resp["Body"].read())
                await loop.run_in_executor(None, _dl_music)
                mix_inputs = ["-i", str(dialogue_path), "-i", str(music_path)]
                filter_graph = (
                    f"[0:a]volume={d_vol:.4f}[d];"
                    f"[1:a]volume={ambient_volume:.4f}[m];"
                    f"[d][m]amix=inputs=2:duration=longest[out];"
                    f"[out]loudnorm=I={target_loudness_lufs}:TP=-1.5:LRA=11,{_limiter}[final]"
                )
            elif ambient_path.exists():
                mix_inputs = ["-i", str(dialogue_path), "-i", str(ambient_path)]
                filter_graph = (
                    f"[0:a]volume={d_vol:.4f}[d];"
                    f"[1:a]volume={ambient_volume:.4f}[m];"
                    f"[d][m]amix=inputs=2:duration=longest[out];"
                    f"[out]loudnorm=I={target_loudness_lufs}:TP=-1.5:LRA=11,{_limiter}[final]"
                )
            else:
                mix_inputs = ["-i", str(dialogue_path)]
                filter_graph = f"[0:a]volume={d_vol:.4f},loudnorm=I={target_loudness_lufs}:TP=-1.5:LRA=11,{_limiter}[final]"

            def _mix():
                return subprocess.run(
                    [
                        ffmpeg_path, "-y",
                        *mix_inputs,
                        "-filter_complex", filter_graph,
                        "-map", "[final]",
                        "-c:a", "aac", "-b:a", "192k",
                        str(output_path),
                    ],
                    capture_output=True, timeout=600,
                )

            result = await loop.run_in_executor(None, _mix)
            if result.returncode != 0:
                raise RuntimeError(
                    f"ffmpeg mix failed: {result.stderr.decode()[-500:]}"
                )

            file_size = output_path.stat().st_size

            def _upload():
                with output_path.open("rb") as f:
                    s3.put_object(
                        Bucket=self._output_bucket,
                        Key=output_key,
                        Body=f,
                        ContentType="audio/aac",
                    )

            await loop.run_in_executor(None, _upload)

        return {
            "output_key": output_key,
            "file_size_bytes": file_size,
            "target_loudness_lufs": target_loudness_lufs,
            "steps": ["normalize_dialogue", "mix_ambient", "loudnorm", "upload"],
            "mock": False,
        }

    def mix(
        self,
        *,
        dialogue_tracks: list[dict[str, Any]],
        music_stems: list[dict[str, Any]],
        sfx_stems: list[dict[str, Any]],
        target_loudness_lufs: float = -14.0,
    ) -> dict[str, Any]:
        """Produce a mix plan (synchronous, for backward compat with tasks.py)."""
        return {
            "dialogue_tracks": dialogue_tracks,
            "music_stems": music_stems,
            "sfx_stems": sfx_stems,
            "target_loudness_lufs": target_loudness_lufs,
            "steps": [
                "normalize_dialogue",
                "duck_music",
                "mix_sfx",
                "render_master",
            ],
            "mock": not bool(dialogue_tracks),
        }
