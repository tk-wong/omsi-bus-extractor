from __future__ import annotations

import argparse
import os
import shutil
from collections import defaultdict
from pathlib import Path
import struct


MODEL_EXTENSIONS = {".o3d", ".cfg"}
TEXTURE_EXTENSIONS = {".bmp", ".dds", ".jpg", ".jpeg", ".png", ".tga"}
TOKEN_EXTENSIONS = MODEL_EXTENSIONS | TEXTURE_EXTENSIONS


def normalize_rel_path(path_text: str) -> str:
    text = path_text.strip().strip('"').strip("'").replace("/", "\\")
    while text.startswith(".\\"):
        text = text[2:]
    return text


def is_within_bus_root(path: Path, bus_root: Path) -> bool:
    try:
        path.resolve().relative_to(bus_root.resolve())
        return True
    except ValueError:
        return False


def resolve_within_bus_root(candidate: Path, bus_root: Path) -> Path | None:
    resolved = candidate.resolve()
    if is_within_bus_root(resolved, bus_root):
        return resolved
    return None


def _maybe_add_token(chunk: str, out_tokens: list[str]) -> None:
    token = chunk.strip().strip('"').strip("'")
    if not token:
        return
    token = token.rstrip(",;)")
    suffix = Path(token).suffix.lower()
    if suffix in TOKEN_EXTENSIONS:
        out_tokens.append(token)


def extract_file_tokens(line: str) -> list[str]:
    # Prefer whole-line path first to support unquoted names with spaces,
    line_token = line.strip().strip('"').strip("'").rstrip(",;)")
    if line_token and Path(line_token).suffix.lower() in TOKEN_EXTENSIONS:
        return [line_token]

    tokens: list[str] = []
    chunk_chars: list[str] = []
    in_quote = False
    quote_char = ""

    for char in line:
        if in_quote:
            if char == quote_char:
                _maybe_add_token("".join(chunk_chars), tokens)
                chunk_chars = []
                in_quote = False
                quote_char = ""
            else:
                chunk_chars.append(char)
            continue

        if char in {'"', "'"}:
            _maybe_add_token("".join(chunk_chars), tokens)
            chunk_chars = []
            in_quote = True
            quote_char = char
            continue

        if char.isspace():
            _maybe_add_token("".join(chunk_chars), tokens)
            chunk_chars = []
            continue

        chunk_chars.append(char)

    _maybe_add_token("".join(chunk_chars), tokens)
    return tokens


def extract_texture_tokens_from_binary(content: bytes | str) -> set[str]:
    """Parses .o3d binary content by scanning for Pascal-style string length

    prefixes and material tags to avoid capturing chunk markers like 'HB' or
    'HC'.
    """
    if isinstance(content, str):
        content_bytes = content.encode("latin-1", errors="ignore")
    else:
        content_bytes = content

    matches: set[str] = set()
    length = len(content_bytes)

    for ext in TEXTURE_EXTENSIONS:
        ext_bytes = ext.encode("ascii")
        ext_len = len(ext_bytes)
        search_from = 0

        while True:
            # Find the extension in the binary stream (case-insensitive search)
            idx = content_bytes.lower().find(ext_bytes, search_from)
            if idx == -1:
                break

            # In Pascal strings (used by Delphi/OMSI), 1 byte before the string specifies its length.
            # We test potential string lengths around the match position.
            end_pos = idx + ext_len

            # Check candidate starting points backward from the match
            for start_pos in range(max(0, idx - 255), idx):
                str_len = end_pos - start_pos

                # Verify if the byte immediately preceding start_pos matches str_len
                if start_pos > 0 and content_bytes[start_pos - 1] == str_len:
                    candidate_bytes = content_bytes[start_pos:end_pos]

                    try:
                        decoded = candidate_bytes.decode("ascii").strip()
                        cleaned = normalize_rel_path(decoded)

                        if (
                            cleaned
                            and Path(cleaned).suffix.lower()
                            in TEXTURE_EXTENSIONS
                        ):
                            matches.add(cleaned)
                            break  # Found exact length-prefixed string match
                    except UnicodeDecodeError:
                        continue

            search_from = idx + ext_len

    # Fallback/Safety Net: If length-prefix matching yielded nothing,
    # strip known 2-letter chunk prefixes like HB, HC, etc., followed by garbage bytes
    cleaned_matches: set[str] = set()
    for match in matches:
        # Trim leading garbage if it matched HB/HC markers
        clean_name = match
        if len(clean_name) > 3 and clean_name[:2] in {"HB", "HC"}:
            clean_name = clean_name[2:].lstrip(" \t\x00\x01\x02\x03\x04\x05'\"")

        cleaned_matches.add(clean_name)

    return cleaned_matches

