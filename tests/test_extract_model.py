"""Tests for extract_model.py — 3D model and texture extraction."""
from __future__ import annotations

from pathlib import Path

import extract_model


# ── normalize_rel_path ────────────────────────────────────────────────────────

class TestNormalizeRelPath:
    def test_strips_quotes(self) -> None:
        assert extract_model.normalize_rel_path('"foo\\bar.o3d"') == "foo\\bar.o3d"
        assert extract_model.normalize_rel_path("'foo\\bar.o3d'") == "foo\\bar.o3d"

    def test_forward_slash_to_backslash(self) -> None:
        assert extract_model.normalize_rel_path("foo/bar/baz.o3d") == "foo\\bar\\baz.o3d"

    def test_strips_leading_dot_slash(self) -> None:
        assert extract_model.normalize_rel_path(".\\foo\\bar.o3d") == "foo\\bar.o3d"
        assert extract_model.normalize_rel_path(".\\.\\foo\\bar.o3d") == "foo\\bar.o3d"

    def test_strips_whitespace(self) -> None:
        assert extract_model.normalize_rel_path("  foo.o3d  ") == "foo.o3d"

    def test_simple_name(self) -> None:
        assert extract_model.normalize_rel_path("body.bmp") == "body.bmp"

# ── extract_file_tokens ──────────────────────────────────────────────────────

class TestExtractFileTokens:
    def test_simple_cfg(self) -> None:
        tokens = extract_model.extract_file_tokens("test_model.cfg")
        assert tokens == ["test_model.cfg"]

    def test_simple_o3d(self) -> None:
        tokens = extract_model.extract_file_tokens("body.o3d")
        assert tokens == ["body.o3d"]

    def test_texture_extension(self) -> None:
        tokens = extract_model.extract_file_tokens("body.bmp")
        assert tokens == ["body.bmp"]

    def test_quoted_path(self) -> None:
        tokens = extract_model.extract_file_tokens('"Model\\test.o3d"')
        assert tokens == ["Model\\test.o3d"]

    def test_mixed_content_ignores_non_file_tokens(self) -> None:
        tokens = extract_model.extract_file_tokens("some_text other_stuff")
        assert tokens == []

    def test_multiple_tokens_on_line(self) -> None:
        # When a line starts with an unquoted token that has a valid extension,
        # extract_file_tokens treats the entire line as one token (whole-line path).
        tokens = extract_model.extract_file_tokens('foo.cfg "bar.o3d"')
        assert len(tokens) == 1
        assert ".o3d" in tokens[0]

    def test_multiple_quoted_tokens(self) -> None:
        # Two separately quoted tokens on the same line.
        # The tokenizer's whole-line check first: since the stripped line ends with
        # a valid extension (.o3d), the entire line is returned as one token.
        tokens = extract_model.extract_file_tokens('"foo.cfg" "bar.o3d"')
        assert len(tokens) == 1

    def test_two_separate_lines(self) -> None:
        # To get two tokens, use separate lines (realistic OMSI cfg usage)
        t1 = extract_model.extract_file_tokens("foo.cfg")
        t2 = extract_model.extract_file_tokens("bar.o3d")
        assert t1 == ["foo.cfg"]
        assert t2 == ["bar.o3d"]

    def test_strips_trailing_punctuation(self) -> None:
        tokens = extract_model.extract_file_tokens("test.cfg,")
        assert tokens == ["test.cfg"]

    def test_empty_line(self) -> None:
        tokens = extract_model.extract_file_tokens("")
        assert tokens == []

    def test_path_with_spaces_quoted(self) -> None:
        tokens = extract_model.extract_file_tokens('"my bus\\body.o3d"')
        assert tokens == ["my bus\\body.o3d"]


# ── extract_texture_tokens_from_binary ────────────────────────────────────────

class TestExtractTextureTokensFromBinary:
    def test_finds_pascal_prefixed_texture(self) -> None:
        from tests.conftest import _make_o3d_with_texture
        data = _make_o3d_with_texture("body.bmp")
        result = extract_model.extract_texture_tokens_from_binary(data)
        assert "body.bmp" in result

    def test_finds_multiple_textures(self) -> None:
        from tests.conftest import _make_o3d_with_texture
        data = (
            _make_o3d_with_texture("body.bmp")
            + b"\x00" * 20
            + _make_o3d_with_texture("interior.tga")
        )
        result = extract_model.extract_texture_tokens_from_binary(data)
        assert "body.bmp" in result
        assert "interior.tga" in result

    def test_empty_content(self) -> None:
        result = extract_model.extract_texture_tokens_from_binary(b"")
        assert result == set()

    def test_no_textures(self) -> None:
        result = extract_model.extract_texture_tokens_from_binary(b"no textures here at all")
        assert result == set()

    def test_strips_hb_prefix(self) -> None:
        # HB-prefixed strings should have the prefix trimmed
        from tests.conftest import _make_o3d_with_texture
        inner = _make_o3d_with_texture("body.bmp")
        data = b"HB" + inner
        result = extract_model.extract_texture_tokens_from_binary(data)
        # Should still find "body.bmp" (HB prefix trimmed)
        assert "body.bmp" in result


