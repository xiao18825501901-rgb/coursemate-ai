import shutil
import subprocess

import pytest

from app.visual.media import MediaValidationError, inspect_video, wan_frames


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg, "ffmpeg is required for real offline media validation (no fake PASS)"
    directory = tmp_path_factory.mktemp("visual-video")
    target = directory / "synthetic-contract-only.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x96:rate=24",
            "-t",
            "3.04",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(target),
        ],
        check=True,
        timeout=30,
    )
    return target.read_bytes()


def test_actual_mp4_decode_stream_frames_no_audio_and_checksum(clip):
    result = inspect_video(
        clip,
        mime_type="video/mp4",
        max_bytes=2_000_000,
        max_width=512,
        max_height=512,
        max_duration=5,
    )
    assert result.width == 160 and result.height == 96
    assert result.fps == 24 and result.frame_count >= 72
    assert 3 <= result.duration_seconds <= 3.2
    assert result.audio_streams == 0 and len(result.sha256) == 64
    assert len(result.samples) == 5
    assert len({sample.sha256 for sample in result.samples}) > 1
    assert result.semantic_review == "PENDING_NOT_PROVEN_BY_DECODE"


@pytest.mark.parametrize("content", [b"", b"\x89PNG\r\n\x1a\n" + b"0" * 256, b"fake MP4"])
def test_png_or_garbage_cannot_be_relabelled_video(content):
    with pytest.raises(MediaValidationError):
        inspect_video(
            content,
            mime_type="video/mp4",
            max_bytes=2_000_000,
            max_width=512,
            max_height=512,
            max_duration=5,
        )


def test_oversized_or_truncated_clip_fails_decode(clip):
    with pytest.raises(MediaValidationError):
        inspect_video(
            clip, mime_type="video/mp4", max_bytes=10, max_width=512, max_height=512, max_duration=5
        )
    with pytest.raises(MediaValidationError):
        inspect_video(
            clip[:64],
            mime_type="video/mp4",
            max_bytes=2_000_000,
            max_width=512,
            max_height=512,
            max_duration=5,
        )


def test_wan_length_rounds_to_model_4n_plus_1_not_legacy_eight_fps():
    assert wan_frames(3, fps=24) == 73
    assert wan_frames(4, fps=24) == 97
    assert wan_frames(5, fps=24) == 121
    with pytest.raises(MediaValidationError):
        wan_frames(20, fps=24)


def test_decoded_video_persists_through_the_existing_visual_service(clip, tmp_path):
    from test_visual_service import make_service, request

    from app.visual.providers.base import ProviderResult

    service, provider = make_service(tmp_path, visual_video_enabled=True)
    provider.get_result = lambda _job: ProviderResult(
        content=clip,
        mime_type="video/mp4",
        width=None,
        height=None,
        duration_seconds=None,
        model_version="offline-transport-fixture",
    )
    job, _ = service.create_job(request(question="Explain how two gears transfer motion"))
    completed = service.run_once("video-test-worker")
    assert completed["status"] == "COMPLETED"
    asset = service.store.assets_for_job(str(job["id"]), user_id="user-1")[0]
    assert asset["type"] == "VIDEO" and asset["mime_type"] == "video/mp4"
    assert asset["storage_key"].endswith(".mp4")
    assert (asset["width"], asset["height"]) == (160, 96)
    assert 3 <= asset["duration_seconds"] <= 3.2
    assert service.storage.read_range(asset["storage_key"], start=0, end=len(clip) - 1) == clip


def test_video_asset_alt_text_matches_the_single_shot_contract(clip, tmp_path):
    from test_visual_service import make_service, request
    from test_visual_spec_router import valid_spec

    from app.visual.api import _project
    from app.visual.planner import load_runtime_prompt
    from app.visual.providers.base import ProviderResult
    from app.visual.spec import VisualSpec

    class FrozenVideoPlanner:
        prompt = load_runtime_prompt()

        def plan(self, **_kwargs):
            return VisualSpec.model_validate(
                valid_spec(
                    visual_type="VIDEO",
                    renderer="COMFY_VIDEO",
                    semantic_precision="ILLUSTRATIVE",
                    motion_is_essential=True,
                    duration_seconds=3,
                    diagram=None,
                    source_grounding=[
                        {
                            "source_id": "document-1",
                            "source_version": "version-1",
                            "locator": "page 1",
                            "supported_claim": "The platter rotates while the arm moves radially.",
                        }
                    ],
                    visual_goal=(
                        "单个硬盘盘片连续旋转，执行器臂同时做一次有边界的径向移动，"
                        "硬盘主体保持固定，并通过分段呈现区分两种运动。"
                    ),
                    must_include=[
                        "单个固定硬盘主体",
                        "圆形盘片连续旋转",
                        "执行器臂做一次有边界的径向移动",
                    ],
                )
            )

    service, provider = make_service(tmp_path, visual_video_enabled=True)
    service.planner = FrozenVideoPlanner()
    provider.get_result = lambda _job: ProviderResult(
        content=clip,
        mime_type="video/mp4",
        width=None,
        height=None,
        duration_seconds=None,
        model_version="offline-transport-fixture",
    )

    job, _ = service.create_job(request(question="Explain HDD motion"))
    completed = service.run_once("video-alt-text-worker")

    assert completed["status"] == "COMPLETED", (
        completed.get("error_code"),
        completed.get("error_detail_safe"),
    )
    asset = service.store.assets_for_job(str(job["id"]), user_id="user-1")[0]
    assert "连续旋转" in asset["alt_text"]
    assert "径向移动" in asset["alt_text"]
    assert "分段呈现" not in asset["alt_text"]

    with service.store.database.connect() as connection:
        connection.execute(
            "UPDATE visual_assets SET alt_text=? WHERE id=?",
            (asset["alt_text"] + "，并通过分段呈现区分两种运动。", asset["id"]),
        )
    projected = _project(service, service.store.get(str(job["id"])), user_id="user-1")
    assert "分段呈现" not in projected["assets"][0]["alt_text"]