def _parse_blender_o3d(buff: bytes, header_idx: int) -> set[str]:
    """Fallback handler for Blender-generated OMSIS3D files."""
    offset = header_idx + 7
    if offset < len(buff) and buff[offset] in (0x00, 0x0A, 0x0D):
        offset += 1

    version, num_sections = struct.unpack_from("<HH", buff, offset=offset)
    offset += 4
    l_header = version >= 3
    if l_header:
        offset += 5

    textures = set()
    for _ in range(num_sections):
        if offset >= len(buff):
            break
        sec_type = buff[offset]
        offset += 1

        if sec_type == 0x17:
            num = struct.unpack_from("<I" if l_header else "<H", buff, offset)[0]
            offset += (4 if l_header else 2) + (num * 32)
        elif sec_type == 0x18:
            num = struct.unpack_from("<I" if l_header else "<H", buff, offset)[0]
            offset += (4 if l_header else 2) + (num * 6)
        elif sec_type == 0x19:
            num_mats = struct.unpack_from("<H", buff, offset)[0]
            offset += 2
            for _ in range(num_mats):
                offset += 44  # Skip color floats
                path_len = buff[offset]
                offset += 1
                if path_len > 0:
                    raw = buff[offset : offset + path_len]
                    offset += path_len
                    tex = raw.decode("cp1252", errors="ignore").strip().replace("/", "\\")
                    if tex:
                        textures.add(tex)
        elif sec_type == 0x1A:
            num = struct.unpack_from("<I" if l_header else "<H", buff, offset)[0]
            offset += (4 if l_header else 2)
            for _ in range(num):
                b_len = buff[offset]
                offset += 1 + b_len
                weights = struct.unpack_from("<H", buff, offset)[0]
                offset += 2 + (weights * 6)
        elif sec_type == 0x1B:
            offset += 64

    return textures

def find_first_bus_file(bus_root: Path) -> Path:
    bus_files = sorted(bus_root.glob("*.bus"))
    if not bus_files:
        raise FileNotFoundError(f"No .bus file found in: {bus_root}")
    return bus_files[0]


def resolve_existing_path(
        raw_path: str,
        base_dir: Path,
        bus_root: Path,
        model_root: Path | None = None,
        out_of_bus: set[str] | None = None,
) -> Path | None:
    raw_rel = normalize_rel_path(raw_path)
    candidate_values = []

    raw_path_obj = Path(raw_rel)
    if raw_path_obj.is_absolute():
        candidate_values.append(raw_path_obj)

    # A leading slash in OMSI cfg frequently means "from Model folder".
    leading_root_style = raw_rel.startswith("\\")
    rel_no_lead = raw_rel.lstrip("\\")

    if not leading_root_style:
        candidate_values.append(base_dir / raw_rel)

    if model_root is not None:
        candidate_values.append(model_root / rel_no_lead)

    candidate_values.append(bus_root / rel_no_lead)
    candidate_values.append(bus_root / "Model" / rel_no_lead)
    candidate_values.append(base_dir / rel_no_lead)

    checked = set()
    any_within_bus = False
    for candidate in candidate_values:
        resolved = candidate.resolve()
        if resolved in checked:
            continue
        checked.add(resolved)
        if not is_within_bus_root(resolved, bus_root):
            continue
        any_within_bus = True
        if resolved.exists() and resolved.is_file():
            return resolved
    if not any_within_bus and out_of_bus is not None:
        out_of_bus.add(raw_rel)
    return None


