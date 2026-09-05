"""Tests for extract_text.py — text/config file extraction."""
from __future__ import annotations

from pathlib import Path

import extract_text


# ── get_bus_file ──────────────────────────────────────────────────────────────

class TestGetBusFile:
    def test_finds_bus_files(self, mock_bus_root: Path) -> None:
        result = extract_text.get_bus_file(str(mock_bus_root))
        assert len(result) == 1
        assert result[0].endswith("test_bus.bus")

    def test_empty_directory(self, tmp_path: Path) -> None:
        result = extract_text.get_bus_file(str(tmp_path))
        assert result == []

    def test_none_directory(self) -> None:
        result = extract_text.get_bus_file(None)
        assert result == []


# ── extract_bus_name ──────────────────────────────────────────────────────────

class TestExtractBusName:
    def test_extracts_filenames(self) -> None:
        paths = ["/a/b/c/foo.bus", "/x/y/bar.bus"]
        result = extract_text.extract_bus_name(paths)
        assert result == {"foo.bus", "bar.bus"}

    def test_empty_list(self) -> None:
        result = extract_text.extract_bus_name([])
        assert result == set()

    def test_none_list(self) -> None:
        result = extract_text.extract_bus_name(None)
        assert result == set()


# ── get_hof_name ──────────────────────────────────────────────────────────────

class TestGetHofName:
    def test_finds_hof_files(self, mock_bus_root: Path) -> None:
        result = extract_text.get_hof_name(str(mock_bus_root))
        assert result == {"TestBus.hof"}

    def test_empty_directory(self, tmp_path: Path) -> None:
        result = extract_text.get_hof_name(str(tmp_path))
        assert result == set()

    def test_none_directory(self) -> None:
        result = extract_text.get_hof_name(None)
        assert result == set()


# ── locate_bus_config_files ───────────────────────────────────────────────────

class TestLocateBusConfigFiles:
    def test_finds_cfg_and_txt(self, mock_bus_root: Path) -> None:
        bus_path = str(mock_bus_root / "test_bus.bus")
        result = extract_text.locate_bus_config_files(bus_path)
        # The .bus file references Model\test_model.cfg and Sound\sound.cfg
        assert "Model\\test_model.cfg" in result
        assert "Sound\\sound.cfg" in result

    def test_no_bus_file(self) -> None:
        result = extract_text.locate_bus_config_files("")
        assert result == set()

    def test_with_txt_and_org_extensions(self, tmp_path: Path) -> None:
        bus_file = tmp_path / "custom.bus"
        bus_file.write_text(
            "Config\\vars.txt\n"
            "Fleet\\register.org\n"
            "Model\\body.cfg\n"
            "Script\\move.osc\n"
            "ignored_image.bmp\n"
            "\n"
            "; comment line\n",
            encoding="utf-8",
        )
        result = extract_text.locate_bus_config_files(str(bus_file))
        assert result == {
            "Config\\vars.txt",
            "Fleet\\register.org",
            "Model\\body.cfg",
            "Script\\move.osc",
        }
        # .bmp should NOT be in the result
        assert all(not item.endswith(".bmp") for item in result)


# ── is_within_bus_root ────────────────────────────────────────────────────────

class TestIsWithinBusRoot:
    def test_within_root(self, mock_bus_root: Path) -> None:
        child = mock_bus_root / "Model" / "test_model.cfg"
        assert extract_text.is_within_bus_root(child, mock_bus_root) is True

    def test_outside_root(self, mock_bus_root: Path) -> None:
        outside = mock_bus_root.parent / "elsewhere" / "file.txt"
        assert extract_text.is_within_bus_root(outside, mock_bus_root) is False

    def test_root_itself(self, mock_bus_root: Path) -> None:
        assert extract_text.is_within_bus_root(mock_bus_root, mock_bus_root) is True


# ── get_bus_config_file ───────────────────────────────────────────────────────

class TestGetBusConfigFile:
    def test_copies_existing_files(self, mock_bus_root: Path, tmp_path: Path) -> None:
        output = tmp_path / "text_out"
        config_files = {"Model\\test_model.cfg", "Sound\\sound.cfg"}
        missing, out_of_bus = extract_text.get_bus_config_file(
            str(mock_bus_root), config_files, str(output)
        )
        assert missing == set()
        assert out_of_bus == set()
        # Verify files were actually copied
        assert (output / "Model" / "test_model.cfg").exists()
        assert (output / "Sound" / "sound.cfg").exists()

    def test_reports_missing_files(self, mock_bus_root: Path, tmp_path: Path) -> None:
        output = tmp_path / "text_out"
        config_files = {"Model\\nonexistent.cfg"}
        missing, out_of_bus = extract_text.get_bus_config_file(
            str(mock_bus_root), config_files, str(output)
        )
        assert "Model\\nonexistent.cfg" in missing
        assert out_of_bus == set()

    def test_reports_out_of_bus(self, mock_bus_root: Path, tmp_path: Path) -> None:
        output = tmp_path / "text_out"
        config_files = {"..\\..\\secret.txt"}
        missing, out_of_bus = extract_text.get_bus_config_file(
            str(mock_bus_root), config_files, str(output)
        )
        assert missing == set()
        assert "..\\..\\secret.txt" in out_of_bus

    def test_empty_config_set(self, mock_bus_root: Path, tmp_path: Path) -> None:
        output = tmp_path / "text_out"
        missing, out_of_bus = extract_text.get_bus_config_file(
            str(mock_bus_root), set(), str(output)
        )
        assert missing == set()
        assert out_of_bus == set()
        # Output dir should exist but be empty
        assert output.exists()
        assert list(output.iterdir()) == []


# ── End-to-end text extraction ────────────────────────────────────────────────

class TestEndToEndTextExtraction:
    def test_full_text_extraction(self, mock_bus_root: Path, tmp_path: Path) -> None:
        """Simulate what main.run_text_extraction does."""
        output = tmp_path / "text_out"

        # 1. Find .bus files
        bus_files = extract_text.get_bus_file(str(mock_bus_root))
        assert len(bus_files) == 1

        # 2. Locate config files referenced in each .bus
        all_config_files: set[str] = set()
        for bf in bus_files:
            all_config_files.update(extract_text.locate_bus_config_files(bf))

        # 3. Add bus names and hof names
        all_config_files.update(extract_text.extract_bus_name(bus_files))
        all_config_files.update(extract_text.get_hof_name(str(mock_bus_root)))

        # 4. Copy to output
        missing, out_of_bus = extract_text.get_bus_config_file(
            str(mock_bus_root), all_config_files, str(output)
        )

        # Verify key files were copied
        assert (output / "Model" / "test_model.cfg").exists()
        assert (output / "Sound" / "sound.cfg").exists()
        assert (output / "TestBus.hof").exists()
        assert (output / "test_bus.bus").exists()
        assert (output / "Config" / "test.txt").exists()
        assert (output / "Script" / "test.osc").exists()

        # No missing or out-of-bus files in our complete mock
        assert missing == set()
        assert out_of_bus == set()
