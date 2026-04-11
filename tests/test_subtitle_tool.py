"""Tests for the subtitle generation module.

Covers:
    - validation (``app.subtitles.validate``)
    - cue planning (``app.subtitles.cues``)
    - ``.srt`` serialization (``app.subtitles.srt``)
    - ffmpeg burn-in (``app.subtitles.burn``) with mocked subprocess
    - storage staging (``app.services.storage.stage_local``)
    - orchestrator (``app.tools.subtitle_tool.SubtitleTool``)
    - offline ffmpeg integration
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.storage import LocalStorage, StagedAsset
from app.subtitles.burn import FORCE_STYLE, burn_subtitles, _build_subtitles_filter
from app.subtitles.cues import (
    MAX_CHARS_PER_CUE,
    MAX_LINE_CHARS,
    SubtitleCue,
    _allocate_proportional,
    build_cues,
    plan_cues_from_script_fallback,
    plan_cues_from_segments,
)
from app.subtitles.srt import format_timestamp, serialize_srt
from app.subtitles.validate import (
    SubtitleValidationError,
    validate_state,
)
from app.tools.subtitle_tool import SubtitleTool


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

SAMPLE_SCRIPT = {
    "title": "Why typing matters",
    "hook": "Types catch bugs you would never see in tests.",
    "body": "Static types document intent. They make refactors easier.",
    "cta": "Follow for more Python tips.",
    "tags": ["python"],
}


def _stub_video(tmp_path: Path, name: str = "video.mp4") -> str:
    p = tmp_path / name
    p.write_bytes(b"\x00" * 128)
    return str(p)


def _stub_state(tmp_path: Path, **overrides) -> dict:
    video = _stub_video(tmp_path)
    state = {
        "job_id": "jtest",
        "video_path": video,
        "script": SAMPLE_SCRIPT,
        "audio_duration_ms": 6000,
        "audio_segments": [
            {"section": "hook", "chunk_index": 0, "text": SAMPLE_SCRIPT["hook"], "duration_ms": 2000},
            {"section": "body", "chunk_index": 0, "text": SAMPLE_SCRIPT["body"], "duration_ms": 3000},
            {"section": "cta", "chunk_index": 0, "text": SAMPLE_SCRIPT["cta"], "duration_ms": 1000},
        ],
    }
    state.update(overrides)
    return state


def _ffmpeg_available() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


requires_ffmpeg = pytest.mark.skipif(
    not _ffmpeg_available(),
    reason="ffmpeg not available on this system",
)


# ===========================================================================
# Validation
# ===========================================================================


class TestValidateState:
    def test_happy_path_returns_context(self, tmp_path):
        ctx = validate_state(_stub_state(tmp_path))
        assert ctx.job_id == "jtest"
        assert ctx.subtitle_key == "jtest/subtitles.srt"
        assert ctx.final_key == "jtest/final.mp4"
        assert ctx.audio_segments is not None
        assert len(ctx.audio_segments) == 3

    def test_missing_job_id(self, tmp_path):
        state = _stub_state(tmp_path)
        del state["job_id"]
        with pytest.raises(SubtitleValidationError, match="job_id"):
            validate_state(state)

    def test_missing_video_path(self, tmp_path):
        state = _stub_state(tmp_path)
        del state["video_path"]
        with pytest.raises(SubtitleValidationError, match="video_path"):
            validate_state(state)

    def test_nonexistent_video_path(self, tmp_path):
        state = _stub_state(tmp_path)
        state["video_path"] = "/nonexistent/v.mp4"
        with pytest.raises(SubtitleValidationError, match="does not exist"):
            validate_state(state)

    def test_missing_script(self, tmp_path):
        state = _stub_state(tmp_path)
        del state["script"]
        with pytest.raises(SubtitleValidationError, match="script"):
            validate_state(state)

    def test_empty_script_section(self, tmp_path):
        state = _stub_state(tmp_path)
        state["script"] = {**SAMPLE_SCRIPT, "hook": ""}
        with pytest.raises(SubtitleValidationError, match="hook"):
            validate_state(state)

    def test_no_timing_metadata(self, tmp_path):
        state = _stub_state(tmp_path)
        del state["audio_segments"]
        del state["audio_duration_ms"]
        with pytest.raises(SubtitleValidationError, match="no timing metadata"):
            validate_state(state)

    def test_fallback_with_only_audio_duration(self, tmp_path):
        state = _stub_state(tmp_path)
        del state["audio_segments"]
        ctx = validate_state(state)
        assert ctx.audio_segments is None
        assert ctx.audio_duration_ms == 6000

    def test_fallback_with_only_segments_path(self, tmp_path):
        state = _stub_state(tmp_path)
        del state["audio_segments"]
        del state["audio_duration_ms"]
        state["audio_segments_path"] = str(tmp_path / "voice.segments.json")
        ctx = validate_state(state)
        assert ctx.audio_segments_path is not None

    def test_malformed_segment_no_text(self, tmp_path):
        state = _stub_state(tmp_path)
        state["audio_segments"] = [{"duration_ms": 1000}]
        with pytest.raises(SubtitleValidationError, match="text"):
            validate_state(state)

    def test_malformed_segment_negative_duration(self, tmp_path):
        state = _stub_state(tmp_path)
        state["audio_segments"] = [{"text": "hi", "duration_ms": -1}]
        with pytest.raises(SubtitleValidationError, match="duration_ms"):
            validate_state(state)


# ===========================================================================
# Cue planning
# ===========================================================================


class TestPlanCuesFromSegments:
    def test_one_cue_per_short_segment(self):
        segments = [
            {"text": "Hello world.", "duration_ms": 1500},
            {"text": "Goodbye.", "duration_ms": 1000},
        ]
        cues = plan_cues_from_segments(segments, total_duration_ms=2500)
        assert len(cues) == 2
        assert cues[0].start_ms == 0
        assert cues[0].end_ms == 1500
        assert cues[1].start_ms == 1500
        assert cues[1].end_ms == 2500
        assert cues[0].text == "Hello world."

    def test_long_segment_splits_into_cards(self):
        long_text = (
            "Static types document intent. They help refactors. "
            "They also make IDEs much smarter about your code."
        )
        segments = [{"text": long_text, "duration_ms": 6000}]
        cues = plan_cues_from_segments(segments, total_duration_ms=6000)
        assert len(cues) >= 2
        # Sub-durations sum to parent duration.
        total = sum(c.duration_ms for c in cues)
        assert total == 6000
        # First cue starts at 0, last cue ends at parent duration.
        assert cues[0].start_ms == 0
        assert cues[-1].end_ms == 6000

    def test_missing_duration_uses_remainder(self):
        segments = [
            {"text": "one", "duration_ms": 1000},
            {"text": "two"},  # missing
            {"text": "three"},  # missing
        ]
        cues = plan_cues_from_segments(segments, total_duration_ms=5000)
        assert cues[-1].end_ms == 5000
        assert cues[0].start_ms == 0

    def test_silent_audio_deterministic(self):
        segments = [
            {"text": "one"},
            {"text": "two"},
        ]
        # total unknown -> 2000 ms per missing segment by default
        cues = plan_cues_from_segments(segments, total_duration_ms=None)
        assert len(cues) == 2
        assert cues[0].duration_ms == 2000
        assert cues[1].duration_ms == 2000

    def test_cue_indexes_are_contiguous(self):
        segments = [
            {"text": "a.", "duration_ms": 500},
            {"text": "b.", "duration_ms": 500},
            {"text": "c.", "duration_ms": 500},
        ]
        cues = plan_cues_from_segments(segments, total_duration_ms=1500)
        assert [c.index for c in cues] == [1, 2, 3]

    def test_empty_segment_text_skipped(self):
        segments = [
            {"text": "hello", "duration_ms": 1000},
            {"text": "", "duration_ms": 500},
            {"text": "world", "duration_ms": 500},
        ]
        cues = plan_cues_from_segments(segments, total_duration_ms=2000)
        assert len(cues) == 2
        # The empty segment's duration is absorbed into the timeline.
        assert cues[1].start_ms == 1500


class TestLineBreaking:
    def test_short_text_one_line(self):
        cues = plan_cues_from_segments(
            [{"text": "Hi there.", "duration_ms": 1000}], 1000
        )
        assert cues[0].lines == ("Hi there.",)

    def test_wraps_to_max_two_lines(self):
        text = "word " * 10  # ~50 chars → wraps to two lines
        cues = plan_cues_from_segments(
            [{"text": text.strip(), "duration_ms": 2000}], 2000
        )
        for cue in cues:
            assert len(cue.lines) <= 2
            for line in cue.lines:
                assert len(line) <= MAX_LINE_CHARS or len(line.split(" ")) == 1

    def test_very_long_text_produces_multiple_cues(self):
        # ~300 chars, far above MAX_CHARS_PER_CUE (~64)
        text = (
            "This is a long narration chunk that definitely needs to be "
            "split into several subtitle cards so that mobile viewers "
            "can comfortably read each card without feeling rushed."
        )
        assert len(text) > MAX_CHARS_PER_CUE
        cues = plan_cues_from_segments([{"text": text, "duration_ms": 8000}], 8000)
        assert len(cues) >= 3
        assert sum(c.duration_ms for c in cues) == 8000

    def test_punctuation_preferred_split(self):
        # Long enough to exceed MAX_CHARS_PER_CUE so splitting kicks in.
        text = (
            "First important phrase with content. "
            "Second important phrase with content. "
            "Third important phrase with content. "
            "Fourth important phrase with content."
        )
        assert len(text) > MAX_CHARS_PER_CUE
        cues = plan_cues_from_segments([{"text": text, "duration_ms": 4000}], 4000)
        # Expect multiple cues because the text is long enough.
        assert len(cues) >= 2
        # Splits should occur on phrase boundaries: each card should end
        # with punctuation or at end-of-text.
        for cue in cues[:-1]:
            assert cue.text.rstrip().endswith((".", "!", "?", ",", ";", ":"))

    def test_stable_cue_ordering(self):
        segments = [
            {"text": "one", "duration_ms": 500},
            {"text": "two", "duration_ms": 500},
            {"text": "three", "duration_ms": 500},
        ]
        first = plan_cues_from_segments(segments, 1500)
        second = plan_cues_from_segments(segments, 1500)
        assert first == second


class TestScriptFallback:
    def test_uses_script_when_no_segments(self):
        cues = plan_cues_from_script_fallback(SAMPLE_SCRIPT, total_duration_ms=6000)
        assert cues
        assert cues[0].start_ms == 0
        assert cues[-1].end_ms == 6000

    def test_handles_zero_duration(self):
        cues = plan_cues_from_script_fallback(SAMPLE_SCRIPT, total_duration_ms=0)
        # Falls back to 2000 ms per card.
        assert cues
        assert all(cue.duration_ms > 0 for cue in cues)

    def test_empty_script_sections_skipped(self):
        script = {**SAMPLE_SCRIPT, "body": ""}
        cues = plan_cues_from_script_fallback(script, total_duration_ms=4000)
        assert cues
        combined = " ".join(c.text for c in cues)
        assert "Static types" not in combined


class TestBuildCues:
    def test_prefers_in_memory_segments(self, tmp_path):
        state = _stub_state(tmp_path)
        ctx = validate_state(state)
        cues = build_cues(ctx)
        assert cues[-1].end_ms == 6000

    def test_loads_segments_file_when_needed(self, tmp_path):
        segments_path = tmp_path / "voice.segments.json"
        segments_path.write_text(
            json.dumps(
                {
                    "segments": [
                        {"section": "hook", "chunk_index": 0, "text": "hi", "duration_ms": 1000},
                        {"section": "cta", "chunk_index": 0, "text": "bye", "duration_ms": 1000},
                    ]
                }
            )
        )
        state = _stub_state(tmp_path)
        del state["audio_segments"]
        state["audio_segments_path"] = str(segments_path)
        ctx = validate_state(state)
        cues = build_cues(ctx)
        assert cues[-1].end_ms == 2000

    def test_falls_back_to_script(self, tmp_path):
        state = _stub_state(tmp_path)
        del state["audio_segments"]
        ctx = validate_state(state)
        cues = build_cues(ctx)
        assert cues
        # Script-fallback uses the audio_duration_ms envelope.
        assert cues[-1].end_ms == 6000


class TestAllocateProportional:
    def test_sums_to_total(self):
        values = _allocate_proportional([1, 2, 3], 10)
        assert sum(values) == 10

    def test_zero_total(self):
        assert _allocate_proportional([1, 2, 3], 0) == [0, 0, 0]

    def test_equal_weights(self):
        assert _allocate_proportional([1, 1, 1], 9) == [3, 3, 3]


# ===========================================================================
# SRT serialization
# ===========================================================================


class TestFormatTimestamp:
    def test_zero(self):
        assert format_timestamp(0) == "00:00:00,000"

    def test_milliseconds(self):
        assert format_timestamp(500) == "00:00:00,500"

    def test_seconds(self):
        assert format_timestamp(2_400) == "00:00:02,400"

    def test_minutes_hours(self):
        assert format_timestamp(3_661_000) == "01:01:01,000"

    def test_negative_clamped(self):
        assert format_timestamp(-5) == "00:00:00,000"


class TestSerializeSrt:
    def test_single_cue(self):
        cues = [SubtitleCue(1, 0, 1500, ("Hello world",))]
        out = serialize_srt(cues)
        assert out.startswith("1\n00:00:00,000 --> 00:00:01,500\nHello world\n")

    def test_multiple_cues_separator(self):
        cues = [
            SubtitleCue(1, 0, 1000, ("one",)),
            SubtitleCue(2, 1000, 2000, ("two",)),
        ]
        out = serialize_srt(cues)
        assert "\n1\n" in f"\n{out}"
        # Blank line between blocks
        assert "\n\n2\n" in out

    def test_reassigns_indices(self):
        cues = [
            SubtitleCue(7, 0, 500, ("a",)),
            SubtitleCue(8, 500, 1000, ("b",)),
        ]
        out = serialize_srt(cues)
        assert out.splitlines()[0] == "1"
        assert "\n\n2\n" in out

    def test_multiline_cue(self):
        cues = [SubtitleCue(1, 0, 1000, ("line one", "line two"))]
        out = serialize_srt(cues)
        assert "line one\nline two" in out

    def test_deterministic(self):
        cues = [
            SubtitleCue(1, 0, 500, ("a",)),
            SubtitleCue(2, 500, 1000, ("b",)),
        ]
        assert serialize_srt(cues) == serialize_srt(cues)


# ===========================================================================
# Burn-in
# ===========================================================================


class TestBurnSubtitles:
    def test_ffmpeg_command_shape(self, tmp_path):
        video = tmp_path / "in.mp4"
        video.write_bytes(b"\x00" * 16)
        srt = tmp_path / "in.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")
        output = tmp_path / "out.mp4"

        with patch("app.subtitles.burn.subprocess.run") as mock_run:
            burn_subtitles(str(video), str(srt), str(output))
            args = mock_run.call_args[0][0]
            assert args[0] == "ffmpeg"
            assert "-y" in args
            assert "-vf" in args
            vf = args[args.index("-vf") + 1]
            assert vf.startswith("subtitles=")
            assert "force_style=" in vf
            assert FORCE_STYLE in vf
            assert "-c:a" in args
            assert "copy" in args
            assert mock_run.call_args.kwargs.get("check") is True
            assert mock_run.call_args.kwargs.get("capture_output") is True

    def test_output_parent_created(self, tmp_path):
        video = tmp_path / "in.mp4"
        video.write_bytes(b"\x00")
        srt = tmp_path / "in.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n")
        output = tmp_path / "nested" / "dir" / "out.mp4"

        def fake_run(cmd, **kwargs):
            out = cmd[-1]
            Path(out).write_bytes(b"FAKE")
            return subprocess.CompletedProcess(cmd, 0)

        with patch("app.subtitles.burn.subprocess.run", side_effect=fake_run):
            burn_subtitles(str(video), str(srt), str(output))
        assert output.parent.is_dir()

    def test_ffmpeg_failure_propagates(self, tmp_path):
        video = tmp_path / "in.mp4"
        video.write_bytes(b"\x00")
        srt = tmp_path / "in.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n")
        output = tmp_path / "out.mp4"
        with patch(
            "app.subtitles.burn.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "ffmpeg", stderr=b"err"),
        ):
            with pytest.raises(subprocess.CalledProcessError):
                burn_subtitles(str(video), str(srt), str(output))

    def test_subtitles_filter_escapes_path(self, tmp_path):
        srt = tmp_path / "sub with : colon.srt"
        vf = _build_subtitles_filter(srt)
        assert r"\:" in vf
        assert FORCE_STYLE in vf


# ===========================================================================
# Storage staging
# ===========================================================================


class TestLocalStorageStageLocal:
    def test_stage_local_by_absolute_path(self, tmp_path):
        storage = LocalStorage(str(tmp_path))
        src = storage.save("j/asset.txt", b"hello")
        staged = storage.stage_local(src)
        assert Path(staged.local_path).read_bytes() == b"hello"
        staged.cleanup()  # no-op for LocalStorage

    def test_stage_local_by_key(self, tmp_path):
        storage = LocalStorage(str(tmp_path))
        storage.save("j/asset.txt", b"world")
        staged = storage.stage_local("j/asset.txt")
        assert Path(staged.local_path).read_bytes() == b"world"

    def test_stage_local_missing_raises(self, tmp_path):
        storage = LocalStorage(str(tmp_path))
        with pytest.raises(FileNotFoundError):
            storage.stage_local("missing/file.bin")

    def test_staged_asset_as_context_manager(self, tmp_path):
        storage = LocalStorage(str(tmp_path))
        storage.save("j/a.txt", b"x")
        with storage.stage_local("j/a.txt") as staged:
            assert Path(staged.local_path).exists()


class TestStagedAssetCleanupS3:
    def test_cleanup_removes_tempdir(self, tmp_path):
        # Simulate an S3-backed staged asset: temp dir + local file inside it.
        tmpdir = tmp_path / "tmp"
        tmpdir.mkdir()
        local = tmpdir / "asset.mp4"
        local.write_bytes(b"fake")
        staged = StagedAsset(local_path=str(local), _cleanup_dir=str(tmpdir))
        staged.cleanup()
        assert not tmpdir.exists()


# ===========================================================================
# SubtitleTool orchestrator
# ===========================================================================


class TestSubtitleTool:
    def _fake_ffmpeg(self):
        """Factory: ffmpeg stub that writes a dummy MP4 to its output arg."""
        def fake_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "ffmpeg":
                out = cmd[-1]
                Path(out).parent.mkdir(parents=True, exist_ok=True)
                Path(out).write_bytes(b"FAKE_MP4")
            return subprocess.CompletedProcess(cmd, 0)
        return fake_run

    def test_happy_path_enriches_state(self, tmp_path):
        state = _stub_state(tmp_path)
        storage = LocalStorage(str(tmp_path / "storage"))
        tool = SubtitleTool(storage=storage)
        with patch("app.subtitles.burn.subprocess.run", side_effect=self._fake_ffmpeg()):
            out = tool.run(state)
        assert out["subtitle_path"].endswith("jtest/subtitles.srt")
        assert out["final_path"].endswith("jtest/final.mp4")
        assert Path(out["subtitle_path"]).exists()
        assert Path(out["final_path"]).exists()
        # original state not mutated
        assert "subtitle_path" not in state

    def test_srt_content_uses_segments(self, tmp_path):
        state = _stub_state(tmp_path)
        storage = LocalStorage(str(tmp_path / "storage"))
        tool = SubtitleTool(storage=storage)
        with patch("app.subtitles.burn.subprocess.run", side_effect=self._fake_ffmpeg()):
            out = tool.run(state)
        srt = Path(out["subtitle_path"]).read_text(encoding="utf-8")
        # First cue timestamp is zero-based.
        assert "00:00:00,000 -->" in srt
        assert "Types catch bugs" in srt

    def test_deterministic_storage_keys(self, tmp_path):
        storage = LocalStorage(str(tmp_path / "storage"))
        tool = SubtitleTool(storage=storage)
        state = _stub_state(tmp_path)
        with patch("app.subtitles.burn.subprocess.run", side_effect=self._fake_ffmpeg()):
            first = tool.run(state)
            second = tool.run(state)
        assert first["subtitle_path"] == second["subtitle_path"]
        assert first["final_path"] == second["final_path"]

    def test_degraded_mode_script_fallback(self, tmp_path):
        state = _stub_state(tmp_path)
        del state["audio_segments"]
        # Only audio_duration_ms remains; use script-driven fallback.
        storage = LocalStorage(str(tmp_path / "storage"))
        tool = SubtitleTool(storage=storage)
        with patch("app.subtitles.burn.subprocess.run", side_effect=self._fake_ffmpeg()):
            out = tool.run(state)
        srt = Path(out["subtitle_path"]).read_text(encoding="utf-8")
        assert "Types catch bugs" in srt
        assert "Follow for more Python tips." in srt

    def test_invalid_state_raises(self, tmp_path):
        storage = LocalStorage(str(tmp_path / "storage"))
        tool = SubtitleTool(storage=storage)
        state = _stub_state(tmp_path)
        del state["video_path"]
        with pytest.raises(SubtitleValidationError):
            tool.run(state)

    def test_audio_track_copied_not_reencoded(self, tmp_path):
        state = _stub_state(tmp_path)
        storage = LocalStorage(str(tmp_path / "storage"))
        tool = SubtitleTool(storage=storage)
        observed = {}

        def recording_run(cmd, **kwargs):
            observed["cmd"] = list(cmd)
            out = cmd[-1]
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_bytes(b"FAKE_MP4")
            return subprocess.CompletedProcess(cmd, 0)

        with patch("app.subtitles.burn.subprocess.run", side_effect=recording_run):
            tool.run(state)
        cmd = observed["cmd"]
        ca_idx = cmd.index("-c:a")
        assert cmd[ca_idx + 1] == "copy"


# ===========================================================================
# Offline ffmpeg integration (skipped if ffmpeg not available)
# ===========================================================================


def _generate_color_clip_with_audio(path: Path, duration_s: float) -> str:
    """Tiny 1080x1920 clip with an AAC audio track so burn-in has both streams."""
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c=black:s=320x568:r=30:d={duration_s:.3f}",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", f"{duration_s:.3f}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return str(path)


@requires_ffmpeg
class TestOfflineIntegration:
    def test_full_subtitle_tool_run(self, tmp_path):
        video = _generate_color_clip_with_audio(tmp_path / "in.mp4", 2.0)
        state = {
            "job_id": "offline",
            "video_path": video,
            "script": SAMPLE_SCRIPT,
            "audio_duration_ms": 2000,
            "audio_segments": [
                {"section": "hook", "chunk_index": 0, "text": "hello world", "duration_ms": 1000},
                {"section": "cta", "chunk_index": 0, "text": "thanks", "duration_ms": 1000},
            ],
        }
        storage = LocalStorage(str(tmp_path / "storage"))
        tool = SubtitleTool(storage=storage)
        out = tool.run(state)
        assert Path(out["subtitle_path"]).exists()
        assert Path(out["final_path"]).exists()
        assert Path(out["final_path"]).stat().st_size > 0

    def test_duration_coherence(self, tmp_path):
        # The .srt last timestamp stays within the video duration envelope.
        video = _generate_color_clip_with_audio(tmp_path / "in.mp4", 3.0)
        state = {
            "job_id": "coh",
            "video_path": video,
            "script": SAMPLE_SCRIPT,
            "audio_duration_ms": 3000,
            "audio_segments": [
                {"section": "hook", "chunk_index": 0, "text": SAMPLE_SCRIPT["hook"], "duration_ms": 1500},
                {"section": "cta", "chunk_index": 0, "text": SAMPLE_SCRIPT["cta"], "duration_ms": 1500},
            ],
        }
        storage = LocalStorage(str(tmp_path / "storage"))
        tool = SubtitleTool(storage=storage)
        out = tool.run(state)
        srt_lines = Path(out["subtitle_path"]).read_text(encoding="utf-8").splitlines()
        # Last time-range line: "HH:MM:SS,mmm --> HH:MM:SS,mmm"
        time_lines = [line for line in srt_lines if "-->" in line]
        last_end = time_lines[-1].split(" --> ")[1]
        # Within 3 seconds envelope.
        assert last_end <= "00:00:03,000"
