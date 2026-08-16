from __future__ import annotations

import argparse
import io
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path

import extract_model
import extract_sound
import extract_text
import extract_texture


@dataclass
class ExtractionSummary:
    missing_text: set[str]
    missing_model: set[str]
    unresolved_textures: set[str]
    unresolved_sound: set[str]
    texture_hook_results: list[str]


def run_text_extraction(
        bus_root: Path,
        output_dir: Path,
        selected_buses: list[Path],
) -> set[str]:
    missing: set[str] = set()
    bus_files = [str(path) for path in selected_buses]

    text_files = set()
    for file in bus_files:
        text_files.update(extract_text.locate_bus_config_files(file))

    text_files.update(extract_text.extract_bus_name(bus_files))
    text_files.update(extract_text.get_hof_name(str(bus_root)))

    missing.update(
        extract_text.get_bus_config_file(
            str(bus_root),
            text_files,
            str(output_dir),
        )
    )
    return missing


def run_model_extraction(
        bus_root: Path,
        output_dir: Path,
        selected_bus: Path,
) -> tuple[list[str], set[str]]:
    model_cfgs = extract_model.parse_bus_for_model_cfgs(selected_bus, bus_root)
    if not model_cfgs:
        return [f"No model cfg references found in: {selected_bus.name}"], set()

    all_cfgs, all_o3d, missing_model_refs, cfg_texture_tokens = extract_model.parse_cfg_dependencies(
        model_cfgs, bus_root
    )
    textures, unresolved_textures = extract_model.gather_textures(
        bus_root / "Texture", cfg_texture_tokens, all_o3d
    )

    files_to_copy = all_cfgs | all_o3d | textures
    extract_model.copy_files_to_output(files_to_copy, bus_root, output_dir)
    return sorted(set(missing_model_refs)), unresolved_textures


def run_sound_extraction(
        bus_root: Path,
        output_dir: Path,
        selected_bus: Path,
) -> set[str]:
    sound_cfgs = extract_sound.parse_bus_for_sound_cfgs(selected_bus, bus_root)
    if not sound_cfgs:
        return {f"No sound cfg references found in: {selected_bus.name}"}

    cfg_files, audio_files, unresolved_sound = extract_sound.parse_sound_dependencies(
        sound_cfgs, bus_root
    )
    extract_sound.copy_files_to_output(
        cfg_files | audio_files, bus_root, output_dir)
    return unresolved_sound


def run_texture_extraction_if_available(
        bus_root: Path,
        output_dir: Path,
        selected_bus: Path,
) -> str:
    # Keep this hook so main.py can use extract_texture.py once it has an entrypoint.
    for fn_name in ("run", "main", "extract"):
        fn = getattr(extract_texture, fn_name, None)
        if callable(fn):
            try:
                fn(bus_root=bus_root, output_dir=output_dir, bus_file=selected_bus)
                return f"extract_texture.{fn_name} executed"
            except TypeError:
                fn()
                return f"extract_texture.{fn_name} executed (no args)"
    return "extract_texture has no callable entrypoint; skipped"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract all required OMSI bus files into one output folder."
    )
    parser.add_argument(
        "--bus-root",
        default=None,
        help="Bus folder containing .bus and asset directories.",
    )
    parser.add_argument(
        "--bus-file",
        action="append",
        default=[],
        help="Optional .bus file name/path. Repeat this option to process multiple specific buses. If omitted, all .bus files in --bus-root are processed.",
    )
    parser.add_argument(
        "--output",
        default="extracted",
        help="Output folder to copy extracted files to.",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch the simple GUI.",
    )
    return parser.parse_args()


def resolve_selected_buses(bus_root: Path, bus_file_args: list[str]) -> list[Path]:
    if bus_file_args:
        selected: list[Path] = []
        seen: set[Path] = set()
        for bus_file_arg in bus_file_args:
            candidate = Path(bus_file_arg)
            if not candidate.is_absolute():
                candidate = (bus_root / candidate).resolve()
            if not candidate.exists():
                raise FileNotFoundError(
                    f"Bus file does not exist: {candidate}")
            if candidate.suffix.lower() != ".bus":
                raise ValueError(f"Not a .bus file: {candidate}")
            if candidate not in seen:
                seen.add(candidate)
                selected.append(candidate)
        return sorted(selected)

    discovered = sorted(bus_root.glob("*.bus"))
    if not discovered:
        raise FileNotFoundError(f"No .bus files found in: {bus_root}")
    return discovered


