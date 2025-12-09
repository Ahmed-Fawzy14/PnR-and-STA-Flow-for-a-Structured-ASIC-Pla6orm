#!/usr/bin/env python3
"""
SA Knob Analysis Script

Runs simulated annealing with a comprehensive set of parameter combinations to explore
how knobs affect the placer's quality (final HPWL) and runtime.

This comprehensive analysis includes:
- Full sweeps of each parameter individually
- Key interaction combinations (alpha × num_temp_steps, alpha × P_refine)
- Expanded parameter ranges for better coverage

Fixed parameters:
- T_initial = 3,000,000
- moves_per_temp = 1000

Varies:
- num_temp_steps: [30, 40, 50, 60, 70, 80]
- alpha (cooling rate): [0.80, 0.85, 0.90, 0.92, 0.95, 0.97, 0.99]
- P_refine: [0.3, 0.5, 0.7, 0.8, 0.9]
- W_initial: [0.3, 0.5, 0.7, 0.8]
- beta: [0.90, 0.92, 0.95, 0.97, 0.99]

Expected: ~85 experiments total
"""

import argparse
import csv
import itertools
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

try:
    import matplotlib.pyplot as plt
    import numpy as np
except ImportError:
    print("[ERROR] matplotlib and numpy are required. Install with: pip install matplotlib numpy")
    sys.exit(1)


def run_sa_experiment(
    design: str,
    data_structures: str,
    initial_map: str,
    out_map: str,
    num_temp_steps: int,
    alpha: float,
    P_refine: float,
    W_initial: float,
    beta: float,
    seed: int = 42,
) -> Tuple[float, float]:
    """
    Run one SA experiment and return (runtime_seconds, final_hpwl).
    
    Returns:
        (runtime, hpwl) or (None, None) if failed
    """
    T_initial = 3000000.0
    moves_per_temp = 1000
    
    # Build command
    cmd = [
        sys.executable,
        "src/simulated_annealing.py",
        "--data-structures", data_structures,
        "--initial-map", initial_map,
        "--out-map", out_map,
        "--num-temp-steps", str(num_temp_steps),
        "--moves-per-temp", str(moves_per_temp),
        "--T-initial", str(T_initial),
        "--alpha", str(alpha),
        "--P-refine", str(P_refine),
        "--W-initial", str(W_initial),
        "--beta", str(beta),
        "--seed", str(seed),
        "--report-interval", "0",  # Disable progress output for cleaner logs
    ]
    
    # Run and measure time
    start_time = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3600,  # 1 hour max per run
            cwd=Path(__file__).parent.parent,
        )
        runtime = time.time() - start_time
        
        if result.returncode != 0:
            print(f"[ERROR] SA failed with return code {result.returncode}")
            print(f"  stderr: {result.stderr[:500]}")
            return None, None
        
        # Extract HPWL from output
        output = result.stdout + result.stderr
        hpwl_match = re.search(r'Best HPWL cost:\s+([\d.]+)', output)
        if not hpwl_match:
            print(f"[ERROR] Could not extract HPWL from output")
            return None, None
        
        hpwl = float(hpwl_match.group(1))
        return runtime, hpwl
        
    except subprocess.TimeoutExpired:
        print(f"[ERROR] SA timed out after 1 hour")
        return None, None
    except Exception as e:
        print(f"[ERROR] Exception running SA: {e}")
        return None, None


