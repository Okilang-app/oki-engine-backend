"""Unit tests for media probe validation logic."""

import pytest

from oki.media.ffprobe import ALLOWLISTED_AUDIO_CODECS, ALLOWLISTED_CONTAINERS, MediaProbe


def test_probe_parses_container_and_streams() -> None:
    probe = MediaProbe()
    data = {
        "format": {
            "format_name": "mp4,mov,m4a,3gp,3g2,mj2",
            "duration": "123.456",
            "bit_rate": "5000000",
            "size": "123456789",
        },
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "h264",
                "codec_long_name": "H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10",
                "bit_rate": "4500000",
                "width": 1920,
                "height": 1080,
            },
            {
                "index": 1,
                "codec_type": "audio",
                "codec_name": "aac",
                "codec_long_name": "AAC (Advanced Audio Coding)",
                "bit_rate": "256000",
                "sample_rate": "48000",
                "channels": 2,
                "tags": {"language": "eng"},
            },
        ],
    }
    container = probe.parse_container(data)
    assert container["container"] == "mp4"
    assert container["duration"] == 123.456
    assert container["bitrate"] == 5_000_000
    assert container["size_bytes"] == 123_456_789

    streams = probe.parse_streams(data)
    assert len(streams) == 2
    assert streams[0]["type"] == "video"
    assert streams[1]["type"] == "audio"
    assert streams[1]["sample_rate"] == 48000
    assert streams[1]["language"] == "eng"


def test_validate_codecs_allows_valid_mp4() -> None:
    probe = MediaProbe()
    data = {
        "format": {"format_name": "mp4", "duration": "60.0"},
        "streams": [
            {"index": 0, "codec_type": "video", "codec_name": "h264"},
            {"index": 1, "codec_type": "audio", "codec_name": "aac", "channels": 2},
        ],
    }
    result = probe.validate_codecs(data, require_audio=True)
    assert result["valid"] is True
    assert result["errors"] == []


def test_validate_codecs_rejects_bad_container() -> None:
    probe = MediaProbe()
    data = {
        "format": {"format_name": "avi", "duration": "60.0"},
        "streams": [
            {"index": 0, "codec_type": "video", "codec_name": "h264"},
            {"index": 1, "codec_type": "audio", "codec_name": "aac", "channels": 2},
        ],
    }
    result = probe.validate_codecs(data, require_audio=True)
    assert result["valid"] is False
    assert any("container_not_allowed" in e for e in result["errors"])


def test_validate_codecs_rejects_missing_audio() -> None:
    probe = MediaProbe()
    data = {
        "format": {"format_name": "mp4", "duration": "60.0"},
        "streams": [
            {"index": 0, "codec_type": "video", "codec_name": "h264"},
        ],
    }
    result = probe.validate_codecs(data, require_audio=True)
    assert result["valid"] is False
    assert "missing_audio_stream" in result["errors"]


def test_validate_codecs_rejects_unallowed_audio_codec() -> None:
    probe = MediaProbe()
    data = {
        "format": {"format_name": "mp4", "duration": "60.0"},
        "streams": [
            {"index": 0, "codec_type": "video", "codec_name": "h264"},
            {"index": 1, "codec_type": "audio", "codec_name": "vorbis", "channels": 2},
        ],
    }
    result = probe.validate_codecs(data, require_audio=True)
    assert result["valid"] is False
    assert any("audio_codec_not_allowed" in e for e in result["errors"])


def test_validate_codecs_rejects_unallowed_video_codec() -> None:
    probe = MediaProbe()
    data = {
        "format": {"format_name": "mp4", "duration": "60.0"},
        "streams": [
            {"index": 0, "codec_type": "video", "codec_name": "mpeg2video"},
            {"index": 1, "codec_type": "audio", "codec_name": "aac", "channels": 2},
        ],
    }
    result = probe.validate_codecs(data, require_audio=True)
    assert result["valid"] is False
    assert any("video_codec_not_allowed" in e for e in result["errors"])


def test_allowlisted_audio_codecs_contains_common_formats() -> None:
    assert "aac" in ALLOWLISTED_AUDIO_CODECS
    assert "opus" in ALLOWLISTED_AUDIO_CODECS
    assert "flac" in ALLOWLISTED_AUDIO_CODECS


def test_allowlisted_containers_contains_common_formats() -> None:
    assert "mp4" in ALLOWLISTED_CONTAINERS
    assert "mkv" in ALLOWLISTED_CONTAINERS
    assert "webm" in ALLOWLISTED_CONTAINERS