def run_extraction_pipeline(
        bus_root: Path,
        output_dir: Path,
        selected_buses: list[Path],
) -> ExtractionSummary:
    missing_text = run_text_extraction(bus_root, output_dir, selected_buses)

    missing_model: set[str] = set()
    unresolved_textures: set[str] = set()
    unresolved_sound: set[str] = set()
    texture_hook_results: list[str] = []

    print("[2/3] Extracting model/texture files...")
    for selected_bus in selected_buses:
        print(f"  Processing: {selected_bus.name}")
        missing_model_for_bus, unresolved_textures_for_bus = run_model_extraction(
            bus_root, output_dir, selected_bus
        )
        missing_model.update(missing_model_for_bus)
        unresolved_textures.update(unresolved_textures_for_bus)

    print("[3/3] Extracting sound files...")
    for selected_bus in selected_buses:
        print(f"  Processing: {selected_bus.name}")
        unresolved_sound_for_bus = run_sound_extraction(
            bus_root, output_dir, selected_bus
        )
        unresolved_sound.update(unresolved_sound_for_bus)

    # print("[4/4] Running extract_texture hook...")
    # for selected_bus in selected_buses:
    #     print(f"  Processing: {selected_bus.name}")
    #     texture_hook_result = run_texture_extraction_if_available(
    #         bus_root, output_dir, selected_bus
    #     )
    #     texture_hook_results.append(
    #         f"{selected_bus.name}: {texture_hook_result}")

    return ExtractionSummary(
        missing_text=missing_text,
        missing_model=missing_model,
        unresolved_textures=unresolved_textures,
        unresolved_sound=unresolved_sound,
        texture_hook_results=texture_hook_results,
    )


def print_summary(summary: ExtractionSummary) -> None:
    missing_text = summary.missing_text
    missing_model = summary.missing_model
    unresolved_textures = summary.unresolved_textures
    unresolved_sound = summary.unresolved_sound
    texture_hook_results = summary.texture_hook_results

    print("\nSummary:")
    print(f"  Missing text/config refs: {len(missing_text)}")
    print(f"  Missing model refs: {len(missing_model)}")
    print(f"  Unresolved textures: {len(unresolved_textures)}")
    print(f"  Unresolved sounds: {len(unresolved_sound)}")
    print(f"  Texture hook entries: {len(texture_hook_results)}")

    if missing_text:
        print("\nMissing text/config files:")
        for item in sorted(missing_text):
            print(f"  {item}")

    if missing_model:
        print("\nMissing model references:")
        for item in sorted(missing_model):
            print(f"  {item}")

    if unresolved_textures:
        print("\nUnresolved texture tokens:")
        for item in sorted(unresolved_textures):
            print(f"  {item}")

    if unresolved_sound:
        print("\nUnresolved sound tokens:")
        for item in sorted(unresolved_sound):
            print(f"  {item}")

    print("\nTexture hook results:")
    for item in texture_hook_results:
        print(f"  {item}")


