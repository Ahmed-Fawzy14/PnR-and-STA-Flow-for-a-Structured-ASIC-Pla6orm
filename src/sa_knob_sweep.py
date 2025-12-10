#!/usr/bin/env python3
"""
sa_knob_sweep.py

Run simulated_annealing over a grid of knob settings for one or more designs,
keeping moves_per_temp fixed at 1000 and varying the other knobs.

Usage:

    # example with three designs
    python3 sa_knob_sweep.py 6502 uart fpu

For each <design>, this script expects:

    build/<design>/data_structures.json
    build/<design>/<design>.map

It produces:

    build/<design>/sa_maps/                 # one .map per knob combination
    build/<design>/<design>_sa_results.csv  # summary of all runs
"""

import argparse
import csv
import itertools
import os
import time
from pathlib import Path
from typing import List

import random
import simulated_annealing as sa  # your SA module


# -------------- knob grid (per design) ----------------
# This is the grid we agreed on:
#
#   T_initial: 2 values  -> [5e5, 1e6]
#   alpha    : 3 values  -> [0.90, 0.95, 0.98]
#   P_refine : 2 values  -> [0.3, 0.7]
#   W_initial: 2 values  -> [0.3, 0.6]
#   beta     : 2 values  -> [0.90, 0.97]
#
# Total combos per design = 2 * 3 * 2 * 2 * 2 = 48

T_INITIAL_SET = [5e5, 1e6]
ALPHA_SET     = [0.90, 0.95, 0.98]
P_REFINE_SET  = [0.3, 0.7]
W_INITIAL_SET = [0.3, 0.6]
BETA_SET      = [0.90, 0.97]

NUM_TEMP_STEPS  = 60       # from project spec
MOVES_PER_TEMP  = 1000     # stays constant as requested
REPORT_INTERVAL = 0        # 0 => no inner SA progress printing
BASE_SEED       = 1234     # used to seed 'random' for reproducibility


# -------------- helpers ----------------

def fmt_float_for_name(x: float) -> str:
    """
    Make a filename-safe string from a float.
    - Large numbers: no decimals, e.g. 500000.0 -> '500000'
    - Small numbers: two decimals, with '.' replaced by 'p', e.g. 0.95 -> '0p95'
    """
    if abs(x) >= 1000:
        s = f"{int(round(x))}"
    else:
        s = f"{x:.2f}".rstrip("0").rstrip(".")
    return s.replace(".", "p")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


# -------------- main sweep logic ----------------

def run_for_design(design: str) -> None:
    print(f"\n==================== Design {design} ====================")

    base = Path("build") / design
    data_path = base / "data_structures_sa.json"
    init_map_path = base / f"{design}.map"

    if not data_path.is_file():
        raise FileNotFoundError(f"Missing {data_path}")
    if not init_map_path.is_file():
        raise FileNotFoundError(f"Missing {init_map_path}")

    # Output directory for all SA maps for this design
    sa_maps_dir = base / "sa_maps"
    ensure_dir(sa_maps_dir)

    # Load design data once
    ds = sa.load_json(str(data_path))
    logical = ds.get("logical")
    fabric = ds.get("fabric")
    if logical is None or fabric is None:
        raise ValueError("data_structures.json must contain 'logical' and 'fabric' keys.")

    instances = logical.get("instances")
    if not isinstance(instances, dict):
        instances = logical.get("cells")
    if not isinstance(instances, dict):
        raise ValueError("'logical.instances' or 'logical.cells' must be a dict.")

    slots_by_phys_type = fabric.get("slots_by_phys_type")
    slot_info = fabric.get("slot_info")
    if not isinstance(slots_by_phys_type, dict):
        raise ValueError("'fabric.slots_by_phys_type' must be a dict.")
    if not isinstance(slot_info, dict):
        raise ValueError("'fabric.slot_info' must be a dict.")

    initial_placement = sa.load_map(str(init_map_path))

    # Prepare CSV summary
    csv_path = base / f"{design}_sa_results.csv"
    rows: List[dict] = []

    combo_iter = list(itertools.product(
        T_INITIAL_SET,
        ALPHA_SET,
        P_REFINE_SET,
        W_INITIAL_SET,
        BETA_SET,
    ))

    for idx, (T_initial, alpha, P_refine, W_initial, beta) in enumerate(combo_iter):
        label = (
            f"T{fmt_float_for_name(T_initial)}"
            f"_a{fmt_float_for_name(alpha)}"
            f"_P{fmt_float_for_name(P_refine)}"
            f"_W{fmt_float_for_name(W_initial)}"
            f"_b{fmt_float_for_name(beta)}"
        )

        print(f"\n[SWEEP] {design}  "
              f"T_initial={T_initial}, alpha={alpha}, "
              f"P_refine={P_refine}, W_initial={W_initial}, beta={beta}")

        # Seed the RNG so each combo is reproducible
        random.seed(BASE_SEED + idx)

        start = time.perf_counter()
        best_placement, best_cost = sa.simulated_annealing(
            instances=instances,
            slot_info=slot_info,
            slots_by_phys_type=slots_by_phys_type,
            initial_placement=initial_placement,
            num_temp_steps=NUM_TEMP_STEPS,
            T_initial=T_initial,
            alpha=alpha,
            moves_per_temp=MOVES_PER_TEMP,
            P_refine=P_refine,
            W_initial=W_initial,
            beta=beta,
            report_interval=REPORT_INTERVAL,
        )
        runtime = time.perf_counter() - start

        # Write map for this combo
        out_map_name = f"{design}_sa_{label}.map"
        out_map_path = sa_maps_dir / out_map_name
        sa.write_map(str(out_map_path), best_placement)

        print(f"[RESULT] design={design} "
              f"T_initial={T_initial} alpha={alpha} "
              f"P_refine={P_refine} W_initial={W_initial} beta={beta} "
              f"HPWL={best_cost:.3f} runtime_s={runtime:.3f} "
              f"map={out_map_path}")

        rows.append({
            "design": design,
            "T_initial": T_initial,
            "alpha": alpha,
            "P_refine": P_refine,
            "W_initial": W_initial,
            "beta": beta,
            "num_temp_steps": NUM_TEMP_STEPS,
            "moves_per_temp": MOVES_PER_TEMP,
            "HPWL": best_cost,
            "runtime_s": runtime,
            "map_path": str(out_map_path),
        })

    # Write CSV for this design
    fieldnames = [
        "design",
        "T_initial",
        "alpha",
        "P_refine",
        "W_initial",
        "beta",
        "num_temp_steps",
        "moves_per_temp",
        "HPWL",
        "runtime_s",
        "map_path",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n[INFO] Wrote SA sweep summary for {design} to {csv_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sweep SA knobs (except moves_per_temp) for multiple designs."
    )
    parser.add_argument(
        "designs",
        nargs="+",
        help="Design names (e.g. 6502 uart fpu)",
    )
    args = parser.parse_args()

    for design in args.designs:
        run_for_design(design)


if __name__ == "__main__":
    main()