def generate_parameter_combinations() -> List[Dict]:
    """
    Generate a comprehensive set of parameter combinations to test.
    
    This creates a systematic exploration of the parameter space with:
    - Expanded ranges for all key parameters
    - More granular steps for better coverage
    - Variations in W_initial and beta as well
    
    Returns list of parameter dicts.
    """
    # Fixed parameters
    T_initial = 3000000.0
    moves_per_temp = 1000
    
    # Expanded parameter ranges for comprehensive analysis
    num_temp_steps_values = [30, 40, 50, 60, 70, 80]
    alpha_values = [0.80, 0.85, 0.90, 0.92, 0.95, 0.97, 0.99]
    P_refine_values = [0.3, 0.5, 0.7, 0.8, 0.9]
    W_initial_values = [0.3, 0.5, 0.7, 0.8]
    beta_values = [0.90, 0.92, 0.95, 0.97, 0.99]
    
    # Generate comprehensive combinations
    # Strategy: Create a focused grid that covers key interactions
    combinations = []
    
    # 1. Baseline and alpha sweep (most important parameter)
    for alpha in alpha_values:
        combinations.append({
            "num_temp_steps": 50,
            "alpha": alpha,
            "P_refine": 0.7,
            "W_initial": 0.5,
            "beta": 0.95,
        })
    
    # 2. num_temp_steps sweep
    for num_temp_steps in num_temp_steps_values:
        if num_temp_steps != 50:  # Avoid duplicate with baseline
            combinations.append({
                "num_temp_steps": num_temp_steps,
                "alpha": 0.85,
                "P_refine": 0.7,
                "W_initial": 0.5,
                "beta": 0.95,
            })
    
    # 3. P_refine sweep
    for P_refine in P_refine_values:
        if P_refine != 0.7:  # Avoid duplicate with baseline
            combinations.append({
                "num_temp_steps": 50,
                "alpha": 0.85,
                "P_refine": P_refine,
                "W_initial": 0.5,
                "beta": 0.95,
            })
    
    # 4. W_initial sweep
    for W_initial in W_initial_values:
        if W_initial != 0.5:  # Avoid duplicate with baseline
            combinations.append({
                "num_temp_steps": 50,
                "alpha": 0.85,
                "P_refine": 0.7,
                "W_initial": W_initial,
                "beta": 0.95,
            })
    
    # 5. beta sweep
    for beta in beta_values:
        if beta != 0.95:  # Avoid duplicate with baseline
            combinations.append({
                "num_temp_steps": 50,
                "alpha": 0.85,
                "P_refine": 0.7,
                "W_initial": 0.5,
                "beta": beta,
            })
    
    # 6. Key interaction combinations (alpha × num_temp_steps)
    for alpha in [0.80, 0.90, 0.95, 0.99]:
        for num_temp_steps in [30, 50, 70]:
            if not (alpha == 0.85 and num_temp_steps == 50):  # Avoid baseline duplicate
                combinations.append({
                    "num_temp_steps": num_temp_steps,
                    "alpha": alpha,
                    "P_refine": 0.7,
                    "W_initial": 0.5,
                    "beta": 0.95,
                })
    
    # 7. Key interaction combinations (alpha × P_refine)
    for alpha in [0.80, 0.90, 0.95, 0.99]:
        for P_refine in [0.5, 0.7, 0.9]:
            if not (alpha == 0.85 and P_refine == 0.7):  # Avoid baseline duplicate
                combinations.append({
                    "num_temp_steps": 50,
                    "alpha": alpha,
                    "P_refine": P_refine,
                    "W_initial": 0.5,
                    "beta": 0.95,
                })
    
    # 8. num_temp_steps × P_refine interactions
    for num_temp_steps in [30, 50, 70]:
        for P_refine in [0.5, 0.7, 0.9]:
            if not (num_temp_steps == 50 and P_refine == 0.7):  # Avoid baseline duplicate
                combinations.append({
                    "num_temp_steps": num_temp_steps,
                    "alpha": 0.85,
                    "P_refine": P_refine,
                    "W_initial": 0.5,
                    "beta": 0.95,
                })
    
    # 9. Extended alpha × num_temp_steps (more coverage)
    for alpha in [0.80, 0.85, 0.90, 0.95, 0.99]:
        for num_temp_steps in [30, 40, 60, 70, 80]:
            if not (alpha == 0.85 and num_temp_steps == 50):  # Avoid baseline duplicate
                combinations.append({
                    "num_temp_steps": num_temp_steps,
                    "alpha": alpha,
                    "P_refine": 0.7,
                    "W_initial": 0.5,
                    "beta": 0.95,
                })
    
    # 10. Extended alpha × P_refine (more coverage)
    for alpha in [0.80, 0.85, 0.90, 0.95, 0.99]:
        for P_refine in [0.3, 0.5, 0.7, 0.8, 0.9]:
            if not (alpha == 0.85 and P_refine == 0.7):  # Avoid baseline duplicate
                combinations.append({
                    "num_temp_steps": 50,
                    "alpha": alpha,
                    "P_refine": P_refine,
                    "W_initial": 0.5,
                    "beta": 0.95,
                })
    
    # 11. 3-way interactions: alpha × num_temp_steps × P_refine (key combinations)
    for alpha in [0.80, 0.90, 0.95, 0.99]:
        for num_temp_steps in [30, 50, 70]:
            for P_refine in [0.5, 0.7, 0.9]:
                if not (alpha == 0.85 and num_temp_steps == 50 and P_refine == 0.7):  # Avoid baseline
                    combinations.append({
                        "num_temp_steps": num_temp_steps,
                        "alpha": alpha,
                        "P_refine": P_refine,
                        "W_initial": 0.5,
                        "beta": 0.95,
                    })
    
    # 12. W_initial × beta interactions
    for W_initial in [0.3, 0.5, 0.7, 0.8]:
        for beta in [0.90, 0.95, 0.99]:
            if not (W_initial == 0.5 and beta == 0.95):  # Avoid baseline duplicate
                combinations.append({
                    "num_temp_steps": 50,
                    "alpha": 0.85,
                    "P_refine": 0.7,
                    "W_initial": W_initial,
                    "beta": beta,
                })
    
    # Remove duplicates (keep first occurrence)
    seen = set()
    unique_combinations = []
    for combo in combinations:
        key = (combo["num_temp_steps"], combo["alpha"], combo["P_refine"], 
               combo["W_initial"], combo["beta"])
        if key not in seen:
            seen.add(key)
            unique_combinations.append(combo)
    
    return unique_combinations


