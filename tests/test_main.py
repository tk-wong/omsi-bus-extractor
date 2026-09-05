"""Tests for main.py — extraction pipeline orchestration."""
from __future__ import annotations

from pathlib import Path

import pytest

import main


# ── resolve_selected_buses ────────────────────────────────────────────────────

class TestResolveSelectedBuses:
    def test_auto_discover(self, mock_bus_root: Path) -> None:
        result = main.resolve_selected_buses(mock_bus_root, [])
        assert len(result) == 1
        assert result[0].name == "test_bus.bus"

    def test_explicit_bus_file(self, mock_bus_root: Path) -> None:
        result = main.resolve_selected_buses(mock_bus_root, ["test_bus.bus"])
        assert len(result) == 1
        assert result[0].name == "test_bus.bus"

    def test_multiple_bus_files(self, mock_bus_root_multi: Path) -> None:
        result = main.resolve_selected_buses(mock_bus_root_multi, [])
        assert len(result) == 2
        names = {p.name for p in result}
        assert names == {"bus_a.bus", "bus_b.bus"}

    def test_raises_when_no_bus_files(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="No .bus files"):
            main.resolve_selected_buses(tmp_path, [])

    def test_raises_when_bus_not_found(self, mock_bus_root: Path) -> None:
        with pytest.raises(FileNotFoundError, match="does not exist"):
            main.resolve_selected_buses(mock_bus_root, ["nonexistent.bus"])

    def test_raises_when_not_bus_extension(self, mock_bus_root: Path) -> None:
        # Create a .txt file and try to use it as a bus file
        fake = mock_bus_root / "not_a_bus.txt"
        fake.write_text("", encoding="utf-8")
        with pytest.raises(ValueError, match="Not a .bus file"):
            main.resolve_selected_buses(mock_bus_root, ["not_a_bus.txt"])


# ── run_text_extraction ──────────────────────────────────────────────────────

class TestRunTextExtraction:
    def test_extracts_text_files(self, mock_bus_root: Path, tmp_path: Path) -> None:
        output = tmp_path / "text_out"
        bus_file = mock_bus_root / "test_bus.bus"
        missing, out_of_bus = main.run_text_extraction(
            mock_bus_root, output, [bus_file]
        )
        assert missing == set()
        assert out_of_bus == set()
        # Key files should be in output
        assert (output / "Model" / "test_model.cfg").exists()
        assert (output / "Sound" / "sound.cfg").exists()
        assert (output / "TestBus.hof").exists()
        assert (output / "test_bus.bus").exists()


# ── run_model_extraction ─────────────────────────────────────────────────────

class TestRunModelExtraction:
    def test_extracts_model_files(self, mock_bus_root: Path, tmp_path: Path) -> None:
        output = tmp_path / "model_out"
        bus_file = mock_bus_root / "test_bus.bus"
        missing, unresolved_tex, oob = main.run_model_extraction(
            mock_bus_root, output, bus_file
        )
        assert missing == []
        assert unresolved_tex == set()
        # Verify output files
        assert (output / "Model" / "test_model.cfg").exists()
        assert (output / "Model" / "sub" / "inner.cfg").exists()
        assert (output / "Model" / "test.o3d").exists()
        assert (output / "Texture" / "body.bmp").exists()
        assert (output / "Texture" / "interior.tga").exists()
        assert (output / "Texture" / "logos" / "brand.png").exists()

    def test_returns_error_when_no_model_cfgs(self, tmp_path: Path) -> None:
        bus_file = tmp_path / "empty.bus"
        bus_file.write_text("[sound]\nsound.cfg\n", encoding="utf-8")
        (tmp_path / "sound.cfg").write_text("", encoding="utf-8")
        missing, unresolved_tex, oob = main.run_model_extraction(
            tmp_path, tmp_path / "out", bus_file
        )
        assert len(missing) == 1
        assert "No model cfg" in missing[0]


# ── run_sound_extraction ─────────────────────────────────────────────────────

class TestRunSoundExtraction:
    def test_extracts_sound_files(self, mock_bus_root: Path, tmp_path: Path) -> None:
        output = tmp_path / "sound_out"
        bus_file = mock_bus_root / "test_bus.bus"
        unresolved, oob = main.run_sound_extraction(
            mock_bus_root, output, bus_file
        )
        assert unresolved == set()
        assert (output / "Sound" / "sound.cfg").exists()
        assert (output / "Sound" / "engine.wav").exists()

    def test_returns_error_when_no_sound_cfgs(self, tmp_path: Path) -> None:
        bus_file = tmp_path / "empty.bus"
        bus_file.write_text("[model]\nModel\\m.cfg\n", encoding="utf-8")
        (tmp_path / "Model").mkdir(parents=True, exist_ok=True)
        (tmp_path / "Model" / "m.cfg").write_text("", encoding="utf-8")
        unresolved, oob = main.run_sound_extraction(
            tmp_path, tmp_path / "out", bus_file
        )
        assert len(unresolved) == 1
        assert "No sound cfg" in unresolved.pop()


