#!/usr/bin/env python3
"""
SA Knob Analysis Script

Runs simulated annealing with different parameter settings and generates
a scatter plot showing the trade-off between runtime and HPWL quality.

This script explores the "Pareto frontier" of SA knob settings.
"""

import argparse
import json
import os
import shutil
import subprocess
import time
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt
import numpy as np


def load_json(path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_sa_experiment(
    data_structures: str,
    initial_map: str,
    out_map: str,
    num_temp_steps: int,
    moves_per_temp: int,
    T_initial: float,
    alpha: float,
    P_refine: float,
    W_initial: float,
    beta: float,
    seed: int = 0,
) -> Tuple[float, float]:
    """
    Run one SA experiment and return (runtime_seconds, final_hpwl).
    
    Returns:
        (runtime_seconds, final_hpwl_um)
    """
    cmd = [
        "python3", "src/simulated_annealing.py",
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
        "--report-interval", "1000",  # Show progress every 1000 moves
    ]
    
    start_time = time.time()
    
    try:
        # Run SA and show output in real-time while capturing it
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # Line buffered
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        
        # Read output line by line and display it
        stdout_lines = []
        hpwl = None
        for line in process.stdout:
            stdout_lines.append(line)
            print(line, end='')  # Print in real-time
            # Also try to parse HPWL as we go
            if "Final Total HPWL:" in line:
                parts = line.split()
                for i, part in enumerate(parts):
                    if part == "HPWL:" and i + 1 < len(parts):
                        hpwl_str = parts[i + 1]
                        try:
                            hpwl = float(hpwl_str)
                            break
                        except ValueError:
                            pass
        
        process.wait()
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, cmd)
        
        runtime = time.time() - start_time
        
        # Parse HPWL from output if not already found
        if hpwl is None:
            for line in stdout_lines:
                if "Final Total HPWL:" in line:
                # Extract number
                parts = line.split()
                for i, part in enumerate(parts):
                    if part == "HPWL:" and i + 1 < len(parts):
                        hpwl_str = parts[i + 1]
                        try:
                            hpwl = float(hpwl_str)
                            break
                        except ValueError:
                            pass
        
        if hpwl is None:
            # Fallback: look for "Best HPWL cost:"
            for line in stdout_lines:
                if "Best HPWL cost:" in line:
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if part == "cost:" and i + 1 < len(parts):
                            hpwl_str = parts[i + 1]
                            try:
                                hpwl = float(hpwl_str)
                                break
                            except ValueError:
                                pass
        
        if hpwl is None:
            raise ValueError(f"Could not parse HPWL from SA output")
        
        return runtime, hpwl
        
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] SA experiment failed:")
        print(f"  Command: {' '.join(cmd)}")
        print(f"  Return code: {e.returncode}")
        print(f"  Stderr: {e.stderr}")
        raise


def generate_knob_experiments(
    base_num_temp_steps: int = 60,
    base_moves_per_temp: int = 1000,
    base_T_initial: float = 200.0,
    base_alpha: float = 0.95,
    base_P_refine: float = 0.7,
    base_W_initial: float = 0.5,
    base_beta: float = 0.95,
) -> List[Dict]:
    """
    Generate a list of experiment configurations to test.
    Reduced to 8 experiments covering key parameter variations.
    
    Returns:
        List of experiment dicts with all parameters
    """
    experiments = []
    
    # Experiment 1-3: Vary cooling rate (alpha) - most important parameter
    for alpha in [0.80, 0.90, 0.98]:
        experiments.append({
            "name": f"alpha={alpha:.2f}",
            "num_temp_steps": base_num_temp_steps,
            "moves_per_temp": base_moves_per_temp,
            "T_initial": base_T_initial,
            "alpha": alpha,
            "P_refine": base_P_refine,
            "W_initial": base_W_initial,
            "beta": base_beta,
        })
    
    # Experiment 4-5: Vary moves per temperature
    for moves_per_temp in [500, 1500]:
        experiments.append({
            "name": f"moves_per_temp={moves_per_temp}",
            "num_temp_steps": base_num_temp_steps,
            "moves_per_temp": moves_per_temp,
            "T_initial": base_T_initial,
            "alpha": base_alpha,
            "P_refine": base_P_refine,
            "W_initial": base_W_initial,
            "beta": base_beta,
        })
    
    # Experiment 6-7: Vary number of temperature steps
    for num_temp_steps in [30, 90]:
        experiments.append({
            "name": f"num_temp_steps={num_temp_steps}",
            "num_temp_steps": num_temp_steps,
            "moves_per_temp": base_moves_per_temp,
            "T_initial": base_T_initial,
            "alpha": base_alpha,
            "P_refine": base_P_refine,
            "W_initial": base_W_initial,
            "beta": base_beta,
        })
    
    # Experiment 8: Vary initial temperature (one extreme)
    experiments.append({
        "name": f"T_initial={300.0:.0f}",
        "num_temp_steps": base_num_temp_steps,
        "moves_per_temp": base_moves_per_temp,
        "T_initial": 300.0,
        "alpha": base_alpha,
        "P_refine": base_P_refine,
        "W_initial": base_W_initial,
        "beta": base_beta,
    })
    
    return experiments