def find_pareto_frontier(results: List[Dict]) -> List[Dict]:
    """
    Find Pareto-optimal points (best HPWL for given runtime, or fastest for given HPWL).
    
    A point is Pareto-optimal if there's no other point that is:
    - Better in HPWL AND better or equal in runtime, OR
    - Better in runtime AND better or equal in HPWL
    """
    valid_results = [r for r in results if r["hpwl"] is not None and r["runtime"] is not None]
    if not valid_results:
        return []
    
    pareto = []
    for point in valid_results:
        is_pareto = True
        for other in valid_results:
            if point == other:
                continue
            # Check if other point dominates this one
            if (other["hpwl"] < point["hpwl"] and other["runtime"] <= point["runtime"]) or \
               (other["hpwl"] <= point["hpwl"] and other["runtime"] < point["runtime"]):
                is_pareto = False
                break
        if is_pareto:
            pareto.append(point)
    
    # Sort by runtime
    pareto.sort(key=lambda x: x["runtime"])
    return pareto


def plot_results(results: List[Dict], output_path: str, design: str) -> None:
    """
    Generate scatter plot: Runtime vs HPWL
    """
    valid_results = [r for r in results if r["hpwl"] is not None and r["runtime"] is not None]
    if not valid_results:
        print("[WARN] No valid results to plot")
        return
    
    pareto = find_pareto_frontier(valid_results)
    
    # Extract data
    runtimes = [r["runtime"] for r in valid_results]
    hpwls = [r["hpwl"] for r in valid_results]
    pareto_runtimes = [r["runtime"] for r in pareto]
    pareto_hpwls = [r["hpwl"] for r in pareto]
    
    # Create plot
    plt.figure(figsize=(12, 8))
    
    # Plot all points
    plt.scatter(runtimes, hpwls, alpha=0.6, s=50, label="All experiments", color="lightblue")
    
    # Plot Pareto frontier
    if pareto:
        pareto_runtimes_sorted, pareto_hpwls_sorted = zip(*sorted(zip(pareto_runtimes, pareto_hpwls)))
        plt.plot(pareto_runtimes_sorted, pareto_hpwls_sorted, 'r-', linewidth=2, label="Pareto frontier")
        plt.scatter(pareto_runtimes, pareto_hpwls, s=150, color="red", marker="*", 
                   label="Pareto-optimal points", zorder=5)
    
    # Find and highlight best points
    if valid_results:
        best_hpwl = min(valid_results, key=lambda x: x["hpwl"])
        fastest = min(valid_results, key=lambda x: x["runtime"])
        
        plt.scatter([best_hpwl["runtime"]], [best_hpwl["hpwl"]], 
                   s=200, color="green", marker="o", label="Best HPWL", zorder=6)
        plt.scatter([fastest["runtime"]], [fastest["hpwl"]], 
                   s=200, color="orange", marker="s", label="Fastest", zorder=6)
    
    plt.xlabel("Runtime (seconds)", fontsize=12)
    plt.ylabel("Final HPWL (μm)", fontsize=12)
    plt.title(f"SA Knob Analysis: {design.upper()}\nRuntime vs HPWL Quality", fontsize=14, fontweight="bold")
    plt.legend(loc="best")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    
    # Save
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    print(f"[INFO] Plot saved to: {output_path}")
    plt.close()