def run_gui() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox
    from tkinter.scrolledtext import ScrolledText

    root = tk.Tk()
    root.title("OMSI Bus Extractor")
    root.geometry("860x620")

    bus_root_var = tk.StringVar(value=str(Path.cwd()))
    output_var = tk.StringVar(value=str((Path.cwd() / "extracted").resolve()))
    use_all_var = tk.BooleanVar(value=True)

    bus_files: list[Path] = []

    def refresh_bus_files() -> None:
        nonlocal bus_files
        listbox.delete(0, tk.END)
        bus_files = []
        bus_root_path = Path(bus_root_var.get()).expanduser().resolve()
        if not bus_root_path.exists() or not bus_root_path.is_dir():
            return
        bus_files = sorted(bus_root_path.glob("*.bus"))
        for bus_file in bus_files:
            listbox.insert(tk.END, bus_file.name)

    def browse_bus_root() -> None:
        selected = filedialog.askdirectory(
            title="Select bus root folder",
            initialdir=bus_root_var.get() or str(Path.cwd()),
        )
        if selected:
            bus_root_var.set(selected)
            refresh_bus_files()

    def browse_output() -> None:
        selected = filedialog.askdirectory(
            title="Select output folder",
            initialdir=output_var.get() or str(Path.cwd()),
        )
        if selected:
            output_var.set(selected)

    def append_log(text: str) -> None:
        log_box.configure(state="normal")
        log_box.insert(tk.END, text)
        log_box.see(tk.END)
        log_box.configure(state="disabled")

    def run_extraction() -> None:
        try:
            bus_root = Path(bus_root_var.get()).expanduser().resolve()
            output_dir = Path(output_var.get()).expanduser().resolve()
            if not bus_root.exists() or not bus_root.is_dir():
                raise FileNotFoundError(f"Bus root does not exist: {bus_root}")

            if use_all_var.get():
                selected_buses = resolve_selected_buses(bus_root, [])
            else:
                indices = listbox.curselection()
                if not indices:
                    raise ValueError("No bus file selected.")
                selected_buses = [bus_files[i] for i in indices]

            append_log(f"Bus root: {bus_root}\n")
            append_log("Selected bus files:\n")
            for selected_bus in selected_buses:
                append_log(f"  - {selected_bus.name}\n")
            append_log(f"Output folder: {output_dir}\n\n")
            append_log("[1/4] Extracting text/config files...\n")

            capture = io.StringIO()
            with redirect_stdout(capture):
                summary = run_extraction_pipeline(
                    bus_root, output_dir, selected_buses)
                print_summary(summary)
                print("\nDone")

            append_log(capture.getvalue() + "\n")
            messagebox.showinfo("OMSI Bus Extractor", "Extraction completed.")
        except Exception as exc:
            messagebox.showerror("OMSI Bus Extractor", str(exc))

    frame_paths = tk.Frame(root)
    frame_paths.pack(fill="x", padx=10, pady=10)

    tk.Label(frame_paths, text="Bus root folder:").grid(
        row=0, column=0, sticky="w")
    tk.Entry(frame_paths, textvariable=bus_root_var, width=85).grid(
        row=1, column=0, padx=(0, 6), sticky="we")
    tk.Button(frame_paths, text="Browse...",
              command=browse_bus_root).grid(row=1, column=1)

    tk.Label(frame_paths, text="Output folder:").grid(
        row=2, column=0, sticky="w", pady=(8, 0))
    tk.Entry(frame_paths, textvariable=output_var, width=85).grid(
        row=3, column=0, padx=(0, 6), sticky="we")
    tk.Button(frame_paths, text="Browse...",
              command=browse_output).grid(row=3, column=1)
    frame_paths.columnconfigure(0, weight=1)

    frame_bus = tk.Frame(root)
    frame_bus.pack(fill="both", expand=False, padx=10, pady=(0, 10))

    tk.Checkbutton(
        frame_bus,
        text="Process all .bus files in the folder",
        variable=use_all_var,
    ).pack(anchor="w")

    tk.Label(frame_bus, text="Or select specific .bus files (Ctrl/Shift for multi-select):").pack(anchor="w")
    listbox = tk.Listbox(frame_bus, selectmode="extended", height=8)
    listbox.pack(fill="x", pady=(4, 6))

    button_row = tk.Frame(frame_bus)
    button_row.pack(fill="x")
    tk.Button(button_row, text="Refresh .bus list",
              command=refresh_bus_files).pack(side="left")
    tk.Button(button_row, text="Run extraction",
              command=run_extraction).pack(side="right")

    tk.Label(root, text="Output log:").pack(anchor="w", padx=10)
    log_box = ScrolledText(root, height=18, state="disabled")
    log_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    refresh_bus_files()
    root.mainloop()


def main() -> None:
    args = parse_args()
    if args.gui or not args.bus_root:
        run_gui()
        return

    workspace_root = Path.cwd()
    bus_root = (workspace_root / args.bus_root).resolve()
    output_dir = (workspace_root / args.output).resolve()

    if not bus_root.exists() or not bus_root.is_dir():
        raise FileNotFoundError(f"Bus root does not exist: {bus_root}")

    selected_buses = resolve_selected_buses(bus_root, args.bus_file)

    print(f"Bus root: {bus_root}")
    print("Selected bus files:")
    for selected_bus in selected_buses:
        print(f"  - {selected_bus.relative_to(bus_root).as_posix()}")
    print(f"Output folder: {output_dir}")

    print("\n[1/4] Extracting text/config files...")
    summary = run_extraction_pipeline(bus_root, output_dir, selected_buses)
    print_summary(summary)

    print("\nDone")


if __name__ == "__main__":
    main()
