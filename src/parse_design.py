#!/usr/bin/env python3
# src/parse_design.py
#
# Convert Yosys <design>_mapped.json into a normalized logical_db.json
# Supports multiple input files in one run.
#
# Usage examples:
#   python3 src/parse_design.py --mapped-json data/z80_mapped.json
#   python3 src/parse_design.py --mapped-json data/6502_mapped.json data/aes_128_mapped.json
#   python3 src/parse_design.py --mapped-json data/*_mapped.json --design 6502 aes_128 arith z80

import argparse
import json
import os
import re
import sys
from typing import Dict, Any, List, Set, Optional


LogicalDB = Dict[str, Any]

# ----------------------------------------------------------------------
# In-memory IR template
# ----------------------------------------------------------------------
def _new_logical_db() -> LogicalDB:
    return {
        "version": "1.0",
        "design": None,
        "top": None,
        "library": None,
        "source": {},
        "ports": {},          # port_name -> {direction,bits[],width,attrs{}}
        "buses": {},          # base_name -> {direction,members:[port_names sorted]}
        "instances": {},      # inst_name -> {type,pins{pin:[bits]},attrs{},params{}}
        "type_counts": {},    # type -> count
        "stats": {},          # quick summary counts
        "nets": {},           # bit_id(str) -> {name, attrs, hide_name}
        "net_graph": {},      # bit_id(str) -> {drivers:[(inst,pin)], sinks:[(inst,pin)]}
        "indexes": {
            "inputs": [],     # [port_name,...]
            "outputs": [],    # [port_name,...]
            "by_type": {}     # type -> [inst_name,...]
        }
    }


# ----------------------------------------------------------------------
# Basic helpers
# ----------------------------------------------------------------------
def open_design(file_name: str) -> Dict[str, Any]:
    try:
        with open(file_name, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"File not found: {file_name}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {file_name}: {e}")


def infer_design_name(path: str) -> str:
    base = os.path.basename(path)
    name = re.sub(r"_mapped\.json$", "", base)
    return name or "unknown"


def pick_top_module(data: Dict[str, Any]) -> str:
    mods = data.get("modules", {})
    if not mods:
        raise KeyError("No 'modules' in mapped JSON.")

    # 1) Yosys top attribute
    for mname, m in mods.items():
        attrs = m.get("attributes", {})
        if str(attrs.get("top", "")).endswith("1"):
            return mname

    # 2) common fallbacks
    for candidate in ("sasic_top", "top", "top_module"):
        if candidate in mods:
            return candidate

    # 3) single module fallback
    if len(mods) == 1:
        return next(iter(mods.keys()))

    raise ValueError("Cannot determine top module (no explicit top and multiple modules present).")


# ----------------------------------------------------------------------
# Constants handling: '0','1','x','z' -> synthetic bit IDs
# ----------------------------------------------------------------------
def build_const_bit_map(data: dict, top: str) -> Dict[str, int]:
    def _collect_int_bits() -> Set[int]:
        ints: Set[int] = set()
        m = data["modules"][top]

        # ports
        for pinfo in m.get("ports", {}).values():
            for b in pinfo.get("bits", []):
                if isinstance(b, int):
                    ints.add(b)

        # cells
        for cell in m.get("cells", {}).values():
            for v in cell.get("connections", {}).values():
                if isinstance(v, list):
                    for b in v:
                        if isinstance(b, int):
                            ints.add(b)
                elif isinstance(v, int):
                    ints.add(v)
        return ints

    int_bits = _collect_int_bits()
    max_bit = max(int_bits) if int_bits else 0
    # Allocate 4 synthetic bit IDs right after the max real one
    return {
        "0": max_bit + 1,
        "1": max_bit + 2,
        "x": max_bit + 3,
        "z": max_bit + 4,
    }


