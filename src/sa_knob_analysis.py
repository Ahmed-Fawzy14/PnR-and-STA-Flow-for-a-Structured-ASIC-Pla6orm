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
    sa_script: str,
    seed: int = 0,
) -> Tuple[float, float]:
    """
    Run one SA experiment and return (runtime_seconds, final_hpwl).
    
    Returns:
        (runtime_seconds, final_hpwl_um)
    """
    cmd = [
        "python3", sa_script,
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
    base_alpha: float = 0.95,
    base_P_refine: float = 0.7,
    base_W_initial: float = 0.5,
    base_beta: float = 0.95,
    preset: str = "full",
) -> List[Dict]:
    """
    Generate experiment configurations for T_initial=4,000,000 with cooling schedule
    that cools fast initially and slow at the end.
    
    Strategy:
        - T_initial = 4,000,000 (fixed)
        - Use higher alpha values (0.95-0.99) for slower overall cooling, which
          naturally creates fast cooling at high T and slow cooling at low T
        - Vary num_temp_steps to allow more exploration
        - Vary other parameters to find optimal combination
    
    Note: moves_per_temp is fixed at 1000 for all experiments.
    
    Returns:
        List of experiment dicts with all parameters
    """
    BASE_MOVES_PER_TEMP = 1000
    T_INITIAL = 4000000.0
    
    experiments: List[Dict] = []
 
    # Keep runtime reasonable by restricting temperature steps to {60, 150}
    # while holding T_initial=4,000,000 and moves_per_temp=1000 fixed.
    schedule_points = [
        # (num_temp_steps, alpha)
        (60, 0.80),
        (60, 0.90),
        (150, 0.80),
        (150, 0.95),
        (150, 0.97),
    ]
 
    prefine_values = [0.5, 0.7, 0.9]
    window_points = [
        # (W_initial, beta)
        (0.3, 0.90),
        (0.5, 0.95),
        (0.7, 0.98),
    ]

    if preset not in ("small", "medium", "full"):
        raise ValueError(f"Unknown preset: {preset!r}")

    if preset == "small":
        # 12 experiments = 2 schedules * 2 P_refine * 3 window settings
        schedule_points = [
            (60, 0.80),
            (60, 0.85),
            (60, 0.90),
            (150, 0.80),
            (150, 0.97),
        ]
        prefine_values = [0.7, 0.9]

    if preset == "medium":
        # 24 experiments = 2 schedules * 3 P_refine * 4 window settings
        schedule_points = [
            (60, 0.80),
            (150, 0.97),
        ]
        prefine_values = [0.5, 0.7, 0.9]
        window_points = [
            (0.3, 0.90),
            (0.5, 0.95),
            (0.7, 0.98),
            (0.5, 0.98),
        ]
 
    for num_temp_steps, alpha in schedule_points:
        for P_refine in prefine_values:
            for W_initial, beta in window_points:
                experiments.append({
                    "name": f"T4M_steps={num_temp_steps}_alpha={alpha:.2f}_Prefine={P_refine:.1f}_W={W_initial:.1f}_beta={beta:.2f}",
                    "num_temp_steps": num_temp_steps,
                    "moves_per_temp": BASE_MOVES_PER_TEMP,
                    "T_initial": T_INITIAL,
                    "alpha": alpha,
                    "P_refine": P_refine,
                    "W_initial": W_initial,
                    "beta": beta,
                })

    # Explicit best-parameter experiments at higher num_temp_steps (added without expanding the full sweep).
    explicit_best_experiments = [
        {
            "name": "T4M_steps=250_alpha=0.80_Prefine=0.9_W=0.3_beta=0.90",
            "num_temp_steps": 250,
            "moves_per_temp": BASE_MOVES_PER_TEMP,
            "T_initial": T_INITIAL,
            "alpha": 0.80,
            "P_refine": 0.90,
            "W_initial": 0.30,
            "beta": 0.90,
        },
        {
            "name": "T4M_steps=350_alpha=0.80_Prefine=0.9_W=0.3_beta=0.90",
            "num_temp_steps": 350,
            "moves_per_temp": BASE_MOVES_PER_TEMP,
            "T_initial": T_INITIAL,
            "alpha": 0.80,
            "P_refine": 0.90,
            "W_initial": 0.30,
            "beta": 0.90,
        },
        {
            "name": "T4M_steps=500_alpha=0.80_Prefine=0.9_W=0.3_beta=0.90",
            "num_temp_steps": 500,
            "moves_per_temp": BASE_MOVES_PER_TEMP,
            "T_initial": T_INITIAL,
            "alpha": 0.80,
            "P_refine": 0.90,
            "W_initial": 0.30,
            "beta": 0.90,
        },
    ]

    for exp in explicit_best_experiments:
        if all(existing.get("name") != exp["name"] for existing in experiments):
            experiments.append(exp)

    extra_exp = {
        "name": "T4M_steps=250_alpha=0.97_Prefine=0.7_W=0.7_beta=0.98",
        "num_temp_steps": 250,
        "moves_per_temp": BASE_MOVES_PER_TEMP,
        "T_initial": T_INITIAL,
        "alpha": 0.97,
        "P_refine": 0.70,
        "W_initial": 0.70,
        "beta": 0.98,
    }

    if all(exp.get("name") != extra_exp["name"] for exp in experiments):
        experiments.append(extra_exp)
 
    return experiments


