"""Tests for the video assembly module: plan, validation, assembler helpers."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from app.video.plan import AssemblyClip, AssemblyPlan
from app.video.assembler import (
    AssemblyValidationError,
    build_plan,
    check_duration_drift,
    concat_clips,
    mux_audio,
    render,
    validate_state,
    write_concat_list,
    DRIFT_TOLERANCE_MS,
)
from app.tools.video_tool import VideoAssemblyTool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_asset(
    path: str = "/tmp/c.mp4",
    section: str = "hook",
    chunk_index: int = 0,
    start_ms: int = 0,
    end_ms: int = 1000,
    duration_ms: int = 1000,
    **extra,
) -> dict:
    return {
        "path": path,
        "section": section,
        "chunk_index": chunk_index,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "duration_ms": duration_ms,
        "asset_type": "clip",
        "provider": "stub",
        "width": 1080,
        "height": 1920,
        "prompt": None,
        "source_url": None,
        **extra,
    }


def _stub_clip(tmp_path: Path, name: str = "clip.mp4") -> str:
    """Create a tiny file acting as a clip stub."""
    p = tmp_path / name
    p.write_bytes(b"\x00" * 64)
    return str(p)


def _stub_audio(tmp_path: Path, name: str = "audio.mp3") -> str:
    """Create a tiny file acting as an audio stub."""
    p = tmp_path / name
    p.write_bytes(b"\x00" * 64)
    return str(p)


# ===================================================================
# AssemblyClip / AssemblyPlan unit tests
# ===================================================================


class TestAssemblyClip:
    def test_duration_s(self):
        clip = AssemblyClip(
            path="/tmp/c.mp4",
            section="hook",
            chunk_index=0,
            start_ms=0,
            end_ms=2500,
            duration_ms=2500,
        )
        assert clip.duration_s == 2.5

    def test_zero_duration(self):
        clip = AssemblyClip(
            path="/tmp/c.mp4",
            section="body",
            chunk_index=0,
            start_ms=0,
            end_ms=0,
            duration_ms=0,
        )
        assert clip.duration_s == 0.0


class TestAssemblyPlan:
    def test_total_visual_duration_ms(self):
        clips = [
            AssemblyClip("/a.mp4", "hook", 0, 0, 1000, 1000),
            AssemblyClip("/b.mp4", "body", 0, 1000, 3000, 2000),
        ]
        plan = AssemblyPlan(clips=clips, audio_path="/a.mp3", output_key="j/v.mp4")
        assert plan.total_visual_duration_ms == 3000

    def test_empty_clips_duration(self):
        plan = AssemblyPlan()
        assert plan.total_visual_duration_ms == 0


# ===================================================================
# build_plan tests
# ===================================================================


class TestBuildPlan:
    def test_deterministic_ordering_by_start_ms(self, tmp_path):
        c1 = _stub_clip(tmp_path, "c1.mp4")
        c2 = _stub_clip(tmp_path, "c2.mp4")
        c3 = _stub_clip(tmp_path, "c3.mp4")
        state = {
            "job_id": "j1",
            "audio_path": _stub_audio(tmp_path),
            "visual_assets": [
                _make_asset(path=c2, section="body", chunk_index=0, start_ms=1000, end_ms=2000, duration_ms=1000),
                _make_asset(path=c3, section="cta", chunk_index=0, start_ms=2000, end_ms=3000, duration_ms=1000),
                _make_asset(path=c1, section="hook", chunk_index=0, start_ms=0, end_ms=1000, duration_ms=1000),
            ],
        }
        plan = build_plan(state)
        assert [c.section for c in plan.clips] == ["hook", "body", "cta"]

    def test_deterministic_ordering_by_chunk_index(self, tmp_path):
        c1 = _stub_clip(tmp_path, "c1.mp4")
        c2 = _stub_clip(tmp_path, "c2.mp4")
        state = {
            "job_id": "j1",
            "audio_path": _stub_audio(tmp_path),
            "visual_assets": [
                _make_asset(path=c2, section="body", chunk_index=1, start_ms=0, end_ms=1000, duration_ms=1000),
                _make_asset(path=c1, section="body", chunk_index=0, start_ms=0, end_ms=1000, duration_ms=1000),
            ],
        }
        plan = build_plan(state)
        assert [c.chunk_index for c in plan.clips] == [0, 1]

    def test_output_key_uses_job_id(self, tmp_path):
        state = {
            "job_id": "abc123",
            "audio_path": _stub_audio(tmp_path),
            "visual_assets": [_make_asset(path=_stub_clip(tmp_path))],
        }
        plan = build_plan(state)
        assert plan.output_key == "abc123/video.mp4"

    def test_audio_duration_ms_carried(self, tmp_path):
        state = {
            "job_id": "j1",
            "audio_path": _stub_audio(tmp_path),
            "audio_duration_ms": 5000,
            "visual_assets": [_make_asset(path=_stub_clip(tmp_path))],
        }
        plan = build_plan(state)
        assert plan.audio_duration_ms == 5000

    def test_audio_duration_ms_none_when_absent(self, tmp_path):
        state = {
            "job_id": "j1",
            "audio_path": _stub_audio(tmp_path),
            "visual_assets": [_make_asset(path=_stub_clip(tmp_path))],
        }
        plan = build_plan(state)
        assert plan.audio_duration_ms is None


# ===================================================================
# validate_state tests
# ===================================================================


class TestValidateState:
    def test_empty_visual_assets_raises(self, tmp_path):
        state = {"visual_assets": [], "audio_path": _stub_audio(tmp_path)}
        with pytest.raises(AssemblyValidationError, match="visual_assets is empty"):
            validate_state(state)

    def test_missing_visual_assets_raises(self, tmp_path):
        state = {"audio_path": _stub_audio(tmp_path)}
        with pytest.raises(AssemblyValidationError, match="visual_assets is empty"):
            validate_state(state)

    def test_missing_audio_path_raises(self, tmp_path):
        state = {"visual_assets": [_make_asset(path=_stub_clip(tmp_path))]}
        with pytest.raises(AssemblyValidationError, match="audio_path is missing"):
            validate_state(state)

    def test_audio_path_not_a_file_raises(self, tmp_path):
        state = {
            "visual_assets": [_make_asset(path=_stub_clip(tmp_path))],
            "audio_path": "/nonexistent/audio.mp3",
        }
        with pytest.raises(AssemblyValidationError, match="audio_path does not exist"):
            validate_state(state)

    def test_malformed_asset_missing_key_raises(self, tmp_path):
        bad_asset = {"path": _stub_clip(tmp_path)}  # missing section, chunk_index, etc.
        state = {
            "visual_assets": [bad_asset],
            "audio_path": _stub_audio(tmp_path),
        }
        with pytest.raises(AssemblyValidationError, match="missing required key"):
            validate_state(state)

    def test_asset_path_not_a_file_raises(self, tmp_path):
        state = {
            "visual_assets": [_make_asset(path="/nonexistent/clip.mp4")],
            "audio_path": _stub_audio(tmp_path),
        }
        with pytest.raises(AssemblyValidationError, match="does not exist"):
            validate_state(state)

    def test_valid_state_passes(self, tmp_path):
        state = {
            "visual_assets": [_make_asset(path=_stub_clip(tmp_path))],
            "audio_path": _stub_audio(tmp_path),
        }
        validate_state(state)  # should not raise


# ===================================================================
# write_concat_list tests
# ===================================================================


class TestWriteConcatList:
    def test_header_and_entries(self, tmp_path):
        clips = [
            AssemblyClip("/a.mp4", "hook", 0, 0, 1000, 1000),
            AssemblyClip("/b.mp4", "body", 0, 1000, 3000, 2000),
        ]
        dest = tmp_path / "list.txt"
        write_concat_list(clips, dest)
        content = dest.read_text()
        assert content.startswith("ffconcat version 1.0\n")
        assert "file '/a.mp4'" in content
        assert "duration 1.000" in content
        assert "file '/b.mp4'" in content
        assert "duration 2.000" in content

    def test_path_ordering_preserved(self, tmp_path):
        clips = [
            AssemblyClip("/first.mp4", "hook", 0, 0, 500, 500),
            AssemblyClip("/second.mp4", "body", 0, 500, 1500, 1000),
        ]
        dest = tmp_path / "list.txt"
        write_concat_list(clips, dest)
        lines = dest.read_text().splitlines()
        file_lines = [line for line in lines if line.startswith("file ")]
        assert file_lines[0] == "file '/first.mp4'"
        assert file_lines[1] == "file '/second.mp4'"

    def test_single_quote_in_path_escaped(self, tmp_path):
        clips = [
            AssemblyClip("/it's a clip.mp4", "hook", 0, 0, 1000, 1000),
        ]
        dest = tmp_path / "list.txt"
        write_concat_list(clips, dest)
        content = dest.read_text()
        assert "it'\\''s a clip.mp4" in content


# ===================================================================
# concat_clips tests (mocked ffmpeg)
# ===================================================================


class TestConcatClips:
    def test_ffmpeg_command_shape(self, tmp_path):
        clips = [AssemblyClip("/a.mp4", "hook", 0, 0, 1000, 1000)]
        output = tmp_path / "out.mp4"
        with patch("app.video.assembler.subprocess.run") as mock_run:
            concat_clips(clips, output)
            args = mock_run.call_args[0][0]
            assert args[0] == "ffmpeg"
            assert "-f" in args
            idx = args.index("-f")
            assert args[idx + 1] == "concat"
            assert "-c" in args
            assert "copy" in args
            assert str(output) in args
            mock_run.assert_called_once()

    def test_ffmpeg_failure_propagates(self, tmp_path):
        clips = [AssemblyClip("/a.mp4", "hook", 0, 0, 1000, 1000)]
        output = tmp_path / "out.mp4"
        with patch(
            "app.video.assembler.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "ffmpeg"),
        ):
            with pytest.raises(subprocess.CalledProcessError):
                concat_clips(clips, output)


# ===================================================================
# mux_audio tests (mocked ffmpeg)
# ===================================================================


class TestMuxAudio:
    def test_mux_command_shape(self, tmp_path):
        video = tmp_path / "v.mp4"
        video.write_bytes(b"\x00")
        output = tmp_path / "out.mp4"
        with patch("app.video.assembler.subprocess.run") as mock_run:
            mux_audio(video, "/audio.mp3", output)
            args = mock_run.call_args[0][0]
            assert args[0] == "ffmpeg"
            assert str(video) in args
            assert "/audio.mp3" in args
            assert "-c:a" in args
            assert "aac" in args
            assert "-shortest" in args

    def test_mux_failure_propagates(self, tmp_path):
        video = tmp_path / "v.mp4"
        video.write_bytes(b"\x00")
        output = tmp_path / "out.mp4"
        with patch(
            "app.video.assembler.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "ffmpeg"),
        ):
            with pytest.raises(subprocess.CalledProcessError):
                mux_audio(video, "/audio.mp3", output)


# ===================================================================
# check_duration_drift tests
# ===================================================================


class TestCheckDurationDrift:
    def test_no_warning_within_tolerance(self):
        plan = AssemblyPlan(
            clips=[AssemblyClip("/a.mp4", "hook", 0, 0, 3000, 3000)],
            audio_duration_ms=3000 + DRIFT_TOLERANCE_MS - 1,
        )
        with patch("app.video.assembler.log") as mock_log:
            check_duration_drift(plan)
            mock_log.warning.assert_not_called()

    def test_warning_beyond_tolerance(self):
        plan = AssemblyPlan(
            clips=[AssemblyClip("/a.mp4", "hook", 0, 0, 3000, 3000)],
            audio_duration_ms=3000 + DRIFT_TOLERANCE_MS + 500,
        )
        with patch("app.video.assembler.log") as mock_log:
            check_duration_drift(plan)
            mock_log.warning.assert_called_once()
            call_kwargs = mock_log.warning.call_args
            assert "duration_drift" in str(call_kwargs)

    def test_no_check_when_audio_duration_none(self):
        plan = AssemblyPlan(
            clips=[AssemblyClip("/a.mp4", "hook", 0, 0, 3000, 3000)],
            audio_duration_ms=None,
        )
        with patch("app.video.assembler.log") as mock_log:
            check_duration_drift(plan)
            mock_log.warning.assert_not_called()


# ===================================================================
# render orchestrator tests (mocked ffmpeg)
# ===================================================================


class TestRender:
    def test_render_calls_concat_then_mux(self, tmp_path):
        plan = AssemblyPlan(
            clips=[AssemblyClip("/a.mp4", "hook", 0, 0, 1000, 1000)],
            audio_path="/audio.mp3",
            output_key="j1/video.mp4",
        )
        with (
            patch("app.video.assembler.concat_clips") as mock_concat,
            patch("app.video.assembler.mux_audio") as mock_mux,
            patch("app.video.assembler.check_duration_drift") as mock_drift,
        ):
            result = render(plan)
            mock_drift.assert_called_once_with(plan)
            mock_concat.assert_called_once()
            mock_mux.assert_called_once()
            assert result.endswith("muxed.mp4")


# ===================================================================
# VideoAssemblyTool integration tests (mocked ffmpeg + storage)
# ===================================================================


class TestVideoAssemblyTool:
    def test_returns_video_path_in_state(self, tmp_path, monkeypatch):
        monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
        monkeypatch.setenv("STORAGE_BACKEND", "local")
        # Clear the settings cache so monkeypatch takes effect
        from app.core.config import get_settings
        get_settings.cache_clear()

        clip = _stub_clip(tmp_path, "clip.mp4")
        audio = _stub_audio(tmp_path, "audio.mp3")
        state = {
            "job_id": "test_job",
            "visual_assets": [_make_asset(path=clip)],
            "audio_path": audio,
        }

        # Mock ffmpeg calls to avoid needing real ffmpeg
        def fake_run(cmd, **kwargs):
            # If the output path is in the command, create a dummy file there
            if isinstance(cmd, list) and cmd[0] == "ffmpeg":
                # Find the output path (last argument)
                out_path = cmd[-1]
                Path(out_path).parent.mkdir(parents=True, exist_ok=True)
                Path(out_path).write_bytes(b"fake_video_data")
            return subprocess.CompletedProcess(cmd, 0)

        with patch("app.video.assembler.subprocess.run", side_effect=fake_run):
            result = VideoAssemblyTool().invoke(state)

        assert "video_path" in result
        assert result["video_path"].endswith("video.mp4")
        assert result["job_id"] == "test_job"
        # Original state keys preserved
        assert result["audio_path"] == audio

        get_settings.cache_clear()

    def test_does_not_mutate_input_state(self, tmp_path, monkeypatch):
        monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
        monkeypatch.setenv("STORAGE_BACKEND", "local")
        from app.core.config import get_settings
        get_settings.cache_clear()

        clip = _stub_clip(tmp_path, "clip.mp4")
        audio = _stub_audio(tmp_path, "audio.mp3")
        state = {
            "job_id": "j1",
            "visual_assets": [_make_asset(path=clip)],
            "audio_path": audio,
        }
        original_keys = set(state.keys())

        def fake_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "ffmpeg":
                Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
                Path(cmd[-1]).write_bytes(b"fake_video_data")
            return subprocess.CompletedProcess(cmd, 0)

        with patch("app.video.assembler.subprocess.run", side_effect=fake_run):
            result = VideoAssemblyTool().invoke(state)

        # Input state must not gain new keys
        assert set(state.keys()) == original_keys
        assert "video_path" not in state
        assert "video_path" in result

        get_settings.cache_clear()

    def test_validation_error_propagates(self, tmp_path):
        state = {"job_id": "j1", "visual_assets": [], "audio_path": "/missing.mp3"}
        with pytest.raises(AssemblyValidationError):
            VideoAssemblyTool().invoke(state)

    def test_deterministic_storage_key(self, tmp_path, monkeypatch):
        monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
        monkeypatch.setenv("STORAGE_BACKEND", "local")
        from app.core.config import get_settings
        get_settings.cache_clear()

        clip = _stub_clip(tmp_path, "clip.mp4")
        audio = _stub_audio(tmp_path, "audio.mp3")

        def fake_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "ffmpeg":
                Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
                Path(cmd[-1]).write_bytes(b"fake_video_data")
            return subprocess.CompletedProcess(cmd, 0)

        for job_id in ["j1", "j1"]:
            state = {
                "job_id": job_id,
                "visual_assets": [_make_asset(path=clip)],
                "audio_path": audio,
            }
            with patch("app.video.assembler.subprocess.run", side_effect=fake_run):
                result = VideoAssemblyTool().invoke(state)
            assert "j1/video.mp4" in result["video_path"]

        get_settings.cache_clear()


# ===================================================================
# Offline integration tests with generated stub media
# ===================================================================


def _generate_silent_audio(path: Path, duration_s: float = 1.0) -> str:
    """Generate a silent MP3 file using ffmpeg."""
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "anullsrc=r=44100:cl=mono",
            "-t", f"{duration_s:.3f}",
            "-c:a", "libmp3lame",
            "-q:a", "9",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return str(path)


def _generate_color_clip(path: Path, duration_s: float = 1.0, color: str = "black") -> str:
    """Generate a tiny color clip at 1080x1920 using ffmpeg."""
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"color=c={color}:s=1080x1920:r=30:d={duration_s:.3f}",
            "-pix_fmt", "yuv420p",
            "-an",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return str(path)


def _ffmpeg_available() -> bool:
    """Check if ffmpeg is available on the system."""
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            check=True,
            capture_output=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


requires_ffmpeg = pytest.mark.skipif(
    not _ffmpeg_available(),
    reason="ffmpeg not available on this system",
)


@requires_ffmpeg
class TestOfflineIntegration:
    """Integration tests that use real ffmpeg with generated stub media."""

    def test_concat_two_clips(self, tmp_path):
        c1 = _generate_color_clip(tmp_path / "hook.mp4", 0.5, "red")
        c2 = _generate_color_clip(tmp_path / "body.mp4", 0.5, "blue")
        clips = [
            AssemblyClip(c1, "hook", 0, 0, 500, 500),
            AssemblyClip(c2, "body", 0, 500, 1000, 500),
        ]
        output = tmp_path / "concat.mp4"
        concat_clips(clips, output)
        assert output.exists()
        assert output.stat().st_size > 0

    def test_mux_audio_onto_clip(self, tmp_path):
        clip_path = _generate_color_clip(tmp_path / "video.mp4", 1.0)
        audio_path = _generate_silent_audio(tmp_path / "audio.mp3", 1.0)
        output = tmp_path / "muxed.mp4"
        mux_audio(Path(clip_path), audio_path, output)
        assert output.exists()
        assert output.stat().st_size > 0

    def test_full_render_pipeline(self, tmp_path):
        c1 = _generate_color_clip(tmp_path / "hook.mp4", 0.5, "red")
        c2 = _generate_color_clip(tmp_path / "body.mp4", 0.5, "blue")
        audio = _generate_silent_audio(tmp_path / "audio.mp3", 1.0)
        plan = AssemblyPlan(
            clips=[
                AssemblyClip(c1, "hook", 0, 0, 500, 500),
                AssemblyClip(c2, "body", 0, 500, 1000, 500),
            ],
            audio_path=audio,
            output_key="test/video.mp4",
            audio_duration_ms=1000,
        )
        result = render(plan)
        assert Path(result).exists()
        assert Path(result).stat().st_size > 0

    def test_full_tool_invoke(self, tmp_path, monkeypatch):
        monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
        monkeypatch.setenv("STORAGE_BACKEND", "local")
        from app.core.config import get_settings
        get_settings.cache_clear()

        c1 = _generate_color_clip(tmp_path / "hook.mp4", 0.5, "red")
        c2 = _generate_color_clip(tmp_path / "body.mp4", 0.5, "blue")
        audio = _generate_silent_audio(tmp_path / "audio.mp3", 1.0)

        state = {
            "job_id": "integration_test",
            "audio_path": audio,
            "audio_duration_ms": 1000,
            "visual_assets": [
                _make_asset(path=c1, section="hook", chunk_index=0, start_ms=0, end_ms=500, duration_ms=500),
                _make_asset(path=c2, section="body", chunk_index=0, start_ms=500, end_ms=1000, duration_ms=500),
            ],
        }

        result = VideoAssemblyTool().invoke(state)
        assert result["video_path"].endswith("video.mp4")
        assert Path(result["video_path"]).exists()
        assert Path(result["video_path"]).stat().st_size > 0

        get_settings.cache_clear()