def register_const_nets(db: LogicalDB, const_map: Dict[str, int]) -> None:
    labels = {"0": "CONST_0", "1": "CONST_1", "x": "CONST_X", "z": "CONST_Z"}
    for sym, bid in const_map.items():
        key = str(bid)
        if key not in db["nets"]:
            db["nets"][key] = {
                "name": labels[sym],
                "attrs": {"is_const": True, "symbol": sym},
                "hide_name": False
            }
        db["net_graph"].setdefault(key, {"drivers": [], "sinks": []})


def _register_const_driver(db: LogicalDB, bit_id: int, symbol: str) -> None:
    node = db["net_graph"].setdefault(str(bit_id), {"drivers": [], "sinks": []})
    entry = ("$const", symbol)  # pseudo-driver
    if entry not in node["drivers"]:
        node["drivers"].append(entry)


# ----------------------------------------------------------------------
# Ports / buses / IO indexes
# ----------------------------------------------------------------------
def parse_ports(db: LogicalDB, data: Dict[str, Any], top: str) -> None:
    db["ports"].clear()
    db["buses"].clear()
    db["indexes"]["inputs"].clear()
    db["indexes"]["outputs"].clear()

    try:
        ports = data["modules"][top]["ports"]
    except KeyError as e:
        raise KeyError(f"Missing key in JSON: {e}. Check module data.")

    for pname, pinfo in ports.items():
        direction = pinfo.get("direction", "unknown")
        bits_raw = pinfo.get("bits", [])
        # normalize to list[int] (ports should already be ints)
        bits = [int(b) for b in (bits_raw if isinstance(bits_raw, list) else [bits_raw])]
        db["ports"][pname] = {
            "direction": direction,
            "bits": bits,
            "width": len(bits),
            "attrs": {}
        }

        if direction == "input":
            db["indexes"]["inputs"].append(pname)
        elif direction == "output":
            db["indexes"]["outputs"].append(pname)

        # bus grouping: name_idx
        if "_" in pname:
            base, idx = pname.rsplit("_", 1)
            if idx.isdigit():
                bus = db["buses"].setdefault(base, {
                    "direction": direction,
                    "members": []
                })
                bus["members"].append(pname)

    for bus in db["buses"].values():
        bus["members"].sort(key=lambda n: int(n.rsplit("_", 1)[1]))

    db["indexes"]["inputs"].sort(key=lambda n: (n.split("_")[0], n))
    db["indexes"]["outputs"].sort(key=lambda n: (n.split("_")[0], n))


# ----------------------------------------------------------------------
# Instances + by_type index (with constants mapping)
# ----------------------------------------------------------------------
def _looks_sequential(cell_type: str) -> bool:
    t = cell_type.lower()
    return any(k in t for k in ("dff", "dfx", "dlat", "sdff", "flop", "ff_", "_ff"))


def _looks_buffer(cell_type: str) -> bool:
    t = cell_type.lower()
    return any(k in t for k in ("buf", "inv", "clkbuf", "clkbuf_"))


def parse_instances(db: LogicalDB, data: Dict[str, Any], top: str, const_map: Dict[str, int]) -> None:
    db["instances"].clear()
    db["indexes"]["by_type"].clear()

    try:
        cells = data["modules"][top]["cells"]
    except KeyError as e:
        raise KeyError(f"Missing key in JSON: {e}. Check module data.")

    def to_bit_id_list(val) -> List[int]:
        # list or scalar; elements can be int or '0','1','x','z'
        if isinstance(val, list):
            out: List[int] = []
            for el in val:
                if isinstance(el, int):
                    out.append(el)
                elif isinstance(el, str) and el in const_map:
                    out.append(const_map[el])
                else:
                    raise ValueError(f"Unsupported bit value in connections: {el!r}")
            return out
        else:
            if isinstance(val, int):
                return [val]
            if isinstance(val, str) and val in const_map:
                return [const_map[val]]
            raise ValueError(f"Unsupported bit value in connections: {val!r}")

    for inst_name, cell in cells.items():
        ctype = str(cell.get("type", "UNKNOWN_CELL"))
        conns = cell.get("connections", {}) or {}
        params = cell.get("parameters", {}) or {}
        attrs  = cell.get("attributes", {}) or {}

        pins = {pin: to_bit_id_list(bits) for pin, bits in conns.items()}

        inst_attrs = {
            "is_seq": _looks_sequential(ctype),
            "is_buffer": _looks_buffer(ctype)
        }
        if attrs:
            inst_attrs["raw"] = attrs

        db["instances"][inst_name] = {
            "type": ctype,
            "pins": pins,
            "attrs": inst_attrs,
            "params": params
        }

        db["indexes"]["by_type"].setdefault(ctype, []).append(inst_name)


