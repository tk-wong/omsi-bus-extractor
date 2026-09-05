"""Tests for extract_sound.py — sound file extraction."""
from __future__ import annotations

from pathlib import Path

import extract_sound


# ── normalize_rel_path ────────────────────────────────────────────────────────

class TestNormalizeRelPath:
    def test_strips_quotes(self) -> None:
        assert extract_sound.normalize_rel_path('"engine.wav"') == "engine.wav"

    def test_forward_slash_to_backslash(self) -> None:
        assert extract_sound.normalize_rel_path("sub/engine.wav") == "sub\\engine.wav"

    def test_strips_leading_dot_slash(self) -> None:
        assert extract_sound.normalize_rel_path(".\\engine.wav") == "engine.wav"

    def test_strips_whitespace(self) -> None:
        assert extract_sound.normalize_rel_path("  engine.wav  ") == "engine.wav"


# ── extract_file_tokens ──────────────────────────────────────────────────────

class TestExtractFileTokens:
    def test_simple_wav(self) -> None:
        tokens = extract_sound.extract_file_tokens("engine.wav")
        assert tokens == ["engine.wav"]

    def test_simple_cfg(self) -> None:
        tokens = extract_sound.extract_file_tokens("sound.cfg")
        assert tokens == ["sound.cfg"]

    def test_ogg(self) -> None:
        tokens = extract_sound.extract_file_tokens("horn.ogg")
        assert tokens == ["horn.ogg"]

    def test_quoted_path(self) -> None:
        tokens = extract_sound.extract_file_tokens('"sub\\engine.wav"')
        assert tokens == ["sub\\engine.wav"]

    def test_non_audio_ignored(self) -> None:
        tokens = extract_sound.extract_file_tokens("not_audio.bmp")
        assert tokens == []

    def test_empty_line(self) -> None:
        tokens = extract_sound.extract_file_tokens("")
        assert tokens == []

    def test_multiple_tokens(self) -> None:
        # When a line starts with an unquoted token that has a valid extension,
        # extract_file_tokens treats the entire line as one token (whole-line path).
        tokens = extract_sound.extract_file_tokens('a.wav "b.ogg"')
        assert len(tokens) == 1
        assert ".ogg" in tokens[0]

    def test_multiple_quoted_tokens(self) -> None:
        # The tokenizer's whole-line check first: since the stripped line ends with
        # a valid extension (.ogg), the entire line is returned as one token.
        tokens = extract_sound.extract_file_tokens('"a.wav" "b.ogg"')
        assert len(tokens) == 1

    def test_two_separate_lines(self) -> None:
        t1 = extract_sound.extract_file_tokens("a.wav")
        t2 = extract_sound.extract_file_tokens("b.ogg")
        assert t1 == ["a.wav"]
        assert t2 == ["b.ogg"]


# ── parse_bus_for_sound_cfgs ──────────────────────────────────────────────────

class TestParseBusForSoundCfgs:
    def test_finds_sound_cfg(self, mock_bus_root: Path) -> None:
        bus_file = mock_bus_root / "test_bus.bus"
        result = extract_sound.parse_bus_for_sound_cfgs(bus_file, mock_bus_root)
        assert len(result) == 1
        cfg = next(iter(result))
        assert cfg.name == "sound.cfg"

    def test_finds_sound_ai_section(self, tmp_path: Path) -> None:
        bus_file = tmp_path / "test.bus"
        bus_file.write_text(
            "[sound_ai]\nSound\\ai.cfg\n",
            encoding="utf-8",
        )
        (tmp_path / "Sound").mkdir(parents=True, exist_ok=True)
        (tmp_path / "Sound" / "ai.cfg").write_text("", encoding="utf-8")
        result = extract_sound.parse_bus_for_sound_cfgs(bus_file, tmp_path)
        assert len(result) == 1
        assert next(iter(result)).name == "ai.cfg"

    def test_no_sound_section(self, tmp_path: Path) -> None:
        bus_file = tmp_path / "test.bus"
        bus_file.write_text("[model]\nModel\\m.cfg\n", encoding="utf-8")
        result = extract_sound.parse_bus_for_sound_cfgs(bus_file, tmp_path)
        assert result == set()

