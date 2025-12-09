# visualize.py
import argparse, json, os
from collections import Counter
from typing import Any, Dict, List, Tuple
from PIL import Image, ImageDraw, ImageFont



#  IO 
def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def ensure_dir_for(path: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)

#  Colors 
PIN_COLORS = {"INPUT": (31,119,180), "OUTPUT": (255,127,14), "INOUT": (44,160,44)}  # rgb
SLOT_PALETTE = [
    (31,119,180), (255,127,14), (44,160,44), (214,39,40), (148,103,189),
    (140,86,75), (227,119,194), (127,127,127), (188,189,34), (23,190,207),
    (57,59,121), (99,121,57), (140,109,49), (132,60,57), (123,65,115)
]

def slot_color_map(types: List[str]) -> Dict[str, Tuple[int,int,int]]:
    cmap: Dict[str, Tuple[int,int,int]] = {}
    for i, t in enumerate(sorted(set(types))):
        cmap[t] = SLOT_PALETTE[i % len(SLOT_PALETTE)]
    return cmap

def with_alpha(rgb: Tuple[int,int,int], alpha: float) -> Tuple[int,int,int,int]:
    a = max(0, min(255, int(round(alpha * 255))))
    return (rgb[0], rgb[1], rgb[2], a)

#  Site dimensions 
def get_site_dims_um(fab: Dict[str, Any], default_w: float, default_h: float) -> Tuple[float, float]:
    fi = fab.get("fabric_info", {}) if isinstance(fab, dict) else {}
    sdim = fi.get("site_dimensions_um", {}) if isinstance(fi, dict) else {}
    sw = sdim.get("width", None)
    sh = sdim.get("height", None)
    site_w_um = float(sw) if sw is not None else float(default_w)
    site_h_um = float(sh) if sh is not None else float(default_h)
    return site_w_um, site_h_um

#  Fabric parsing
def collect_slots(fab: Dict[str, Any], default_w: float, default_h: float) -> List[Dict[str, Any]]:
    site_w_um, site_h_um = get_site_dims_um(fab, default_w, default_h)
    slots: List[Dict[str, Any]] = []

    for t in fab.get("tiles", []):
        for g in t.get("gates", []):
            w_sites = g.get("width_sites", None)
            if w_sites is not None:
                w_um = float(w_sites) * site_w_um
            else:
                w_um = float(g.get("w", default_w))

            # prefer single-row height = site_h_um
            h_um = float(site_h_um) if site_h_um is not None else float(g.get("h", default_h))

            x_um = float(g.get("x", g.get("x_um", 0.0)))
            y_um = float(g.get("y", g.get("y_um", 0.0)))

            slots.append({
                "name": g.get("name", ""),
                "type": g.get("type","UNK"),
                "x": x_um, "y": y_um, "w": w_um, "h": h_um,
                "width_sites": w_sites,
                "physical_cell_type": g.get("physical_cell_type", None),
                "orient": g.get("orient", None),
            })

    if not slots:
        raise ValueError("No gates found (tiles[*].gates is empty).")
    return slots

