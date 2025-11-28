#!/usr/bin/env python3
"""
Placer: Two-Stage Placement Algorithm

This module implements a high-quality, two-stage placement algorithm:
1. Greedy Initial Placement (I/O-Driven Seed & Grow)
2. Simulated Annealing Optimization

The placer maps logical instances to physical fabric slots, optimizing
for minimal total Half-Perimeter Wirelength (HPWL).
"""

import argparse
import json
import os
import sys
from typing import Any, Dict

# Import functions from greedy placer
from greedyPlacer import (
    load_json as load_ds_json,
    greedy_place,
    write_map_file,
)

# Import functions from simulated annealing
from simulated_annealing import (
    load_map,
    simulated_annealing,
    write_map as write_sa_map,
    compute_total_hpwl,
    build_net_to_insts,
)


def ensure_dir_for(path: str) -> None:
    """Ensure directory exists for output file."""
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


def run_greedy_stage(
    data_structures_path: str,
    greedy_map_path: str,
) -> Dict[str, str]:
    """
    Stage 1: Greedy Initial Placement (I/O-Driven Seed & Grow)
    
    Args:
        data_structures_path: Path to data_structures.json
        greedy_map_path: Path to write greedy placement map
        
    Returns:
        Greedy placement: inst_name -> slot_name
    """
    print("\n" + "="*60)
    print("Stage 1: Greedy Initial Placement")
    print("="*60)
    
    # Load data structures
    print(f"[INFO] Loading data structures from '{data_structures_path}'...")
    ds = load_ds_json(data_structures_path)
    
    logical = ds.get("logical")
    fabric = ds.get("fabric")
    
    if logical is None or fabric is None:
        raise ValueError("data_structures.json must contain 'logical' and 'fabric' keys")
    
    # Extract required data
    # In data_structures.json:
    # - logical.instances is a DICT (for SA) with inst_name -> {type, pins, ...}
    # - logical.instance_order is a LIST (for greedy) of instance names
    # - logical.cell_type is a dict mapping instance names to cell types
    instance_list = logical.get("instance_order")
    if not isinstance(instance_list, list):
        # Fallback: if instances is a dict, use its keys
        instances_dict = logical.get("instances")
        if isinstance(instances_dict, dict):
            instance_list = sorted(instances_dict.keys())
        else:
            raise ValueError("'logical.instance_order' must be a list or 'logical.instances' must be a dict")
    
    cell_type = logical.get("cell_type", {})
    if not isinstance(cell_type, dict):
        raise ValueError("'logical.cell_type' must be a dict")
    
    slots_by_phys_type = fabric.get("slots_by_phys_type")
    if not isinstance(slots_by_phys_type, dict):
        raise ValueError("'fabric.slots_by_phys_type' must be a dict")
    
    print(f"[INFO] Placing {len(instance_list)} instances...")
    
    # Run greedy placement
    # Note: greedy_place modifies slots_by_phys_type in place (pops slots)
    # So we need to make a copy
    slots_by_phys_type_copy = {
        k: list(v) for k, v in slots_by_phys_type.items()
    }
    
    placement = greedy_place(
        instances=instance_list,
        cell_type=cell_type,
        slots_by_phys_type=slots_by_phys_type_copy,
        strict=True,
    )
    
    # Write greedy map
    print(f"[INFO] Writing greedy placement to '{greedy_map_path}'...")
    ensure_dir_for(greedy_map_path)
    write_map_file(greedy_map_path, placement)
    
    print(f"[INFO] Greedy placement complete: {len(placement)} instances placed")
    
    return placement


def run_sa_stage(
    data_structures_path: str,
    greedy_placement: Dict[str, str],
    num_temp_steps: int = 60,
    moves_per_temp: int = 1000,
    T_initial: float = 200.0,
    alpha: float = 0.95,
    P_refine: float = 0.7,
    W_initial: float = 0.5,
    beta: float = 0.95,
    seed: int = 0,
    report_interval: int = 1000,
) -> tuple[Dict[str, str], float]:
    """
    Stage 2: Simulated Annealing Optimization
    
    Args:
        data_structures_path: Path to data_structures.json
        greedy_placement: Initial placement from greedy stage
        num_temp_steps: Number of temperature steps
        moves_per_temp: Moves per temperature step
        T_initial: Initial temperature
        alpha: Cooling rate
        P_refine: Probability of refine (swap) move
        W_initial: Initial exploration window size (fraction of die)
        beta: Window cooling rate
        seed: Random seed (0 = system randomness)
        report_interval: Progress report interval
        
    Returns:
        (best_placement, best_hpwl)
    """
    print("\n" + "="*60)
    print("Stage 2: Simulated Annealing Optimization")
    print("="*60)
    
    # Load data structures
    print(f"[INFO] Loading data structures from '{data_structures_path}'...")
    ds = load_ds_json(data_structures_path)
    
    logical = ds.get("logical")
    fabric = ds.get("fabric")
    
    if logical is None or fabric is None:
        raise ValueError("data_structures.json must contain 'logical' and 'fabric' keys")
    
    # For SA, we need instances as a dict (inst_name -> cell_info with pins)
    # dataStructuresGenerator creates logical.instances as a dict for SA
    instances = logical.get("instances")
    if not isinstance(instances, dict):
        # Try alternative names
        instances = logical.get("cells")
        if not isinstance(instances, dict):
            raise ValueError("'logical.instances' must be a dict for SA stage (with pin information)")
    
    slot_info = fabric.get("slot_info")
    slots_by_phys_type = fabric.get("slots_by_phys_type")
    
    if not isinstance(slot_info, dict):
        raise ValueError("'fabric.slot_info' must be a dict")
    if not isinstance(slots_by_phys_type, dict):
        raise ValueError("'fabric.slots_by_phys_type' must be a dict")
    
    # Run simulated annealing
    print(f"[INFO] Running SA with: num_temp_steps={num_temp_steps}, "
          f"moves_per_temp={moves_per_temp}, T_initial={T_initial}, "
          f"alpha={alpha}, P_refine={P_refine}, W_initial={W_initial}, beta={beta}")
    
    best_placement, best_hpwl = simulated_annealing(
        instances=instances,
        slot_info=slot_info,
        slots_by_phys_type=slots_by_phys_type,
        initial_placement=greedy_placement,
        num_temp_steps=num_temp_steps,
        T_initial=T_initial,
        alpha=alpha,
        moves_per_temp=moves_per_temp,
        P_refine=P_refine,
        W_initial=W_initial,
        beta=beta,
        report_interval=report_interval,
    )
    
    return best_placement, best_hpwl