def parse_bus_for_model_cfgs(bus_file: Path, bus_root: Path) -> set[Path]:
    model_cfgs: set[Path] = set()

    lines = bus_file.read_text(encoding="utf-8", errors="ignore").splitlines()
    expecting_model_path = False

    for line in lines:
        stripped = line.strip()
        lowered = stripped.lower()

        if lowered == "[model]":
            expecting_model_path = True
            continue

        if expecting_model_path:
            candidate = resolve_existing_path(
                stripped, bus_file.parent, bus_root)
            if candidate and candidate.suffix.lower() == ".cfg":
                model_cfgs.add(candidate)
            expecting_model_path = False

    # Fallback: collect model cfg references from all bus lines.
    for line in lines:
        for token in extract_file_tokens(line):
            if Path(token).suffix.lower() != ".cfg":
                continue
            resolved = resolve_existing_path(token, bus_file.parent, bus_root)
            if resolved and "model" in resolved.parts:
                model_cfgs.add(resolved)

    return model_cfgs


def parse_cfg_dependencies(
        start_cfgs: set[Path],
        bus_root: Path,
) -> tuple[set[Path], set[Path], list[str], set[str], set[str]]:
    all_cfgs: set[Path] = set()
    all_o3d: set[Path] = set()
    missing_paths: list[str] = []
    cfg_texture_tokens: set[str] = set()
    out_of_bus: set[str] = set()

    queue = sorted(start_cfgs)
    seen_cfgs: set[Path] = set()

    while queue:
        cfg_file = queue.pop(0)
        cfg_file = cfg_file.resolve()
        if cfg_file in seen_cfgs:
            continue
        seen_cfgs.add(cfg_file)
        all_cfgs.add(cfg_file)

        model_root = cfg_file.parent
        lines = cfg_file.read_text(
            encoding="utf-8", errors="ignore").splitlines()
        for line in lines:
            for token in extract_file_tokens(line):
                suffix = Path(token).suffix.lower()
                if suffix not in TOKEN_EXTENSIONS:
                    continue

                if suffix in TEXTURE_EXTENSIONS:
                    cfg_texture_tokens.add(token)
                    continue

                resolved = resolve_existing_path(
                    token,
                    cfg_file.parent,
                    bus_root,
                    model_root=model_root,
                    out_of_bus=out_of_bus,
                )
                if resolved is None:
                    missing_paths.append(f"{cfg_file.name}: {token}")
                    continue

                if suffix == ".o3d":
                    all_o3d.add(resolved)
                elif suffix == ".cfg" and resolved not in seen_cfgs:
                    queue.append(resolved)

    return all_cfgs, all_o3d, missing_paths, cfg_texture_tokens, out_of_bus


def build_texture_index(texture_root: Path) -> tuple[dict[str, Path], dict[str, list[Path]]]:
    by_relpath: dict[str, Path] = {}
    by_basename: dict[str, list[Path]] = defaultdict(list)

    if not texture_root.exists():
        return by_relpath, by_basename

    for file_path in texture_root.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in TEXTURE_EXTENSIONS:
            continue

        rel = file_path.relative_to(texture_root).as_posix().lower()
        by_relpath[rel] = file_path
        by_basename[file_path.name.lower()].append(file_path)

    return by_relpath, by_basename


def resolve_texture_token(
        token: str,
        texture_root: Path,
        by_relpath: dict[str, Path],
        by_basename: dict[str, list[Path]],
        bus_root: Path,
        out_of_bus: set[str] | None = None,
) -> set[Path]:
    normalized = normalize_rel_path(token)
    normalized = normalized.lstrip("\\")
    lower_rel = normalized.replace("\\", "/").lower()
    file_name = Path(normalized).name.lower()
    candidates: set[Path] = set()

    if lower_rel.startswith("texture/"):
        lower_rel = lower_rel[len("texture/"):]

    rel_match = by_relpath.get(lower_rel)
    if rel_match:
        candidates.add(rel_match)

    direct_path = (texture_root / normalized).resolve()
    if not is_within_bus_root(direct_path, bus_root):
        if out_of_bus is not None:
            out_of_bus.add(normalized)
    elif direct_path.exists() and direct_path.is_file():
        candidates.add(direct_path)

    # Fallback by filename if relative path was not found.
    if file_name in by_basename:
        for item in by_basename[file_name]:
            candidates.add(item)

    return candidates


def parse_o3d_textures(o3d_file: Path) -> set[str]:
    data = o3d_file.read_bytes()
    ascii_text = data.decode("latin-1", errors="ignore")
    return extract_texture_tokens_from_binary(ascii_text)


