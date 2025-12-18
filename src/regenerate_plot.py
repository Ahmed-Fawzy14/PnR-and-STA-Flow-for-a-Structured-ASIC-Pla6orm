#!/usr/bin/env python3
"""
Quick script to regenerate the plot from existing CSV results.
This avoids re-running all experiments.
Generates a single knob analysis plot.
"""
import csv
import os
import sys
import matplotlib.pyplot as plt
import numpy as np
from typing import List, Tuple, Dict

def load_results_from_csv(csv_path: str) -> Tuple[List[Tuple[str, float, float, str]], List[Dict]]:
    """Load results and experiments from CSV file."""
    results = []
    experiments = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Support both old and new CSV schemas.
            # Old:  HPWL (µm), Runtime (s)
            # New:  HPWL_best (µm), Runtime_mean (s), Runtime_best_hpwl (s)
            name = row['Experiment Name']

            hpwl_key = 'HPWL_best (µm)' if 'HPWL_best (µm)' in row else 'HPWL (µm)'
            runtime_key = 'Runtime_mean (s)' if 'Runtime_mean (s)' in row else 'Runtime (s)'

            hpwl = float(row[hpwl_key])
            runtime = float(row[runtime_key])
            temp_map = ''
            results.append((name, runtime, hpwl, temp_map))
            
            # Build experiment dict
            exp = {
                'name': name,
                'T_initial': float(row.get('T_initial', 0)) if row.get('T_initial') else 0.0,
                'alpha': float(row.get('alpha', 0)) if row.get('alpha') else None,
                'num_temp_steps': int(row.get('num_temp_steps', 0)) if row.get('num_temp_steps') else None,
                'moves_per_temp': int(row.get('moves_per_temp', 0)) if row.get('moves_per_temp') else None,
                'P_refine': float(row.get('P_refine', 0)) if row.get('P_refine') else None,
                'W_initial': float(row.get('W_initial', 0)) if row.get('W_initial') else None,
                'beta': float(row.get('beta', 0)) if row.get('beta') else None,
            }
            experiments.append(exp)
    return results, experiments

def plot_knob_analysis(
    results: List[Tuple[str, float, float, str]],
    experiments: List[Dict],
    out_path: str,
    design_name: str,
    T_initial: float = None,
) -> None:
    """Generate scatter plot of Runtime vs HPWL in millimeters."""
    if not results:
        print("[WARN] No results to plot")
        return
    
    # Filter by T_initial if specified
    if T_initial is not None:
        filtered_results = []
        exp_by_name = {exp['name']: exp for exp in experiments}
        for name, runtime, hpwl, temp_map in results:
            exp = exp_by_name.get(name, {})
            if exp.get('T_initial') == T_initial:
                filtered_results.append((name, runtime, hpwl, temp_map))
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
    # Reserve some space on the right for text boxes so they don't cover points
    fig.subplots_adjust(right=0.76)
    
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
    
    # Find Pareto frontier
    pareto_indices = []
    for i in range(len(results)):
        is_pareto = True
        for j in range(len(results)):
            if i != j:
                if runtimes[j] < runtimes[i] and hpwls_mm[j] < hpwls_mm[i]:
                    is_pareto = False
                    break
        if is_pareto:
            pareto_indices.append(i)
    
    # Highlight Pareto frontier
    if pareto_indices:
        pareto_runtimes = runtimes[pareto_indices]
        pareto_hpwls_mm = hpwls_mm[pareto_indices]
        
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

    # Best-fit line (linear regression) across all experiments
    if len(results) >= 2:
        fit_m, fit_b = np.polyfit(runtimes, hpwls_mm, 1)
        fit_x = np.linspace(float(np.min(runtimes)), float(np.max(runtimes)), 200)
        fit_y = fit_m * fit_x + fit_b
        ax_main.plot(
            fit_x,
            fit_y,
            color='black',
            linestyle='-',
            linewidth=1.5,
            alpha=0.7,
            label='Best Fit (Linear)',
            zorder=9
        )
    
    # Find best HPWL and fastest runtime
    best_hpwl_idx = np.argmin(hpwls_mm)
    fastest_idx = np.argmin(runtimes)
    
    # Find best trade-off
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
    if best_exp_config.get('T_initial'):
        best_params_text += f"  T_initial: {best_exp_config['T_initial']:.0f}\n"
    if best_exp_config.get('alpha') is not None:
        best_params_text += f"  alpha: {best_exp_config['alpha']:.2f}\n"
    if best_exp_config.get('num_temp_steps'):
        best_params_text += f"  num_temp_steps: {best_exp_config['num_temp_steps']}\n"
    if best_exp_config.get('moves_per_temp'):
        best_params_text += f"  moves_per_temp: {best_exp_config['moves_per_temp']}\n"
    if best_exp_config.get('P_refine') is not None:
        best_params_text += f"  P_refine: {best_exp_config['P_refine']:.2f}\n"
    if best_exp_config.get('W_initial') is not None:
        best_params_text += f"  W_initial: {best_exp_config['W_initial']:.2f}\n"
    if best_exp_config.get('beta') is not None:
        best_params_text += f"  beta: {best_exp_config['beta']:.2f}\n"
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
    ax_main.legend(
        loc='upper left',
        bbox_to_anchor=(1.005, 1.0),
        borderaxespad=0.0,
        fontsize=10,
        framealpha=0.9,
    )
    
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
    
    # Put the text boxes in the right-side margin (outside the axes)
    fig.text(
        0.78, 0.08, stats_text,
        va='bottom',
        ha='left',
        bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.9),
        fontsize=9,
        family='monospace'
    )

    fig.text(
        0.78, 0.92, best_params_text,
        va='top',
        ha='left',
        bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.9),
        fontsize=9,
        family='monospace'
    )
    
    plt.tight_layout()

    os.makedirs(os.path.dirname(out_path), exist_ok=True) if os.path.dirname(out_path) else None
    plt.savefig(out_path, dpi=200, bbox_inches='tight')
    print(f"[INFO] Saved knob analysis plot to '{out_path}'")
    plt.close(fig)