def infer_die_core_from_slots(slots: List[Dict[str, Any]], margin_um: float = 5.0):
    xs = [s["x"] for s in slots]; ys = [s["y"] for s in slots]
    xmin, ymin = min(xs), min(ys)
    xmax = max(s["x"] + s["w"] for s in slots)
    ymax = max(s["y"] + s["h"] for s in slots)

    W = (xmax - xmin) + 2 * margin_um
    H = (ymax - ymin) + 2 * margin_um

    dx, dy = margin_um - xmin, margin_um - ymin
    for s in slots:
        s["x"] += dx; s["y"] += dy

    die  = {"width_um": W, "height_um": H, "core_margin_um": margin_um, "corner_keepout_um": 0.0}
    core = {"x_um": margin_um, "y_um": margin_um, "width_um": W - 2*margin_um, "height_um": H - 2*margin_um}
    pre  = {"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax}
    return die, core, pre

def normalize_die_core(fab: Dict[str, Any], slots: List[Dict[str, Any]]):
    die_in  = fab.get("die")  or {}
    core_in = fab.get("core") or {}

    dw = die_in.get("width_um", die_in.get("width"))
    dh = die_in.get("height_um", die_in.get("height"))
    margin = float(die_in.get("core_margin_um", die_in.get("core_margin", 0.0)))
    ck = float(die_in.get("corner_keepout_um", die_in.get("corner_keepout", 0.0)))

    cw = core_in.get("width_um", core_in.get("width"))
    ch = core_in.get("height_um", core_in.get("height"))
    cx = core_in.get("x_um", core_in.get("x")); cy = core_in.get("y_um", core_in.get("y"))

    die = None; core = None; origin = "inferred"
    if dw is not None and dh is not None:
        die = {"width_um": float(dw), "height_um": float(dh), "core_margin_um": margin, "corner_keepout_um": ck}
        origin = "file(die)"
    if cw is not None and ch is not None:
        if cx is None or cy is None:
            if die is not None:
                cx = margin if margin else (die["width_um"]  - float(cw)) / 2.0
                cy = margin if margin else (die["height_um"] - float(ch)) / 2.0
            else:
                cx, cy = 0.0, 0.0
        core = {"x_um": float(cx), "y_um": float(cy), "width_um": float(cw), "height_um": float(ch)}
        origin += "+file(core)"

    if die is None or core is None:
        die, core, pre = infer_die_core_from_slots(slots, margin_um=margin or 5.0)
        origin = f"inferred(margin={margin or 5.0})"
    else:
        xs = [s["x"] for s in slots]; ys = [s["y"] for s in slots]
        pre = {"xmin": min(xs), "ymin": min(ys), "xmax": max(s["x"]+s["w"] for s in slots), "ymax": max(s["y"]+s["h"] for s in slots)}
    return die, core, pre, origin


def parse_pins(fab: Dict[str, Any], die_um: Dict[str, Any]) -> List[Dict[str, Any]]:
    pins: List[Dict[str, Any]] = []
    die_w = die_um["width_um"]
    die_h = die_um["height_um"]

    print(f"[DEBUG parse_pins] die_w={die_w:.2f}, die_h={die_h:.2f}")  # ADD THIS

    for p in fab.get("pins", []):
        side = p.get("side", "").lower()
        x_um = float(p.get("x_um", p.get("x", 0.0)))
        y_um = float(p.get("y_um", p.get("y", 0.0)))

        print(f"[DEBUG] Pin {p.get('name', '')} side={side} x_um={x_um} y_um={y_um}")  # ADD THIS

        # Adjust position based on side
        if side == "west":
            final_x = 0.0
            final_y = y_um
        elif side == "east":
            final_x = die_w
            final_y = y_um
        elif side == "north":
            final_x = x_um
            final_y = die_h
        elif side == "south":
            final_x = x_um
            final_y = 0.0
        else:
            final_x = x_um
            final_y = y_um

        print(f"[DEBUG]   -> final_x={final_x:.2f}, final_y={final_y:.2f}")  # ADD THIS

        pins.append({
            "pin_id": p.get("name", ""),
            "side": side,
            "x": final_x,
            "y": final_y,
            "w": float(p.get("w", 2.0)),
            "h": float(p.get("h", 2.0)),
            "direction": p.get("direction", ""),
        })
    return pins

def compute_tile_boxes(fab: Dict[str, Any]):
    boxes = {}
    for t in fab.get("tiles", []):
        xs, ys, xes, yes = [], [], [], []
        for g in t.get("gates", []):
            x = float(g.get("x", g.get("x_um", 0.0)))
            y = float(g.get("y", g.get("y_um", 0.0)))
            fi_w, fi_h = get_site_dims_um(fab, 0.46, 2.72)
            if g.get("width_sites", None) is not None:
                w_um = float(g["width_sites"]) * fi_w
            else:
                w_um = float(g.get("w", fi_w))
            h_um = float(fi_h)
            xs.append(x); ys.append(y)
            xes.append(x + w_um); yes.append(y + h_um)
        if xs and ys:
            boxes[t.get("name","")] = (min(xs), min(ys), max(xes), max(yes))
    return boxes

#  Scaling 
def auto_scale(die_um: Dict[str,float], args) -> float:
    if args.scale is not None:
        return float(args.scale)
    W_um = float(die_um["width_um"]); H_um = float(die_um["height_um"])
    tw = args.target_width or 6000
    th = args.target_height or int(tw * (H_um / max(1e-9, W_um)))
    sx = tw / W_um
    sy = th / H_um
    return max(1.0, min(sx, sy))

def scale_all(die_um, core_um, slots, pins, tiles, scale, fat_x_px, fat_y_px):
    die_px = {
        "width": die_um["width_um"]*scale, "height": die_um["height_um"]*scale,
        "core_margin_px": float(die_um.get("core_margin_um",0.0))*scale,
        "corner_keepout_px": float(die_um.get("corner_keepout_um",0.0))*scale,
    }
    core_px = {
        "x": core_um["x_um"]*scale, "y": core_um["y_um"]*scale,
        "width": core_um["width_um"]*scale, "height": core_um["height_um"]*scale,
    }
    # carry name/type/meta for debug
    slots_px = [{
        "name": s.get("name",""), "type": s["type"],
        "x": s["x"]*scale, "y": s["y"]*scale,
        "w": max(0.0, s["w"]*scale + fat_x_px),
        "h": max(0.0, s["h"]*scale + fat_y_px),
        "__orig": s
    } for s in slots]
    pins_px = [{
        "pin_id": p["pin_id"],
        "side": p["side"],
        "x": p["x"] * scale,
        "y": p["y"] * scale,
        "w": p["w"] * scale,
        "h": p["h"] * scale,
        "direction": p["direction"]
    } for p in pins]
    tiles_px = {k: (x0*scale, y0*scale, x1*scale, y1*scale) for k,(x0,y0,x1,y1) in tiles.items()}
    return die_px, core_px, slots_px, pins_px, tiles_px

#  Draw helpers 
def y_map(y: float, h: float, H: float, y_origin: str) -> float:
    return H - (y + h) if y_origin == "bottom" else y

def draw_rect(draw: ImageDraw.ImageDraw, x,y,w,h, fill=None, outline=None, width=1):
    x1, y1 = x+w, y+h
    if fill is not None:
        draw.rectangle([x, y, x1, y1], fill=fill, outline=outline, width=width)
    else:
        draw.rectangle([x, y, x1, y1], outline=outline, width=width)

def try_font(size_px: int) -> ImageFont.FreeTypeFont:
    for name in ["DejaVuSans.ttf", "Arial.ttf"]:
        try:
            return ImageFont.truetype(name, size_px)
        except Exception:
            pass
    return ImageFont.load_default()

def to_canvas_xy(x: float, y: float, h: float, H_fabric: float, ox: int, oy: int, y_origin: str) -> Tuple[float,float]:
    yy = y_map(y, h, H_fabric, y_origin)
    return ox + x, oy + yy

def draw_panel(draw, x, y, w, h, title, font, bg=(250,250,250,255), border=(60,60,60,255)):
    draw.rectangle([x, y, x+w, y+h], fill=bg, outline=border, width=1)
    th = 18
    draw.rectangle([x, y, x+w, y+th], fill=(235,235,235,255), outline=border, width=1)
    draw.text((x+8, y+2), title, font=font, fill=(30,30,30,255))

def draw_dim(draw, p0, p1, offset, text, font, horizontal=True, color=(0,0,0,230)):
    (x0, y0), (x1, y1) = p0, p1
    if horizontal:
        y = y0 + offset
        draw.line([(x0, y), (x1, y)], fill=color, width=1)
        for s in (-1, 1):
            draw.line([(x0, y), (x0+8, y-6*s)], fill=color, width=1)
            draw.line([(x1, y), (x1-8, y-6*s)], fill=color, width=1)
        tw, th = _text_wh(draw, text, font)
        draw.rectangle([ (x0+x1)//2 - tw//2 - 4, y- th - 6,
                         (x0+x1)//2 + tw//2 + 4, y - 2],
                       fill=(255,255,255,220))
        draw.text(((x0+x1)//2 - tw//2, y - th - 6), text, font=font, fill=(30,30,30,255))
    else:
        x = x0 + offset
        draw.line([(x, y0), (x, y1)], fill=color, width=1)
        for s in (-1, 1):
            draw.line([(x, y0), (x-6*s, y0+8)], fill=color, width=1)
            draw.line([(x, y1), (x-6*s, y1-8)], fill=color, width=1)
        tw, th = _text_wh(draw, text, font)
        draw.rectangle([ x - tw//2 - 4, (y0+y1)//2 - th//2 - 4,
                         x + tw//2 + 4, (y0+y1)//2 + th//2 + 4],
                       fill=(255,255,255,220))
        draw.text((x - tw//2, (y0+y1)//2 - th//2), text, font=font, fill=(30,30,30,255))

def draw_ruler(draw, x0, y0, length, px_per_um, every_um=50, label_every_um=200, horizontal=True, color=(0,0,0,180), font=None):
    if px_per_um <= 0: return
    step_px = every_um * px_per_um
    label_step_px = label_every_um * px_per_um
    if horizontal:
        draw.line([(x0, y0), (x0+length, y0)], fill=color, width=1)
        t = 0.0
        while t <= length + 1:
            xt = x0 + t
            tick = 8 if abs((t % label_step_px)) < 1e-6 else 4
            draw.line([(xt, y0), (xt, y0 - tick)], fill=color, width=1)
            if tick == 8 and font:
                label_um = int(round(t / px_per_um))
                draw.text((xt+2, y0 - 16), f"{label_um}", font=font, fill=color)
            t += step_px
    else:
        draw.line([(x0, y0), (x0, y0+length)], fill=color, width=1)
        t = 0.0
        while t <= length + 1:
            yt = y0 + t
            tick = 8 if abs((t % label_step_px)) < 1e-6 else 4
            draw.line([(x0, yt), (x0 - tick, yt)], fill=color, width=1)
            if tick == 8 and font:
                label_um = int(round(t / px_per_um))
                draw.text((x0 - 28, yt - 6), f"{label_um}", font=font, fill=color)
            t += step_px

def fmt_dim(px, px_per_um):
    um = px / max(1e-9, px_per_um)
    return f"{int(round(px))} px  ({um:.1f} µm)"

def _text_wh(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> Tuple[int,int]:
    l,t,r,b = draw.textbbox((0,0), text, font=font)
    return (r-l, b-t)

#  Render 
def render_png(out_path: str,
               die_px: Dict[str,float],
               core_px: Dict[str,float],
               slots_px: List[Dict[str,Any]],
               pins_px: List[Dict[str,Any]],
               tiles_px: Dict[str,Tuple[float,float,float,float]],
               slot_alpha: float,
               y_origin: str,
               slot_colors: Dict[str, Tuple[int,int,int]],
               show_tile_grid: bool,
               show_keepouts: bool,
               scale_px_per_um: float,
               title: str,
               tile_grid_stride: int,
               ui_scale: float = 1.0,
               margin_left: int = 260,
               margin_right: int = 260,
               margin_top: int = 160,
               margin_bottom: int = 180,
               show_core_dims: bool = True,
               show_die_dims: bool = True,
               show_rulers: bool = True,
               pin_label_mode: str = "outside",
               pin_label_font_px: int = 12,
               tight: bool = False,
               border_width: int = 2):

    s = max(0.5, float(ui_scale))
    if tight:
        margin_left = margin_right = margin_top = margin_bottom = 0
        show_core_dims = show_die_dims = show_rulers = False
        pin_label_mode = "inline"  # outside labels would need a right/left margin
    else:
        margin_left   = int(round(margin_left   * s))
        margin_right  = int(round(margin_right  * s))
        margin_top    = int(round(margin_top    * s))
        margin_bottom = int(round(margin_bottom * s))

    # --- fonts (sizes) ---
    font_base_px  = max(10, int(round(12 * s)))
    font_small_px = max(9,  int(round(10 * s)))
    pin_font_px   = max(8,  int(round(pin_label_font_px * s)))

    # --- font objects ---
    font       = try_font(font_base_px)
    font_small = try_font(font_small_px)
    pin_font   = try_font(pin_font_px)

    W_f = int(round(die_px["width"]))
    H_f = int(round(die_px["height"]))

    CW = W_f + margin_left + margin_right
    CH = H_f + margin_top + margin_bottom
    ox, oy = margin_left, margin_top

    img = Image.new("RGBA", (CW, CH), (255,255,255,255))
    draw = ImageDraw.Draw(img, "RGBA")

    overlay = Image.new("RGBA", (CW, CH), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay, "RGBA")
    if not tight:
        if border_width > 0:
            # crisp outer border
            bw = int(border_width)
            draw.rectangle([bw//2, bw//2, CW-1-bw//2, CH-1-bw//2], outline=(80,80,80,255), width=bw)
        draw.text((ox, int(22*s)), title, font=font, fill=(34,34,34,255))
        # North arrow
        draw.line([(CW - int(30*s), int(44*s)), (CW - int(30*s), int(68*s))], fill=(0,0,0,255), width=2)
        draw.text((CW - int(44*s), int(26*s)), "N", font=font, fill=(0,0,0,255))

    # Die outline
    draw_rect(draw, ox, oy, W_f, H_f, fill=None, outline=(0,0,0,255), width=2)

    # Keep-outs
    ck = die_px.get("corner_keepout_px", 0.0)
    if show_keepouts and ck > 0:
        a = with_alpha((221,102,102), 0.40)
        corners = [(0,0),(W_f-ck,0),(0,H_f-ck),(W_f-ck,H_f-ck)]
        for (x0,y0) in corners:
            draw_rect(draw, ox + x0, oy + y0, ck, ck, fill=a, outline=(214,102,102,255), width=1)

    # Core outline
    cx, cy, cw, ch = int(round(core_px["x"])), int(round(core_px["y"])), int(round(core_px["width"])), int(round(core_px["height"]))
    core_draw_y = oy + (H_f - (cy + ch) if y_origin=="bottom" else cy)
    draw_rect(draw, ox + cx, core_draw_y, cw, ch, fill=None, outline=(0,119,170,255), width=2)

    # Rulers only if not tight
    if show_rulers and not tight:
        draw_ruler(draw, ox, oy - int(20*s), W_f, scale_px_per_um, every_um=50, label_every_um=200, horizontal=True, color=(0,0,0,160), font=font_small)
        draw_ruler(draw, ox - int(20*s), oy, H_f, scale_px_per_um, every_um=50, label_every_um=200, horizontal=False, color=(0,0,0,160), font=font_small)
        draw.text((ox - int(45 * s), oy - int(36 * s)), "µm", font=font_small, fill=(60,60,60,200))

    # Sparse tile grid (faint)
    if show_tile_grid and tile_grid_stride > 0:
        i = 0
        for _, (x0, y0, x1, y1) in tiles_px.items():
            if (i % tile_grid_stride) == 0:
                w, h = (x1 - x0), (y1 - y0)
                tx, ty = to_canvas_xy(x0, y0, h, H_f, ox, oy, y_origin)
                draw_rect(draw, tx, ty, w, h, fill=None, outline=(204,204,204,180), width=1)
            i += 1

    # Slots (semi-transparent)
    type_rgba: Dict[str, Tuple[int,int,int,int]] = {
        t: with_alpha(slot_colors.get(t, (170,170,170)), 0.5) for t in slot_colors
    }
    edge = (34,34,34,160)
    for srec in slots_px:
        tx, ty = to_canvas_xy(srec["x"], srec["y"], srec["h"], H_f, ox, oy, y_origin)
        draw_rect(odraw, tx, ty, srec["w"], srec["h"],
                  fill=type_rgba.get(srec["type"], with_alpha((170,170,170), 0.5)),
                  outline=edge, width=1)
        srec["__canvas_xy"] = (tx, ty)

    for p in pins_px:
        rgb = PIN_COLORS.get(p.get("direction","").upper(), (34,34,34))
        fill = with_alpha(rgb, 0.5)
        tx, ty = to_canvas_xy(p["x"], p["y"], p["h"], H_f, ox, oy, y_origin)
        draw_rect(odraw, tx, ty, p["w"], p["h"], fill=fill, outline=(17,17,17,210), width=1)
        p["__canvas_xy"] = (tx, ty)
        p["__center"] = (tx + p["w"]/2.0, ty + p["h"]/2.0)

    # Legend & labels only if not tight
    if not tight:
        # Legend
        panel_w, panel_h = int(220*s), int(260*s)
        panel_x, panel_y = int(20*s), int(20*s)
        draw_panel(draw, panel_x, panel_y, panel_w, panel_h, "Legend", font)
        ly = panel_y + int(26*s)
        draw.text((panel_x + int(10*s), ly), "Slot types:", font=font, fill=(34,34,34,255)); ly += int(16*s)
        hist = Counter(s["type"] for s in slots_px)
        shown = 0
        for t, rgb in sorted(slot_colors.items(), key=lambda kv: kv[0]):
            if shown >= 28: break
            draw_rect(odraw, panel_x + int(12*s), ly, int(16*s), int(12*s), fill=with_alpha(rgb, 0.5), outline=(51,51,51,255), width=1)
            draw.text((panel_x + int(34*s), ly - int(2*s)), f"{t}  (×{hist.get(t,0)})", font=font, fill=(34,34,34,255))
            ly += int(16*s); shown += 1
        ly += int(8*s)
        draw.text((panel_x + int(10*s), ly), "Pins:", font=font, fill=(34,34,34,255)); ly += int(16*s)
        for label, rgb in PIN_COLORS.items():
            draw_rect(draw, panel_x + int(12*s), ly, int(16*s), int(12*s), fill=with_alpha(rgb, 0.5), outline=(51,51,51,255), width=1)
            draw.text((panel_x + int(34*s), ly - int(2*s)), label, font=font, fill=(34,34,34,255))
            ly += int(16*s)

        # Dimensions
        if show_die_dims:
            draw_dim(draw, (ox, oy), (ox + W_f, oy), offset=-int(40*s),
                     text=f"Die width: {fmt_dim(W_f, scale_px_per_um)}", font=font, horizontal=True)
            draw_dim(draw, (ox, oy), (ox, oy + H_f), offset=-int(40*s),
                     text=f"Die height: {fmt_dim(H_f, scale_px_per_um)}", font=font, horizontal=False)

        if show_core_dims:
            draw_dim(draw, (ox + cx, core_draw_y + ch), (ox + cx + cw, core_draw_y + ch), offset=int(30*s),
                     text=f"Core width: {fmt_dim(cw, scale_px_per_um)}", font=font, horizontal=True)
            draw_dim(draw, (ox + cx + cw, core_draw_y), (ox + cx + cw, core_draw_y + ch), offset=int(30*s),
                     text=f"Core height: {fmt_dim(ch, scale_px_per_um)}", font=font, horizontal=False)

        # Origin & scale bar
        draw.ellipse([ox - 3, oy - 3, ox + 3, oy + 3], fill=(0, 0, 0, 200))
        draw.text((ox - int(12 * s), oy - int(18 * s)), "(0,0)", font=font_small, fill=(40, 40, 40, 255))
        draw.text((ox + W_f + int(6 * s), oy + H_f + int(2 * s)), "x (px/µm)", font=font_small, fill=(60, 60, 60, 230))
        draw.text((ox - int(50 * s), oy - int(28 * s)), "y (px/µm)", font=font_small, fill=(60, 60, 60, 230))

        bar_um = 100.0
        bar_px = int(round(bar_um * scale_px_per_um))
        bx, by = ox, oy + H_f + int(48*s)
        draw_rect(draw, bx, by, bar_px, int(6*s), fill=(0,0,0,255), outline=(0,0,0,255))
        draw.text((bx, by - int(18 * s)), f"{int(bar_um)} µm  ({bar_px} px)", font=font_small, fill=(34, 34, 34, 255))

        # Pin labels (crowding-safe)
        if pin_label_mode.lower() == "outside-smart":
            _labels_outside_smart(draw, pins_px, ox, oy, W_f, H_f, s, pin_font)
        elif pin_label_mode.lower() == "outside":
            _labels_outside_right(draw, pins_px, ox, oy, W_f, H_f, s, pin_font, font_small)
        elif pin_label_mode.lower() == "inline":
            _labels_inline(draw, pins_px, s, pin_font, avoid_overlaps=False)
        elif pin_label_mode.lower() == "smart":
            _labels_inline(draw, pins_px, s, pin_font, avoid_overlaps=True)
    else:
        # tight: inline labels only (small), or none
        if pin_label_mode.lower() != "none":
            _labels_inline(draw, pins_px, 1.0, try_font(10), avoid_overlaps=True)

    ensure_dir_for(out_path)
    img.alpha_composite(overlay)
    img.save(out_path, format="PNG")
    print(f"[OK] Wrote PNG: {out_path}")

#  Pin label strategies 
def _labels_inline(draw: ImageDraw.ImageDraw,
                   pins_px: List[Dict[str,Any]],
                   ui_scale: float,
                   font: ImageFont.ImageFont,
                   avoid_overlaps: bool = True):
    pad = int(3 * ui_scale)
    min_gap = int(12 * ui_scale)
    placed_boxes: List[Tuple[int,int,int,int]] = []
    for p in pins_px:
        tx, ty = p["__canvas_xy"]
        label = str(p.get("pin_id",""))
        tw, th = _text_wh(draw, label, font)
        lx = int(tx + p["w"] + pad)
        ly = int(ty - pad)
        box = (lx, ly, lx + tw, ly + th)
        place = True
        if avoid_overlaps:
            for (x0,y0,x1,y1) in placed_boxes:
                if not (box[2] < x0 - min_gap or box[0] > x1 + min_gap or box[3] < y0 - min_gap or box[1] > y1 + min_gap):
                    place = False
                    break
        if place:
            draw.text((lx, ly), label, font=font, fill=(34,34,34,255))
            placed_boxes.append(box)

def _labels_outside_right(draw: ImageDraw.ImageDraw,
                          pins_px: List[Dict[str,Any]],
                          ox: int, oy: int, W_f: int, H_f: int,
                          ui_scale: float,
                          font: ImageFont.ImageFont,
                          font_small: ImageFont.ImageFont):
    right_x = ox + W_f + int(24 * ui_scale)
    top_y   = oy + int(8 * ui_scale)
    line_gap = max(14, int(16 * ui_scale))
    pins_sorted = sorted(pins_px, key=lambda p: p["__center"][1])
    ycur = top_y
    for p in pins_sorted:
        label = str(p.get("pin_id", ""))
        tw, th = _text_wh(draw, label, font)
        lx, ly = right_x + int(8 * ui_scale), ycur
        draw.text((lx, ly), label, font=font, fill=(34,34,34,255))
        cx, cy = p["__center"]
        mid_x = right_x
        draw.line([(cx, cy), (mid_x, cy)], fill=(60,60,60,220), width=1)
        draw.line([(mid_x, cy), (lx - int(6*ui_scale), ly + th//2)], fill=(60,60,60,220), width=1)
        ycur += line_gap

def _labels_outside_smart(draw: ImageDraw.ImageDraw,
                          pins_px: List[Dict[str,Any]],
                          ox: int, oy: int, W_f: int, H_f: int,
                          ui_scale: float,
                          font: ImageFont.ImageFont):

    if not pins_px:
        return

    # Split by die center
    cx_mid = ox + W_f / 2.0
    left_pins, right_pins = [], []
    for p in pins_px:
        cx, cy = p["__center"]
        (left_pins if cx <= cx_mid else right_pins).append(p)

    left_pins.sort(key=lambda pp: pp["__center"][1])
    right_pins.sort(key=lambda pp: pp["__center"][1])

    gap_side = int(24 * ui_scale)          # gap between die edge and leader junction
    text_gap = int(8 * ui_scale)           # gap from leader to text
    line_gap = max(14, int(16 * ui_scale)) # min vertical gap between labels

    left_x  = ox - gap_side
    right_x = ox + W_f + gap_side

    def pack_side(pins_ordered, side: str):
        placed_y = -10**9
        for p in pins_ordered:
            label = str(p.get("pin_id", ""))
            tw, th = _text_wh(draw, label, font)
            cx, cy = p["__center"]

            # target y near the pin, then enforce spacing
            ty = max(cy - th//2, placed_y + line_gap)
            ty = int(max(oy + 2, min(oy + H_f - th - 2, ty)))  # clamp
            placed_y = ty

            if side == "right":
                lx = right_x + text_gap
                draw.line([(cx, cy), (right_x, cy)], fill=(60,60,60,220), width=1)
                draw.line([(right_x, cy), (lx - text_gap//2, ty + th//2)], fill=(60,60,60,220), width=1)
                draw.text((lx, ty), label, font=font, fill=(34,34,34,255))
            else:
                lx = left_x - text_gap - tw
                draw.line([(cx, cy), (left_x, cy)], fill=(60,60,60,220), width=1)
                draw.line([(left_x, cy), (lx + tw + text_gap//2, ty + th//2)], fill=(60,60,60,220), width=1)
                draw.text((lx, ty), label, font=font, fill=(34,34,34,255))

    pack_side(left_pins,  "left")
    pack_side(right_pins, "right")

#  Debug 
def dump_hist(slots: List[Dict[str, Any]]) -> Counter:
    return Counter(s["type"] for s in slots)

#  CLI 
def main():
    ap = argparse.ArgumentParser(description="Fast PNG fabric visualizer. Honors width_sites+site_dimensions_um. Adds border + outside-smart labels.")
    ap.add_argument("--fabric-db", required=True, help="Path to fabric_db.json")
    ap.add_argument("--out", required=True, help="Output PNG")

    # Fallbacks if DB lacks site dims / width_sites
    ap.add_argument("--slot-w", type=float, default=0.46, help="Fallback single-site width (µm)")
    ap.add_argument("--slot-h", type=float, default=2.72, help="Fallback row height (µm)")

    ap.add_argument("--alpha",  type=float, default=0.6, help="Slot fill opacity (0..1)")
    ap.add_argument("--y-origin", choices=["bottom","top"], default="bottom", help="Coordinate origin mode.")
    ap.add_argument("--scale", type=float, default=None, help="Pixels per µm. If omitted, auto-fit.")
    ap.add_argument("--target-width", type=int, default=6000, help="Auto-fit width if --scale not set.")
    ap.add_argument("--target-height", type=int, default=None, help="Auto-fit height (optional).")
    ap.add_argument("--slot-fat-x", type=float, default=0.0, help="Add pixels to each slot width (post-scale).")
    ap.add_argument("--slot-fat-y", type=float, default=0.0, help="Add pixels to each slot height (post-scale).")
    ap.add_argument("--tile-grid-stride", type=int, default=50, help="Draw every Nth tile box (0 to disable).")
    ap.add_argument("--no-keepouts", action="store_true", help="Disable corner keepout overlays.")
    ap.add_argument("--title", default="Fabric Overview (Phase-1)", help="Figure title.")
    ap.add_argument("--debug", action="store_true", help="Verbose summary debug.")
    ap.add_argument("--debug-samples", type=int, default=8, help="How many slot samples to show.")

    # UI controls
    ap.add_argument("--ui-scale", type=float, default=1.4, help="Scale ONLY UI (fonts/margins/panels).")
    ap.add_argument("--pin-label-mode",
                    choices=["inline","outside","outside-smart","none","smart"],
                    default="outside-smart",
                    help="Pin labels: inline | outside (right only) | outside-smart (both sides, non-overlap) | none | smart (inline non-overlap)")
    ap.add_argument("--pin-label-font", type=int, default=12, help="Base pin label font size (px).")
    ap.add_argument("--no-core-dims", action="store_true", help="Hide core dimension arrows.")
    ap.add_argument("--no-die-dims", action="store_true", help="Hide die dimension arrows.")
    ap.add_argument("--no-rulers",    action="store_true", help="Hide µm rulers.")
    ap.add_argument("--border-width", type=int, default=2, help="Outer border width in pixels (0 = no border).")

    # Canvas modes
    ap.add_argument("--tight", action="store_true", help="Render die-only (no margins/title/legend/rulers).")

    # Debug cells
    ap.add_argument("--debug-cells", action="store_true", help="Print a line for every gate with µm and px sizes/positions.")

    args = ap.parse_args()

    fab = load_json(args.fabric_db)
    slots = collect_slots(fab, args.slot_w, args.slot_h)
    die_um, core_um, pre_bounds, origin = normalize_die_core(fab, slots)
    pins = parse_pins(fab, die_um)
    tiles_um = compute_tile_boxes(fab)

    # scale
    scale = auto_scale(die_um, args)
    die_px, core_px, slots_px, pins_px, tiles_px = scale_all(
        die_um, core_um, slots, pins, tiles_um, scale, args.slot_fat_x, args.slot_fat_y
    )

    if args.debug:
        site_w_um, site_h_um = get_site_dims_um(fab, args.slot_w, args.slot_h)
        tiles_count = len(fab.get("tiles", []))
        gates_total = len(slots)
        hist = dump_hist(slots)
        print("[DEBUG] Summary:")
        print(f"  tiles: {tiles_count}")
        print(f"  gates: {gates_total}")
        print(f"  pins : {len(pins)}")
        print(f"  site dims (µm): width={site_w_um:.3f} height={site_h_um:.3f}")
        print(f"  die/core source: {origin}")
        print(f"  pre-shift slot bounds (µm): xmin={pre_bounds['xmin']:.3f}, ymin={pre_bounds['ymin']:.3f}, xmax={pre_bounds['xmax']:.3f}, ymax={pre_bounds['ymax']:.3f}")
        print(f"  die used (µm): width={die_um['width_um']:.3f} height={die_um['height_um']:.3f}")
        print(f"  core used (µm): x={core_um['x_um']:.3f} y={core_um['y_um']:.3f} width={core_um['width_um']:.3f} height={core_um['height_um']:.3f}")
        print("[DEBUG] Slot type histogram (type: count):")
        for t, c in sorted(hist.items()):
            print(f"  {t:>10s}: {c}")
        print(f"[DEBUG] y-origin: {args.y_origin}, scale: {scale:.4f} px/µm (auto if None), fit width: {args.target_width}px")

    #per-cell prints
    if args.debug_cells:
        print("[DEBUG-CELLS] name,type,phys,width_sites,w_um,h_um,x_um,y_um -> x_px,y_px,w_px,h_px")
        for sp in slots_px:
            s = sp["__orig"]
            name = s.get("name","")
            t = s.get("type","")
            phys = s.get("physical_cell_type","")
            wsites = s.get("width_sites", None)
            w_um = s["w"]; h_um = s["h"]; x_um = s["x"]; y_um = s["y"]
            print(f"  {name},{t},{phys},{wsites},{w_um:.3f},{h_um:.3f},{x_um:.3f},{y_um:.3f} -> "
                  f"{sp['x']:.1f},{sp['y']:.1f},{sp['w']:.1f},{sp['h']:.1f}")

    # colors
    types = [s["type"] for s in slots_px]
    cmap = slot_color_map(types)

    # render
    ensure_dir_for(args.out)
    render_png(
        out_path=args.out,
        die_px=die_px,
        core_px=core_px,
        slots_px=slots_px,
        pins_px=pins_px,
        tiles_px=tiles_px,
        slot_alpha=args.alpha,
        y_origin=args.y_origin,
        slot_colors=cmap,
        show_tile_grid=(args.tile_grid_stride > 0),
        show_keepouts=(not args.no_keepouts),
        scale_px_per_um=scale,
        title=args.title,
        tile_grid_stride=args.tile_grid_stride,
        ui_scale=args.ui_scale,
        show_core_dims=(not args.no_core_dims),
        show_die_dims=(not args.no_die_dims),
        show_rulers=(not args.no_rulers),
        pin_label_mode=args.pin_label_mode,
        pin_label_font_px=args.pin_label_font,
        tight=args.tight,
        border_width=args.border_width,
    )

if __name__ == "__main__":
    main()