# ----------------------------------------------------------------------
# Netnames (optional enrichment)
# ----------------------------------------------------------------------
def parse_netnames(db: LogicalDB, data: Dict[str, Any], top: str) -> None:
    db["nets"].clear()
    nets = data["modules"][top].get("netnames", {})
    for net_name, info in nets.items():
        bits_val = info.get("bits", [])
        bits = bits_val if isinstance(bits_val, list) else [bits_val]
        hide = bool(info.get("hide_name", 0))
        attrs = info.get("attributes", {}) or {}
        for b in bits:
            if isinstance(b, int):
                db["nets"][str(b)] = {
                    "name": (None if hide else net_name),
                    "attrs": attrs,
                    "hide_name": hide
                }


# ----------------------------------------------------------------------
# Net graph (drivers/sinks) + multi-driver count + constants drivers
# ----------------------------------------------------------------------
_OUTPUT_PIN_HINTS = {"X", "Y", "Z", "Q", "QN", "QB", "Q_N", "Z0", "Z1", "ZN"}

def build_net_graph(db: LogicalDB, data: Dict[str, Any], top: str, const_map: Dict[str, int]) -> None:
    db["net_graph"].clear()

    try:
        cells = data["modules"][top]["cells"]
    except KeyError as e:
        raise KeyError(f"Missing key in JSON: {e}. Check module data.")

    # Initialize nodes for any bit referenced by ports
    for p in db["ports"].values():
        for b in p["bits"]:
            db["net_graph"].setdefault(str(b), {"drivers": [], "sinks": []})

    # Map instance pins
    for inst_name, cell in cells.items():
        pdirs = cell.get("port_directions", {}) or {}
        conns = cell.get("connections", {}) or {}

        for pin, bit_list in conns.items():
            bits = bit_list if isinstance(bit_list, list) else [bit_list]
            # direction: from port_directions if present; else heuristic
            direction = pdirs.get(pin)
            if direction is None:
                direction = "output" if pin in _OUTPUT_PIN_HINTS else "input"

            for rawb in bits:
                if isinstance(rawb, int):
                    b = rawb
                elif isinstance(rawb, str) and rawb in const_map:
                    b = const_map[rawb]
                else:
                    raise ValueError(f"Unsupported bit value in net_graph: {rawb!r}")

                node = db["net_graph"].setdefault(str(b), {"drivers": [], "sinks": []})
                if direction == "output":
                    node["drivers"].append((inst_name, pin))
                else:
                    node["sinks"].append((inst_name, pin))

    # Ensure constants have a pseudo driver
    for sym, bid in const_map.items():
        _register_const_driver(db, bid, sym)

    # Count multi-driver bits (warn-level metric)
    multi = sum(1 for node in db["net_graph"].values() if len(node["drivers"]) > 1)
    db["stats"]["num_multidriver_bits"] = multi


# ----------------------------------------------------------------------
# Counts / stats / library
# ----------------------------------------------------------------------
def compute_type_counts(db: LogicalDB) -> None:
    counts: Dict[str, int] = {}
    for inst in db["instances"].values():
        t = inst["type"]
        counts[t] = counts.get(t, 0) + 1
    db["type_counts"] = dict(sorted(counts.items()))


