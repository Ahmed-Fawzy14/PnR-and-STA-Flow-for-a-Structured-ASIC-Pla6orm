import argparse
import json
import os
import re
from collections import Counter
from typing import Any, Dict, List, Tuple, Optional
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------
#  I/O & Parsing
# ---------------------------------------------------------

def load_json(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        print(f"[ERROR] Fabric file not found: {path}")
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def parse_map_file(path: str) -> Dict[str, str]:
    """
    Parses the .map file.
    Expects lines: <Logical_Name> <Physical_Site_Name>
    Returns: { Physical_Site_Name : Logical_Name }
    """
    mapping = {}
    if not os.path.exists(path):
        print(f"[WARN] Map file not found: {path}. Visualization will show ALL cells.")
        return None
        
    print(f"[INFO] Parsing map file: {path}")
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 2:
                logical_name = parts[0]
                physical_name = parts[1]
                mapping[physical_name] = logical_name
    
    print(f"[INFO] Found {len(mapping)} mapped instances.")
    return mapping

def ensure_dir_for(path: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)

# ---------------------------------------------------------
#  Colors & Styling
# ---------------------------------------------------------

PIN_COLORS = {"INPUT": (31,119,180), "OUTPUT": (255,127,14), "INOUT": (44,160,44)} 

# Distinct palette for logic cells
SLOT_PALETTE = [
    (31,119,180), (255,127,14), (44,160,44), (214,39,40), (148,103,189),
    (140,86,75), (227,119,194), (127,127,127), (188,189,34), (23,190,207),
    (57,59,121), (99,121,57), (140,109,49), (132,60,57), (123,65,115)
]

def slot_color_map(types: List[str]) -> Dict[str, Tuple[int,int,int]]:
    cmap = {}
    sorted_types = sorted(list(set(types)))
    for i, t in enumerate(sorted_types):
        cmap[t] = SLOT_PALETTE[i % len(SLOT_PALETTE)]
    return cmap

def with_alpha(rgb: Tuple[int,int,int], alpha: float) -> Tuple[int,int,int,int]:
    a = max(0, min(255, int(round(alpha * 255))))
    return (rgb[0], rgb[1], rgb[2], a)

def clean_type_name(phys_type: str) -> str:
    """
    Converts 'sky130_fd_sc_hd__nand2_2' -> 'NAND2' for cleaner legends.
    """
    if not phys_type: return "UNK"
    # Remove standard library prefix
    s = phys_type.replace("sky130_fd_sc_hd__", "").replace("sky130_fd_sc_hvl__", "")
    # Remove drive strength suffix (e.g., _1, _2, _4)
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

def collect_slots(fab: Dict[str, Any], 
                  placement_map: Optional[Dict[str, str]], 
                  default_w: float, default_h: float) -> List[Dict[str, Any]]:
    """
    Iterates over the fabric. 
    If placement_map is provided, it ONLY returns cells that appear in the map.
    """
    site_w_um, site_h_um = get_site_dims_um(fab, default_w, default_h)
    slots = []

    tiles = fab.get("tiles", [])
    for t in tiles:
        # Support both 'cells' (new format) and 'gates' (old format)
        cells = t.get("cells", t.get("gates", []))
        
        for g in cells:
            phys_name = g.get("name", "UNKNOWN")
            
            # Filtering Logic
            logical_name = None
            if placement_map is not None:
                if phys_name in placement_map:
                    logical_name = placement_map[phys_name]
                else:
                    # This physical site is empty in the current design -> Skip it
                    continue
            else:
                # No map provided, show everything (raw fabric view)
                logical_name = phys_name

            # Dimensions
            w_sites = g.get("width_sites", None)
            if w_sites is not None:
                w_um = float(w_sites) * site_w_um
            else:
                w_um = float(g.get("w", default_w))

            h_um = float(site_h_um) 

            x_um = float(g.get("x", g.get("x_um", 0.0)))
            y_um = float(g.get("y", g.get("y_um", 0.0)))

            raw_type = g.get("physical_cell_type", g.get("type", "UNK"))
            clean_type = clean_type_name(raw_type)

            slots.append({
                "name": logical_name,         # The name from the .map file (e.g., slice$4911)
                "phys_loc": phys_name,        # The grid location (e.g., T17Y0...)
                "type": clean_type,           # The simplified type (e.g., NAND2)
                "x": x_um, "y": y_um, "w": w_um, "h": h_um,
                "width_sites": w_sites,
                "orient": g.get("orient", "N"),
            })

    return slots

def infer_die_core(fab: Dict[str, Any], slots: List[Dict[str, Any]]):
    # Try to read explicit die/core first
    die_in = fab.get("die", {})
    core_in = fab.get("core", {})
    
    dw, dh = die_in.get("width_um"), die_in.get("height_um")
    margin = float(die_in.get("core_margin_um", 0.0))
    
    cw, ch = core_in.get("width_um"), core_in.get("height_um")
    cx, cy = core_in.get("x_um"), core_in.get("y_um")

    # If missing, infer from bounds of all objects (pins + cells)
    if dw is None or dh is None:
        xs = [s["x"] for s in slots]
        ys = [s["y"] for s in slots]
        if not xs: xs = [0.0]
        if not ys: ys = [0.0]
        
        # Add pin coordinates to bounds
        for p in fab.get("pins", []):
            xs.append(float(p.get("x_um", p.get("x", 0))))
            ys.append(float(p.get("y_um", p.get("y", 0))))

        # Add a default 10um margin around everything found
        margin = 10.0
        dw = (max(xs) - min(xs)) + 2 * margin
        dh = (max(ys) - min(ys)) + 2 * margin
        # Assume origin 0,0 is inside the margin
        cx = margin
        cy = margin
        cw = dw - 2*margin
        ch = dh - 2*margin

    die_um = {"width_um": float(dw), "height_um": float(dh), "core_margin_um": margin}
    core_um = {"x_um": float(cx if cx else margin), 
               "y_um": float(cy if cy else margin), 
               "width_um": float(cw), "height_um": float(ch)}
               
    return die_um, core_um

def parse_pins(fab: Dict[str, Any], die_um: Dict[str, Any]) -> List[Dict[str, Any]]:
    pins = []
    die_w = die_um["width_um"]
    die_h = die_um["height_um"]

    for p in fab.get("pins", []):
        side = p.get("side", "").lower()
        x_um = float(p.get("x_um", p.get("x", 0.0)))
        y_um = float(p.get("y_um", p.get("y", 0.0)))

        # Snap to edge based on side
        if side == "west":  x, y = 0.0, y_um
        elif side == "east": x, y = die_w, y_um
        elif side == "north": x, y = x_um, die_h
        elif side == "south": x, y = x_um, 0.0
        else: x, y = x_um, y_um

        pins.append({
            "name": p.get("name", ""),
            "side": side,
            "x": x, "y": y,
            "w": float(p.get("w", 2.0)),
            "h": float(p.get("h", 2.0)),
            "direction": p.get("direction", "INOUT"),
        })
    return pins

# ---------------------------------------------------------
#  Drawing Engine
# ---------------------------------------------------------

def try_font(size_px: int) -> ImageFont.FreeTypeFont:
    # Try common system fonts
    candidates = ["DejaVuSans.ttf", "Arial.ttf", "arial.ttf", "msgothic.ttc"]
    for name in candidates:
        try:
            return ImageFont.truetype(name, size_px)
        except Exception:
            pass
    return ImageFont.load_default()

def draw_rect(draw, x, y, w, h, fill=None, outline=None, width=1):
    draw.rectangle([x, y, x+w, y+h], fill=fill, outline=outline, width=width)

def render_png(out_path: str, 
               die_px: Dict, core_px: Dict, 
               slots_px: List, pins_px: List, 
               scale: float, 
               slot_colors: Dict,
               title: str):
    
    img = create_placement_image(die_px, core_px, slots_px, pins_px, scale, slot_colors, title)
    img.save(out_path)
    print(f"[SUCCESS] Wrote image to {out_path}")

def create_placement_image(die_px: Dict, core_px: Dict, 
               slots_px: List, pins_px: List, 
               scale: float, 
               slot_colors: Dict,
               title: str) -> Image.Image:

    # Layout Configuration
    margin = 60  # px
    legend_width = 250
    
    W_die = int(die_px["width"])
    H_die = int(die_px["height"])
    
    W_img = W_die + (margin * 2) + legend_width
    H_img = H_die + (margin * 2)
    
    ox = margin
    oy = margin # Top-left of die in image coords
    
    # Create Image
    img = Image.new("RGBA", (W_img, H_img), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img, "RGBA")
    
    font_title = try_font(20)
    font_lbl = try_font(12)
    font_tiny = try_font(10)

    # 1. Draw Title
    draw.text((ox, 15), title, font=font_title, fill=(0,0,0,255))

    # 2. Draw Die Boundary
    draw_rect(draw, ox, oy, W_die, H_die, outline=(0,0,0,255), width=3)
    
    # 3. Draw Core Boundary
    # Note: core_px is relative to die origin (0,0 bottom left)
    # Image coordinates have (0,0) at top left.
    # To draw core:
    #  x = ox + core_x
    #  y = oy + (DieHeight - core_y - core_height)
    
    cx = ox + core_px["x"]
    cy = oy + (H_die - core_px["y"] - core_px["height"]) 
    
    draw_rect(draw, cx, cy, core_px["width"], core_px["height"], outline=(100,100,100,255), width=1)

    # 4. Draw Slots (The placed cells)
    overlay = Image.new("RGBA", (W_img, H_img), (0,0,0,0))
    ov_draw = ImageDraw.Draw(overlay)

    for s in slots_px:
        # Cartesian to Image coords (Y-flip)
        sx = ox + s["x"]
        sy = oy + (H_die - s["y"] - s["h"])
        
        color = with_alpha(slot_colors.get(s["type"], (150,150,150)), 0.8)
        
        draw_rect(ov_draw, sx, sy, s["w"], s["h"], fill=color, outline=(50,50,50,200))
        
        # If big enough, draw text
        if s["w"] > 20 and s["h"] > 10:
            ov_draw.text((sx+2, sy+2), s["type"], font=font_tiny, fill=(255,255,255,200))

    img.alpha_composite(overlay)

    # 5. Draw Pins
    for p in pins_px:
        px = ox + p["x"]
        # For pins on North/South, we need to flip logic carefully
        py = oy + (H_die - p["y"]) 
        
        pw, ph = p["w"], p["h"]
        
        rect_x = px - (pw/2) if p["side"] in ["north", "south"] else px
        rect_y = py - (ph/2) if p["side"] in ["east", "west"] else py - ph
        
        if p["side"] == "south": rect_y = oy + H_die - ph
        if p["side"] == "north": rect_y = oy
        
        col = PIN_COLORS.get(p["direction"], (50,50,50))
        draw_rect(draw, rect_x, rect_y, pw, ph, fill=with_alpha(col, 0.8), outline="black")
        
        # Label
        label_x = rect_x + pw + 2
        label_y = rect_y
        if p["side"] == "east": label_x = rect_x + pw + 5
        elif p["side"] == "west": label_x = rect_x - 50
        
        draw.text((label_x, label_y), p["name"], font=font_lbl, fill="black")

    # 6. Draw Legend
    lx = ox + W_die + 40
    ly = oy
    
    draw.text((lx, ly), "Legend:", font=font_lbl, fill="black")
    ly += 25
    
    # Cell Types
    counts = Counter(s["type"] for s in slots_px)
    for ctype, count in sorted(counts.items()):
        col = slot_colors.get(ctype, (150,150,150))
        draw_rect(draw, lx, ly, 15, 15, fill=with_alpha(col, 1.0), outline="black")
        draw.text((lx + 25, ly), f"{ctype} ({count})", font=font_lbl, fill="black")
        ly += 20
    
    ly += 20
    # Pin Types
    for ptype, col in PIN_COLORS.items():
        draw_rect(draw, lx, ly, 15, 15, fill=with_alpha(col, 1.0), outline="black")
        draw.text((lx + 25, ly), f"PIN: {ptype}", font=font_lbl, fill="black")
        ly += 20

    return img

# ---------------------------------------------------------
#  Main
# ---------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Visualize Placement Map")
    parser.add_argument("--fabric", default="fabric_cells.json", help="Path to fabric JSON")
    parser.add_argument("--map", default="z80islam.map", help="Path to placement .map file")
    parser.add_argument("--out", default="fawzyz80.png", help="Output PNG path")
    parser.add_argument("--width", type=int, default=2000, help="Target image width in pixels")
    
    # Fallbacks if site dims missing in JSON
    parser.add_argument("--slot-w", type=float, default=0.46)
    parser.add_argument("--slot-h", type=float, default=2.72)
    
    args = parser.parse_args()

    # 1. Load Data
    fab = load_json(args.fabric)
    placement_map = parse_map_file(args.map) # Returns None if file missing

    if not fab:
        return

    # 2. Process Geometry
    slots = collect_slots(fab, placement_map, args.slot_w, args.slot_h)
    die_um, core_um = infer_die_core(fab, slots)
    pins = parse_pins(fab, die_um)

    print(f"[INFO] Visualizing {len(slots)} cells and {len(pins)} pins.")

    # 3. Scaling
    # Calculate pixels per micron
    scale = args.width / max(1.0, die_um["width_um"])
    
    # FIX: Explicitly map keys to avoid "KeyError: width" vs "width_um"
    die_px = {
        "width": die_um["width_um"] * scale,
        "height": die_um["height_um"] * scale
    }
    
    core_px = {
        "x": core_um["x_um"] * scale,
        "y": core_um["y_um"] * scale,
        "width": core_um["width_um"] * scale,
        "height": core_um["height_um"] * scale
    }
    
    slots_px = []
    for s in slots:
        slots_px.append({
            "type": s["type"],
            "x": s["x"] * scale,
            "y": s["y"] * scale,
            "w": s["w"] * scale,
            "h": s["h"] * scale
        })
        
    pins_px = []
    for p in pins:
        pins_px.append({
            "name": p["name"],
            "side": p["side"],
            "direction": p["direction"],
            "x": p["x"] * scale,
            "y": p["y"] * scale,
            "w": p["w"] * scale,
            "h": p["h"] * scale
        })

    # 4. Colors
    unique_types = [s["type"] for s in slots_px]
    cmap = slot_color_map(unique_types)

    # 5. Render
    render_png(args.out, die_px, core_px, slots_px, pins_px, scale, cmap, 
               title=f"Placement: {args.map}")

if __name__ == "__main__":
    main()