# ── build_sound_index ────────────────────────────────────────────────────────

class TestBuildSoundIndex:
    def test_indexes_sound_files(self, mock_bus_root: Path) -> None:
        sound_root = mock_bus_root / "Sound"
        by_relpath, by_basename = extract_sound.build_sound_index(sound_root)
        assert "engine.wav" in by_relpath
        assert "engine.wav" in by_basename
        assert "sub/nested.wav" in by_relpath
        assert "nested.wav" in by_basename

    def test_empty_dir(self, tmp_path: Path) -> None:
        sound_root = tmp_path / "Sound"
        sound_root.mkdir()
        by_relpath, by_basename = extract_sound.build_sound_index(sound_root)
        assert by_relpath == {}
        assert by_basename == {}

    def test_nonexistent_dir(self, tmp_path: Path) -> None:
        by_relpath, by_basename = extract_sound.build_sound_index(
            tmp_path / "nonexistent"
        )
        assert by_relpath == {}
        assert by_basename == {}


# ── resolve_sound_token ──────────────────────────────────────────────────────

class TestResolveSoundToken:
    def test_resolve_by_basename(self, mock_bus_root: Path) -> None:
        sound_root = mock_bus_root / "Sound"
        by_relpath, by_basename = extract_sound.build_sound_index(sound_root)
        result = extract_sound.resolve_sound_token(
            "engine.wav",
            sound_root,
            mock_bus_root,
            sound_root,
            by_relpath,
            by_basename,
        )
        assert len(result) >= 1
        assert any(p.name == "engine.wav" for p in result)

    def test_resolve_by_relative_path(self, mock_bus_root: Path) -> None:
        sound_root = mock_bus_root / "Sound"
        by_relpath, by_basename = extract_sound.build_sound_index(sound_root)
        result = extract_sound.resolve_sound_token(
            "sub\\nested.wav",
            sound_root,
            mock_bus_root,
            sound_root,
            by_relpath,
            by_basename,
        )
        assert len(result) >= 1
        assert any(p.name == "nested.wav" for p in result)

    def test_resolve_with_sound_prefix(self, mock_bus_root: Path) -> None:
        sound_root = mock_bus_root / "Sound"
        by_relpath, by_basename = extract_sound.build_sound_index(sound_root)
        result = extract_sound.resolve_sound_token(
            "sound\\engine.wav",
            sound_root,
            mock_bus_root,
            sound_root,
            by_relpath,
            by_basename,
        )
        assert len(result) >= 1

    def test_unresolved_token(self, mock_bus_root: Path) -> None:
        sound_root = mock_bus_root / "Sound"
        by_relpath, by_basename = extract_sound.build_sound_index(sound_root)
        result = extract_sound.resolve_sound_token(
            "ghost.wav",
            sound_root,
            mock_bus_root,
            sound_root,
            by_relpath,
            by_basename,
        )
        assert result == set()


# ── parse_sound_dependencies (BFS) ───────────────────────────────────────────

class TestParseSoundDependencies:
    def test_discovers_audio_files(self, mock_bus_root: Path) -> None:
        start_cfg = mock_bus_root / "Sound" / "sound.cfg"
        all_cfgs, all_audio, unresolved, oob = (
            extract_sound.parse_sound_dependencies({start_cfg}, mock_bus_root)
        )
        assert len(all_cfgs) == 1
        audio_names = {a.name for a in all_audio}
        assert "engine.wav" in audio_names

    def test_bfs_through_chained_cfgs(self, mock_bus_root_nested_sound: Path) -> None:
        start_cfg = mock_bus_root_nested_sound / "Sound" / "main_sound.cfg"
        all_cfgs, all_audio, unresolved, oob = (
            extract_sound.parse_sound_dependencies(
                {start_cfg}, mock_bus_root_nested_sound
            )
        )
        # main_sound.cfg -> sub_sound.cfg -> engine.wav
        cfg_names = {c.name for c in all_cfgs}
        assert "main_sound.cfg" in cfg_names
        assert "sub_sound.cfg" in cfg_names
        audio_names = {a.name for a in all_audio}
        assert "engine.wav" in audio_names

    def test_unresolved_tokens(self, mock_bus_root_missing: Path) -> None:
        start_cfg = mock_bus_root_missing / "Sound" / "missing_sound.cfg"
        all_cfgs, all_audio, unresolved, oob = (
            extract_sound.parse_sound_dependencies(
                {start_cfg}, mock_bus_root_missing
            )
        )
        assert len(unresolved) >= 1
        assert any("ghost.wav" in u for u in unresolved)