def save_results_to_file(
    results: List[Tuple[str, float, float, float, str]],
    experiments: List[Dict],
    out_path: str,
    design_name: str,
) -> None:
    """
    Save comprehensive results to a text file and CSV file.
    
    Args:
        results: List of (experiment_name, runtime_mean_sec, hpwl_best_um, runtime_best_hpwl_sec, best_map_path) tuples
        experiments: List of experiment configuration dicts
        out_path: Base output path (will create .txt and .csv versions)
        design_name: Design name for header
    """
    import csv
    from datetime import datetime
    
    # Create output directory if needed
    os.makedirs(os.path.dirname(out_path), exist_ok=True) if os.path.dirname(out_path) else None
    
    # Text summary file
    txt_path = out_path.replace('.png', '_results.txt') if out_path.endswith('.png') else out_path + '_results.txt'
    
    # CSV file path (needed for writing to text file)
    csv_path = out_path.replace('.png', '_results.csv') if out_path.endswith('.png') else out_path + '_results.csv'
    
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(f"{'='*80}\n")
        f.write(f"SA KNOB ANALYSIS RESULTS - {design_name}\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"{'='*80}\n\n")
        
        f.write(f"Experiment Strategy:\n")
        f.write(f"  Focus: T_initial=4,000,000 with cooling schedule optimization\n")
        f.write(f"  Goal: Fast cooling at beginning, slow cooling at end\n")
        f.write(f"  Strategy:\n")
        f.write(f"    - T_initial: 4,000,000 (fixed)\n")
        f.write(f"    - Higher alpha values (0.90-0.99) for slower overall cooling\n")
        f.write(f"    - Vary num_temp_steps (60, 90, 120, 150) for more exploration\n")
        f.write(f"    - Vary P_refine, W_initial, and beta to find optimal combination\n")
        f.write(f"  moves_per_temp: 1000 (fixed - constant)\n")
        f.write(f"  Baseline values (when not varied):\n")
        f.write(f"    alpha: 0.97\n")
        f.write(f"    num_temp_steps: 60\n")
        f.write(f"    P_refine: 0.7\n")
        f.write(f"    W_initial: 0.5\n")
        f.write(f"    beta: 0.95\n\n")
        
        f.write(f"Total Experiments: {len(experiments)}\n")
        f.write(f"Successful Experiments: {len(results)}\n\n")
        
        if not results:
            f.write("No successful experiments.\n")
            return
        
        runtimes = [r[1] for r in results]
        hpwls = [r[2] for r in results]
        
        # Overall statistics
        f.write(f"{'='*80}\n")
        f.write(f"OVERALL STATISTICS\n")
        f.write(f"{'='*80}\n")
        f.write(f"  Best HPWL: {min(hpwls):.2f} µm\n")
        f.write(f"  Worst HPWL: {max(hpwls):.2f} µm\n")
        f.write(f"  Mean HPWL: {np.mean(hpwls):.2f} µm\n")
        f.write(f"  Std Dev HPWL: {np.std(hpwls):.2f} µm\n")
        f.write(f"  HPWL Range: {max(hpwls) - min(hpwls):.2f} µm\n")
        f.write(f"  HPWL Improvement: {((max(hpwls) - min(hpwls)) / max(hpwls) * 100):.1f}%\n")
        f.write(f"  Fastest runtime: {min(runtimes):.2f} s\n")
        f.write(f"  Slowest runtime: {max(runtimes):.2f} s\n")
        f.write(f"  Mean runtime: {np.mean(runtimes):.2f} s\n")
        f.write(f"  Runtime Range: {max(runtimes) - min(runtimes):.2f} s\n\n")
        
        # All results sorted by HPWL
        sorted_results = sorted(results, key=lambda x: x[2])
        f.write(f"{'='*80}\n")
        f.write(f"ALL RESULTS (Sorted by HPWL - Best First)\n")
        f.write(f"{'='*80}\n")
        f.write(f"{'Rank':<6} {'Experiment Name':<45} {'HPWL (µm)':<15} {'RuntimeMean (s)':<15}\n")
        f.write(f"{'-'*6} {'-'*45} {'-'*15} {'-'*15}\n")
        for rank, (name, runtime_mean, hpwl_best, _runtime_best, _best_map) in enumerate(sorted_results, 1):
            f.write(f"{rank:<6} {name[:43]:<45} {hpwl_best:<15.2f} {runtime_mean:<15.2f}\n")
        
        # Top 10 best HPWL
        f.write(f"\n{'='*80}\n")
        f.write(f"TOP 10 BEST HPWL RESULTS\n")
        f.write(f"{'='*80}\n")
        f.write(f"{'Rank':<6} {'Experiment Name':<45} {'HPWL (µm)':<15} {'RuntimeMean (s)':<15}\n")
        f.write(f"{'-'*6} {'-'*45} {'-'*15} {'-'*15}\n")
        for rank, (name, runtime_mean, hpwl_best, _runtime_best, _best_map) in enumerate(sorted_results[:10], 1):
            f.write(f"{rank:<6} {name[:43]:<45} {hpwl_best:<15.2f} {runtime_mean:<15.2f}\n")
        
        # Top 10 fastest
        sorted_by_runtime = sorted(results, key=lambda x: x[1])
        f.write(f"\n{'='*80}\n")
        f.write(f"TOP 10 FASTEST RESULTS\n")
        f.write(f"{'='*80}\n")
        f.write(f"{'Rank':<6} {'Experiment Name':<45} {'RuntimeMean (s)':<15} {'HPWL (µm)':<15}\n")
        f.write(f"{'-'*6} {'-'*45} {'-'*15} {'-'*15}\n")
        for rank, (name, runtime_mean, hpwl_best, _runtime_best, _best_map) in enumerate(sorted_by_runtime[:10], 1):
            f.write(f"{rank:<6} {name[:43]:<45} {runtime_mean:<15.2f} {hpwl_best:<15.2f}\n")
        
        # Best trade-off
        runtime_norm = (np.array(runtimes) - np.min(runtimes)) / (np.max(runtimes) - np.min(runtimes) + 1e-10)
        hpwl_norm = (np.array(hpwls) - np.min(hpwls)) / (np.max(hpwls) - np.min(hpwls) + 1e-10)
        tradeoff_scores = np.sqrt(runtime_norm**2 + hpwl_norm**2)
        best_tradeoff_idx = np.argmin(tradeoff_scores)
        best_tradeoff = results[best_tradeoff_idx]
        
        f.write(f"\n{'='*80}\n")
        f.write(f"BEST TRADE-OFF (Balanced Runtime/HPWL)\n")
        f.write(f"{'='*80}\n")
        f.write(f"  Experiment: {best_tradeoff[0]}\n")
        f.write(f"  HPWL: {best_tradeoff[2]:.2f} µm\n")
        f.write(f"  Runtime: {best_tradeoff[1]:.2f} s\n")
        
        # Parameter analysis
        f.write(f"\n{'='*80}\n")
        f.write(f"PARAMETER ANALYSIS\n")
        f.write(f"{'='*80}\n")
        
        # Create experiment lookup by name
        exp_by_name = {exp['name']: exp for exp in experiments}
        
        # Group by parameter variations
        alpha_results = {}
        steps_results = {}
        moves_results = {}
        t_initial_results = {}
        prefine_results = {}
        winitial_results = {}
        beta_results = {}
        
        for name, _runtime_mean, hpwl, _runtime_best, _best_map in results:
            exp = exp_by_name.get(name, {})
            if 'alpha' in exp:
                alpha = exp['alpha']
                if alpha not in alpha_results:
                    alpha_results[alpha] = []
                alpha_results[alpha].append(hpwl)
            if 'num_temp_steps' in exp:
                steps = exp['num_temp_steps']
                if steps not in steps_results:
                    steps_results[steps] = []
                steps_results[steps].append(hpwl)
            if 'moves_per_temp' in exp:
                moves = exp['moves_per_temp']
                if moves not in moves_results:
                    moves_results[moves] = []
                moves_results[moves].append(hpwl)
            if 'T_initial' in exp:
                t_init = exp['T_initial']
                if t_init not in t_initial_results:
                    t_initial_results[t_init] = []
                t_initial_results[t_init].append(hpwl)
            if 'P_refine' in exp:
                prefine = exp['P_refine']
                if prefine not in prefine_results:
                    prefine_results[prefine] = []
                prefine_results[prefine].append(hpwl)
            if 'W_initial' in exp:
                winitial = exp['W_initial']
                if winitial not in winitial_results:
                    winitial_results[winitial] = []
                winitial_results[winitial].append(hpwl)
            if 'beta' in exp:
                beta = exp['beta']
                if beta not in beta_results:
                    beta_results[beta] = []
                beta_results[beta].append(hpwl)
        
        if alpha_results:
            best_alpha = min(alpha_results.items(), key=lambda x: np.mean(x[1]))
            f.write(f"  Best alpha (avg HPWL): {best_alpha[0]:.2f} (avg: {np.mean(best_alpha[1]):.2f} µm)\n")
        
        if steps_results:
            best_steps = min(steps_results.items(), key=lambda x: np.mean(x[1]))
            f.write(f"  Best num_temp_steps (avg HPWL): {int(best_steps[0])} (avg: {np.mean(best_steps[1]):.2f} µm)\n")
        
        if moves_results:
            best_moves = min(moves_results.items(), key=lambda x: np.mean(x[1]))
            f.write(f"  Best moves_per_temp (avg HPWL): {int(best_moves[0])} (avg: {np.mean(best_moves[1]):.2f} µm)\n")
        
        if t_initial_results:
            best_t_init = min(t_initial_results.items(), key=lambda x: np.mean(x[1]))
            f.write(f"  Best T_initial (avg HPWL): {best_t_init[0]:.0f} (avg: {np.mean(best_t_init[1]):.2f} µm)\n")
        
        if prefine_results:
            best_prefine = min(prefine_results.items(), key=lambda x: np.mean(x[1]))
            f.write(f"  Best P_refine (avg HPWL): {best_prefine[0]:.2f} (avg: {np.mean(best_prefine[1]):.2f} µm)\n")
        
        if winitial_results:
            best_winitial = min(winitial_results.items(), key=lambda x: np.mean(x[1]))
            f.write(f"  Best W_initial (avg HPWL): {best_winitial[0]:.2f} (avg: {np.mean(best_winitial[1]):.2f} µm)\n")
        
        if beta_results:
            best_beta = min(beta_results.items(), key=lambda x: np.mean(x[1]))
            f.write(f"  Best beta (avg HPWL): {best_beta[0]:.2f} (avg: {np.mean(best_beta[1]):.2f} µm)\n")
        
        # Output files
        f.write(f"\n{'='*80}\n")
        f.write(f"OUTPUT FILES\n")
        f.write(f"{'='*80}\n")
        plot_path = out_path.replace('_results.txt', '.png') if '_results.txt' in out_path else out_path.replace('.txt', '.png')
        f.write(f"  Plot: {plot_path}\n")
        f.write(f"  Results summary: {txt_path}\n")
        f.write(f"  Results CSV: {csv_path}\n")
        f.write(f"  Best HPWL map: build/{design_name}/{design_name}_best_hpwl.map\n")
    
    print(f"[INFO] Saved results summary to '{txt_path}'")
    
    # CSV file with all experiment details
    exp_by_name = {exp['name']: exp for exp in experiments}
    
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'Experiment Name', 'HPWL_best (µm)', 'Runtime_mean (s)', 'Runtime_best_hpwl (s)',
            'alpha', 'num_temp_steps', 'P_refine', 'W_initial', 'beta',
            'T_initial', 'moves_per_temp'
        ])
        
        for name, runtime_mean, hpwl_best, runtime_best, _best_map in sorted_results:
            exp = exp_by_name.get(name, {})
            writer.writerow([
                name,
                f"{hpwl_best:.2f}",
                f"{runtime_mean:.2f}",
                f"{runtime_best:.2f}",
                exp.get('alpha', ''),
                exp.get('num_temp_steps', ''),
                exp.get('P_refine', ''),
                exp.get('W_initial', ''),
                exp.get('beta', ''),
                exp.get('T_initial', ''),
                exp.get('moves_per_temp', ''),
            ])
    
    print(f"[INFO] Saved CSV results to '{csv_path}'")