def save_results_csv(results: List[Dict], output_path: str) -> None:
    """Save results to CSV file."""
    if not results:
        return
    
    fieldnames = [
        "num_temp_steps", "alpha", "P_refine", "W_initial", "beta",
        "runtime", "hpwl", "status"
    ]
    
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow({
                "num_temp_steps": r["num_temp_steps"],
                "alpha": r["alpha"],
                "P_refine": r["P_refine"],
                "W_initial": r["W_initial"],
                "beta": r["beta"],
                "runtime": r.get("runtime", ""),
                "hpwl": r.get("hpwl", ""),
                "status": "success" if r.get("hpwl") is not None else "failed",
            })
    
    print(f"[INFO] Results saved to: {output_path}")


def print_summary(results: List[Dict], pareto: List[Dict]) -> None:
    """Print summary statistics."""
    valid_results = [r for r in results if r["hpwl"] is not None and r["runtime"] is not None]
    if not valid_results:
        print("\n[SUMMARY] No valid results to summarize")
        return
    
    print("\n" + "="*80)
    print("SA KNOB ANALYSIS SUMMARY")
    print("="*80)
    
    print(f"\nTotal experiments: {len(results)}")
    print(f"Successful: {len(valid_results)}")
    print(f"Failed: {len(results) - len(valid_results)}")
    
    if valid_results:
        best_hpwl = min(valid_results, key=lambda x: x["hpwl"])
        fastest = min(valid_results, key=lambda x: x["runtime"])
        
        print(f"\n{'='*80}")
        print("BEST HPWL (Lowest Wirelength):")
        print(f"  HPWL: {best_hpwl['hpwl']:.3f} μm")
        print(f"  Runtime: {best_hpwl['runtime']:.2f} seconds")
        print(f"  Parameters:")
        print(f"    num_temp_steps: {best_hpwl['num_temp_steps']}")
        print(f"    alpha: {best_hpwl['alpha']}")
        print(f"    P_refine: {best_hpwl['P_refine']}")
        print(f"    W_initial: {best_hpwl['W_initial']}")
        print(f"    beta: {best_hpwl['beta']}")
        
        print(f"\n{'='*80}")
        print("FASTEST (Shortest Runtime):")
        print(f"  Runtime: {fastest['runtime']:.2f} seconds")
        print(f"  HPWL: {fastest['hpwl']:.3f} μm")
        print(f"  Parameters:")
        print(f"    num_temp_steps: {fastest['num_temp_steps']}")
        print(f"    alpha: {fastest['alpha']}")
        print(f"    P_refine: {fastest['P_refine']}")
        print(f"    W_initial: {fastest['W_initial']}")
        print(f"    beta: {fastest['beta']}")
        
        if pareto:
            print(f"\n{'='*80}")
            print(f"PARETO FRONTIER ({len(pareto)} points):")
            print("  (Points that are optimal trade-offs between runtime and HPWL)")
            for i, point in enumerate(pareto[:5], 1):  # Show top 5
                print(f"\n  Point {i}:")
                print(f"    HPWL: {point['hpwl']:.3f} μm, Runtime: {point['runtime']:.2f} s")
                print(f"    num_temp_steps: {point['num_temp_steps']}, alpha: {point['alpha']}, "
                      f"P_refine: {point['P_refine']}, W_initial: {point['W_initial']}, beta: {point['beta']}")
            if len(pareto) > 5:
                print(f"\n  ... and {len(pareto) - 5} more Pareto-optimal points")
    
    print("\n" + "="*80)


