import argparse
import json
import os
import re
from collections import Counter
from typing import Any, Dict, List, Tuple, Optional, Set
from PIL import Image, ImageDraw, ImageFont


# ---------------------------------------------------------
#  I/O & Parsing
# ---------------------------------------------------------

def load_json(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        print(f"[ERROR] File not found: {path}")
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_map_file(path: str) -> Dict[str, str]:
    """
    Parses the .map file.
    Expects lines: <Logical_Name> <Physical_Site_Name>
    Returns: { Logical_Name : Physical_Site_Name }
    """
    mapping = {}
    if not os.path.exists(path):
        print(f"[ERROR] Map file not found: {path}")
        return None

    print(f"[INFO] Parsing map file: {path}")
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 2:
                logical_name = parts[0]
                physical_name = parts[1]
                mapping[logical_name] = physical_name

    print(f"[INFO] Found {len(mapping)} mapped instances.")
    return mapping


def ensure_dir_for(path: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


# ---------------------------------------------------------
#  Data Processing
# ---------------------------------------------------------

def get_added_edges(old_graph: Dict[str, List[str]], new_graph: Dict[str, List[str]]) -> List[Tuple[str, str]]:
    """
    Identifies edges that are present in new_graph but not in old_graph.
    Returns list of (source_node, dest_node).
    """
    added = []
    for src, new_dests in new_graph.items():
        old_dests = set(old_graph.get(src, []))
        # Handle new_dests being a list
        for dst in new_dests:
            if dst not in old_dests:
                added.append((src, dst))
    return added


# ---------------------------------------------------------
#  Colors & Styling
# ---------------------------------------------------------

PIN_COLORS = {"INPUT": (31, 119, 180), "OUTPUT": (255, 127, 14), "INOUT": (44, 160, 44)}

# Distinct palette for logic cells
SLOT_PALETTE = [
    (31, 119, 180), (255, 127, 14), (44, 160, 44), (214, 39, 40), (148, 103, 189),
    (140, 86, 75), (227, 119, 194), (127, 127, 127), (188, 189, 34), (23, 190, 207),
    (57, 59, 121), (99, 121, 57), (140, 109, 49), (132, 60, 57), (123, 65, 115)
]

CTS_COLOR = (255, 0, 0, 255)  # Red for CTS lines
CTS_WIDTH = 2


def slot_color_map(types: List[str]) -> Dict[str, Tuple[int, int, int]]:
    cmap = {}
    sorted_types = sorted(list(set(types)))
    for i, t in enumerate(sorted_types):
        cmap[t] = SLOT_PALETTE[i % len(SLOT_PALETTE)]
    return cmap


def with_alpha(rgb: Tuple[int, int, int], alpha: float) -> Tuple[int, int, int, int]:
    a = max(0, min(255, int(round(alpha * 255))))
    return (rgb[0], rgb[1], rgb[2], a)


def clean_type_name(phys_type: str) -> str:
    if not phys_type: return "UNK"
    s = phys_type.replace("sky130_fd_sc_hd__", "").replace("sky130_fd_sc_hvl__", "")
    s = re.sub(r"_\d+$", "", s)
    return s.upper()


# ---------------------------------------------------------
#  Fabric Logic
# ---------------------------------------------------------

def get_site_dims_um(fab: Dict[str, Any], default_w: float, default_h: float) -> Tuple[float, float]:
    fi = fab.get("fabric_info", {})
    sdim = fi.get("site_dimensions_um", {})
    sw = sdim.get("width")
    sh = sdim.get("height")

    site_w_um = float(sw) if sw is not None else float(default_w)
    site_h_um = float(sh) if sh is not None else float(default_h)
    return site_w_um, site_h_um


def build_physical_db(fab: Dict[str, Any], default_w: float, default_h: float) -> Dict[str, Dict[str, Any]]:
    """
    Builds a database of physical sites: { phys_name: {x, y, w, h} }
    """
    site_w_um, site_h_um = get_site_dims_um(fab, default_w, default_h)
    db = {}

    def add_gate(g: Dict[str, Any]) -> None:
        phys_name = g.get("name")
        if not phys_name:
            return

        # Dimensions
        w_sites = g.get("width_sites", None)
        if w_sites is not None:
            w_um = float(w_sites) * site_w_um
        else:
            w_um = float(g.get("w", default_w))

        h_um = float(g.get("h", site_h_um))
        x_um = float(g.get("x", g.get("x_um", 0.0)))
        y_um = float(g.get("y", g.get("y_um", 0.0)))

        # Center coordinates for line drawing
        cx = x_um + (w_um / 2)
        cy = y_um + (h_um / 2)

        db[phys_name] = {
            "x": x_um, "y": y_um, "w": w_um, "h": h_um,
            "cx": cx, "cy": cy,
            "type": clean_type_name(g.get("physical_cell_type", g.get("type", "UNK")))
        }

    # Supported fabric formats:
    # 1) tiles-based: {"tiles": [{"cells": [...]}, ...]}
    # 2) raw slot dict: {"TAP": [{...}], "BUF": [{...}], ...}
    tiles = fab.get("tiles", None)
    if isinstance(tiles, list) and tiles:
        for t in tiles:
            # Support both 'cells' and 'gates'
            cells = t.get("cells", t.get("gates", []))
            for g in cells:
                if isinstance(g, dict):
                    add_gate(g)
        return db

    # Raw slot dict format
    if isinstance(fab, dict):
        for _, slots in fab.items():
            if not isinstance(slots, list):
                continue
            for g in slots:
                if isinstance(g, dict):
                    add_gate(g)
    return db


def infer_die_core(fab: Dict[str, Any], slots: List[Dict[str, Any]]):
    # Try to read explicit die/core first
    die_in = fab.get("die", {})
    core_in = fab.get("core", {})

    dw, dh = die_in.get("width_um"), die_in.get("height_um")
    margin = float(die_in.get("core_margin_um", 0.0))

    cw, ch = core_in.get("width_um"), core_in.get("height_um")
    cx, cy = core_in.get("x_um"), core_in.get("y_um")

    # If missing, infer from bounds
    if dw is None or dh is None:
        xs = [s["x"] for s in slots]
        ys = [s["y"] for s in slots]
        if not xs: xs = [0.0]
        if not ys: ys = [0.0]

        for p in fab.get("pins", []):
            xs.append(float(p.get("x_um", p.get("x", 0))))
            ys.append(float(p.get("y_um", p.get("y", 0))))

        margin = 10.0
        dw = (max(xs) - min(xs)) + 2 * margin
        dh = (max(ys) - min(ys)) + 2 * margin
        cx = margin
        cy = margin
        cw = dw - 2 * margin
        ch = dh - 2 * margin

    die_um = {"width_um": float(dw), "height_um": float(dh), "core_margin_um": margin}
    core_um = {"x_um": float(cx if cx else margin),
               "y_um": float(cy if cy else margin),
               "width_um": float(cw), "height_um": float(ch)}

    return die_um, core_um


# ---------------------------------------------------------
#  Drawing Engine
# ---------------------------------------------------------

def try_font(size_px: int) -> ImageFont.FreeTypeFont:
    candidates = ["DejaVuSans.ttf", "Arial.ttf", "arial.ttf", "msgothic.ttc"]
    for name in candidates:
        try:
            return ImageFont.truetype(name, size_px)
        except Exception:
            pass
    return ImageFont.load_default()


def draw_rect(draw, x, y, w, h, fill=None, outline=None, width=1):
    draw.rectangle([x, y, x + w, y + h], fill=fill, outline=outline, width=width)


def to_img_coords(x_um, y_um, h_um, ox, oy, H_die, scale):
    """
    Converts logical UM coordinates (origin bottom-left) to Image coords (origin top-left).
    y input is the BOTTOM of the object.
    """
    sx = ox + (x_um * scale)
    sy = oy + (H_die - (y_um * scale) - (h_um * scale))
    return sx, sy


def to_img_point(x_um, y_um, ox, oy, H_die, scale):
    """
    Converts a single Point (x,y) from bottom-left origin to top-left origin
    """
    sx = ox + (x_um * scale)
    sy = oy + (H_die - (y_um * scale))
    return sx, sy


def render_cts_vis(out_path: str,
                   die_um: Dict, core_um: Dict,
                   phys_db: Dict,
                   logical_map: Dict,
                   cts_edges: List[Tuple[str, str]],
                   slot_colors: Dict[str, Tuple[int, int, int]],
                   width_px: int):
    margin = 50
    # Add legend width
    legend_width = 250
    scale = width_px / max(1.0, die_um["width_um"])

    W_die_px = die_um["width_um"] * scale
    H_die_px = die_um["height_um"] * scale

    W_img = int(W_die_px + 2 * margin + legend_width)
    H_img = int(max(H_die_px + 2 * margin, 50 + len(slot_colors) * 25))

    img = Image.new("RGBA", (W_img, H_img), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img, "RGBA")

    ox = margin
    oy = margin  # top-left of die box in image

    # 1. Draw Die
    draw_rect(draw, ox, oy, W_die_px, H_die_px, outline="black", width=3)

    # 2. Draw Core
    cx = ox + (core_um["x_um"] * scale)
    cy = oy + (H_die_px - (core_um["y_um"] * scale) - (core_um["height_um"] * scale))
    draw_rect(draw, cx, cy, core_um["width_um"] * scale, core_um["height_um"] * scale, outline="gray")

    # 3. Draw Placed Cells
    # Build coordinate map for logical instances {logical_name: (cx, cy)}
    logical_coords = {}

    for logical, phys in logical_map.items():
        if phys in phys_db:
            p = phys_db[phys]
            ctype = p["type"]

            # Save logical coord
            logical_coords[logical] = (p["cx"], p["cy"])

            # Draw Cell
            sx, sy = to_img_coords(p["x"], p["y"], p["h"], ox, oy, H_die_px, scale)
            sw = p["w"] * scale
            sh = p["h"] * scale

            fill_col = with_alpha(slot_colors.get(ctype, (200, 200, 200)), 0.8)
            draw_rect(draw, sx, sy, sw, sh, fill=fill_col, outline=(50, 50, 50, 100))

    # 4. Draw CTS Lines
    for src, dst in cts_edges:
        if src in logical_coords and dst in logical_coords:
            p1 = logical_coords[src]
            p2 = logical_coords[dst]

            x1, y1 = to_img_point(p1[0], p1[1], ox, oy, H_die_px, scale)
            x2, y2 = to_img_point(p2[0], p2[1], ox, oy, H_die_px, scale)

            draw.line([(x1, y1), (x2, y2)], fill=CTS_COLOR, width=CTS_WIDTH)

            # Optional: Draw small circles at endpoints
            r = 2
            draw.ellipse([x1 - r, y1 - r, x1 + r, y1 + r], fill=CTS_COLOR)
            draw.ellipse([x2 - r, y2 - r, x2 + r, y2 + r], fill=CTS_COLOR)

    # 5. Title / Legend
    font = try_font(20)
    font_lbl = try_font(12)
    draw.text((ox, 10), f"CTS Visualization: {len(cts_edges)} added edges", font=font, fill="black")

    # Legend
    lx = ox + W_die_px + 40
    ly = oy

    draw.text((lx, ly), "Legend:", font=font_lbl, fill="black")
    ly += 25

    for ctype, color in sorted(slot_colors.items()):
        draw_rect(draw, lx, ly, 15, 15, fill=with_alpha(color, 1.0), outline="black")
        draw.text((lx + 25, ly), ctype, font=font_lbl, fill="black")
        ly += 20

    ensure_dir_for(out_path)
    img.save(out_path)
    print(f"[SUCCESS] Saved visualization to {out_path}")


# ---------------------------------------------------------
#  Main
# ---------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Visualize CTS changes")
    parser.add_argument("--fabric", required=True, help="Path to fabric JSON")
    parser.add_argument("--map", required=True, help="Path to placement .map file")
    parser.add_argument("--old_netlist", required=True, help="Path to pre-CTS netlist JSON")
    parser.add_argument("--new_netlist", required=True, help="Path to post-CTS netlist JSON")
    parser.add_argument("--out", default="cts_vis.png", help="Output PNG path")
    parser.add_argument("--width", type=int, default=2000, help="Target image width")

    parser.add_argument("--slot-w", type=float, default=0.46)
    parser.add_argument("--slot-h", type=float, default=2.72)

    args = parser.parse_args()

    # 1. Load Data
    fab = load_json(args.fabric)
    mapping = parse_map_file(args.map)
    old_net = load_json(args.old_netlist)
    new_net = load_json(args.new_netlist)

    if not fab or not mapping:
        return

    # 2. Process Fabric
    # We ignore "visualizing ALL slots" in favor of just the occupied ones for clarity? 
    # Or we build the DB of all slots so we can look up coordinates.
    phys_db = build_physical_db(fab, args.slot_w, args.slot_h)

    # Infer Die Size
    # We just pass the raw slots list to the helper
    # Re-construct simple slots list for helper
    slots_list = []
    for k, v in phys_db.items():
        slots_list.append(v)

    # We filter slots_list to only those in the mapping for tighter bounds? 
    # Or just use all. Let's use all to show full die.
    die_um, core_um = infer_die_core(fab, slots_list)

    # 3. Identify CTS Edges
    cts_edges = get_added_edges(old_net, new_net)
    print(f"[INFO] Found {len(cts_edges)} new edges in CTS.")

    # 4. Colors
    # Collect all types found in the mapping
    present_types = set()
    for logical, phys in mapping.items():
        if phys in phys_db:
            present_types.add(phys_db[phys]["type"])

    slot_colors = slot_color_map(list(present_types))

    # 5. Render
    render_cts_vis(args.out, die_um, core_um, phys_db, mapping, cts_edges, slot_colors, args.width)


if __name__ == "__main__":
    main()