# ── parse_bus_for_model_cfgs ──────────────────────────────────────────────────

class TestParseBusForModelCfgs:
    def test_finds_model_cfg(self, mock_bus_root: Path) -> None:
        bus_file = mock_bus_root / "test_bus.bus"
        result = extract_model.parse_bus_for_model_cfgs(bus_file, mock_bus_root)
        assert len(result) == 1
        cfg = next(iter(result))
        assert cfg.name == "test_model.cfg"
        assert "Model" in cfg.parts

    def test_empty_bus_file(self, tmp_path: Path) -> None:
        bus_file = tmp_path / "empty.bus"
        bus_file.write_text("[sound]\nsound.cfg\n", encoding="utf-8")
        (tmp_path / "sound.cfg").write_text("", encoding="utf-8")
        result = extract_model.parse_bus_for_model_cfgs(bus_file, tmp_path)
        # No [model] section -> no model cfgs from primary path
        # Fallback also won't find any .cfg in "model" path
        assert result == set()

    def test_fallback_finds_model_cfgs(self, tmp_path: Path) -> None:
        """Fallback scans all lines for .cfg tokens in a 'model' directory.
        The code checks ``"model" in resolved.parts`` (lowercase), so the
        directory must be named ``model`` (lowercase) for the fallback to match."""
        bus_file = tmp_path / "test.bus"
        bus_file.write_text(
            "model\\helper.cfg\n",
            encoding="utf-8",
        )
        (tmp_path / "model").mkdir(parents=True, exist_ok=True)
        (tmp_path / "model" / "helper.cfg").write_text("", encoding="utf-8")
        result = extract_model.parse_bus_for_model_cfgs(bus_file, tmp_path)
        assert len(result) == 1
        assert next(iter(result)).name == "helper.cfg"


# ── parse_cfg_dependencies (BFS) ─────────────────────────────────────────────

class TestParseCfgDependencies:
    def test_bfs_discovers_nested_cfgs(self, mock_bus_root: Path) -> None:
        start_cfg = mock_bus_root / "Model" / "test_model.cfg"
        all_cfgs, all_o3d, missing, tex_tokens, oob = (
            extract_model.parse_cfg_dependencies({start_cfg}, mock_bus_root)
        )
        # test_model.cfg chains to sub/inner.cfg
        cfg_names = {c.name for c in all_cfgs}
        assert "test_model.cfg" in cfg_names
        assert "inner.cfg" in cfg_names

    def test_discovers_o3d_files(self, mock_bus_root: Path) -> None:
        start_cfg = mock_bus_root / "Model" / "test_model.cfg"
        all_cfgs, all_o3d, missing, tex_tokens, oob = (
            extract_model.parse_cfg_dependencies({start_cfg}, mock_bus_root)
        )
        o3d_names = {o.name for o in all_o3d}
        assert "test.o3d" in o3d_names

    def test_collects_texture_tokens(self, mock_bus_root: Path) -> None:
        start_cfg = mock_bus_root / "Model" / "test_model.cfg"
        all_cfgs, all_o3d, missing, tex_tokens, oob = (
            extract_model.parse_cfg_dependencies({start_cfg}, mock_bus_root)
        )
        # test_model.cfg references body.bmp and Texture\interior.tga
        # inner.cfg references Texture\logos\brand.png
        assert "body.bmp" in tex_tokens
        assert "Texture\\interior.tga" in tex_tokens
        assert "Texture\\logos\\brand.png" in tex_tokens

    def test_missing_references_reported(self, mock_bus_root_missing: Path) -> None:
        start_cfg = mock_bus_root_missing / "Model" / "missing_model.cfg"
        all_cfgs, all_o3d, missing, tex_tokens, oob = (
            extract_model.parse_cfg_dependencies({start_cfg}, mock_bus_root_missing)
        )
        # nonexistent.o3d and ghost.bmp should be reported as missing
        assert len(missing) >= 1
        # At least "nonexistent.o3d" should be in missing
        assert any("nonexistent.o3d" in m for m in missing)


# ── build_texture_index ──────────────────────────────────────────────────────

