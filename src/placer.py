#!/usr/bin/env python3
# placer.py
"""
Combined placer driver.

Runs the four existing scripts in order, **without** modifying them:

  1) dataStructuresGenerator.py
  2) greedyPlacer.py
  3) dataStructuresGenerator_SA.py
  4) simulated_annealing.py

Typical usage:
    python placer.py --design 6502

Artifacts:
  - build/<design>/data_structures.json          (for greedy)
  - build/<design>/<design>.map                 (greedy initial map)
  - build/<design>/data_structures_sa.json      (for SA)
  - build/<design>/<design>_sa.map              (SA-optimized map)

Additionally (this file):
  - build/<design>/<design>_place_metrics.json  (HPWL + runtime + utilization, etc.)
"""

import argparse
import json
import os
import time
import platform
from pathlib import Path
from typing import Any, Dict, Tuple

import dataStructuresGenerator as dg
import greedyPlacer as gp
import dataStructuresGenerator_SA as dsa
import simulated_annealing as sa


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def safe_load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    if not isinstance(obj, dict):
        raise ValueError(f"Expected JSON object at '{path}', got {type(obj)}")
    return obj


def try_get_total_ram_bytes() -> int | None:
    """Best-effort RAM detection (Linux/WSL first, then None)."""
    # Linux / WSL: /proc/meminfo
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        try:
            txt = meminfo.read_text(encoding="utf-8", errors="ignore")
            # MemTotal:       16343464 kB
            for line in txt.splitlines():
                if line.startswith("MemTotal:"):
                    parts = line.split()
                    kb = int(parts[1])
                    return kb * 1024
        except Exception:
            pass
    return None


def compute_utilization(logical_db_path: str, fabric_db_path: str, cells_by_type_path: str) -> Dict[str, Any]:
    """
    Compute per-type utilization: required/available for each cell type.

    We try multiple schemas:
      - logical_db: {"instances": {inst: {"type": "..."} } } OR {"logical": {"instances": ...}}
      - cells_by_type.json: { "sky130_fd_sc_hd__nand2_2": ["slot1", ...], ... }
      - fabric_db.json: either has similar dict by type OR list of slots with a type field
    """
    logical_db = safe_load_json(logical_db_path)

    # ---- required_by_type ----
    instances = None
    if "instances" in logical_db and isinstance(logical_db["instances"], dict):
        instances = logical_db["instances"]
    elif "logical" in logical_db and isinstance(logical_db["logical"], dict):
        l = logical_db["logical"]
        if "instances" in l and isinstance(l["instances"], dict):
            instances = l["instances"]

    if instances is None:
        raise ValueError(f"Could not find instances dict in logical DB '{logical_db_path}'")

    required_by_type: Dict[str, int] = {}
    for _, inst in instances.items():
        if not isinstance(inst, dict):
            continue
        ctype = inst.get("type", "UNKNOWN")
        required_by_type[ctype] = required_by_type.get(ctype, 0) + 1

    # ---- available_by_type ----
    available_by_type: Dict[str, int] = {}

    # Prefer cells_by_type.json if it exists & matches expected schema
    try:
        cbt = safe_load_json(cells_by_type_path)
        if all(isinstance(v, list) for v in cbt.values()):
            for ctype, slots in cbt.items():
                available_by_type[str(ctype)] = len(slots)
    except Exception:
        pass

    # Fallback to fabric_db.json if needed
    if not available_by_type:
        fabric_db = safe_load_json(fabric_db_path)

        # Case A: already grouped by type
        if all(isinstance(v, list) for v in fabric_db.values()):
            for ctype, slots in fabric_db.items():
                available_by_type[str(ctype)] = len(slots)
        else:
            # Case B: fabric_db has a list of slots somewhere
            slots_list = None
            for k in ("slots", "cells", "fabric_cells", "slot_info"):
                if k in fabric_db and isinstance(fabric_db[k], list):
                    slots_list = fabric_db[k]
                    break
            if slots_list is None:
                # Some schemas store slot_info as dict {slot_name: {...}}
                if "slot_info" in fabric_db and isinstance(fabric_db["slot_info"], dict):
                    slots_list = list(fabric_db["slot_info"].values())

            if isinstance(slots_list, list):
                for slot in slots_list:
                    if not isinstance(slot, dict):
                        continue
                    ctype = (
                        slot.get("physical_cell_type")
                        or slot.get("type")
                        or slot.get("cell_type")
                        or "UNKNOWN"
                    )
                    available_by_type[ctype] = available_by_type.get(ctype, 0) + 1

    # ---- build utilization table ----
    util_by_type: Dict[str, Dict[str, Any]] = {}
    worst = {"cell_type": None, "utilization": None, "required": None, "available": None}

    all_types = set(required_by_type.keys()) | set(available_by_type.keys())
    for ctype in sorted(all_types):
        req = int(required_by_type.get(ctype, 0))
        avail = int(available_by_type.get(ctype, 0))
        util = (req / avail) if avail > 0 else None

        util_by_type[ctype] = {
            "required": req,
            "available": avail,
            "utilization": util,  # None if avail==0
        }

        if util is not None:
            if worst["utilization"] is None or util > worst["utilization"]:
                worst = {"cell_type": ctype, "utilization": util, "required": req, "available": avail}

    total_required = sum(required_by_type.values())
    total_available = sum(available_by_type.values()) if available_by_type else None

    return {
        "required_by_type": required_by_type,
        "available_by_type": available_by_type,
        "utilization_by_type": util_by_type,
        "worst_case_type_utilization": worst,
        "total_required_instances": total_required,
        "total_available_slots_sum": total_available,
    }