def gather_textures(
        texture_root: Path,
        cfg_texture_tokens: set[str],
        o3d_files: set[Path],
        bus_root: Path,
) -> tuple[set[Path], set[str], set[str]]:
    by_relpath, by_basename = build_texture_index(texture_root)
    all_tokens: set[str] = set(cfg_texture_tokens)
    unresolved: set[str] = set()
    out_of_bus: set[str] = set()
    resolved_textures: set[Path] = set()

    for o3d_file in o3d_files:
        all_tokens.update(parse_o3d_textures(o3d_file))

    for token in sorted(all_tokens):
        if Path(token).suffix.lower() not in TEXTURE_EXTENSIONS:
            continue
        matches = resolve_texture_token(
            token,
            texture_root,
            by_relpath,
            by_basename,
            bus_root,
            out_of_bus=out_of_bus,
        )
        if not matches:
            unresolved.add(token)
            continue
        resolved_textures.update(matches)

    return resolved_textures, unresolved, out_of_bus


def print_relative_file_list(title: str, files: set[Path], bus_root: Path) -> None:
    print(f"\n{title} ({len(files)}):")
    for file_path in sorted(files):
        print(f"  {file_path.relative_to(bus_root).as_posix()}")


def copy_files_to_output(
        files: set[Path],
        bus_root: Path,
        output_dir: Path,
        out_of_bus: set[str] | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for source in files:
        if not is_within_bus_root(source, bus_root):
            if out_of_bus is not None:
                out_of_bus.add(str(source))
            continue
        relative = source.relative_to(bus_root)
        target = output_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract OMSI bus model and texture dependencies."
    )
    parser.add_argument(
        "--bus-root",
        default="ADL_Enviro500MMC_N32&N34_2025ver",
        help="Bus folder containing .bus, Model and Texture directories.",
    )
    parser.add_argument(
        "--bus-file",
        default=None,
        help="Optional .bus file path. If omitted, the first .bus in --bus-root is used.",
    )
    parser.add_argument(
        "--output",
        default="extracted",
        help="Output folder to copy extracted files to.",
    )
    args = parser.parse_args()

    workspace_root = Path.cwd()
    bus_root = (workspace_root / args.bus_root).resolve()

    if not bus_root.exists() or not bus_root.is_dir():
        raise FileNotFoundError(f"Bus root does not exist: {bus_root}")

    if args.bus_file:
        bus_file = Path(args.bus_file)
        if not bus_file.is_absolute():
            bus_file = (bus_root / bus_file).resolve()
        if not bus_file.exists():
            raise FileNotFoundError(f"Bus file does not exist: {bus_file}")
    else:
        bus_file = find_first_bus_file(bus_root)

    texture_root = bus_root / "Texture"
    output_dir = (workspace_root / args.output).resolve()

    model_cfgs = parse_bus_for_model_cfgs(bus_file, bus_root)
    if not model_cfgs:
        raise RuntimeError(f"No model cfg references found in: {bus_file}")

    all_cfgs, all_o3d, missing_model_refs, cfg_texture_tokens, out_of_bus = (
        parse_cfg_dependencies(model_cfgs, bus_root)
    )
    textures, unresolved_textures, texture_out_of_bus = gather_textures(
        texture_root, cfg_texture_tokens, all_o3d, bus_root)
    out_of_bus = out_of_bus | texture_out_of_bus

    model_files = all_cfgs | all_o3d

    print(f"Bus root: {bus_root}")
    print(f"Bus file: {bus_file.relative_to(bus_root).as_posix()}")
    print(f"Output folder: {output_dir}")

    print_relative_file_list("Required model files", model_files, bus_root)
    print_relative_file_list("Required texture files", textures, bus_root)

    if missing_model_refs:
        print(f"\nMissing model references ({len(missing_model_refs)}):")
        for item in sorted(set(missing_model_refs)):
            print(f"  {item}")

    if unresolved_textures:
        print(f"\nUnresolved texture tokens ({len(unresolved_textures)}):")
        for item in sorted(unresolved_textures):
            print(f"  {item}")

    if out_of_bus:
        print(f"\ntexture/file out of bus ({len(out_of_bus)}):")
        for item in sorted(out_of_bus):
            print(f"  {item}")

    files_to_copy = model_files | textures
    copy_files_to_output(
        files_to_copy, bus_root, output_dir, out_of_bus=out_of_bus)
    print(f"\nCopied {len(files_to_copy)} files to: {output_dir}")


if __name__ == "__main__":
    main()
