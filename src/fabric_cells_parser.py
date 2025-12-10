#!/usr/bin/env python3
# fabric_cells_parser.py
"""
Driver script to build the fabric DB.

Step 1 (cells):
  - Calls fabricCellsParser.load_fabric_definition()
  - Calls fabricCellsParser.parse_fabric()
  - Writes:
      build/fabric/type_counts.txt
      build/fabric/fabric_db_1.json

Step 2 (pins):
  - Calls pins_parser.load_pins("fabric/pins.yaml")
  - Merges pin-related data into build/fabric/fabric_db.json
"""

import json
from pathlib import Path

from fabricCellsParser import load_fabric_definition, parse_fabric
from pins_parser import load_pins, get_pin_list

# New paths (moved from fabricCellsParser.py into this driver)
INPUT_FILE = "fabric/fabric_cells.yaml"
FABRIC_DEFINITION = "fabric/fabric.yaml"
OUTPUT_COUNTS = "build/fabric/type_counts.txt"
OUTPUT_JSON = "build/fabric/fabric_db.json"
PINS_FILE = "fabric/pins.yaml"


def run_fabric_cells():
    """Run the fabricCellsParser part with the new paths."""
    print("\n=== [1/2] Building fabric DB from cells ===")

    # Ensure output dirs exist
    Path(OUTPUT_COUNTS).parent.mkdir(parents=True, exist_ok=True)
    Path(OUTPUT_JSON).parent.mkdir(parents=True, exist_ok=True)

    # Use the module's function but override the default path
    template_map = load_fabric_definition(path=FABRIC_DEFINITION)

    type_counts, fabric_json = parse_fabric(INPUT_FILE, template_map)

    print("Final type counts:")
    with open(OUTPUT_COUNTS, "w") as f:
        for cell_type, num in sorted(type_counts.items()):
            line = f"{cell_type}: {num}"
            print(line)
            f.write(line + "\n")

    print(f"\n✅ Type count results written to: {OUTPUT_COUNTS}")

    with open(OUTPUT_JSON, "w") as f:
        json.dump(fabric_json, f, indent=2)

    print(f"✅ Fabric structure JSON written to: {OUTPUT_JSON}")


def run_pins_merge():
    """Run the pins_parser part and merge into the same JSON DB."""
    print("\n=== [2/2] Parsing pins and merging into fabric DB ===")

    try:
        pins_db = load_pins(PINS_FILE)
    except FileNotFoundError as e:
        print(f"⚠ Pins file not found, skipping pin merge: {e}")
        return
    except Exception as e:
        print(f"⚠ Error parsing pins, skipping pin merge: {e}")
        return

    num_pins = len(pins_db.get("pins", []))
    layers = {pin.get("layer", "unknown") for pin in pins_db.get("pins", [])}
    layers_str = "/".join(sorted(layers))
    print(f"Found {num_pins} pins ({layers_str})")

    if pins_db.get("pins"):
        example_pin = pins_db["pins"][0]
        example_dict = {
            "name": example_pin.get("name"),
            "side": example_pin.get("side"),
            "x_um": example_pin.get("x_um"),
            "y_um": example_pin.get("y_um"),
        }
        print(f"Example pin: {example_dict}")

    # Optional debug use of get_pin_list
    pin_list = get_pin_list(pins_db)
    if pin_list:
        print(f"\nPin list example (first pin): {pin_list[0]}")

    # Read existing DB (created by run_fabric_cells)
    try:
        with open(OUTPUT_JSON, "r") as f:
            existing = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print(f"⚠ {OUTPUT_JSON} not found or invalid; starting fresh DB for pins merge.")
        existing = {}

    # Merge pins-related fields into existing DB
    existing.update({
        "pins": pins_db.get("pins", []),
        "version": pins_db.get("version", existing.get("version")),
        "units": pins_db.get("units", existing.get("units")),
        "layers": pins_db.get("layers", existing.get("layers")),
        "tracks": pins_db.get("tracks", existing.get("tracks")),
        "die": pins_db.get("die", existing.get("die")),
        "core": pins_db.get("core", existing.get("core")),
        "pin_spacing_um": pins_db.get("pin_spacing_um", existing.get("pin_spacing_um")),
    })

    with open(OUTPUT_JSON, "w") as f:
        json.dump(existing, f, indent=2)

    print(f"\n✅ Pins appended/updated in {OUTPUT_JSON}")


def main():
    run_fabric_cells()
    run_pins_merge()


if __name__ == "__main__":
    main()