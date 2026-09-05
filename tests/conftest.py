"""Shared pytest fixtures that build synthetic OMSI bus addon folder structures.

All test data is generated programmatically. No real OMSI game assets are used.
"""
from __future__ import annotations

import struct
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helper: build a Pascal-length-prefixed texture string for .o3d binaries
# ---------------------------------------------------------------------------

def _make_o3d_with_texture(texture_name: str) -> bytes:
    """Return a minimal .o3d binary blob that encodes *texture_name* using a
    Pascal-style 1-byte length prefix (the format OMSI / Delphi uses).

    The encoder in ``extract_model.extract_texture_tokens_from_binary`` scans
    backward from a known extension to find a byte whose value equals the
    distance from the candidate start to the end of the extension.  We place
    the length byte immediately before the string so the math lines up.
    """
    name_bytes = texture_name.encode("ascii")
    length_byte = bytes([len(name_bytes)])
    # Pad before so the length-byte is not at offset 0 (the parser requires
    # ``start_pos > 0``).
    padding = b"\x00" * 8
    trailing = b"\x00" * 8
    return padding + length_byte + name_bytes + trailing


# ---------------------------------------------------------------------------
# Tiny valid file contents
# ---------------------------------------------------------------------------

TINY_WAV_HEADER = (
    b"RIFF"
    + struct.pack("<I", 36)          # file size - 8
    + b"WAVE"
    + b"fmt "
    + struct.pack("<I", 16)          # chunk size
    + struct.pack("<HHIIHH", 1, 1, 44100, 88200, 2, 16)
    + b"data"
    + struct.pack("<I", 0)           # data chunk size (no actual audio)
)