# ── run_extraction_pipeline ──────────────────────────────────────────────────

class TestRunExtractionPipeline:
    def test_full_pipeline(self, mock_bus_root: Path, tmp_path: Path) -> None:
        output = tmp_path / "full_out"
        bus_file = mock_bus_root / "test_bus.bus"
        summary = main.run_extraction_pipeline(
            mock_bus_root, output, [bus_file]
        )
        # No missing or unresolved items in our complete mock
        assert summary.missing_text == set()
        assert summary.missing_model == set()
        assert summary.unresolved_textures == set()
        assert summary.unresolved_sound == set()
        # All output files should exist
        assert (output / "Model" / "test_model.cfg").exists()
        assert (output / "Model" / "test.o3d").exists()
        assert (output / "Texture" / "body.bmp").exists()
        assert (output / "Sound" / "sound.cfg").exists()
        assert (output / "Sound" / "engine.wav").exists()
        assert (output / "TestBus.hof").exists()

    def test_pipeline_with_multiple_buses(
        self, mock_bus_root_multi: Path, tmp_path: Path
    ) -> None:
        output = tmp_path / "multi_out"
        bus_files = sorted(mock_bus_root_multi.glob("*.bus"))
        summary = main.run_extraction_pipeline(
            mock_bus_root_multi, output, bus_files
        )
        # Both buses share the same body.wav and body.bmp
        assert (output / "Model" / "model_a.cfg").exists()
        assert (output / "Model" / "model_b.cfg").exists()
        assert (output / "Sound" / "engine.wav").exists()
        assert (output / "Texture" / "body.bmp").exists()

    def test_pipeline_with_missing_files(
        self, mock_bus_root_missing: Path, tmp_path: Path
    ) -> None:
        output = tmp_path / "missing_out"
        bus_file = mock_bus_root_missing / "test_bus.bus"
        summary = main.run_extraction_pipeline(
            mock_bus_root_missing, output, [bus_file]
        )
        # Should report missing items, not crash
        assert len(summary.missing_model) >= 1 or len(summary.unresolved_sound) >= 1


# ── ExtractionSummary ────────────────────────────────────────────────────────

class TestExtractionSummary:
    def test_dataclass_fields(self) -> None:
        summary = main.ExtractionSummary(
            missing_text=set(),
            missing_model=set(),
            unresolved_textures=set(),
            unresolved_sound=set(),
            out_of_bus_files=set(),
            texture_hook_results=[],
        )
        assert summary.missing_text == set()
        assert summary.texture_hook_results == []


# ── run_texture_extraction_if_available ───────────────────────────────────────

class TestRunTextureExtractionIfAvailable:
    def test_returns_skipped_when_no_entrypoint(
        self, mock_bus_root: Path, tmp_path: Path
    ) -> None:
        result = main.run_texture_extraction_if_available(
            mock_bus_root, tmp_path / "out", mock_bus_root / "test_bus.bus"
        )
        assert "skipped" in result


# ── print_summary ────────────────────────────────────────────────────────────

class TestPrintSummary:
    def test_prints_empty_summary(self, capsys: pytest.CaptureFixture[str]) -> None:
        summary = main.ExtractionSummary(
            missing_text=set(),
            missing_model=set(),
            unresolved_textures=set(),
            unresolved_sound=set(),
            out_of_bus_files=set(),
            texture_hook_results=[],
        )
        main.print_summary(summary)
        captured = capsys.readouterr()
        assert "Summary:" in captured.out
        assert "Missing text/config refs: 0" in captured.out

    def test_prints_with_items(self, capsys: pytest.CaptureFixture[str]) -> None:
        summary = main.ExtractionSummary(
            missing_text={"a.txt"},
            missing_model={"b.cfg"},
            unresolved_textures={"c.bmp"},
            unresolved_sound={"d.wav"},
            out_of_bus_files={"e.o3d"},
            texture_hook_results=["hook ran"],
        )
        main.print_summary(summary)
        captured = capsys.readouterr()
        assert "Missing text/config files:" in captured.out
        assert "Missing model references:" in captured.out
        assert "Unresolved texture tokens:" in captured.out
        assert "Unresolved sound tokens:" in captured.out
        assert "texture/file out of bus:" in captured.out
        assert "hook ran" in captured.out
