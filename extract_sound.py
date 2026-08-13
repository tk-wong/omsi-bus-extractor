from __future__ import annotations

import argparse
import shutil
from collections import defaultdict
from pathlib import Path


SOUND_CONFIG_EXTENSIONS = {".cfg"}
SOUND_FILE_EXTENSIONS = {".wav", ".ogg", ".flac", ".mp3"}
TOKEN_EXTENSIONS = SOUND_CONFIG_EXTENSIONS | SOUND_FILE_EXTENSIONS


def normalize_rel_path(path_text: str) -> str:
    text = path_text.strip().strip('"').strip("'").replace("/", "\\")
    while text.startswith(".\\"):
        text = text[2:]
    return text


def is_comment_or_empty(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith(";") or stripped.startswith("//")


def _maybe_add_token(chunk: str, out_tokens: list[str]) -> None:
    token = chunk.strip().strip('"').strip("'")
    if not token:
        return
    token = token.rstrip(",;)")
    suffix = Path(token).suffix.lower()
    if suffix in TOKEN_EXTENSIONS:
        out_tokens.append(token)


def extract_file_tokens(line: str) -> list[str]:
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


def find_first_bus_file(bus_root: Path) -> Path:
    bus_files = sorted(bus_root.glob("*.bus"))
    if not bus_files:
        raise FileNotFoundError(f"No .bus file found in: {bus_root}")
    return bus_files[0]


def resolve_existing_path(raw_path: str, base_dir: Path, bus_root: Path) -> Path | None:
    raw_rel = normalize_rel_path(raw_path)
    rel_no_lead = raw_rel.lstrip("\\")
    candidate_values = []

    raw_path_obj = Path(raw_rel)
    if raw_path_obj.is_absolute():
        candidate_values.append(raw_path_obj)

    candidate_values.append(base_dir / raw_rel)
    candidate_values.append(base_dir / rel_no_lead)
    candidate_values.append(bus_root / rel_no_lead)
    candidate_values.append(bus_root / "sound" / rel_no_lead)
    candidate_values.append(bus_root / "Sound" / rel_no_lead)

    # Handle tokens that begin with "sound\\..." when appending under Sound folder.
    lowered = rel_no_lead.lower()
    if lowered.startswith("sound\\"):
        trimmed = rel_no_lead[6:]
        candidate_values.append(bus_root / "sound" / trimmed)
        candidate_values.append(bus_root / "Sound" / trimmed)

    checked = set()
    for candidate in candidate_values:
        resolved = candidate.resolve()
        if resolved in checked:
            continue
        checked.add(resolved)
        if resolved.exists() and resolved.is_file():
            return resolved
    return None


def parse_bus_for_sound_cfgs(bus_file: Path, bus_root: Path) -> set[Path]:
    sound_cfgs: set[Path] = set()
    lines = bus_file.read_text(encoding="utf-8", errors="ignore").splitlines()

    target_tags = {"[sound]", "[sound_ai]"}
    expecting_sound_path = False

    for line in lines:
        stripped = line.strip()
        lowered = stripped.lower()

        if lowered in target_tags:
            expecting_sound_path = True
            continue

        if expecting_sound_path:
            if is_comment_or_empty(stripped):
                continue
            candidate = resolve_existing_path(
                stripped, bus_file.parent, bus_root)
            if candidate and candidate.suffix.lower() == ".cfg":
                sound_cfgs.add(candidate)
            expecting_sound_path = False

    return sound_cfgs


def build_sound_index(sound_root: Path) -> tuple[dict[str, Path], dict[str, list[Path]]]:
    by_relpath: dict[str, Path] = {}
    by_basename: dict[str, list[Path]] = defaultdict(list)

    if not sound_root.exists():
        return by_relpath, by_basename

    for file_path in sound_root.rglob("*"):
        if not file_path.is_file():
            continue
        suffix = file_path.suffix.lower()
        if suffix not in TOKEN_EXTENSIONS:
            continue
        rel = file_path.relative_to(sound_root).as_posix().lower()
        by_relpath[rel] = file_path
        by_basename[file_path.name.lower()].append(file_path)

    return by_relpath, by_basename


def resolve_sound_token(
        token: str,
        base_dir: Path,
        bus_root: Path,
        sound_root: Path,
        by_relpath: dict[str, Path],
        by_basename: dict[str, list[Path]],
) -> set[Path]:
    normalized = normalize_rel_path(token).lstrip("\\")
    lower_rel = normalized.replace("\\", "/").lower()
    file_name = Path(normalized).name.lower()
    candidates: set[Path] = set()

    direct_resolved = resolve_existing_path(token, base_dir, bus_root)
    if direct_resolved:
        candidates.add(direct_resolved)

    if lower_rel.startswith("sound/"):
        lower_rel = lower_rel[len("sound/"):]

    rel_match = by_relpath.get(lower_rel)
    if rel_match:
        candidates.add(rel_match)

    direct_under_sound = (sound_root / normalized).resolve()
    if direct_under_sound.exists() and direct_under_sound.is_file():
        candidates.add(direct_under_sound)

    # Fallback by filename to tolerate mixed or omitted subfolder references.
    if file_name in by_basename:
        candidates.update(by_basename[file_name])

    return candidates


def parse_sound_dependencies(
        start_cfgs: set[Path],
        bus_root: Path,
) -> tuple[set[Path], set[Path], set[str]]:
    all_cfgs: set[Path] = set()
    all_audio: set[Path] = set()
    unresolved_tokens: set[str] = set()

    sound_root = bus_root / "sound"
    if not sound_root.exists():
        sound_root = bus_root / "Sound"

    by_relpath, by_basename = build_sound_index(sound_root)

    queue = sorted(start_cfgs)
    seen_cfgs: set[Path] = set()

    while queue:
        cfg_file = queue.pop(0).resolve()
        if cfg_file in seen_cfgs:
            continue
        seen_cfgs.add(cfg_file)
        all_cfgs.add(cfg_file)

        lines = cfg_file.read_text(
            encoding="utf-8", errors="ignore").splitlines()
        for line in lines:
            for token in extract_file_tokens(line):
                suffix = Path(token).suffix.lower()
                matches = resolve_sound_token(
                    token,
                    cfg_file.parent,
                    bus_root,
                    sound_root,
                    by_relpath,
                    by_basename,
                )

                if not matches:
                    unresolved_tokens.add(f"{cfg_file.name}: {token}")
                    continue

                if suffix == ".cfg":
                    for item in matches:
                        if item not in seen_cfgs:
                            queue.append(item)
                else:
                    all_audio.update(matches)

    return all_cfgs, all_audio, unresolved_tokens


def print_relative_file_list(title: str, files: set[Path], bus_root: Path) -> None:
    print(f"\n{title} ({len(files)}):")
    for file_path in sorted(files):
        print(f"  {file_path.relative_to(bus_root).as_posix()}")


def copy_files_to_output(files: set[Path], bus_root: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for source in files:
        relative = source.relative_to(bus_root)
        target = output_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract OMSI bus sound dependencies."
    )
    parser.add_argument(
        "--bus-root",
        default="ADL_Enviro500MMC_N32&N34_2025ver",
        help="Bus folder containing .bus and sound directories.",
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

    output_dir = (workspace_root / args.output).resolve()

    sound_cfgs = parse_bus_for_sound_cfgs(bus_file, bus_root)
    if not sound_cfgs:
        raise RuntimeError(f"No sound cfg references found in: {bus_file}")

    cfg_files, audio_files, unresolved = parse_sound_dependencies(
        sound_cfgs, bus_root)

    print(f"Bus root: {bus_root}")
    print(f"Bus file: {bus_file.relative_to(bus_root).as_posix()}")
    print(f"Output folder: {output_dir}")

    print_relative_file_list(
        "Required sound config files", cfg_files, bus_root)
    print_relative_file_list(
        "Required sound audio files", audio_files, bus_root)

    if unresolved:
        print(f"\nUnresolved sound tokens ({len(unresolved)}):")
        for item in sorted(unresolved):
            print(f"  {item}")

    files_to_copy = cfg_files | audio_files
    copy_files_to_output(files_to_copy, bus_root, output_dir)
    print(f"\nCopied {len(files_to_copy)} files to: {output_dir}")


if __name__ == "__main__":
    main()
