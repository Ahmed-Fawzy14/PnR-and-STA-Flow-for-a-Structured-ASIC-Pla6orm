import yaml
import json
import re
from collections import Counter

INPUT_FILE = "fabric_cells.yaml"
OUTPUT_COUNTS = "gate_counts.txt"
OUTPUT_JSON = "fabric_cells.json"

# Matches names like:  T0Y0__R0_NAND_2  ->  NAND
gate_pattern = re.compile(r".*__(?:R\d+_)?([A-Za-z]+)_\d+$")


def parse_fabric(file_path):
    with open(file_path, "r") as f:
        data = yaml.safe_load(f)

    tiles = data["fabric_cells_by_tile"]["tiles"]

    gate_counter = Counter()
    structured_json = {"tiles": []}

    print("\n--- Starting tile parsing ---")

    for tile_name, tile_details in tiles.items():
        print(f"\n[TILE] {tile_name}")

        tile_entry = {
            "name": tile_name,
            "x": tile_details.get("x"),
            "y": tile_details.get("y"),
            "gates": []
        }

        cells = tile_details.get("cells", [])
        if not cells:
            print("  No cells in this tile.")
            continue

        for cell in cells:
            cell_name = cell.get("name", None)
            print(f"  Checking cell: {cell_name}")

            if not cell_name:
                print("    (Skipped: missing name)")
                continue

            match = gate_pattern.match(cell_name)

            if match:
                gate_type = match.group(1)    # Extract NAND / TAP / etc.
                gate_counter[gate_type] += 1
                print(f"    ✅ Gate type detected: {gate_type}")
            else:
                print("    ❌ No gate type match")
                gate_type = None

            # Add cell info to structured JSON
            tile_entry["gates"].append({
                "name": cell_name,
                "type": gate_type,
                "x": cell.get("x"),
                "y": cell.get("y"),
                "orient": cell.get("orient")
            })

        structured_json["tiles"].append(tile_entry)

    print("\n--- Finished parsing ---\n")
    return gate_counter, structured_json


if __name__ == "__main__":
    gate_counts, fabric_json = parse_fabric(INPUT_FILE)

    # Save gate counts .txt
    print("Final gate counts:")
    with open(OUTPUT_COUNTS, "w") as f:
        for gate, num in sorted(gate_counts.items()):
            print(f"  {gate}: {num}")
            f.write(f"{gate}: {num}\n")

    print(f"\n✅ Gate count results written to: {OUTPUT_COUNTS}")

    # Save structured JSON
    with open(OUTPUT_JSON, "w") as f:
        json.dump(fabric_json, f, indent=4)

    print(f"✅ Fabric structure JSON written to: {OUTPUT_JSON}")