def write_metrics_json(path: str, metrics: Dict[str, Any]) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------
# CLI
# ---------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run dataStructuresGenerator -> greedyPlacer -> "
                    "dataStructuresGenerator_SA -> simulated_annealing."
    )
    p.add_argument(
        "--design",
        required=True,
        help="Design name (e.g., 6502, z80, ...).",
    )
    p.add_argument(
        "--greedy-only",
        action="store_true",
        help="Run only up to greedyPlacer (skip simulated annealing).",
    )

    # Metrics output
    p.add_argument(
        "--metrics-out",
        default=None,
        help="Where to write Phase-2 metrics JSON. Default: build/<design>/<design>_place_metrics.json",
    )
    p.add_argument(
        "--no-metrics",
        action="store_true",
        help="Disable writing metrics JSON.",
    )

    # SA knobs (mirroring simulated_annealing.py, prefixed with sa-)
    p.add_argument("--sa-num-temp-steps", type=int, default=60)
    p.add_argument("--sa-moves-per-temp", type=int, default=1000)
    p.add_argument("--sa-T-initial", dest="sa_T_initial", type=float, default=200.0)
    p.add_argument("--sa-alpha", type=float, default=0.95)
    p.add_argument("--sa-P-refine", dest="sa_P_refine", type=float, default=0.7)
    p.add_argument("--sa-W-initial", dest="sa_W_initial", type=float, default=0.5)
    p.add_argument("--sa-beta", type=float, default=0.95)
    p.add_argument("--sa-report-interval", type=int, default=1000)
    p.add_argument("--sa-seed", type=int, default=0)

    return p.parse_args()


# ---------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------

