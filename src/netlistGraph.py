import os
import json
from pathlib import Path

FOLDER = "./designs"
OUTPUT = "./build"


def generate_graph(design_path: Path):
    name = design_path.stem
    print(f"[+] Parsing {name}")

    with open(design_path, "r") as f:
        data = json.load(f)

    module = list(data["modules"].values())[0]
    cells = module.get("cells", {})

    # Build: net_bit → { "driver": cell_name, "sinks": [cell1, cell2...] }
    net_map = {}

    for cell_name, cell in cells.items():
        for port, bits in cell.get("connections", {}).items():
            direction = cell["port_directions"].get(port, None)

            for bit in bits:
                net_entry = net_map.setdefault(bit, {"driver": None, "sinks": []})

                if direction == "output":
                    net_entry["driver"] = cell_name
                elif direction == "input":
                    net_entry["sinks"].append(cell_name)

    # Build adjacency: driver -> sinks
    netlist_graph = {}

    for bit, info in net_map.items():
        driver = info["driver"]
        sinks = info["sinks"]

        if driver is None:
            continue

        netlist_graph.setdefault(driver, [])
        netlist_graph[driver].extend(sinks)

    # Write JSON output
    os.makedirs(OUTPUT, exist_ok=True)
    out_path = Path(OUTPUT) / f"{name}_netlist_graph.json"

    with open(out_path, "w") as f:
        json.dump(netlist_graph, f, indent=4)

    print(f"✅ Saved graph JSON: {out_path}")


def main():
    design_files = list(Path(FOLDER).glob("*.json"))
    if not design_files:
        print("❌ No JSON files found in ./designs")
        return

    for design_path in design_files:
        generate_graph(design_path)


if __name__ == "__main__":
    main()
