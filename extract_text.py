import glob
import os
import shutil
from pathlib import Path


def is_within_bus_root(path: Path, bus_root: Path) -> bool:
    try:
        path.resolve().relative_to(bus_root.resolve())
        return True
    except ValueError:
        return False


def get_bus_file(directory):
    if not directory:
        print("Invalid directory")
        return []
    search_path = os.path.join(directory, "*.bus")
    bus_file_list = glob.glob(search_path)
    return bus_file_list


def extract_bus_name(bus_file_list):
    if not bus_file_list:
        print("Invalid list")
        return set()
    return {os.path.split(i)[1] for i in bus_file_list}


def get_hof_name(directory):
    if not directory:
        print("Invalid Directory")
        return set()
    search_path = os.path.join(directory, "*.hof")
    hof_file_list = glob.glob(search_path)
    return {os.path.split(i)[1] for i in hof_file_list}

def locate_bus_config_files(bus_path):
    if not bus_path:
        print("No bus file")
        return set()
    suffix_list = (".cfg", ".txt", ".org", ".osc")
    file_set = set()
    with open(bus_path, encoding="utf-8") as f:
        for lines in f:
            strip_line = lines.strip()
            if strip_line.endswith(suffix_list):
                file_set.add(strip_line)
    return file_set


def get_bus_config_file(bus_root_path, cofig_files, output_path):
    missing_file = set()
    out_of_bus = set()
    bus_root = Path(bus_root_path).resolve()
    output_dir = Path(output_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    for file in cofig_files:
        source = (bus_root / file).resolve()
        if not is_within_bus_root(source, bus_root):
            out_of_bus.add(file)
            print(f"{file} is outside the bus folder; skipped")
            continue
        if not source.exists():
            missing_file.add(file)
            print(f"{file} not found")
            continue
        relative = source.relative_to(bus_root)
        target = output_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(source, target)
    return missing_file, out_of_bus