class TestBuildTextureIndex:
    def test_indexes_textures(self, mock_bus_root: Path) -> None:
        texture_root = mock_bus_root / "Texture"
        by_relpath, by_basename = extract_model.build_texture_index(texture_root)
        # body.bmp should be indexed
        assert "body.bmp" in by_relpath
        assert "body.bmp" in by_basename
        # interior.tga
        assert "interior.tga" in by_relpath
        # logos/brand.png
        assert "logos/brand.png" in by_relpath
        assert "brand.png" in by_basename

    def test_empty_texture_dir(self, tmp_path: Path) -> None:
        texture_root = tmp_path / "Texture"
        texture_root.mkdir()
        by_relpath, by_basename = extract_model.build_texture_index(texture_root)
        assert by_relpath == {}
        assert by_basename == {}

    def test_nonexistent_dir(self, tmp_path: Path) -> None:
        texture_root = tmp_path / "nonexistent"
        by_relpath, by_basename = extract_model.build_texture_index(texture_root)
        assert by_relpath == {}
        assert by_basename == {}


# ── resolve_texture_token ────────────────────────────────────────────────────

class TestResolveTextureToken:
    def test_resolve_by_basename(self, mock_bus_root: Path) -> None:
        texture_root = mock_bus_root / "Texture"
        by_relpath, by_basename = extract_model.build_texture_index(texture_root)
        result = extract_model.resolve_texture_token(
            "body.bmp", texture_root, by_relpath, by_basename, mock_bus_root
        )
        assert len(result) >= 1
        assert any(p.name == "body.bmp" for p in result)

    def test_resolve_by_relative_path(self, mock_bus_root: Path) -> None:
        texture_root = mock_bus_root / "Texture"
        by_relpath, by_basename = extract_model.build_texture_index(texture_root)
        result = extract_model.resolve_texture_token(
            "Texture\\interior.tga", texture_root, by_relpath, by_basename, mock_bus_root
        )
        assert len(result) >= 1
        assert any(p.name == "interior.tga" for p in result)

    def test_unresolved_token(self, mock_bus_root: Path) -> None:
        texture_root = mock_bus_root / "Texture"
        by_relpath, by_basename = extract_model.build_texture_index(texture_root)
        result = extract_model.resolve_texture_token(
            "nonexistent.bmp", texture_root, by_relpath, by_basename, mock_bus_root
        )
        assert result == set()


# ── gather_textures ──────────────────────────────────────────────────────────

class TestGatherTextures:
    def test_gathers_from_cfg_and_o3d(self, mock_bus_root: Path) -> None:
        texture_root = mock_bus_root / "Texture"
        cfg_tokens = {"body.bmp", "Texture\\interior.tga"}
        o3d_files = {mock_bus_root / "Model" / "test.o3d"}
        resolved, unresolved, oob = extract_model.gather_textures(
            texture_root, cfg_tokens, o3d_files, mock_bus_root
        )
        # Both cfg-referenced textures and o3d-referenced textures should resolve
        resolved_names = {p.name for p in resolved}
        assert "body.bmp" in resolved_names
        assert "interior.tga" in resolved_names
        # Note: brand.png is from inner.cfg (a nested dependency) and is NOT in
        # the explicit cfg_tokens passed here, so it won't be resolved. The BFS
        # in parse_cfg_dependencies collects those tokens; gather_textures only
        # processes what it receives.
        assert unresolved == set()

    def test_unresolved_tokens(self, mock_bus_root: Path) -> None:
        texture_root = mock_bus_root / "Texture"
        cfg_tokens = {"ghost.bmp"}
        o3d_files = set()
        resolved, unresolved, oob = extract_model.gather_textures(
            texture_root, cfg_tokens, o3d_files, mock_bus_root
        )
        assert resolved == set()
        assert "ghost.bmp" in unresolved


# ── copy_files_to_output ─────────────────────────────────────────────────────

class TestCopyFilesToOutput:
    def test_copies_files_preserving_structure(self, mock_bus_root: Path, tmp_path: Path) -> None:
        output = tmp_path / "model_out"
        files = {
            mock_bus_root / "Model" / "test_model.cfg",
            mock_bus_root / "Model" / "test.o3d",
            mock_bus_root / "Texture" / "body.bmp",
        }
        extract_model.copy_files_to_output(files, mock_bus_root, output)
        assert (output / "Model" / "test_model.cfg").exists()
        assert (output / "Model" / "test.o3d").exists()
        assert (output / "Texture" / "body.bmp").exists()

    def test_skips_out_of_bus_files(self, mock_bus_root: Path, tmp_path: Path) -> None:
        output = tmp_path / "model_out"
        oob_file = mock_bus_root.parent / "outside" / "escape.o3d"
        oob_file.parent.mkdir(parents=True)
        oob_file.write_bytes(b"\x00")
        oob_set: set[str] = set()
        extract_model.copy_files_to_output(
            {oob_file}, mock_bus_root, output, out_of_bus=oob_set
        )
        assert not list(output.iterdir())
        assert len(oob_set) >= 1


# ── resolve_existing_path ────────────────────────────────────────────────────

