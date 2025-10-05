import extract_text


def main():
    bus_dir = "ADL_Enviro500MMC_N32&N34_2025ver"
    output_dir = "./temp"
    bus_file = extract_text.get_bus_file(bus_dir)
    if not bus_file:
        print("No bus file in directory")
        return
    all_text_file = set()
    for file in bus_file:
        bus_text_file = extract_text.locate_bus_config_files(file)
        all_text_file.update(bus_text_file)
    bus_file_name = extract_text.extract_bus_name(bus_file)
    all_text_file.update(bus_file_name)
    hof_file_set = extract_text.get_hof_name(bus_dir)
    all_text_file.update(hof_file_set)
    missing_file = extract_text.get_bus_config_file(bus_dir,all_text_file,output_dir)


if __name__ == "__main__":
    main()
