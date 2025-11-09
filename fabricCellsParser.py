import yaml
import json
from collections import Counter
from pathlib import Path

INPUT_FILE = "fabric_cells.yaml"
FABRIC_DEFINITION = "fabric.yaml"
OUTPUT_COUNTS = "type_counts.txt"
OUTPUT_JSON = "fabric_cells.json"


def load_fabric_definition(path=FABRIC_DEFINITION):
    """
    Loads: template_name → { cell_type, width_sites, origin_sites }
    from fabric.yaml.
    """
    print(f"\n--- Loading fabric definition: {path} ---")

    if not Path(path).exists():
        raise FileNotFoundError(f"fabric definition not found: {path}")

    with open(path, "r") as f:
        fab = yaml.safe_load(f)

    cell_defs = fab.get("cell_definitions", {})
    tile_cells = fab.get("tile_definition", {}).get("cells", [])

    template_map = {}

    for cell in tile_cells:
        template = cell["template_name"]        # R0_NAND_0
        cell_type = cell["cell_type"]           # sky130_fd_sc_hd__nand2_2
        origin = cell["origin_sites"]

        # Lookup width from cell_definitions
        width_sites = cell_defs.get(cell_type, {}).get("width_sites")

        if width_sites is None:
            print(f"⚠ WARNING: Missing width_sites for cell_type: {cell_type}")

        template_map[template] = {
            "cell_type": cell_type,
            "width_sites": width_sites,
            "origin_sites": origin,
        }

    print("✅ Fabric definition loaded.")
    return template_map


def parse_fabric(file_path, template_map):
    with open(file_path, "r") as f:
        data = yaml.safe_load(f)

    tiles = data["fabric_cells_by_tile"]["tiles"]

    type_counter = Counter()
    structured_json = {"tiles": []}

    print("\n--- Starting tile parsing ---")

    for tile_name, tile_details in tiles.items():
        print(f"\n[TILE] {tile_name}")

        tile_entry = {
            "name": tile_name,
            "x": tile_details.get("x"),
            "y": tile_details.get("y"),
            "cells": []     # renamed from 'gates' to 'cells'
        }

        cells = tile_details.get("cells", [])
        if not cells:
            print("  No cells in this tile.")
            continue

        for cell in cells:
            cell_name = cell.get("name")
            print(f"  Checking cell: {cell_name}")

            if not cell_name:
                print("    (Skipped: missing name)")
                continue

            try:
                # Extract template name after "__"
                template_name = cell_name.split("__", 1)[1]
            except IndexError:
                print("    ❌ Invalid name format (no template)")
                continue

            info = template_map.get(template_name, {})
            physical_cell_type = info.get("cell_type")

            if physical_cell_type:
                type_counter[physical_cell_type] += 1
                print(f"    ✅ Type counted: {physical_cell_type}")
            else:
                print(f"    ⚠ No cell type for template: {template_name}")

            tile_entry["cells"].append({
                "name": cell_name,
                "physical_cell_type": physical_cell_type,
                "width_sites": info.get("width_sites"),
                "x": cell.get("x"),
                "y": cell.get("y"),
                "orient": cell.get("orient")
            })

        structured_json["tiles"].append(tile_entry)

    print("\n--- Finished parsing ---\n")
    return type_counter, structured_json


if __name__ == "__main__":
    template_map = load_fabric_definition()

    # Parse and count by PHYSICAL CELL TYPE
    type_counts, fabric_json = parse_fabric(INPUT_FILE, template_map)

    print("Final type counts:")
    with open(OUTPUT_COUNTS, "w") as f:
        for cell_type, num in sorted(type_counts.items()):
            print(f"{cell_type}: {num}")
            f.write(f"{cell_type}: {num}\n")

    print(f"\n✅ Type count results written to: {OUTPUT_COUNTS}")

    with open(OUTPUT_JSON, "w") as f:
        json.dump(fabric_json, f, indent=4)

    print(f"✅ Fabric structure JSON written to: {OUTPUT_JSON}")
