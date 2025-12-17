#!/usr/bin/env python3
# placer.py
"""
Combined placer driver.

Runs the four existing scripts in order, **without** modifying them:

  1) dataStructuresGenerator.py
  2) greedyPlacer.py
  3) dataStructuresGenerator_SA.py
  4) simulated_annealing.py  (HPWL + congestion)

Typical usage:

    python placer.py --design 6502

Artifacts:

  - build/<design>/data_structures.json          (for greedy)
  - build/<design>/<design>.map                  (greedy initial map)
  - build/<design>/data_structures_sa.json       (for SA)
  - build/<design>/<design>_sa.map               (SA-optimized map)
"""

import argparse
import json
import os

import dataStructuresGenerator as dg
import greedyPlacer as gp
import dataStructuresGenerator_SA as dsa
import simulated_annealing as sa


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

    # SA knobs (mirroring simulated_annealing.py, prefixed with sa-)
    p.add_argument("--sa-num-temp-steps", type=int, default=60,
                   help="SA: number of temperature steps (default: 60).")
    p.add_argument("--sa-moves-per-temp", type=int, default=1000,
                   help="SA: moves per temperature step (default: 1000).")
    p.add_argument("--sa-T-initial", dest="sa_T_initial", type=float, default=200.0,
                   help="SA: initial temperature (default: 200.0).")
    p.add_argument("--sa-alpha", type=float, default=0.95,
                   help="SA: cooling rate alpha (default: 0.95).")
    p.add_argument("--sa-P-refine", dest="sa_P_refine", type=float, default=0.7,
                   help="SA: probability of refine (swap) moves (default: 0.7).")
    p.add_argument("--sa-W-initial", dest="sa_W_initial", type=float, default=0.5,
                   help="SA: initial exploration window fraction (default: 0.5).")
    p.add_argument("--sa-beta", type=float, default=0.95,
                   help="SA: window cooling rate beta (default: 0.95).")
    p.add_argument("--sa-report-interval", type=int, default=1000,
                   help="SA: print progress every N moves (default: 1000).")
    p.add_argument("--sa-seed", type=int, default=0,
                   help="SA: random seed (0 = system randomness, default: 0).")

    # ---------------- NEW: HPWL + congestion knobs ----------------
    p.add_argument("--sa-gamma", type=float, default=0.75,
                   help="SA: weighted HPWL strength: w=1+gamma*log2(deg). (default: 0.75)")
    p.add_argument("--sa-lambda-cong", dest="sa_lambda_cong", type=float, default=0.10,
                   help="SA: congestion weight λ in total = hpwl + λ*cong. (default: 0.10)")
    p.add_argument("--sa-lambda-growth", dest="sa_lambda_growth", type=float, default=1.00,
                   help="SA: multiply λ each temp step: λ_k = λ0*(growth^k). (default: 1.00)")
    p.add_argument("--sa-cong-bins-x", dest="sa_cong_bins_x", type=int, default=30,
                   help="SA: congestion grid bins in X. (default: 30)")
    p.add_argument("--sa-cong-bins-y", dest="sa_cong_bins_y", type=int, default=30,
                   help="SA: congestion grid bins in Y. (default: 30)")

    return p.parse_args()


# ---------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------

def main() -> None:
    args = parse_args()
    design = args.design

    base_dir = os.path.join("build", design)
    netlist_path = os.path.join(base_dir, f"{design}_mapped_netlist_graph.json")
    logical_path = os.path.join(base_dir, f"{design}_logical_db.json")

    # NOTE: keep your existing paths (I didn't change your flow assumptions)
    fabric_path = os.path.join("build", "fabric", "cells_by_type.json")
    fabric_path_greedy = os.path.join("build", "fabric", "fabric_db.json")

    # Files that match your existing scripts’ expectations
    greedy_ds_path = os.path.join(base_dir, "data_structures.json")        # for greedy
    greedy_map_path = os.path.join(base_dir, f"{design}.map")              # greedy output
    sa_ds_path     = os.path.join(base_dir, "data_structures_sa.json")     # for SA
    sa_map_path    = os.path.join(base_dir, f"{design}_sa.map")            # SA output

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
        print("[PIPELINE] --greedy-only set; skipping simulated annealing.")
        print(f"[PIPELINE] Final map (greedy) = {greedy_map_path}")
        return

    # -----------------------------------------------------
    # 3) dataStructuresGenerator_SA.py
    # -----------------------------------------------------
    print("[PIPELINE] Stage 3: dataStructuresGenerator_SA.py")
    logical_db = dsa.load_json(logical_path)
    fabric_db  = dsa.load_json(fabric_path)

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
    print("[PIPELINE] Stage 4: simulated_annealing.py (HPWL + congestion)")

    if args.sa_seed != 0:
        sa.random.seed(args.sa_seed)  # uses the random module imported inside simulated_annealing.py
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
    print(f"[PIPELINE] SA: logical.instances = {len(instances)}, "
          f"initial_placement = {len(initial_placement)}")

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
        gamma=args.sa_gamma,
        lambda_cong=args.sa_lambda_cong,
        lambda_growth=args.sa_lambda_growth,
        cong_bins_x=args.sa_cong_bins_x,
        cong_bins_y=args.sa_cong_bins_y,
        report_interval=args.sa_report_interval,
    )

    print("[PIPELINE] SA: Writing best map...")
    sa.write_map(sa_map_path, best_placement)
    print(f"[PIPELINE] SA: Best TOTAL cost = {best_cost:.3f}")
    print(f"[PIPELINE] Final SA map = {sa_map_path}")
    print("=" * 80)
    print("[PIPELINE] Done.")


if __name__ == "__main__":
    main()