# ── resolve_existing_path ────────────────────────────────────────────────────

class TestResolveExistingPath:
    def test_finds_file(self, mock_bus_root: Path) -> None:
        result = extract_sound.resolve_existing_path(
            "Sound\\engine.wav",
            mock_bus_root / "Sound",
            mock_bus_root,
        )
        assert result is not None
        assert result.name == "engine.wav"

    def test_finds_with_sound_prefix_stripped(self, mock_bus_root: Path) -> None:
        result = extract_sound.resolve_existing_path(
            "sound\\engine.wav",
            mock_bus_root / "Sound",
            mock_bus_root,
        )
        assert result is not None
        assert result.name == "engine.wav"

    def test_returns_none_for_missing(self, mock_bus_root: Path) -> None:
        result = extract_sound.resolve_existing_path(
            "ghost.wav",
            mock_bus_root / "Sound",
            mock_bus_root,
        )
        assert result is None


# ── copy_files_to_output ─────────────────────────────────────────────────────

class TestCopyFilesToOutput:
    def test_copies_files(self, mock_bus_root: Path, tmp_path: Path) -> None:
        output = tmp_path / "sound_out"
        files = {
            mock_bus_root / "Sound" / "sound.cfg",
            mock_bus_root / "Sound" / "engine.wav",
        }
        extract_sound.copy_files_to_output(files, mock_bus_root, output)
        assert (output / "Sound" / "sound.cfg").exists()
        assert (output / "Sound" / "engine.wav").exists()

    def test_skips_out_of_bus(self, mock_bus_root: Path, tmp_path: Path) -> None:
        output = tmp_path / "sound_out"
        oob_file = mock_bus_root.parent / "outside" / "escape.wav"
        oob_file.parent.mkdir(parents=True)
        oob_file.write_bytes(b"\x00")
        oob_set: set[str] = set()
        extract_sound.copy_files_to_output(
            {oob_file}, mock_bus_root, output, out_of_bus=oob_set
        )
        assert not list(output.iterdir())
        assert len(oob_set) >= 1


# ── End-to-end sound extraction ──────────────────────────────────────────────

class TestEndToEndSoundExtraction:
    def test_full_pipeline(self, mock_bus_root: Path, tmp_path: Path) -> None:
        output = tmp_path / "sound_out"
        bus_file = mock_bus_root / "test_bus.bus"

        # 1. Parse .bus for sound cfgs
        sound_cfgs = extract_sound.parse_bus_for_sound_cfgs(bus_file, mock_bus_root)
        assert len(sound_cfgs) == 1

        # 2. BFS dependency walk
        cfg_files, audio_files, unresolved, oob = (
            extract_sound.parse_sound_dependencies(sound_cfgs, mock_bus_root)
        )
        assert len(audio_files) == 1
        assert next(iter(audio_files)).name == "engine.wav"
        assert unresolved == set()

        # 3. Copy to output
        extract_sound.copy_files_to_output(
            cfg_files | audio_files, mock_bus_root, output, out_of_bus=oob
        )
        assert (output / "Sound" / "sound.cfg").exists()
        assert (output / "Sound" / "engine.wav").exists()

    def test_pipeline_with_chained_cfgs(
        self, mock_bus_root_nested_sound: Path, tmp_path: Path
    ) -> None:
        output = tmp_path / "sound_out"
        bus_file = mock_bus_root_nested_sound / "test_bus.bus"

        sound_cfgs = extract_sound.parse_bus_for_sound_cfgs(
            bus_file, mock_bus_root_nested_sound
        )
        cfg_files, audio_files, unresolved, oob = (
            extract_sound.parse_sound_dependencies(
                sound_cfgs, mock_bus_root_nested_sound
            )
        )
        # Two cfgs (main + nested) and one audio file
        assert len(cfg_files) == 2
        assert len(audio_files) == 1
        assert unresolved == set()