def plot_knob_analysis(
    results: List[Tuple[str, float, float, str]],
    experiments: List[Dict],
    out_path: str,
    design_name: str,
    T_initial: float = None,
) -> None:
    """
    Generate comprehensive scatter plot of Runtime vs HPWL with enhanced analysis.
    
    Args:
        results: List of (experiment_name, runtime_sec, hpwl_um, temp_map_path) tuples
        experiments: List of experiment configuration dicts
        out_path: Output PNG path
        design_name: Design name for title
        T_initial: Filter by T_initial value (None = all)
    """
    if not results:
        print("[WARN] No results to plot")
        return
    
    # Filter by T_initial if specified
    if T_initial is not None:
        filtered_results = []
        exp_by_name = {exp['name']: exp for exp in experiments}
        for name, runtime, hpwl, *_rest in results:
            exp = exp_by_name.get(name, {})
            if exp.get('T_initial') == T_initial:
                filtered_results.append((name, runtime, hpwl, _rest[-1] if _rest else None))
        results = filtered_results
    
    if not results:
        print(f"[WARN] No results for T_initial={T_initial}")
        return
    
    names, runtimes, hpwls_um, temp_maps = zip(*results)
    
    # Convert to arrays and convert HPWL from µm to mm
    runtimes = np.array(runtimes)
    hpwls_um = np.array(hpwls_um)
    hpwls_mm = hpwls_um / 1000.0  # Convert to millimeters
    
    # Create figure with single main plot
    fig, ax_main = plt.subplots(figsize=(12, 8))
    
    # Color code by HPWL quality (normalized)
    hpwl_normalized = (hpwls_mm - np.min(hpwls_mm)) / (np.max(hpwls_mm) - np.min(hpwls_mm) + 1e-10)
    colors = plt.cm.RdYlGn_r(hpwl_normalized)  # Red-Yellow-Green reversed (green = better)
    
    # Scatter plot with size based on runtime
    sizes = 50 + 100 * (runtimes - np.min(runtimes)) / (np.max(runtimes) - np.min(runtimes) + 1e-10)
    scatter = ax_main.scatter(
        runtimes,
        hpwls_mm,
        s=sizes,
        alpha=0.7,
        c=colors,
        edgecolors='black',
        linewidths=1.5
    )
    
    # Find Pareto frontier (points that are not dominated)
    pareto_indices = []
    for i in range(len(results)):
        is_pareto = True
        for j in range(len(results)):
            if i != j:
                # j dominates i if j has both lower runtime and lower HPWL
                if runtimes[j] < runtimes[i] and hpwls_mm[j] < hpwls_mm[i]:
                    is_pareto = False
                    break
        if is_pareto:
            pareto_indices.append(i)
    
    # Highlight Pareto frontier
    if pareto_indices:
        pareto_runtimes = runtimes[pareto_indices]
        pareto_hpwls_mm = hpwls_mm[pareto_indices]
        
        # Sort by runtime for line drawing
        sort_idx = np.argsort(pareto_runtimes)
        pareto_runtimes = pareto_runtimes[sort_idx]
        pareto_hpwls_mm = pareto_hpwls_mm[sort_idx]
        
        ax_main.plot(
            pareto_runtimes,
            pareto_hpwls_mm,
            'r--',
            linewidth=2.5,
            alpha=0.8,
            label='Pareto Frontier',
            zorder=10
        )
        
        # Highlight Pareto points
        ax_main.scatter(
            pareto_runtimes,
            pareto_hpwls_mm,
            s=200,
            facecolors='none',
            edgecolors='red',
            linewidths=3,
            label='Pareto Optimal',
            zorder=11
        )
    
    # Find best HPWL and fastest runtime
    best_hpwl_idx = np.argmin(hpwls_mm)
    fastest_idx = np.argmin(runtimes)
    
    # Find best trade-off (closest to origin in normalized space)
    runtime_norm = (runtimes - np.min(runtimes)) / (np.max(runtimes) - np.min(runtimes) + 1e-10)
    hpwl_norm = (hpwls_mm - np.min(hpwls_mm)) / (np.max(hpwls_mm) - np.min(hpwls_mm) + 1e-10)
    tradeoff_scores = np.sqrt(runtime_norm**2 + hpwl_norm**2)
    best_tradeoff_idx = np.argmin(tradeoff_scores)
    
    # Extract best parameters from experiments
    exp_by_name = {exp['name']: exp for exp in experiments}
    best_exp_name = names[best_hpwl_idx]
    best_exp_config = exp_by_name.get(best_exp_name, {})
    
    # Build best parameters text
    best_params_text = "Best Parameters:\n"
    best_params_text += f"  T_initial: {best_exp_config.get('T_initial', 'N/A'):.0f}\n"
    best_params_text += f"  alpha: {best_exp_config.get('alpha', 'N/A'):.2f}\n"
    best_params_text += f"  num_temp_steps: {best_exp_config.get('num_temp_steps', 'N/A')}\n"
    best_params_text += f"  moves_per_temp: {best_exp_config.get('moves_per_temp', 'N/A')}\n"
    best_params_text += f"  P_refine: {best_exp_config.get('P_refine', 'N/A'):.2f}\n"
    best_params_text += f"  W_initial: {best_exp_config.get('W_initial', 'N/A'):.2f}\n"
    best_params_text += f"  beta: {best_exp_config.get('beta', 'N/A'):.2f}\n"
    best_params_text += f"\nBest HPWL: {hpwls_mm[best_hpwl_idx]:.2f} mm"
    
    # Annotate best HPWL point
    ax_main.annotate(
        f'Best HPWL\n{names[best_hpwl_idx][:30]}\n{hpwls_mm[best_hpwl_idx]:.2f} mm',
        xy=(runtimes[best_hpwl_idx], hpwls_mm[best_hpwl_idx]),
        xytext=(15, 15),
        textcoords='offset points',
        bbox=dict(boxstyle='round,pad=0.5', facecolor='green', alpha=0.8),
        arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0.2', lw=2),
        fontsize=9,
        fontweight='bold'
    )
    
    # Annotate fastest point
    ax_main.annotate(
        f'Fastest\n{names[fastest_idx][:30]}\n{runtimes[fastest_idx]:.1f}s',
        xy=(runtimes[fastest_idx], hpwls_mm[fastest_idx]),
        xytext=(15, -35),
        textcoords='offset points',
        bbox=dict(boxstyle='round,pad=0.5', facecolor='blue', alpha=0.8),
        arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0.2', lw=2),
        fontsize=9,
        fontweight='bold'
    )
    
    # Annotate best trade-off
    ax_main.annotate(
        f'Best Trade-off\n{names[best_tradeoff_idx][:30]}',
        xy=(runtimes[best_tradeoff_idx], hpwls_mm[best_tradeoff_idx]),
        xytext=(-15, 15),
        textcoords='offset points',
        bbox=dict(boxstyle='round,pad=0.5', facecolor='orange', alpha=0.8),
        arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0.2', lw=2),
        fontsize=9,
        fontweight='bold'
    )
    
    # Determine T_initial label for title
    if T_initial is not None:
        if T_initial == 200.0:
            t_label = "T_initial = 200"
        elif T_initial == 300.0:
            t_label = "T_initial = 300"
        elif T_initial == 4000000.0:
            t_label = "T_initial = 4,000,000"
        else:
            t_label = f"T_initial = {T_initial:.0f}"
    else:
        t_label = "All T_initial values"
    
    # Labels and title
    ax_main.set_xlabel('Runtime (seconds)', fontsize=13, fontweight='bold')
    ax_main.set_ylabel('Final HPWL (mm)', fontsize=13, fontweight='bold')
    ax_main.set_title(
        f'{design_name} - SA Knob Analysis: Runtime vs HPWL\n'
        f'{t_label} | Total Experiments: {len(results)}',
        fontsize=14,
        fontweight='bold'
    )
    
    # Grid
    ax_main.grid(True, alpha=0.3, linestyle='--')
    
    # Legend
    ax_main.legend(loc='best', fontsize=10, framealpha=0.9)
    
    # Enhanced statistics text (bottom-left)
    hpwl_range_mm = np.max(hpwls_mm) - np.min(hpwls_mm)
    runtime_range = np.max(runtimes) - np.min(runtimes)
    hpwl_improvement = ((np.max(hpwls_mm) - np.min(hpwls_mm)) / np.max(hpwls_mm)) * 100
    
    stats_text = (
        f'Best HPWL: {np.min(hpwls_mm):.2f} mm\n'
        f'Worst HPWL: {np.max(hpwls_mm):.2f} mm\n'
        f'HPWL Range: {hpwl_range_mm:.2f} mm ({hpwl_improvement:.1f}%)\n'
        f'Fastest: {np.min(runtimes):.1f} s\n'
        f'Slowest: {np.max(runtimes):.1f} s\n'
        f'Runtime Range: {runtime_range:.1f} s\n'
        f'Pareto Points: {len(pareto_indices)}\n'
        f'Mean HPWL: {np.mean(hpwls_mm):.2f} mm\n'
        f'Std HPWL: {np.std(hpwls_mm):.2f} mm'
    )
    
    ax_main.text(
        0.02, 0.02, stats_text,
        transform=ax_main.transAxes,
        verticalalignment='bottom',
        bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.9),
        fontsize=9,
        family='monospace'
    )
    
    # Best parameters text (top-right)
    ax_main.text(
        0.98, 0.98, best_params_text,
        transform=ax_main.transAxes,
        verticalalignment='top',
        horizontalalignment='right',
        bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.9),
        fontsize=9,
        family='monospace'
    )
    
    plt.tight_layout()
    os.makedirs(os.path.dirname(out_path), exist_ok=True) if os.path.dirname(out_path) else None
    plt.savefig(out_path, dpi=200, bbox_inches='tight')
    print(f"[INFO] Saved comprehensive knob analysis plot to '{out_path}'")
    plt.close()