def plot_knob_analysis(
    results: List[Tuple[str, float, float, str]],
    out_path: str,
    design_name: str,
) -> None:
    """
    Generate scatter plot of Runtime vs HPWL.
    
    Args:
        results: List of (experiment_name, runtime_sec, hpwl_um) tuples
        out_path: Output PNG path
        design_name: Design name for title
    """
    if not results:
        print("[WARN] No results to plot")
        return
    
    names, runtimes, hpwls, temp_maps = zip(*results)
    
    # Convert to arrays
    runtimes = np.array(runtimes)
    hpwls = np.array(hpwls)
    
    # Create figure
    fig, ax = plt.subplots(figsize=(12, 8))
    
    # Scatter plot
    scatter = ax.scatter(
        runtimes,
        hpwls,
        s=100,
        alpha=0.6,
        c=range(len(runtimes)),
        cmap='viridis',
        edgecolors='black',
        linewidths=1.5
    )
    
    # Find Pareto frontier (points that are not dominated)
    # A point is on the Pareto frontier if no other point has both
    # lower runtime AND lower HPWL
    pareto_indices = []
    for i in range(len(results)):
        is_pareto = True
        for j in range(len(results)):
            if i != j:
                # j dominates i if j has both lower runtime and lower HPWL
                if runtimes[j] < runtimes[i] and hpwls[j] < hpwls[i]:
                    is_pareto = False
                    break
        if is_pareto:
            pareto_indices.append(i)
    
    # Highlight Pareto frontier
    if pareto_indices:
        pareto_runtimes = runtimes[pareto_indices]
        pareto_hpwls = hpwls[pareto_indices]
        
        # Sort by runtime for line drawing
        sort_idx = np.argsort(pareto_runtimes)
        pareto_runtimes = pareto_runtimes[sort_idx]
        pareto_hpwls = pareto_hpwls[sort_idx]
        
        ax.plot(
            pareto_runtimes,
            pareto_hpwls,
            'r--',
            linewidth=2,
            alpha=0.7,
            label='Pareto Frontier'
        )
        
        # Highlight Pareto points
        ax.scatter(
            pareto_runtimes,
            pareto_hpwls,
            s=150,
            facecolors='none',
            edgecolors='red',
            linewidths=2.5,
            label='Pareto Optimal'
        )
    
    # Find best HPWL and fastest runtime
    best_hpwl_idx = np.argmin(hpwls)
    fastest_idx = np.argmin(runtimes)
    
    # Annotate best HPWL point
    ax.annotate(
        f'Best HPWL\n{names[best_hpwl_idx]}\n{hpwls[best_hpwl_idx]:.2f} µm',
        xy=(runtimes[best_hpwl_idx], hpwls[best_hpwl_idx]),
        xytext=(10, 10),
        textcoords='offset points',
        bbox=dict(boxstyle='round,pad=0.5', facecolor='green', alpha=0.7),
        arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0'),
        fontsize=9
    )
    
    # Annotate fastest point
    ax.annotate(
        f'Fastest\n{names[fastest_idx]}\n{runtimes[fastest_idx]:.1f}s',
        xy=(runtimes[fastest_idx], hpwls[fastest_idx]),
        xytext=(10, -30),
        textcoords='offset points',
        bbox=dict(boxstyle='round,pad=0.5', facecolor='blue', alpha=0.7),
        arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0'),
        fontsize=9
    )
    
    # Labels and title
    ax.set_xlabel('Runtime (seconds)', fontsize=12, fontweight='bold')
    ax.set_ylabel('Final HPWL (µm)', fontsize=12, fontweight='bold')
    ax.set_title(
        f'{design_name} - SA Knob Analysis: Runtime vs HPWL\n'
        f'Total Experiments: {len(results)}',
        fontsize=14,
        fontweight='bold'
    )
    
    # Grid
    ax.grid(True, alpha=0.3, linestyle='--')
    
    # Legend
    ax.legend(loc='best', fontsize=10)
    
    # Statistics text
    stats_text = (
        f'Best HPWL: {np.min(hpwls):.2f} µm\n'
        f'Worst HPWL: {np.max(hpwls):.2f} µm\n'
        f'Fastest: {np.min(runtimes):.1f} s\n'
        f'Slowest: {np.max(runtimes):.1f} s\n'
        f'Pareto Points: {len(pareto_indices)}'
    )
    
    ax.text(
        0.02, 0.98, stats_text,
        transform=ax.transAxes,
        verticalalignment='top',
        bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8),
        fontsize=10,
        family='monospace'
    )
    
    plt.tight_layout()
    os.makedirs(os.path.dirname(out_path), exist_ok=True) if os.path.dirname(out_path) else None
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    print(f"[INFO] Saved knob analysis plot to '{out_path}'")
    plt.close()