def _write(path: Path, content: bytes | str = "") -> Path:
    """Write *content* to *path*, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_bytes(content)
    return path


# ---------------------------------------------------------------------------
# Primary fixture: a complete minimal bus addon
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_bus_root(tmp_path: Path) -> Path:
    """Build a synthetic OMSI bus addon folder with the following layout::

        <tmp_path>/
          test_bus.bus          # main bus definition
          TestBus.hof           # destination display config
          TestBus.org           # organisation / registration
          Config/test.txt       # generic config text file
          Script/test.osc       # OMSI script
          Model/
            test_model.cfg      # model config -> references test.o3d + texture
            sub/inner.cfg       # nested cfg referenced by test_model.cfg
            test.o3d            # binary 3D model (contains texture ref)
          Texture/
            body.bmp            # body texture
            interior.tga        # interior texture
            logos/brand.png     # nested texture
          Sound/
            sound.cfg           # sound config -> references engine.wav
            engine.wav          # engine audio sample
            sub/nested.wav      # nested audio

    The .bus file references ``Model/test_model.cfg`` under ``[model]`` and
    ``Sound/sound.cfg`` under ``[sound]``.  ``test_model.cfg`` in turn
    references ``sub/inner.cfg`` (a nested dependency) and ``test.o3d`` and
    two texture filenames.  ``inner.cfg`` references another texture.
    """
    root = tmp_path / "mock_bus"
    root.mkdir()

    # -- .bus file ----------------------------------------------------------
    # The text extractor reads with ANSI encoding; the model/sound extractors
    # read with utf-8 + errors="ignore".  Plain ASCII works for both.
    _write(root / "test_bus.bus", (
        "[model]\n"
        "Model\\test_model.cfg\n"
        "\n"
        "[sound]\n"
        "Sound\\sound.cfg\n"
        "\n"
        "[sound_ai]\n"
        "\n"
        "Config\\test.txt\n"
        "Script\\test.osc\n"
        "TestBus.org\n"
        "\n"
        "; this is a comment\n"
        "// this is also a comment\n"
    ))

    # -- .hof / .org / .osc / .txt -----------------------------------------
    _write(root / "TestBus.hof", "hof content")
    _write(root / "TestBus.org", "org content")
    _write(root / "Script" / "test.osc", "osc content")
    _write(root / "Config" / "test.txt", "config content")

    # -- Model configs ------------------------------------------------------
    # test_model.cfg references:
    #   - sub/inner.cfg (nested dependency)
    #   - test.o3d       (3D model)
    #   - body.bmp       (texture by relative name)
    #   - Texture\\interior.tga  (texture with leading Texture\ prefix)
    _write(root / "Model" / "test_model.cfg", (
        "sub\\inner.cfg\n"
        "test.o3d\n"
        "body.bmp\n"
        "Texture\\interior.tga\n"
    ))

    # inner.cfg references one more texture to test BFS chain
    _write(root / "Model" / "sub" / "inner.cfg", (
        "Texture\\logos\\brand.png\n"
    ))

    # -- .o3d binary (contains a Pascal-encoded texture reference) ----------
    o3d_data = _make_o3d_with_texture("body.bmp")
    _write(root / "Model" / "test.o3d", o3d_data)

    # -- Textures -----------------------------------------------------------
    _write(root / "Texture" / "body.bmp", b"\x42\x4D" + b"\x00" * 10)
    _write(root / "Texture" / "interior.tga", b"\x00" * 12)
    _write(root / "Texture" / "logos" / "brand.png", b"\x89PNG" + b"\x00" * 8)

    # -- Sound --------------------------------------------------------------
    _write(root / "Sound" / "sound.cfg", "engine.wav\n")
    _write(root / "Sound" / "engine.wav", TINY_WAV_HEADER)
    _write(root / "Sound" / "sub" / "nested.wav", TINY_WAV_HEADER)

    return root


@pytest.fixture()
def output_dir(tmp_path: Path) -> Path:
    """A clean output directory for extraction results."""
    out = tmp_path / "output"
    out.mkdir()
    return out


# ---------------------------------------------------------------------------
# Edge-case fixture: bus root with missing / out-of-bus references
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_bus_root_missing(tmp_path: Path) -> Path:
    """A bus addon where some referenced files do not exist on disk."""
    root = tmp_path / "mock_bus_missing"
    root.mkdir()

    _write(root / "test_bus.bus", (
        "[model]\n"
        "Model\\missing_model.cfg\n"
        "\n"
        "[sound]\n"
        "Sound\\missing_sound.cfg\n"
    ))

    # Model config references a file that does NOT exist
    _write(root / "Model" / "missing_model.cfg", (
        "nonexistent.o3d\n"
        "ghost.bmp\n"
    ))

    # Sound config references a file that does NOT exist
    _write(root / "Sound" / "missing_sound.cfg", (
        "ghost.wav\n"
    ))

    return root


# ---------------------------------------------------------------------------
# Edge-case fixture: out-of-bus references (paths escaping the root)
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_bus_root_out_of_bus(tmp_path: Path) -> Path:
    """A bus addon that references paths outside the bus root."""
    root = tmp_path / "mock_bus_oob"
    root.mkdir()

    # The .bus file points to a model cfg using an absolute or upward path
    _write(root / "test_bus.bus", (
        "[model]\n"
        "Model\\oob_model.cfg\n"
    ))

    # The cfg references a path that escapes the bus root
    _write(root / "Model" / "oob_model.cfg", (
        "..\\..\\outside\\secret.o3d\n"
    ))

    return root


# ---------------------------------------------------------------------------
# Edge-case fixture: nested sound dependencies (cfg -> cfg -> audio)
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_bus_root_nested_sound(tmp_path: Path) -> Path:
    """A bus addon with chained sound config dependencies."""
    root = tmp_path / "mock_bus_nested_sound"
    root.mkdir()

    _write(root / "test_bus.bus", (
        "[sound]\n"
        "Sound\\main_sound.cfg\n"
    ))

    # main_sound.cfg chains to sub_sound.cfg
    _write(root / "Sound" / "main_sound.cfg", (
        "sub\\sub_sound.cfg\n"
    ))

    _write(root / "Sound" / "sub" / "sub_sound.cfg", (
        "engine.wav\n"
    ))

    _write(root / "Sound" / "engine.wav", TINY_WAV_HEADER)

    return root


# ---------------------------------------------------------------------------
# Edge-case fixture: multiple bus files
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_bus_root_multi(tmp_path: Path) -> Path:
    """A bus addon with two .bus files to test multi-bus extraction."""
    root = tmp_path / "mock_bus_multi"
    root.mkdir()

    _write(root / "bus_a.bus", (
        "[model]\n"
        "Model\\model_a.cfg\n"
        "\n"
        "[sound]\n"
        "Sound\\sound_a.cfg\n"
    ))

    _write(root / "bus_b.bus", (
        "[model]\n"
        "Model\\model_b.cfg\n"
        "\n"
        "[sound]\n"
        "Sound\\sound_b.cfg\n"
    ))

    _write(root / "Model" / "model_a.cfg", "model_a.o3d\nbody.bmp\n")
    _write(root / "Model" / "model_b.cfg", "model_b.o3d\nbody.bmp\n")
    _write(root / "Model" / "model_a.o3d", _make_o3d_with_texture("body.bmp"))
    _write(root / "Model" / "model_b.o3d", _make_o3d_with_texture("body.bmp"))

    _write(root / "Texture" / "body.bmp", b"\x42\x4D" + b"\x00" * 10)

    _write(root / "Sound" / "sound_a.cfg", "engine.wav\n")
    _write(root / "Sound" / "sound_b.cfg", "engine.wav\n")
    _write(root / "Sound" / "engine.wav", TINY_WAV_HEADER)

    return root
