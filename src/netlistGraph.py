#!/usr/bin/env python3
# netlistGraph.py
import argparse
import json
import os
from pathlib import Path

# Default folders (can still be overridden on the CLI)
DESIGNS_DIR = Path("designs")
BUILD_DIR = Path("build")


def generate_graph(design: str, design_path: Path, outdir: Path):
    print(f"[+] Parsing {design} from {design_path}")

    with open(design_path, "r", encoding="utf-8") as f:
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

    # Write JSON output to build/<design>/<design>_mapped_netlist_graph.json
    os.makedirs(outdir, exist_ok=True)
    out_path = outdir / f"{design}_mapped_netlist_graph.json"

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(netlist_graph, f, indent=4)

    print(f"✅ Saved graph JSON: {out_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build netlist adjacency graph from a mapped Yosys JSON."
    )
    parser.add_argument(
        "--design",
        required=True,
        help="Design name, e.g. 6502",
    )
    parser.add_argument(
        "--mapped-json",
        help="Path to <design>_mapped.json (default: designs/<design>_mapped.json)",
    )
    parser.add_argument(
        "--outdir",
        help="Output directory (default: build/<design>)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    design = args.design

    # Input JSON: designs/<design>_mapped.json (unless overridden)
    if args.mapped_json:
        design_path = Path(args.mapped_json)
    else:
        design_path = DESIGNS_DIR / f"{design}_mapped.json"

    # Output dir: build/<design> (unless overridden)
    if args.outdir:
        outdir = Path(args.outdir)
    else:
        outdir = BUILD_DIR / design

    if not design_path.is_file():
        print(f"❌ Mapped JSON not found: {design_path}")
        return

    generate_graph(design, design_path, outdir)


if __name__ == "__main__":
    main()