def main():
    """Main entry point for the placer."""
    parser = argparse.ArgumentParser(
        description="Two-stage placer: Greedy initial placement + Simulated Annealing optimization"
    )
    
    # Required arguments
    parser.add_argument(
        "--data-structures",
        required=True,
        help="Path to data_structures.json"
    )
    parser.add_argument(
        "--out-map",
        required=True,
        help="Path to write final placement map"
    )
    
    # Optional: intermediate greedy map
    parser.add_argument(
        "--greedy-map",
        help="Path to write intermediate greedy map (optional)"
    )
    
    # SA parameters
    parser.add_argument(
        "--num-temp-steps",
        type=int,
        default=60,
        help="Number of temperature steps (default: 60)"
    )
    parser.add_argument(
        "--moves-per-temp",
        type=int,
        default=1000,
        help="Moves per temperature step (default: 1000)"
    )
    parser.add_argument(
        "--T-initial",
        dest="T_initial",
        type=float,
        default=200.0,
        help="Initial temperature (default: 200.0)"
    )
    parser.add_argument(
        "--alpha",
        type=float,
        default=0.95,
        help="Cooling rate (default: 0.95)"
    )
    parser.add_argument(
        "--P-refine",
        dest="P_refine",
        type=float,
        default=0.7,
        help="Probability of refine (swap) move (default: 0.7)"
    )
    parser.add_argument(
        "--W-initial",
        dest="W_initial",
        type=float,
        default=0.5,
        help="Initial exploration window size (fraction of die, default: 0.5)"
    )
    parser.add_argument(
        "--beta",
        type=float,
        default=0.95,
        help="Window cooling rate (default: 0.95)"
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Random seed (0 = system randomness, default: 0)"
    )
    parser.add_argument(
        "--report-interval",
        type=int,
        default=1000,
        help="Progress report interval (default: 1000)"
    )
    parser.add_argument(
        "--skip-sa",
        action="store_true",
        help="Skip SA stage, only run greedy placement"
    )
    
    args = parser.parse_args()
    
    # Set random seed if specified
    if args.seed != 0:
        import random
        random.seed(args.seed)
        print(f"[INFO] Using random seed {args.seed}")
    
    try:
        # Stage 1: Greedy placement
        greedy_map_path = args.greedy_map or args.out_map.replace(".map", "_greedy.map")
        greedy_placement = run_greedy_stage(
            data_structures_path=args.data_structures,
            greedy_map_path=greedy_map_path,
        )
        
        if args.skip_sa:
            # Just write greedy placement to output
            print(f"\n[INFO] Skipping SA stage, writing greedy placement to '{args.out_map}'...")
            ensure_dir_for(args.out_map)
            write_map_file(args.out_map, greedy_placement)
            
            # Compute and print HPWL
            ds = load_ds_json(args.data_structures)
            logical = ds.get("logical")
            fabric = ds.get("fabric")
            instances = logical.get("instances") or logical.get("cells")
            slot_info = fabric.get("slot_info")
            
            net_to_insts = build_net_to_insts(instances)
            hpwl = compute_total_hpwl(net_to_insts, slot_info, greedy_placement)
            
            print("\n" + "="*60)
            print(f"Final Total HPWL: {hpwl:.3f} µm")
            print("="*60 + "\n")
        else:
            # Stage 2: Simulated Annealing
            best_placement, best_hpwl = run_sa_stage(
                data_structures_path=args.data_structures,
                greedy_placement=greedy_placement,
                num_temp_steps=args.num_temp_steps,
                moves_per_temp=args.moves_per_temp,
                T_initial=args.T_initial,
                alpha=args.alpha,
                P_refine=args.P_refine,
                W_initial=args.W_initial,
                beta=args.beta,
                seed=args.seed,
                report_interval=args.report_interval,
            )
            
            # Write final placement
            print(f"\n[INFO] Writing final placement to '{args.out_map}'...")
            ensure_dir_for(args.out_map)
            write_sa_map(args.out_map, best_placement)
            
            # Print final HPWL
            print("\n" + "="*60)
            print(f"Final Total HPWL: {best_hpwl:.3f} µm")
            print("="*60 + "\n")
        
        print("[INFO] Placement complete!")
        
    except Exception as e:
        print(f"\n[ERROR] Placement failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

