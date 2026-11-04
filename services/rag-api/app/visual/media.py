"""Bounded, offline decoding. A playable file is not semantic qualification."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path


class MediaValidationError(ValueError):
    pass


@dataclass(frozen=True)
class VideoSample:
    seconds: float
    sha256: str
    png: bytes


@dataclass(frozen=True)
class VideoInspection:
    width: int
    height: int
    fps: float
    frame_count: int
    duration_seconds: float
    audio_streams: int
    sha256: str
    samples: tuple[VideoSample, ...]
    semantic_review: str = "PENDING_NOT_PROVEN_BY_DECODE"


def wan_frames(duration: float, *, fps: int = 24) -> int:
    if not math.isfinite(duration) or not 3 <= duration <= 5 or fps != 24:
        raise MediaValidationError("WAN_BOUNDED_DURATION_INVALID")
    return 4 * math.ceil(duration * fps / 4) + 1


def _run(arguments: list[str], *, timeout: int = 60) -> bytes:
    try:
        result = subprocess.run(arguments, capture_output=True, timeout=timeout, check=True)
    except (OSError, subprocess.SubprocessError):
        raise MediaValidationError("MEDIA_DECODE_FAILED") from None
    return result.stdout


def inspect_video(
    content: bytes,
    *,
    mime_type: str,
    max_bytes: int,
    max_width: int,
    max_height: int,
    max_duration: float,
) -> VideoInspection:
    if not content or len(content) > max_bytes or mime_type not in {"video/mp4", "video/webm"}:
        raise MediaValidationError("MEDIA_SIZE_OR_TYPE_INVALID")
    if mime_type == "video/mp4" and (len(content) < 16 or content[4:8] != b"ftyp"):
        raise MediaValidationError("MEDIA_MAGIC_INVALID")
    if mime_type == "video/webm" and content[:4] != b"\x1a\x45\xdf\xa3":
        raise MediaValidationError("MEDIA_MAGIC_INVALID")
    ffprobe, ffmpeg = shutil.which("ffprobe"), shutil.which("ffmpeg")
    if not ffprobe or not ffmpeg:
        raise MediaValidationError("MEDIA_DECODER_NOT_AVAILABLE")
    with tempfile.TemporaryDirectory(prefix="coursejesus-media-") as directory:
        path = Path(directory) / ("clip.mp4" if mime_type == "video/mp4" else "clip.webm")
        path.write_bytes(content)
        try:
            metadata = json.loads(
                _run(
                    [
                        ffprobe,
                        "-v",
                        "error",
                        "-protocol_whitelist",
                        "file,pipe",
                        "-show_entries",
                        "format=duration:stream=codec_type,codec_name,width,height,avg_frame_rate,nb_frames,duration",
                        "-of",
                        "json",
                        str(path),
                    ]
                )
            )
            videos = [stream for stream in metadata["streams"] if stream["codec_type"] == "video"]
            audio = sum(stream["codec_type"] == "audio" for stream in metadata["streams"])
            if len(videos) != 1 or audio:
                raise MediaValidationError("MEDIA_STREAMS_INVALID")
            video = videos[0]
            width, height = int(video["width"]), int(video["height"])
            fps = float(Fraction(video["avg_frame_rate"]))
            reported_frames = int(video.get("nb_frames") or 0)
            duration = float(video.get("duration") or metadata["format"]["duration"])
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            raise MediaValidationError("MEDIA_METADATA_INVALID") from None
        if (
            not 1 <= width <= max_width
            or not 1 <= height <= max_height
            or not 1 <= fps <= 60
            or not 0 < duration <= max_duration
            or reported_frames > 901
            or width * height * math.ceil(duration * fps + 1) > 400_000_000
            or video["codec_name"] not in {"h264", "vp9", "av1"}
        ):
            raise MediaValidationError("MEDIA_GEOMETRY_OR_DURATION_INVALID")
        checksums = _run(
            [
                ffmpeg,
                "-v",
                "error",
                "-xerror",
                "-protocol_whitelist",
                "file,pipe",
                "-i",
                str(path),
                "-map",
                "0:v:0",
                "-an",
                "-f",
                "framemd5",
                "-",
            ],
            timeout=120,
        ).decode()
        frame_digests = [
            line.rsplit(",", 1)[-1].strip()
            for line in checksums.splitlines()
            if line and not line.startswith("#")
        ]
        frames = len(frame_digests)
        if (
            frames < 2
            or frames > 901
            or (reported_frames and frames != reported_frames)
            or width * height * frames > 400_000_000
            or len(set(frame_digests)) < 2
        ):
            raise MediaValidationError("MEDIA_STATIC_OR_INCOMPLETE_CLIP")
        samples = []
        for index in range(5):
            seconds = (duration - 1 / fps) * index / 4
            png = _run(
                [
                    ffmpeg,
                    "-v",
                    "error",
                    "-xerror",
                    "-protocol_whitelist",
                    "file,pipe",
                    "-i",
                    str(path),
                    "-ss",
                    str(max(0, seconds)),
                    "-frames:v",
                    "1",
                    "-an",
                    "-f",
                    "image2pipe",
                    "-vcodec",
                    "png",
                    "-",
                ]
            )
            if not png.startswith(b"\x89PNG\r\n\x1a\n"):
                raise MediaValidationError("MEDIA_SAMPLE_DECODE_FAILED")
            samples.append(VideoSample(seconds, hashlib.sha256(png).hexdigest(), png))
    return VideoInspection(
        width,
        height,
        fps,
        frames,
        duration,
        audio,
        hashlib.sha256(content).hexdigest(),
        tuple(samples),
    )
