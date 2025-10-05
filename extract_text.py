import glob
import os
import shutil


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
    os.makedirs(output_path, exist_ok=True)
    for file in cofig_files:
        full_path = os.path.join(bus_root_path, file)
        if not os.path.exists(full_path):
            missing_file.add(file)
            print(f"{file} not found")
        else:
            file_dir, _ = os.path.split(file)
            os.makedirs(os.path.join(output_path, file_dir), exist_ok=True)
            new_path = os.path.join(output_path, file)
            shutil.copy(full_path, new_path)
    return missing_file
