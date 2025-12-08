#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from typing import Dict, Tuple, Any

import matplotlib.pyplot as plt


# -----------------------------
# Basic helpers
# -----------------------------

def load_json(path: Path) -> Any:
    with open(path, "r") as f:
        return json.load(f)


def load_fabric_slot_coords(fabric_path: Path) -> Dict[str, Tuple[float, float]]:
    """
    Load slot coordinates from build/fabric/fabric_db.json.

    This is robust to:
      - top-level list of cells
      - dict with "tiles" -> "cells"
      - any nested mix of dicts/lists

    Any dict with:
        name + (x or x_um) + (y or y_um)
    is treated as a slot entry.
    """
    print(f"[PROBE] Loading fabric from: {fabric_path}")
    raw = load_json(fabric_path)

    slot_coords: Dict[str, Tuple[float, float]] = {}

    def visit(node):
        if isinstance(node, dict):
            name = node.get("name")
            x = node.get("x", node.get("x_um"))
            y = node.get("y", node.get("y_um"))

            if name is not None and x is not None and y is not None:
                try:
                    slot_coords[str(name)] = (float(x), float(y))
                except (TypeError, ValueError):
                    pass

            for v in node.values():
                visit(v)

        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(raw)

    print(f"[PROBE] Loaded coordinates for {len(slot_coords)} slots.")
    return slot_coords


# -----------------------------
# Probing + plot
# -----------------------------

def probe_point(
    fabric_path: Path,
    x_probe: float,
    y_probe: float,
    out_path: Path,
):
    slot_coords = load_fabric_slot_coords(fabric_path)
    if not slot_coords:
        print("[PROBE] ERROR: No slot coordinates available; nothing to plot.")
        return

    xs = [coord[0] for coord in slot_coords.values()]
    ys = [coord[1] for coord in slot_coords.values()]

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    print(f"[PROBE] Fabric bbox: x in [{min_x:.2f}, {max_x:.2f}], "
          f"y in [{min_y:.2f}, {max_y:.2f}]")
    print(f"[PROBE] Probe point: ({x_probe:.2f}, {y_probe:.2f})")

    # Plot
    plt.figure(figsize=(10, 10))

    # All fabric slots in light gray
    plt.scatter(xs, ys, s=5, alpha=0.3, label="Fabric slots")

    # Probe point in red X
    plt.scatter([x_probe], [y_probe], s=80, marker="x", label="Probe point")
    plt.text(
        x_probe,
        y_probe,
        f"  ({x_probe:.1f}, {y_probe:.1f})",
        ha="left",
        va="center",
        fontsize=8,
    )

    plt.xlabel("X (sites or µm)")
    plt.ylabel("Y (sites or µm)")
    plt.title("Probe point on fabric")

    plt.legend(loc="best")
    plt.gca().set_aspect("equal", adjustable="box")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(out_path, dpi=300)
    print(f"[PROBE] Saved probe plot to: {out_path}")
    plt.close()


# -----------------------------
# Main
# -----------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Probe a point (x, y) on the fabric layout "
                    "and visualize where it lies."
    )
    parser.add_argument(
        "--x", type=float, required=True,
        help="X coordinate of the probe point (in same units as fabric_db).",
    )
    parser.add_argument(
        "--y", type=float, required=True,
        help="Y coordinate of the probe point (in same units as fabric_db).",
    )
    parser.add_argument(
        "--fabric",
        help="Path to fabric_db.json "
             "(default: build/fabric/fabric_db.json)",
    )
    parser.add_argument(
        "--out",
        help="Output PNG path "
             "(default: build/probe_point.png)",
    )

    args = parser.parse_args()

    fabric_path = Path(args.fabric) if args.fabric else Path("build") / "fabric" / "fabric_db.json"
    out_path = Path(args.out) if args.out else Path("build") / "probe_point.png"

    probe_point(
        fabric_path=fabric_path,
        x_probe=args.x,
        y_probe=args.y,
        out_path=out_path,
    )


if __name__ == "__main__":
    main()