def compute_stats(db: LogicalDB) -> None:
    n_inst = len(db["instances"])
    n_types = len(db["type_counts"])
    n_ports = len(db["ports"])

    bits: Set[int] = set()
    for p in db["ports"].values():
        bits.update(p["bits"])
    for inst in db["instances"].values():
        for blist in inst["pins"].values():
            bits.update(blist)

    db["stats"].update({
        "num_instances": n_inst,
        "num_unique_types": n_types,
        "num_ports": n_ports,
        "num_bits_referenced": len(bits)
    })


def infer_library_from_types(types: List[str]) -> str:
    libs = set()
    for t in types:
        if "__" in t:
            libs.add(t.split("__", 1)[0])
    if len(libs) == 1:
        return next(iter(libs))
    return "unknown"


# ----------------------------------------------------------------------
# Build one logical DB from a mapped file
# ----------------------------------------------------------------------
def build_logical_db(mapped_json_path: str, design_name: Optional[str] = None) -> LogicalDB:
    data = open_design(mapped_json_path)
    top = pick_top_module(data)

    db = _new_logical_db()
    db["design"] = design_name or infer_design_name(mapped_json_path)
    db["top"] = top
    db["source"] = {
        "mapped_json": mapped_json_path,
        "generator": os.path.basename(sys.argv[0]) if sys.argv else "parse_design.py"
    }

    # Parse core sections (ports first to know existing bit range)
    parse_ports(db, data, top)

    # Constants: allocate synthetic bit IDs and register as nets
    const_map = build_const_bit_map(data, top)
    register_const_nets(db, const_map)

    # Instances + optional netnames
    parse_instances(db, data, top, const_map)
    parse_netnames(db, data, top)

    # Net drivers/sinks
    build_net_graph(db, data, top, const_map)

    # Library + counts + stats
    all_types = [inst["type"] for inst in db["instances"].values()]
    db["library"] = infer_library_from_types(all_types)
    compute_type_counts(db)
    compute_stats(db)

    return db


def write_output(db: LogicalDB, out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)
        f.write("\n")


# ----------------------------------------------------------------------
# CLI (multi-file)
# ----------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Parse one or more Yosys <design>_mapped.json files into logical_db.json")
    p.add_argument(
        "--mapped-json",
        nargs="+",
        required=True,
        help="Path(s) to one or more <design>_mapped.json files"
    )
    p.add_argument(
        "--design",
        nargs="*",
        default=None,
        help="Optional design name(s); if omitted, inferred from file name(s)"
    )
    p.add_argument(
        "--outdir",
        default="build",
        help="Base output directory (default: build)"
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    mapped_files: List[str] = args.mapped_json
    explicit_names: Optional[List[str]] = args.design
    outdir: str = args.outdir

    # Align design names (None means infer per file)
    if explicit_names is not None and len(explicit_names) not in (0, len(mapped_files)):
        raise SystemExit("If you provide --design, you must pass exactly one name per --mapped-json file.")

    names: List[Optional[str]] = explicit_names or [None] * len(mapped_files)

    for i, fpath in enumerate(mapped_files):
        design = names[i] or infer_design_name(fpath)
        print(f"\n→ Building logical DB for {design} …")

        db = build_logical_db(fpath, design)
        out_path = os.path.join(outdir, design, f"{design}_logical_db.json")
        write_output(db, out_path)

        # Console summary
        print(f"[OK] {out_path} written.")
        print(f"  design   : {db['design']}")
        print(f"  top      : {db['top']}")
        print(f"  library  : {db['library']}")
        print(f"  instances: {db['stats']['num_instances']}")
        print(f"  types    : {db['stats']['num_unique_types']}")
        print(f"  ports    : {db['stats']['num_ports']}")
        if 'num_multidriver_bits' in db['stats']:
            print(f"  multi-driver bits: {db['stats']['num_multidriver_bits']}")


if __name__ == "__main__":
    main()
