#!/usr/bin/env python3
#generate_pd_eco.py
import argparse
import json
from pathlib import Path
from typing import Dict, Tuple, Set, Any

import matplotlib.pyplot as plt


# -----------------------------
# Basic helpers
# -----------------------------

def load_json(path: Path) -> Any:
    with open(path, "r") as f:
        return json.load(f)


def load_placement_map(map_path: Path) -> Dict[str, str]:
    """
    Load a placement map of the form:

        <inst_name> <slot_name>

    One per line, whitespace-separated. Lines starting with '#' or blank lines
    are ignored.
    """
    mapping: Dict[str, str] = {}
    with open(map_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            inst, slot = parts[0], parts[1]
            mapping[inst] = slot
    return mapping


def load_fabric_slot_coords(fabric_path: Path) -> Dict[str, Tuple[float, float]]:
    """
    Load slot coordinates from build/fabric/fabric_db.json.

    This is robust to almost any structure:
      - top-level list of cells
      - dict with "tiles" -> "cells"
      - any nested mix of dicts/lists

    We consider any dict with:
        name + (x or x_um) + (y or y_um)
    as a slot entry and record (name, x, y).
    """
    print(f"[VIS] Loading fabric from: {fabric_path}")
    raw = load_json(fabric_path)

    slot_coords: Dict[str, Tuple[float, float]] = {}

    def visit(node):
        # Recurse through the JSON tree and collect cell-like dicts
        if isinstance(node, dict):
            name = node.get("name")
            x = node.get("x", node.get("x_um"))
            y = node.get("y", node.get("y_um"))

            if name is not None and x is not None and y is not None:
                try:
                    slot_coords[str(name)] = (float(x), float(y))
                except (TypeError, ValueError):
                    # If x/y aren't numeric, just ignore this entry
                    pass

            # Recurse into all values
            for v in node.values():
                visit(v)

        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(raw)

    print(f"[VIS] Loaded coordinates for {len(slot_coords)} slots from fabric_db.")
    return slot_coords

def load_unused_instances(unused_path: Path) -> Set[str]:
    """
    Load unused instances from JSON.

    Supports:
      - a plain list: ["inst1", "inst2", ...]
      - or a dict with a key like "unused_instances".
    """
    raw = load_json(unused_path)
    if isinstance(raw, list):
        return set(raw)
    if isinstance(raw, dict):
        for key in ["unused_instances", "unused", "instances"]:
            if key in raw and isinstance(raw[key], list):
                return set(raw[key])
    raise ValueError(f"Cannot interpret unused instances JSON: {unused_path}")


def load_tielo_info(tie_info_path: Path) -> str:
    """
    Load tie-low instance name from JSON.

    Supports shapes like:
      { "tielo_inst": "<name>", ... }
      { "inst_name": "<name>", ... }
    """
    tie_info = load_json(tie_info_path)
    if not isinstance(tie_info, dict):
        raise ValueError("Tie-low info JSON must be a dict.")

    if "tielo_inst" in tie_info:
        return tie_info["tielo_inst"]
    if "inst_name" in tie_info:
        return tie_info["inst_name"]

    raise ValueError(
        f"Could not find 'tielo_inst' or 'inst_name' in {tie_info_path}"
    )


# -----------------------------
# Visualization
# -----------------------------

def visualize_pd_eco(
    design: str,
    fabric_path: Path,
    map_path: Path,
    unused_path: Path,
    tie_info_path: Path,
    out_path: Path,
):
    print(f"[VIS] Design: {design}")

    print(f"[VIS] Loading placement map from: {map_path}")
    inst_to_slot = load_placement_map(map_path)

    print(f"[VIS] Loading unused instances from: {unused_path}")
    unused_instances: Set[str] = load_unused_instances(unused_path)
    print(f"[VIS] #unused instances (PD ECO): {len(unused_instances)}")

    print(f"[VIS] Loading tie-low info from: {tie_info_path}")
    tielo_inst = load_tielo_info(tie_info_path)
    print(f"[VIS] Tie-low driver instance: {tielo_inst}")

    # Fabric / coordinates from raw fabric_db
    slot_coords: Dict[str, Tuple[float, float]] = load_fabric_slot_coords(fabric_path)
    if not slot_coords:
        print("[VIS] ERROR: No slot coordinates available; nothing to plot.")
        return

    # Reverse: slot -> inst
    slot_to_inst: Dict[str, str] = {}
    for inst, slot in inst_to_slot.items():
        slot_to_inst[slot] = inst

    used_logic_x = []
    used_logic_y = []

    spares_x = []
    spares_y = []

    filler_x = []
    filler_y = []

    tielo_x = []
    tielo_y = []

    used_count = 0
    spare_count = 0
    filler_count = 0
    tielo_count = 0

    # Iterate over all fabric slots
    for slot_name, coord in slot_coords.items():
        if not isinstance(coord, (list, tuple)) or len(coord) < 2:
            continue
        x, y = coord[0], coord[1]

        inst = slot_to_inst.get(slot_name)

        if inst is not None:
            if inst == tielo_inst:
                tielo_x.append(x)
                tielo_y.append(y)
                tielo_count += 1
            elif inst in unused_instances:
                spares_x.append(x)
                spares_y.append(y)
                spare_count += 1
            else:
                used_logic_x.append(x)
                used_logic_y.append(y)
                used_count += 1
        else:
            filler_x.append(x)
            filler_y.append(y)
            filler_count += 1

    print("[VIS] Plotted cells:")
    print(f"      Used logic         : {used_count}")
    print(f"      Powered-down spares: {spare_count}")
    print(f"      Filler/empty       : {filler_count}")
    print(f"      Tie-low driver     : {tielo_count}")

    # -----------------------------
    # Matplotlib scatter plot
    # -----------------------------
    plt.figure(figsize=(10, 10))

    handles = []

    if filler_x:
        h = plt.scatter(filler_x, filler_y, s=5, alpha=0.3, label="Filler / empty")
        handles.append(h)

    if used_logic_x:
        h = plt.scatter(used_logic_x, used_logic_y, s=10, alpha=0.8, label="Used logic")
        handles.append(h)

    if spares_x:
        h = plt.scatter(spares_x, spares_y, s=20, marker="s", alpha=0.9, label="Powered-down spares")
        handles.append(h)

    if tielo_x:
        h = plt.scatter(tielo_x, tielo_y, s=40, marker="*", alpha=1.0, label="Tie-low driver")
        handles.append(h)

    plt.xlabel("X (sites or µm)")
    plt.ylabel("Y (sites or µm)")
    plt.title(f"Power-Down ECO Visualization – {design}")

    if handles:
        plt.legend(loc="best")

    plt.gca().set_aspect("equal", adjustable="box")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(out_path, dpi=300)
    print(f"[VIS] Saved plot to: {out_path}")
    plt.close()


# -----------------------------
# Main
# -----------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Visualize power-down ECO: show used logic, powered-down spares, "
                    "filler slots and tie-low driver on the fabric."
    )
    parser.add_argument(
        "--design",
        required=True,
        help="Design name (expects build/<design>/ with PD ECO JSON + map files).",
    )
    parser.add_argument(
        "--fabric",
        help="Path to fabric_db.json "
             "(default: build/fabric/fabric_db.json)",
    )
    parser.add_argument(
        "--map",
        help="Path to placement map (default: build/<design>/<design>_sa.map)",
    )
    parser.add_argument(
        "--unused",
        help="Path to <design>_pd_unused_instances.json "
             "(default: build/<design>/<design>_pd_unused_instances.json)",
    )
    parser.add_argument(
        "--tieinfo",
        help="Path to <design>_pd_tielo_source.json "
             "(default: build/<design>/<design>_pd_tielo_source.json)",
    )
    parser.add_argument(
        "--out",
        help="Output plot path (default: build/<design>/<design>_pd_eco_plot.png)",
    )

    args = parser.parse_args()
    design = args.design

    base_dir = Path("build") / design

    fabric_path = Path(args.fabric) if args.fabric else Path("build") / "fabric" / "cells_by_type.json"
    map_path = Path(args.map) if args.map else base_dir / f"{design}_sa.map"
    unused_path = Path(args.unused) if args.unused else base_dir / f"{design}_pd_unused_instances.json"
    tie_info_path = Path(args.tieinfo) if args.tieinfo else base_dir / f"{design}_pd_tielo_source.json"
    out_path = Path(args.out) if args.out else base_dir / f"{design}_pd_eco_plot.png"

    visualize_pd_eco(
        design=design,
        fabric_path=fabric_path,
        map_path=map_path,
        unused_path=unused_path,
        tie_info_path=tie_info_path,
        out_path=out_path,
    )


if __name__ == "__main__":
    main()