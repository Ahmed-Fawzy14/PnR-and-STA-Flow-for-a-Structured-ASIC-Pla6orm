import json
import sys

logical_db = {}

def open_design(file_name):
    try:
        with open(file_name, "r", encoding="utf-8") as json_file:
            data = json.load(json_file)
            return data
    except FileNotFoundError:
        raise FileNotFoundError(f"File not found: {file_name}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {file_name}: {e}")

def parse_ports(data):
    logical_db["ports"] = {}
    try:
        ports = data["modules"]["sasic_top"]["ports"]
    except KeyError as e:
        raise KeyError(f"Missing key in JSON: {e}. Check module data and file structure.")

    for port in ports.items():
        logical_db["ports"][port[0]] = port[1]



data = open_design("../data/z80_mapped.json")
parse_ports(data)
print(logical_db)