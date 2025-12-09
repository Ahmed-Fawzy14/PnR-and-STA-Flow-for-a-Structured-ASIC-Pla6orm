#!/usr/bin/env python3
# animated_eco_pd.py
import argparse
import json
from pathlib import Path
from typing import Dict, Tuple, Set, Any, List

import matplotlib.pyplot as plt
from matplotlib import animation


# =============================
# Basic helpers
# =============================

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

    Robust to:
      - top-level list of cells
      - dict with "tiles" -> "cells"
      - any nested mix of dicts/lists

    Any dict with:
        name + (x or x_um) + (y or y_um)
    is treated as a slot entry.
    """
    print(f"[VIS] Loading fabric from: {fabric_path}")
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

    print(f"[VIS] Loaded coordinates for {len(slot_coords)} slots from fabric_db.")
    return slot_coords


def load_unused_instances(unused_path: Path) -> Set[str]:
    """
    Load unused instances from JSON.

    Supports:
      - a plain list: ["inst1", "inst2", ...]
      - a dict with a key like "unused_instances", "unused", or "instances".
    """
    raw = load_json(unused_path)
    if isinstance(raw, list):
        return set(raw)
    if isinstance(raw, dict):
        for key in ["unused_instances", "unused", "instances"]:
            if key in raw and isinstance(raw[key], list):
                return set(raw[key])
    raise ValueError(f"Cannot interpret unused instances JSON: {unused_path}")


def load_tielo_info_full(path: Path) -> Tuple[str, int]:
    """
    Load tie-low instance + LO net bit from JSON.

    Accepts various key names for robustness.
    """
    tie_info = load_json(path)
    if not isinstance(tie_info, dict):
        raise ValueError(f"Tie-low info JSON must be a dict: {path}")

    inst_keys = ["tielo_inst", "conb_inst", "inst", "tielo_instance", "inst_name"]
    bit_keys = ["tielo_lo_bit", "lo_bit", "LO_bit", "bit", "tielo_net_bit"]

    inst_name = None
    bit_val = None

    for k in inst_keys:
        if k in tie_info:
            inst_name = tie_info[k]
            break

    for k in bit_keys:
        if k in tie_info:
            bit_val = tie_info[k]
            break

    if inst_name is None or bit_val is None:
        raise ValueError(
            f"Invalid tielo info in {path}: expected one of {inst_keys} for instance "
            f"and one of {bit_keys} for bit, got {list(tie_info.keys())}"
        )

    return inst_name, int(bit_val)


def load_data_structures(ds_path: Path) -> Dict[str, dict]:
    """
    Load data_structures.json and return the logical_db (instances dict),
    if available. Otherwise returns an empty dict.
    """
    if not ds_path.exists():
        print(f"[VIS] WARNING: data_structures.json not found at {ds_path}; "
              f"will not use nicer instance/type names.")
        return {}

    raw = load_json(ds_path)
    if isinstance(raw, dict) and "logical_db" in raw and isinstance(raw["logical_db"], dict):
        return raw["logical_db"]

    print(f"[VIS] WARNING: Could not find 'logical_db' dict in {ds_path}; "
          f"will not use nicer instance/type names.")
    return {}


def short_inst_suffix(inst_name: str) -> str:
    """
    Extract a shorter ID from a long ABC/Yosys-style name like:

        $abc$9276$auto$blifparse.cc:396:parse_blif$11608

    We return "U11608" in this case.

    If no numeric suffix is found, we truncate the name.
    """
    import re
    m = re.search(r"\$(\d+)$", inst_name)
    if m:
        return f"U{m.group(1)}"

    # Fallback: last part or truncated version
    if len(inst_name) > 32:
        return inst_name[-32:]
    return inst_name


def pretty_inst_label(inst_name: str, logical_db: Dict[str, dict]) -> str:
    """
    Build a user-friendly label for an instance using:
      - its cell type (from logical_db, if available)
      - a short unique suffix like U11608
    """
    inst_rec = logical_db.get(inst_name, {})
    ctype = inst_rec.get("type", "?")
    suffix = short_inst_suffix(inst_name)
    return f"{ctype} ({suffix})"


# =============================
# Static visualization
# =============================

def visualize_pd_eco_static(
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
    tielo_inst, tielo_lo_bit = load_tielo_info_full(tie_info_path)
    print(f"[VIS] Tie-low driver instance: {tielo_inst} (LO bit = {tielo_lo_bit})")

    slot_coords: Dict[str, Tuple[float, float]] = load_fabric_slot_coords(fabric_path)
    if not slot_coords:
        print("[VIS] ERROR: No slot coordinates available; nothing to plot.")
        return

    # Reverse: slot -> inst
    slot_to_inst: Dict[str, str] = {slot: inst for inst, slot in inst_to_slot.items()}

    used_logic_x: List[float] = []
    used_logic_y: List[float] = []

    spares_x: List[float] = []
    spares_y: List[float] = []

    filler_x: List[float] = []
    filler_y: List[float] = []

    tielo_x: List[float] = []
    tielo_y: List[float] = []

    used_count = spare_count = filler_count = tielo_count = 0

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

    plt.figure(figsize=(10, 10))
    handles = []

    if filler_x:
        h = plt.scatter(filler_x, filler_y, s=5, alpha=0.3, label="Filler / empty")
        handles.append(h)
    if used_logic_x:
        h = plt.scatter(used_logic_x, used_logic_y, s=10, alpha=0.8, label="Used logic")
        handles.append(h)
    if spares_x:
        h = plt.scatter(spares_x, spares_y, s=20, marker="s", alpha=0.9,
                        label="Powered-down spares")
        handles.append(h)
    if tielo_x:
        h = plt.scatter(tielo_x, tielo_y, s=40, marker="*", alpha=1.0,
                        label="Tie-low driver")
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


# =============================
# Animated visualization
# =============================

def animate_pd_eco(
    design: str,
    fabric_path: Path,
    map_path: Path,
    unused_path: Path,
    tie_info_path: Path,
    data_structures_path: Path,
    out_gif_path: Path,
):
    print(f"[VIS] Design: {design}")

    print(f"[VIS] Loading placement map from: {map_path}")
    inst_to_slot = load_placement_map(map_path)

    print(f"[VIS] Loading unused instances from: {unused_path}")
    unused_instances: Set[str] = load_unused_instances(unused_path)
    print(f"[VIS] #unused instances (PD ECO): {len(unused_instances)}")

    print(f"[VIS] Loading tie-low info from: {tie_info_path}")
    tielo_inst, tielo_lo_bit = load_tielo_info_full(tie_info_path)
    print(f"[VIS] Tie-low driver instance: {tielo_inst} (LO bit = {tielo_lo_bit})")

    # Logical DB for pretty labels
    logical_db = load_data_structures(data_structures_path)

    # Fabric
    slot_coords: Dict[str, Tuple[float, float]] = load_fabric_slot_coords(fabric_path)
    if not slot_coords:
        print("[VIS] ERROR: No slot coordinates available; cannot animate.")
        return

    # Reverse: slot -> inst
    slot_to_inst: Dict[str, str] = {slot: inst for inst, slot in inst_to_slot.items()}

    # Collect coordinates
    used_logic_pts: List[Tuple[float, float]] = []
    spare_pts: List[Tuple[float, float, str]] = []  # (x, y, inst_name)
    filler_pts: List[Tuple[float, float]] = []
    tielo_coord: Tuple[float, float] = None

    for slot_name, coord in slot_coords.items():
        if not isinstance(coord, (list, tuple)) or len(coord) < 2:
            continue
        x, y = coord[0], coord[1]

        inst = slot_to_inst.get(slot_name)
        if inst is not None:
            if inst == tielo_inst:
                tielo_coord = (x, y)
            elif inst in unused_instances:
                spare_pts.append((x, y, inst))
            else:
                used_logic_pts.append((x, y))
        else:
            filler_pts.append((x, y))

    if tielo_coord is None:
        print("[VIS] ERROR: Could not locate tie-low driver on fabric; cannot animate.")
        return

    print("[VIS] Plotted cells (for animation):")
    print(f"      Used logic         : {len(used_logic_pts)}")
    print(f"      Powered-down spares: {len(spare_pts)}")
    print(f"      Filler/empty       : {len(filler_pts)}")
    print(f"      Tie-low driver     : 1")

    if not spare_pts:
        print("[VIS] Skipping animation: no unused spares to connect.")
        return

    # =============================
    # NEW: limit complexity for big designs
    # =============================
    total_spares = len(spare_pts)
    MAX_SPARES_TO_ANIMATE = 800   # you can tune this

    if total_spares > MAX_SPARES_TO_ANIMATE:
        step = max(1, total_spares // MAX_SPARES_TO_ANIMATE)
        print(f"[VIS] Too many spares ({total_spares}); "
              f"sampling every {step}-th spare for animation.")

        spare_pts = spare_pts[::step]   # downsample
        total_spares = len(spare_pts)

    # =============================
    # Set up figure
    # =============================
    fig, ax = plt.subplots(figsize=(10, 10))

    # Static scatter layers
    filler_x = [p[0] for p in filler_pts]
    filler_y = [p[1] for p in filler_pts]
    used_x = [p[0] for p in used_logic_pts]
    used_y = [p[1] for p in used_logic_pts]
    sp_x = [p[0] for p in spare_pts]
    sp_y = [p[1] for p in spare_pts]
    tielo_x, tielo_y = tielo_coord

    handles = []

    if filler_x:
        h = ax.scatter(filler_x, filler_y, s=5, alpha=0.3, label="Filler / empty")
        handles.append(h)
    if used_x:
        h = ax.scatter(used_x, used_y, s=10, alpha=0.8, label="Used logic")
        handles.append(h)
    if sp_x:
        h = ax.scatter(sp_x, sp_y, s=20, marker="s", alpha=0.9,
                       label="Powered-down spares")
        handles.append(h)

    h = ax.scatter([tielo_x], [tielo_y], s=40, marker="*", alpha=1.0,
                   label="Tie-low driver")
    handles.append(h)

    if handles:
        ax.legend(loc="upper right")

    ax.set_xlabel("X (sites or µm)")
    ax.set_ylabel("Y (sites or µm)")
    ax.set_title(f"Power-Down ECO Animation – {design}")
    ax.set_aspect("equal", adjustable="box")

    # Flying wires (one Line2D per spare)
    lines = []
    for _ in spare_pts:
        line, = ax.plot([], [], linewidth=0.8, alpha=0.0, color="red")
        lines.append(line)

    # -----------------------------
    # Text overlays
    # -----------------------------
    text_info = ax.text(
        650, 1010, "",
        # transform=ax.transAxes,
        ha="right", va="top",
        fontsize=8,
        bbox=dict(boxstyle="round", facecolor="white", alpha=0.8)
    )
    text_counter = ax.text(
        0.99, 0.86, "",
        transform=ax.transAxes,
        ha="right", va="top",
        fontsize=8,
        bbox=dict(boxstyle="round", facecolor="white", alpha=0.8)
    )

    # Pre-compute pretty labels
    pretty_spares = [
        pretty_inst_label(inst_name, logical_db) for (_, _, inst_name) in spare_pts
    ]
    pretty_tielo = pretty_inst_label(tielo_inst, logical_db)

    # =============================
    # NEW: fewer frames per spare
    # =============================
    FRAMES_PER_SPARE = 4  # was 10
    total_frames = total_spares * FRAMES_PER_SPARE

    def init():
        for line in lines:
            line.set_data([], [])
            line.set_alpha(0.0)
        text_info.set_text("")
        text_counter.set_text(
            f"Remaining unconnected spares: {total_spares}"
        )
        return lines + [text_info, text_counter]

    def update(frame: int):
        spare_idx = frame // FRAMES_PER_SPARE
        step = frame % FRAMES_PER_SPARE

        connected = min(spare_idx, total_spares)
        remaining = total_spares - connected

        text_counter.set_text(
            f"Remaining unconnected spares: {remaining}"
        )

        if spare_idx < total_spares:
            text_info.set_text(
                f"Connecting {pretty_spares[spare_idx]} → {pretty_tielo}"
            )
        else:
            text_info.set_text("All spares tied to tie-low.")

        for i, line in enumerate(lines):
            sx, sy, _inst = spare_pts[i]

            if i < spare_idx:
                line.set_data([tielo_x, sx], [tielo_y, sy])
                line.set_alpha(0.4)
            elif i == spare_idx and spare_idx < total_spares:
                frac = (step + 1) / float(FRAMES_PER_SPARE)
                x = tielo_x + frac * (sx - tielo_x)
                y = tielo_y + frac * (sy - tielo_y)
                line.set_data([tielo_x, x], [tielo_y, y])
                line.set_alpha(0.9)
            else:
                line.set_data([], [])
                line.set_alpha(0.0)

        return lines + [text_info, text_counter]

    print(f"[VIS] Creating animation: {total_spares} spares, {total_frames} frames "
          f"({FRAMES_PER_SPARE} frames/spare)")

    anim = animation.FuncAnimation(
        fig,
        update,
        init_func=init,
        frames=total_frames,
        interval=80,
        blit=True
    )

    out_gif_path = Path(out_gif_path)
    out_gif_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[VIS] Saving GIF to: {out_gif_path}")
    anim.save(out_gif_path, writer="pillow", fps=12)
    plt.close(fig)


# =============================
# Main
# =============================

def main():
    parser = argparse.ArgumentParser(
        description="Visualize and animate power-down ECO: show used logic, "
                    "powered-down spares, filler slots and tie-low driver on the fabric."
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
        help="Path to placement map "
             "(default: build/<design>/<design>_sa.map)",
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
        "--data",
        help="Path to data_structures.json "
             "(default: build/<design>/data_structures.json)",
    )
    parser.add_argument(
        "--out",
        help="Output static plot path "
             "(default: build/<design>/<design>_pd_eco_plot.png)",
    )
    parser.add_argument(
        "--gif",
        help="Output GIF path for animation "
             "(default: build/<design>/<design>_pd_eco_anim.gif)",
    )
    parser.add_argument(
        "--animate",
        action="store_true",
        help="If set, generate animated GIF of wires tying spares to tie-low.",
    )

    args = parser.parse_args()
    design = args.design

    base_dir = Path("build") / design

    fabric_path = Path(args.fabric) if args.fabric else Path("build") / "fabric" / "fabric_db.json"
    map_path = Path(args.map) if args.map else base_dir / f"{design}_sa.map"
    unused_path = Path(args.unused) if args.unused else base_dir / f"{design}_pd_unused_instances.json"
    tie_info_path = Path(args.tieinfo) if args.tieinfo else base_dir / f"{design}_pd_tielo_source.json"
    data_structures_path = Path(args.data) if args.data else base_dir / "data_structures.json"
    out_plot_path = Path(args.out) if args.out else base_dir / f"{design}_pd_eco_plot.png"
    out_gif_path = Path(args.gif) if args.gif else base_dir / f"{design}_pd_eco_anim.gif"

    # Always create static plot
    visualize_pd_eco_static(
        design=design,
        fabric_path=fabric_path,
        map_path=map_path,
        unused_path=unused_path,
        tie_info_path=tie_info_path,
        out_path=out_plot_path,
    )

    # Optionally animate
    if args.animate:
        animate_pd_eco(
            design=design,
            fabric_path=fabric_path,
            map_path=map_path,
            unused_path=unused_path,
            tie_info_path=tie_info_path,
            data_structures_path=data_structures_path,
            out_gif_path=out_gif_path,
        )


if __name__ == "__main__":
    main()