def plot_temperature_schedules(
    experiments: List[Dict],
    out_path: str,
    design_name: str,
    log_y: bool = True,
    linear_out_path: str = None,
) -> None:
    """Plot temperature schedule T_k for each experiment.

    Uses the same schedule as simulated_annealing.py:
        T_k = T_initial * (alpha ** k)

    """  # noqa: D401
    # Filter to experiments that have schedule parameters
    sched_exps = [
        e for e in experiments
        if e.get('T_initial') and (e.get('alpha') is not None) and e.get('num_temp_steps') and e.get('moves_per_temp')
    ]

    if not sched_exps:
        print("[WARN] No experiments with T_initial/alpha/num_temp_steps/moves_per_temp; cannot plot temperature schedule")
        return

    fig, (ax_moves, ax_steps) = plt.subplots(1, 2, figsize=(14, 5), sharey=True)

    for exp in sched_exps:
        t0 = float(exp['T_initial'])
        alpha = float(exp['alpha'])
        steps = int(exp['num_temp_steps'])
        moves_per_temp = int(exp['moves_per_temp'])
        if steps <= 0 or moves_per_temp <= 0:
            continue

        k = np.arange(steps)
        T_k = t0 * (alpha ** k)
        # Represent "time" as cumulative attempted moves
        moves = k * moves_per_temp

        # Light lines to avoid clutter
        ax_moves.plot(moves, T_k, alpha=0.25, linewidth=1.0)
        ax_steps.plot(k, T_k, alpha=0.25, linewidth=1.0)

    ax_moves.set_xlabel('Cumulative moves (k * moves_per_temp)')
    ax_steps.set_xlabel('Temperature step (k)')
    ax_moves.set_ylabel('Temperature T')

    ax_moves.set_title('T schedule vs moves')
    ax_steps.set_title('T schedule vs steps')

    ax_moves.grid(True, alpha=0.3, linestyle='--')
    ax_steps.grid(True, alpha=0.3, linestyle='--')

    # Log scale is usually the most readable for exponential decay
    if log_y:
        ax_moves.set_yscale('log')

    fig.suptitle(f'{design_name} - SA Temperature Schedules (one curve per experiment)')

    plt.tight_layout()
    os.makedirs(os.path.dirname(out_path), exist_ok=True) if os.path.dirname(out_path) else None
    plt.savefig(out_path, dpi=200, bbox_inches='tight')
    print(f"[INFO] Saved temperature schedule plot to '{out_path}'")

    if not log_y and linear_out_path:
        fig, (ax_moves, ax_steps) = plt.subplots(1, 2, figsize=(14, 5), sharey=True)

        for exp in sched_exps:
            t0 = float(exp['T_initial'])
            alpha = float(exp['alpha'])
            steps = int(exp['num_temp_steps'])
            moves_per_temp = int(exp['moves_per_temp'])
            if steps <= 0 or moves_per_temp <= 0:
                continue

            k = np.arange(steps)
            T_k = t0 * (alpha ** k)
            # Represent "time" as cumulative attempted moves
            moves = k * moves_per_temp

            # Light lines to avoid clutter
            ax_moves.plot(moves, T_k, alpha=0.25, linewidth=1.0)
            ax_steps.plot(k, T_k, alpha=0.25, linewidth=1.0)

        ax_moves.set_xlabel('Cumulative moves (k * moves_per_temp)')
        ax_steps.set_xlabel('Temperature step (k)')
        ax_moves.set_ylabel('Temperature T')

        ax_moves.set_title('T schedule vs moves')
        ax_steps.set_title('T schedule vs steps')

        ax_moves.grid(True, alpha=0.3, linestyle='--')
        ax_steps.grid(True, alpha=0.3, linestyle='--')

        fig.suptitle(f'{design_name} - SA Temperature Schedules (one curve per experiment) Linear')

        plt.tight_layout()
        os.makedirs(os.path.dirname(linear_out_path), exist_ok=True) if os.path.dirname(linear_out_path) else None
        plt.savefig(linear_out_path, dpi=200, bbox_inches='tight')
        print(f"[INFO] Saved linear temperature schedule plot to '{linear_out_path}'")

    plt.close()

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 regenerate_plot.py <design_name> [--csv <path>] [--out <path>] [--t-initial <value>] ")
        print("Example: python3 regenerate_plot.py arith")
        print("Example: python3 regenerate_plot.py arith --t-initial 4000000")
        sys.exit(1)
    
    design_name = sys.argv[1]
 
    csv_path = f"build/{design_name}/sa_knob_analysis_results.csv"
    out_path = f"build/{design_name}/sa_knob_analysis.png"
    temp_plot_path = f"build/{design_name}/sa_temperature_schedules.png"
    linear_temp_plot_path = f"build/{design_name}/sa_temperature_schedules_linear.png"
    t_initial = None
    plot_temp = False
    temp_linear = False
 
    # Minimal arg parsing (avoid adding new dependencies)
    i = 2
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--csv" and i + 1 < len(sys.argv):
            csv_path = sys.argv[i + 1]
            i += 2
            continue
        if arg == "--out" and i + 1 < len(sys.argv):
            out_path = sys.argv[i + 1]
            i += 2
            continue
        if arg == "--temp-out" and i + 1 < len(sys.argv):
            temp_plot_path = sys.argv[i + 1]
            i += 2
            continue
        if arg in ("--plot-temp", "--temp-plot"):
            plot_temp = True
            i += 1
            continue
        if arg in ("--temp-linear", "--linear-temp"):
            temp_linear = True
            i += 1
            continue
        if arg in ("--t-initial", "--T-initial") and i + 1 < len(sys.argv):
            try:
                t_initial = float(sys.argv[i + 1])
            except ValueError:
                print(f"[ERROR] Invalid --t-initial value: {sys.argv[i + 1]!r}")
                sys.exit(1)
            i += 2
            continue
 
        print(f"[WARN] Unknown argument ignored: {arg!r}")
        i += 1
 
    if not os.path.exists(csv_path):
        print(f"[ERROR] CSV file not found: {csv_path}")
        print("[INFO] You need to run sa_knob_analysis.py first to generate results.")
        sys.exit(1)
 
    print(f"[INFO] Loading results from {csv_path}...")
    results, experiments = load_results_from_csv(csv_path)
    print(f"[INFO] Loaded {len(results)} experiments")
 
    # Match sa_knob_analysis default: one plot over all experiments.
    if t_initial is None:
        print("[INFO] Generating plot for all T_initial values...")
    else:
        print(f"[INFO] Generating plot filtered by T_initial={t_initial:.0f}...")
 
    plot_knob_analysis(results, experiments, out_path, design_name, T_initial=t_initial)

    if plot_temp:
        plot_temperature_schedules(experiments, temp_plot_path, design_name, log_y=(not temp_linear), linear_out_path=linear_temp_plot_path if temp_linear else None)
 
    print("[INFO] Done!")

if __name__ == "__main__":
    main()