def main():
    parser = argparse.ArgumentParser(
        description="Run SA knob experiments and generate analysis plot"
    )
    parser.add_argument(
        "--design",
        required=True,
        help="Design name (e.g., '6502')"
    )
    parser.add_argument(
        "--data-structures",
        help="Path to data_structures.json (default: build/<design>/data_structures.json)"
    )
    parser.add_argument(
        "--initial-map",
        help="Path to initial greedy map (default: build/<design>/<design>.map)"
    )
    parser.add_argument(
        "--out-plot",
        help="Output path for analysis plot (default: build/<design>/sa_knob_analysis.png)"
    )
    parser.add_argument(
        "--max-experiments",
        type=int,
        default=None,
        help="Maximum number of experiments to run (default: all)"
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42)"
    )
    
    args = parser.parse_args()
    
    # Set defaults
    if args.data_structures is None:
        args.data_structures = f"build/{args.design}/data_structures.json"
    if args.initial_map is None:
        args.initial_map = f"build/{args.design}/{args.design}.map"
    if args.out_plot is None:
        args.out_plot = f"build/{args.design}/sa_knob_analysis.png"
    
    # Check files exist
    if not os.path.exists(args.data_structures):
        raise FileNotFoundError(f"Data structures file not found: {args.data_structures}")
    if not os.path.exists(args.initial_map):
        raise FileNotFoundError(f"Initial map file not found: {args.initial_map}")
    
    # Generate experiments
    print("[INFO] Generating experiment configurations...")
    experiments = generate_knob_experiments()
    
    if args.max_experiments:
        experiments = experiments[:args.max_experiments]
    
    print(f"[INFO] Running {len(experiments)} SA experiments...")
    
    # Run experiments
    results = []
    temp_map_dir = f"build/{args.design}/sa_temp"
    os.makedirs(temp_map_dir, exist_ok=True)
    
    for i, exp in enumerate(experiments, 1):
        print(f"\n[EXPERIMENT {i}/{len(experiments)}] {exp['name']}")
        print(f"  Parameters: alpha={exp['alpha']:.2f}, moves_per_temp={exp['moves_per_temp']}, "
              f"T_initial={exp['T_initial']:.0f}, num_temp_steps={exp['num_temp_steps']}")
        print(f"  Running SA...", end=" ", flush=True)
        
        temp_map = os.path.join(temp_map_dir, f"temp_{i}.map")
        
        try:
            runtime, hpwl = run_sa_experiment(
                data_structures=args.data_structures,
                initial_map=args.initial_map,
                out_map=temp_map,
                num_temp_steps=exp['num_temp_steps'],
                moves_per_temp=exp['moves_per_temp'],
                T_initial=exp['T_initial'],
                alpha=exp['alpha'],
                P_refine=exp['P_refine'],
                W_initial=exp['W_initial'],
                beta=exp['beta'],
                seed=args.seed,
            )
            
            results.append((exp['name'], runtime, hpwl, temp_map))  # Store temp_map path
            print(f"✓ Done! Runtime: {runtime:.2f}s, HPWL: {hpwl:.2f} µm")
            
        except Exception as e:
            print(f"  ✗ Failed: {e}")
            continue
    
    if not results:
        print("[ERROR] No successful experiments!")
        return
    
    # Find best HPWL map
    if results:
        runtimes_list = [r[1] for r in results]
        hpwls_list = [r[2] for r in results]
        temp_maps_list = [r[3] for r in results]
        
        best_hpwl_idx = hpwls_list.index(min(hpwls_list))
        best_map_path = temp_maps_list[best_hpwl_idx]
        best_hpwl_value = hpwls_list[best_hpwl_idx]
        best_experiment_name = results[best_hpwl_idx][0]
        
        # Save best map to a named file
        best_map_output = f"build/{args.design}/{args.design}_best_hpwl.map"
        shutil.copy2(best_map_path, best_map_output)
        print(f"\n[INFO] Best HPWL map saved: {best_map_output}")
        print(f"  Experiment: {best_experiment_name}")
        print(f"  HPWL: {best_hpwl_value:.2f} µm")
    
    # Generate plot
    print(f"\n[INFO] Generating analysis plot...")
    plot_knob_analysis(results, args.out_plot, args.design)
    
    # Print summary
    print(f"\n[SUMMARY]")
    print(f"  Successful experiments: {len(results)}/{len(experiments)}")
    if results:
        runtimes = [r[1] for r in results]
        hpwls = [r[2] for r in results]
        print(f"  Best HPWL: {min(hpwls):.2f} µm")
        print(f"  Fastest runtime: {min(runtimes):.2f} s")
        print(f"  Plot saved to: {args.out_plot}")
        print(f"  Best HPWL map: build/{args.design}/{args.design}_best_hpwl.map")
    
    print("[INFO] Done.")


if __name__ == "__main__":
    main()