def main():
    parser = argparse.ArgumentParser(
        description="Run SA knob analysis to find best parameters"
    )
    parser.add_argument(
        "--design",
        type=str,
        default="arith",
        help="Design name (default: arith)",
    )
    parser.add_argument(
        "--resume",
        type=str,
        help="Resume from existing CSV file (skip already-run experiments)",
    )
    parser.add_argument(
        "--max-experiments",
        type=int,
        help="Maximum number of experiments to run (for testing)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed (default: 42)",
    )
    
    args = parser.parse_args()
    
    design = args.design
    base_dir = Path(__file__).parent.parent
    build_dir = base_dir / "build" / design
    
    # Paths
    data_structures = build_dir / "data_structures.json"
    initial_map = build_dir / f"{design}.map"
    out_map_template = build_dir / f"{design}_sa_analysis_{{exp_id}}.map"
    results_csv = build_dir / "sa_analysis_results.csv"
    plot_png = build_dir / "sa_knob_analysis.png"
    
    # Check inputs exist
    if not data_structures.exists():
        print(f"[ERROR] Data structures not found: {data_structures}")
        sys.exit(1)
    if not initial_map.exists():
        print(f"[ERROR] Initial map not found: {initial_map}")
        sys.exit(1)
    
    # Load existing results if resuming
    existing_results = []
    if args.resume and Path(args.resume).exists():
        print(f"[INFO] Resuming from: {args.resume}")
        with open(args.resume, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("status") == "success":
                    existing_results.append({
                        "num_temp_steps": int(row["num_temp_steps"]),
                        "alpha": float(row["alpha"]),
                        "P_refine": float(row["P_refine"]),
                        "W_initial": float(row["W_initial"]),
                        "beta": float(row["beta"]),
                        "runtime": float(row["runtime"]) if row["runtime"] else None,
                        "hpwl": float(row["hpwl"]) if row["hpwl"] else None,
                    })
        print(f"[INFO] Loaded {len(existing_results)} existing results")
    
    # Generate parameter combinations
    all_combinations = generate_parameter_combinations()
    print(f"[INFO] Total parameter combinations: {len(all_combinations)}")
    
    # Filter out already-run combinations if resuming
    if existing_results:
        existing_keys = {
            (r["num_temp_steps"], r["alpha"], r["P_refine"], r["W_initial"], r["beta"])
            for r in existing_results
        }
        all_combinations = [
            c for c in all_combinations
            if (c["num_temp_steps"], c["alpha"], c["P_refine"], c["W_initial"], c["beta"]) not in existing_keys
        ]
        print(f"[INFO] Remaining combinations to test: {len(all_combinations)}")
    
    # Limit if requested
    if args.max_experiments:
        all_combinations = all_combinations[:args.max_experiments]
        print(f"[INFO] Limited to {len(all_combinations)} experiments")
    
    # Run experiments
    results = list(existing_results)  # Start with existing
    total = len(all_combinations)
    
    print(f"\n[INFO] Starting {total} SA experiments...")
    print(f"[INFO] Fixed: T_initial=3,000,000, moves_per_temp=1000")
    print(f"[INFO] Design: {design}\n")
    
    for exp_id, params in enumerate(all_combinations, 1):
        out_map = str(out_map_template).format(exp_id=exp_id)
        
        print(f"[{exp_id}/{total}] Testing: "
              f"steps={params['num_temp_steps']}, alpha={params['alpha']}, "
              f"P_refine={params['P_refine']}, W_init={params['W_initial']}, beta={params['beta']}")
        
        runtime, hpwl = run_sa_experiment(
            design=design,
            data_structures=str(data_structures),
            initial_map=str(initial_map),
            out_map=out_map,
            num_temp_steps=params["num_temp_steps"],
            alpha=params["alpha"],
            P_refine=params["P_refine"],
            W_initial=params["W_initial"],
            beta=params["beta"],
            seed=args.seed,
        )
        
        result = {
            **params,
            "runtime": runtime,
            "hpwl": hpwl,
        }
        results.append(result)
        
        if runtime is not None and hpwl is not None:
            print(f"         ✓ Success: HPWL={hpwl:.3f} μm, Runtime={runtime:.2f} s")
        else:
            print(f"         ✗ Failed")
        
        # Save intermediate results every 10 experiments
        if exp_id % 10 == 0:
            save_results_csv(results, str(results_csv))
            print(f"         [Saved intermediate results]")
    
    # Final save and analysis
    print("\n[INFO] All experiments complete. Generating analysis...")
    save_results_csv(results, str(results_csv))
    
    pareto = find_pareto_frontier(results)
    plot_results(results, str(plot_png), design)
    print_summary(results, pareto)
    
    print(f"\n[INFO] Analysis complete!")
    print(f"  Results CSV: {results_csv}")
    print(f"  Plot PNG: {plot_png}")


if __name__ == "__main__":
    main()