def parse_experiment_params(name: str) -> Dict[str, float]:
    """
    Parse experiment name to extract parameter values.
    Handles both old format (alpha=0.80) and new format (T300_alpha=0.80).
    Returns dict with parameter values (or None if not found).
    """
    params = {}
    
    # Extract T_initial from name patterns
    if 'T200' in name:
        params['T_initial'] = 200.0
    elif 'T300' in name or 'T_initial=300' in name:
        params['T_initial'] = 300.0
    elif 'T4M' in name or 'T4000M' in name or 'T_initial=4000000' in name:
        params['T_initial'] = 4000000.0
    
    # Extract alpha (handles both "alpha=0.80" and "T300_alpha=0.80")
    if 'alpha=' in name:
        try:
            alpha_part = name.split('alpha=')[1]
            # Extract value until next underscore or end of string
            if '_' in alpha_part:
                alpha_str = alpha_part.split('_')[0]
            else:
                alpha_str = alpha_part
            params['alpha'] = float(alpha_str)
        except (ValueError, IndexError):
            pass
    
    # Extract num_temp_steps (handles "steps=" format)
    if 'steps=' in name:
        try:
            steps_part = name.split('steps=')[1]
            if '_' in steps_part:
                steps_str = steps_part.split('_')[0]
            else:
                steps_str = steps_part
            params['num_temp_steps'] = float(steps_str)
        except (ValueError, IndexError):
            pass
    
    # Extract moves_per_temp (handles "moves=" format)
    if 'moves=' in name:
        try:
            moves_part = name.split('moves=')[1]
            if '_' in moves_part:
                moves_str = moves_part.split('_')[0]
            else:
                moves_str = moves_part
            params['moves_per_temp'] = float(moves_str)
        except (ValueError, IndexError):
            pass
    
    # Extract P_refine (handles "Prefine=" format)
    if 'Prefine=' in name:
        try:
            prefine_part = name.split('Prefine=')[1]
            if '_' in prefine_part:
                prefine_str = prefine_part.split('_')[0]
            else:
                prefine_str = prefine_part
            params['P_refine'] = float(prefine_str)
        except (ValueError, IndexError):
            pass
    
    # Extract W_initial (handles "Winit=" format)
    if 'Winit=' in name:
        try:
            w_part = name.split('Winit=')[1]
            if '_' in w_part:
                w_str = w_part.split('_')[0]
            else:
                w_str = w_part
            params['W_initial'] = float(w_str)
        except (ValueError, IndexError):
            pass
    
    # Extract beta (handles "beta=" format)
    if 'beta=' in name:
        try:
            beta_part = name.split('beta=')[1]
            if '_' in beta_part:
                beta_str = beta_part.split('_')[0]
            else:
                beta_str = beta_part
            params['beta'] = float(beta_str)
        except (ValueError, IndexError):
            pass
    
    return params


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
        "--preset",
        choices=["small", "medium", "full"],
        default="full",
        help="Experiment sweep size preset (small=12, medium=24, full=36). Default: full"
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42)"
    )

    parser.add_argument(
        "--sa-script",
        default="src/simulated_annealing.py",
        help="Path to the simulated annealing script to run (default: src/simulated_annealing.py)"
    )

    parser.add_argument(
        "--seeds",
        default=None,
        help="Comma-separated list of seeds to run per experiment (overrides --seed). Example: 11,22,33"
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
    print("[INFO] Constraints: T_initial=4,000,000 and moves_per_temp=1000")
    print("[INFO] Runtime cap: num_temp_steps restricted to {60, 150}")
    print("[INFO] Running multiple seeds per experiment and taking best HPWL")
    print(f"[INFO] Preset: {args.preset}")
    experiments = generate_knob_experiments(preset=args.preset)
    
    if args.max_experiments:
        experiments = experiments[:args.max_experiments]
    
    seeds = [args.seed]
    if args.seeds:
        seeds = [int(s.strip()) for s in args.seeds.split(',') if s.strip()]
        if not seeds:
            raise ValueError("--seeds was provided but no valid seeds were parsed")

    print(f"[INFO] Running {len(experiments)} SA experiments...")
    print(f"[INFO] Seeds per experiment: {len(seeds)} ({seeds})")
    
    # Run experiments
    results: List[Tuple[str, float, float, float, str]] = []
    temp_map_dir = f"build/{args.design}/sa_temp"
    os.makedirs(temp_map_dir, exist_ok=True)
    
    for i, exp in enumerate(experiments, 1):
        print(f"\n[EXPERIMENT {i}/{len(experiments)}] {exp['name']}")
        print(f"  T_initial={exp['T_initial']:.0f} (fixed), alpha={exp['alpha']:.2f}, num_temp_steps={exp['num_temp_steps']}, "
              f"moves_per_temp={exp['moves_per_temp']}, P_refine={exp['P_refine']:.2f}, "
              f"W_initial={exp['W_initial']:.2f}, beta={exp['beta']:.2f}")
        print(f"  Running SA ({len(seeds)} seeds)...")

        runtimes_seed: List[float] = []
        hpwls_seed: List[float] = []
        best_hpwl = None
        best_runtime = None
        best_map_path = None

        for seed in seeds:
            temp_map = os.path.join(temp_map_dir, f"temp_{i}_seed{seed}.map")
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
                    sa_script=args.sa_script,
                    seed=seed,
                )
                runtimes_seed.append(runtime)
                hpwls_seed.append(hpwl)
                if best_hpwl is None or hpwl < best_hpwl:
                    best_hpwl = hpwl
                    best_runtime = runtime
                    best_map_path = temp_map
                print(f"    seed={seed} → runtime={runtime:.2f}s, hpwl={hpwl:.2f} µm")
            except Exception as e:
                print(f"    seed={seed} ✗ Failed: {e}")
                continue

        if not hpwls_seed or best_hpwl is None or best_runtime is None or best_map_path is None:
            print("  ✗ Failed: no successful seeds")
            continue

        runtime_mean = float(np.mean(runtimes_seed))
        results.append((exp['name'], runtime_mean, float(best_hpwl), float(best_runtime), best_map_path))
        print(f"  ✓ Best HPWL across seeds: {best_hpwl:.2f} µm | runtime_mean={runtime_mean:.2f}s | runtime_best_hpwl={best_runtime:.2f}s")
    
    if not results:
        print("[ERROR] No successful experiments!")
        return
    
    # Find best HPWL map
    runtimes_list = [r[1] for r in results]
    hpwls_list = [r[2] for r in results]
    best_maps_list = [r[4] for r in results]
 
    best_hpwl_idx = hpwls_list.index(min(hpwls_list))
    best_map_path = best_maps_list[best_hpwl_idx]
    best_hpwl_value = hpwls_list[best_hpwl_idx]
    best_experiment_name = results[best_hpwl_idx][0]
 
    # Save best map to a named file
    best_map_output = f"build/{args.design}/{args.design}_best_hpwl.map"
    shutil.copy2(best_map_path, best_map_output)
    print(f"\n[INFO] Best HPWL map saved: {best_map_output}")
    print(f"  Experiment: {best_experiment_name}")
    print(f"  HPWL: {best_hpwl_value:.2f} µm")
    
    # Generate plot for T_initial=4M only
    print(f"\n[INFO] Generating analysis plot...")
    
    # Generate single plot for T_initial=4M
    base_plot_path = args.out_plot.replace('.png', '')
    plot_path = f"{base_plot_path}_T4M.png"
    
    print(f"[INFO] Generating plot for T_initial=4,000,000...")
    plot_results = [(n, rt_mean, hpwl_best, best_map) for (n, rt_mean, hpwl_best, _rt_best, best_map) in results]
    plot_knob_analysis(plot_results, experiments, plot_path, args.design, T_initial=4000000.0)
    
    # Save results to files
    print(f"\n[INFO] Saving results to files...")
    save_results_to_file(results, experiments, args.out_plot, args.design)
    
    # Print comprehensive results summary
    print(f"\n{'='*80}")
    print(f"COMPREHENSIVE RESULTS SUMMARY")
    print(f"{'='*80}")
    print(f"  Successful experiments: {len(results)}/{len(experiments)}")
    
    if results:
        runtimes = [r[1] for r in results]
        hpwls = [r[2] for r in results]
        
        # Overall statistics
        print(f"\n[OVERALL STATISTICS]")
        print(f"  Best HPWL: {min(hpwls):.2f} µm")
        print(f"  Worst HPWL: {max(hpwls):.2f} µm")
        print(f"  Mean HPWL: {np.mean(hpwls):.2f} µm")
        print(f"  Std Dev HPWL: {np.std(hpwls):.2f} µm")
        print(f"  HPWL Range: {max(hpwls) - min(hpwls):.2f} µm")
        print(f"  HPWL Improvement: {((max(hpwls) - min(hpwls)) / max(hpwls) * 100):.1f}%")
        print(f"  Fastest runtime: {min(runtimes):.2f} s")
        print(f"  Slowest runtime: {max(runtimes):.2f} s")
        print(f"  Mean runtime: {np.mean(runtimes):.2f} s")
        print(f"  Runtime Range: {max(runtimes) - min(runtimes):.2f} s")
        
        # Sort results by HPWL (best first)
        sorted_results = sorted(results, key=lambda x: x[2])
        
        # Top 10 best HPWL results
        print(f"\n[TOP 10 BEST HPWL RESULTS]")
        print(f"{'Rank':<6} {'Experiment Name':<40} {'HPWL (µm)':<12} {'Runtime (s)':<12}")
        print(f"{'-'*6} {'-'*40} {'-'*12} {'-'*12}")
        for rank, (name, runtime_mean, hpwl_best, runtime_best, _best_map) in enumerate(sorted_results[:10], 1):
            print(f"{rank:<6} {name[:38]:<40} {hpwl_best:<12.2f} {runtime_mean:<12.2f}")
        
        # Top 10 fastest results
        sorted_by_runtime = sorted(results, key=lambda x: x[1])
        print(f"\n[TOP 10 FASTEST RESULTS]")
        print(f"{'Rank':<6} {'Experiment Name':<40} {'Runtime (s)':<12} {'HPWL (µm)':<12}")
        print(f"{'-'*6} {'-'*40} {'-'*12} {'-'*12}")
        for rank, (name, runtime_mean, hpwl_best, runtime_best, _best_map) in enumerate(sorted_by_runtime[:10], 1):
            print(f"{rank:<6} {name[:38]:<40} {runtime_mean:<12.2f} {hpwl_best:<12.2f}")
        
        # Best trade-off (normalized distance to origin)
        runtime_norm = (np.array(runtimes) - np.min(runtimes)) / (np.max(runtimes) - np.min(runtimes) + 1e-10)
        hpwl_norm = (np.array(hpwls) - np.min(hpwls)) / (np.max(hpwls) - np.min(hpwls) + 1e-10)
        tradeoff_scores = np.sqrt(runtime_norm**2 + hpwl_norm**2)
        best_tradeoff_idx = np.argmin(tradeoff_scores)
        best_tradeoff = results[best_tradeoff_idx]
        
        print(f"\n[BEST TRADE-OFF (Balanced Runtime/HPWL)]")
        print(f"  Experiment: {best_tradeoff[0]}")
        print(f"  HPWL: {best_tradeoff[2]:.2f} µm")
        print(f"  Runtime: {best_tradeoff[1]:.2f} s")
        
        # Parameter analysis
        print(f"\n[PARAMETER ANALYSIS]")
        
        # Group by parameter variations
        alpha_results = {}
        steps_results = {}
        moves_results = {}
        t_initial_results = {}
        prefine_results = {}
        winitial_results = {}
        beta_results = {}
        
        for name, runtime_mean, hpwl_best, runtime_best, _best_map in results:
            params = parse_experiment_params(name)
            if 'alpha' in params:
                alpha = params['alpha']
                if alpha not in alpha_results:
                    alpha_results[alpha] = []
                alpha_results[alpha].append(hpwl_best)
            if 'num_temp_steps' in params:
                steps = params['num_temp_steps']
                if steps not in steps_results:
                    steps_results[steps] = []
                steps_results[steps].append(hpwl_best)
            if 'moves_per_temp' in params:
                moves = params['moves_per_temp']
                if moves not in moves_results:
                    moves_results[moves] = []
                moves_results[moves].append(hpwl_best)
            if 'T_initial' in params:
                t_init = params['T_initial']
                if t_init not in t_initial_results:
                    t_initial_results[t_init] = []
                t_initial_results[t_init].append(hpwl_best)
            if 'P_refine' in params:
                prefine = params['P_refine']
                if prefine not in prefine_results:
                    prefine_results[prefine] = []
                prefine_results[prefine].append(hpwl_best)
            if 'W_initial' in params:
                winitial = params['W_initial']
                if winitial not in winitial_results:
                    winitial_results[winitial] = []
                winitial_results[winitial].append(hpwl_best)
            if 'beta' in params:
                beta = params['beta']
                if beta not in beta_results:
                    beta_results[beta] = []
                beta_results[beta].append(hpwl_best)
        
        if alpha_results:
            best_alpha = min(alpha_results.items(), key=lambda x: np.mean(x[1]))
            print(f"  Best alpha (avg HPWL): {best_alpha[0]:.2f} (avg: {np.mean(best_alpha[1]):.2f} µm)")
        
        if steps_results:
            best_steps = min(steps_results.items(), key=lambda x: np.mean(x[1]))
            print(f"  Best num_temp_steps (avg HPWL): {int(best_steps[0])} (avg: {np.mean(best_steps[1]):.2f} µm)")
        
        if moves_results:
            best_moves = min(moves_results.items(), key=lambda x: np.mean(x[1]))
            print(f"  Best moves_per_temp (avg HPWL): {int(best_moves[0])} (avg: {np.mean(best_moves[1]):.2f} µm)")
        
        if t_initial_results:
            best_t_init = min(t_initial_results.items(), key=lambda x: np.mean(x[1]))
            print(f"  Best T_initial (avg HPWL): {best_t_init[0]:.0f} (avg: {np.mean(best_t_init[1]):.2f} µm)")
        
        if prefine_results:
            best_prefine = min(prefine_results.items(), key=lambda x: np.mean(x[1]))
            print(f"  Best P_refine (avg HPWL): {best_prefine[0]:.2f} (avg: {np.mean(best_prefine[1]):.2f} µm)")
        
        if winitial_results:
            best_winitial = min(winitial_results.items(), key=lambda x: np.mean(x[1]))
            print(f"  Best W_initial (avg HPWL): {best_winitial[0]:.2f} (avg: {np.mean(best_winitial[1]):.2f} µm)")
        
        if beta_results:
            best_beta = min(beta_results.items(), key=lambda x: np.mean(x[1]))
            print(f"  Best beta (avg HPWL): {best_beta[0]:.2f} (avg: {np.mean(best_beta[1]):.2f} µm)")
        
        print(f"\n[OUTPUT FILES]")
        print(f"  Plot saved to: {args.out_plot}")
        results_txt = args.out_plot.replace('.png', '_results.txt') if args.out_plot.endswith('.png') else args.out_plot + '_results.txt'
        results_csv = args.out_plot.replace('.png', '_results.csv') if args.out_plot.endswith('.png') else args.out_plot + '_results.csv'
        print(f"  Results summary: {results_txt}")
        print(f"  Results CSV: {results_csv}")
        print(f"  Best HPWL map: build/{args.design}/{args.design}_best_hpwl.map")
        print(f"{'='*80}")
    
    print("[INFO] Done.")


if __name__ == "__main__":
    main()