class TestResolveExistingPath:
    def test_finds_relative_to_base(self, mock_bus_root: Path) -> None:
        result = extract_model.resolve_existing_path(
            "Model\\test_model.cfg",
            mock_bus_root,
            mock_bus_root,
        )
        assert result is not None
        assert result.name == "test_model.cfg"

    def test_finds_relative_to_bus_root(self, mock_bus_root: Path) -> None:
        result = extract_model.resolve_existing_path(
            "Model\\test.o3d",
            mock_bus_root / "Model",
            mock_bus_root,
            model_root=mock_bus_root / "Model",
        )
        assert result is not None
        assert result.name == "test.o3d"

    def test_returns_none_for_missing(self, mock_bus_root: Path) -> None:
        result = extract_model.resolve_existing_path(
            "ghost.o3d",
            mock_bus_root,
            mock_bus_root,
        )
        assert result is None

    def test_leading_slash_resolves_from_model_root(self, mock_bus_root: Path) -> None:
        result = extract_model.resolve_existing_path(
            "\\test.o3d",
            mock_bus_root,
            mock_bus_root,
            model_root=mock_bus_root / "Model",
        )
        assert result is not None
        assert result.name == "test.o3d"


# ── find_first_bus_file ──────────────────────────────────────────────────────

class TestFindFirstBusFile:
    def test_finds_bus_file(self, mock_bus_root: Path) -> None:
        result = extract_model.find_first_bus_file(mock_bus_root)
        assert result.name == "test_bus.bus"

    def test_raises_when_none(self, tmp_path: Path) -> None:
        import pytest
        with pytest.raises(FileNotFoundError):
            extract_model.find_first_bus_file(tmp_path)


# ── is_within_bus_root ────────────────────────────────────────────────────────

class TestIsWithinBusRoot:
    def test_within(self, mock_bus_root: Path) -> None:
        assert extract_model.is_within_bus_root(
            mock_bus_root / "Model" / "test.o3d", mock_bus_root
        ) is True

    def test_outside(self, mock_bus_root: Path) -> None:
        outside = mock_bus_root.parent / "other" / "file.txt"
        assert extract_model.is_within_bus_root(outside, mock_bus_root) is False


# ── End-to-end model extraction ──────────────────────────────────────────────

class TestEndToEndModelExtraction:
    def test_full_pipeline(self, mock_bus_root: Path, tmp_path: Path) -> None:
        """Run the complete model extraction pipeline on mock data."""
        output = tmp_path / "model_out"
        bus_file = mock_bus_root / "test_bus.bus"
        texture_root = mock_bus_root / "Texture"

        # 1. Parse .bus for model cfgs
        model_cfgs = extract_model.parse_bus_for_model_cfgs(bus_file, mock_bus_root)
        assert len(model_cfgs) == 1

        # 2. BFS dependency walk
        all_cfgs, all_o3d, missing, cfg_tex_tokens, oob = (
            extract_model.parse_cfg_dependencies(model_cfgs, mock_bus_root)
        )
        assert len(all_cfgs) == 2  # test_model.cfg + inner.cfg
        assert len(all_o3d) == 1   # test.o3d

        # 3. Gather textures
        textures, unresolved, tex_oob = extract_model.gather_textures(
            texture_root, cfg_tex_tokens, all_o3d, mock_bus_root
        )
        assert len(textures) == 3  # body.bmp, interior.tga, brand.png
        assert unresolved == set()

        # 4. Copy everything to output
        files_to_copy = all_cfgs | all_o3d | textures
        extract_model.copy_files_to_output(
            files_to_copy, mock_bus_root, output, out_of_bus=oob
        )

        # Verify output structure
        assert (output / "Model" / "test_model.cfg").exists()
        assert (output / "Model" / "sub" / "inner.cfg").exists()
        assert (output / "Model" / "test.o3d").exists()
        assert (output / "Texture" / "body.bmp").exists()
        assert (output / "Texture" / "interior.tga").exists()
        assert (output / "Texture" / "logos" / "brand.png").exists()

    def test_pipeline_with_missing_files(self, mock_bus_root_missing: Path, tmp_path: Path) -> None:
        """Pipeline handles missing references gracefully."""
        output = tmp_path / "model_out"
        bus_file = mock_bus_root_missing / "test_bus.bus"

        model_cfgs = extract_model.parse_bus_for_model_cfgs(
            bus_file, mock_bus_root_missing
        )
        assert len(model_cfgs) == 1

        all_cfgs, all_o3d, missing, cfg_tex_tokens, oob = (
            extract_model.parse_cfg_dependencies(model_cfgs, mock_bus_root_missing)
        )
        # The referenced files don't exist -> reported as missing
        assert len(missing) >= 1
        # No files to copy (nothing was resolved)
        assert all_o3d == set()