def main() -> None:
    args = parse_args()
    design = args.design

    t0_total = time.time()

    base_dir = os.path.join("build", design)
    netlist_path = os.path.join(base_dir, f"{design}_mapped_netlist_graph.json")
    logical_path = os.path.join(base_dir, f"{design}_logical_db.json")

    # Fabric paths
    fabric_path_cells_by_type = os.path.join("build", "fabric", "cells_by_type.json")
    fabric_path_greedy = os.path.join("build", "fabric", "fabric_db.json")

    # Files that match your existing scripts’ expectations
    greedy_ds_path = os.path.join(base_dir, "data_structures.json")        # for greedy
    greedy_map_path = os.path.join(base_dir, f"{design}.map")              # greedy output
    sa_ds_path     = os.path.join(base_dir, "data_structures_sa.json")     # for SA
    sa_map_path    = os.path.join(base_dir, f"{design}_sa.map")            # SA output

    # Default metrics out path
    metrics_out = args.metrics_out or os.path.join(base_dir, f"{design}_place_metrics.json")

    print("=" * 80)
    print(f"[PIPELINE] Starting combined placer for design '{design}'")
    print("=" * 80)

    # -----------------------------------------------------
    # 1) dataStructuresGenerator.py
    # -----------------------------------------------------
    print("[PIPELINE] Stage 1: dataStructuresGenerator.py")
    dg.build_and_save_structures(
        netlist_graph_path=netlist_path,
        logical_db_path=logical_path,
        fabric_cells_path=fabric_path_greedy,
        output_json_path=greedy_ds_path,
    )
    print(f"[PIPELINE] Greedy data_structures written to: {greedy_ds_path}")

    # -----------------------------------------------------
    # 2) greedyPlacer.py
    # -----------------------------------------------------
    print("[PIPELINE] Stage 2: greedyPlacer.py")
    placer = gp.GreedyPlacer(design_name=design, processed_json_path=greedy_ds_path)
    placer.run_seed_placement()
    placer.run_grow_placement()
    placer.write_map_file(greedy_map_path)
    print(f"[PIPELINE] Greedy map written to: {greedy_map_path}")

    if args.greedy_only:
        runtime_total_s = time.time() - t0_total

        # Utilization + Phase 2 requirements (greedy-only)
        util = compute_utilization(
            logical_db_path=logical_path,
            fabric_db_path=fabric_path_greedy,
            cells_by_type_path=fabric_path_cells_by_type,
        )

        metrics = {
            "design": design,
            "phase": 2,
            "mode": "greedy_only",
            "hpwl_um": None,  # greedy HPWL not computed here unless your greedy script provides it
            "runtime_total_s": float(runtime_total_s),
            "runtime_sa_s": None,
            "utilization": util,
            "requirements_phase2": {
                "ran_data_structures_generator": True,
                "ran_greedy_placer": True,
                "ran_sa": False,
                "wrote_greedy_map": Path(greedy_map_path).exists(),
                "wrote_sa_map": False,
                "reported_final_hpwl": False,
            },
            "artifacts": {
                "greedy_ds": greedy_ds_path,
                "greedy_map": greedy_map_path,
                "sa_ds": None,
                "sa_map": None,
            },
            "machine": {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "cpu_count": os.cpu_count(),
                "processor": platform.processor(),
                "total_ram_bytes": try_get_total_ram_bytes(),
                # You can optionally add your own fields manually later (CPU model, RAM, etc.)
            },
        }

        if not args.no_metrics:
            write_metrics_json(metrics_out, metrics)
            print(f"[PIPELINE] Wrote placement metrics to: {metrics_out}")

        print("[PIPELINE] --greedy-only set; skipping simulated annealing.")
        print(f"[PIPELINE] Final map (greedy) = {greedy_map_path}")
        return

    # -----------------------------------------------------
    # 3) dataStructuresGenerator_SA.py
    # -----------------------------------------------------
    print("[PIPELINE] Stage 3: dataStructuresGenerator_SA.py")
    logical_db = dsa.load_json(logical_path)
    fabric_db  = dsa.load_json(fabric_path_cells_by_type)

    logical_section = dsa.build_logical_section(logical_db)
    fabric_section  = dsa.build_fabric_section(fabric_db)
    nets_section    = dsa.build_nets_section(logical_db)

    sa_out_obj = {
        "logical": logical_section,
        "fabric":  fabric_section,
        "nets":    nets_section,
    }
    dsa.ensure_dir_for(sa_ds_path)
    with open(sa_ds_path, "w", encoding="utf-8") as f:
        json.dump(sa_out_obj, f, indent=2, sort_keys=True)
    print(f"[PIPELINE] SA data_structures written to: {sa_ds_path}")

    # -----------------------------------------------------
    # 4) simulated_annealing.py
    # -----------------------------------------------------
    print("[PIPELINE] Stage 4: simulated_annealing.py")

    if args.sa_seed != 0:
        sa.random.seed(args.sa_seed)  # type: ignore[attr-defined]
        print(f"[PIPELINE] SA: Using random seed {args.sa_seed}.")
    else:
        print("[PIPELINE] SA: Using system randomness (no fixed seed).")

    print(f"[PIPELINE] SA: Loading data structures from '{sa_ds_path}'...")
    ds = sa.load_json(sa_ds_path)

    logical_sa = ds.get("logical")
    fabric_sa  = ds.get("fabric")
    if logical_sa is None or fabric_sa is None:
        raise ValueError("data_structures_sa.json must contain 'logical' and 'fabric' keys.")

    instances = logical_sa.get("instances")
    if not isinstance(instances, dict):
        instances = logical_sa.get("cells")
    if not isinstance(instances, dict):
        raise ValueError("'logical.instances' or 'logical.cells' must be a dict in SA data_structures.json.")

    slots_by_phys_type = fabric_sa.get("slots_by_phys_type")
    slot_info          = fabric_sa.get("slot_info")
    if not isinstance(slots_by_phys_type, dict):
        raise ValueError("'fabric.slots_by_phys_type' must be a dict in SA data_structures.json.")
    if not isinstance(slot_info, dict):
        raise ValueError("'fabric.slot_info' must be a dict in SA data_structures.json.")

    print(f"[PIPELINE] SA: Loading initial map from '{greedy_map_path}'...")
    initial_placement = sa.load_map(greedy_map_path)
    print(f"[PIPELINE] SA: logical.instances = {len(instances)}, initial_placement = {len(initial_placement)}")

    t0_sa = time.time()
    best_placement, best_cost = sa.simulated_annealing(
        instances=instances,
        slot_info=slot_info,
        slots_by_phys_type=slots_by_phys_type,
        initial_placement=initial_placement,
        num_temp_steps=args.sa_num_temp_steps,
        T_initial=args.sa_T_initial,
        alpha=args.sa_alpha,
        moves_per_temp=args.sa_moves_per_temp,
        P_refine=args.sa_P_refine,
        W_initial=args.sa_W_initial,
        beta=args.sa_beta,
        report_interval=args.sa_report_interval,
    )
    runtime_sa_s = time.time() - t0_sa

    print("[PIPELINE] SA: Writing best map...")
    sa.write_map(sa_map_path, best_placement)
    print(f"[PIPELINE] SA: Best HPWL = {best_cost:.3f}")
    print(f"[PIPELINE] Final SA map = {sa_map_path}")

    # -----------------------------------------------------
    # Metrics: HPWL + runtime + utilization + requirements
    # -----------------------------------------------------
    runtime_total_s = time.time() - t0_total

    util = compute_utilization(
        logical_db_path=logical_path,
        fabric_db_path=fabric_path_greedy,
        cells_by_type_path=fabric_path_cells_by_type,
    )

    metrics = {
        "design": design,
        "phase": 2,
        "mode": "greedy_plus_sa",
        "hpwl_um": float(best_cost),
        "runtime_total_s": float(runtime_total_s),
        "runtime_sa_s": float(runtime_sa_s),
        "utilization": util,
        "requirements_phase2": {
            "ran_data_structures_generator": True,
            "ran_greedy_placer": True,
            "ran_sa": True,
            "wrote_greedy_map": Path(greedy_map_path).exists(),
            "wrote_sa_map": Path(sa_map_path).exists(),
            "reported_final_hpwl": True,
        },
        "sa_knobs": {
            "num_temp_steps": args.sa_num_temp_steps,
            "moves_per_temp": args.sa_moves_per_temp,
            "T_initial": args.sa_T_initial,
            "alpha": args.sa_alpha,
            "P_refine": args.sa_P_refine,
            "W_initial": args.sa_W_initial,
            "beta": args.sa_beta,
            "report_interval": args.sa_report_interval,
            "seed": args.sa_seed,
        },
        "artifacts": {
            "greedy_ds": greedy_ds_path,
            "greedy_map": greedy_map_path,
            "sa_ds": sa_ds_path,
            "sa_map": sa_map_path,
        },
        "machine": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
            "processor": platform.processor(),
            "total_ram_bytes": try_get_total_ram_bytes(),
            # Add more fields manually later if you want (CPU model string, RAM GB, etc.)
        },
    }

    if not args.no_metrics:
        write_metrics_json(metrics_out, metrics)
        print(f"[PIPELINE] Wrote placement metrics to: {metrics_out}")

    print(f"[PIPELINE] Phase-2 runtime_total_s = {runtime_total_s:.2f} s")
    print(f"[PIPELINE] Phase-2 runtime_sa_s    = {runtime_sa_s:.2f} s")

    print("=" * 80)
    print("[PIPELINE] Done.")


if __name__ == "__main__":
    main()