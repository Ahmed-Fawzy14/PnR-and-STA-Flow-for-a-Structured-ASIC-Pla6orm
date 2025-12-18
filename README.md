# Structured ASIC Flow — Final Report

## 1) How to Run (Makefile)

### One-time setup
```bash
make deps
```

### Run the full flow
```bash
make DESIGN=arith all
```

### Run phase-by-phase
```bash
make DESIGN=arith validate   # Phase 1
make DESIGN=arith place      # Phase 2
make DESIGN=arith eco        # Phase 3
make DESIGN=arith route      # Phase 4
make DESIGN=arith sta        # Phase 5
```

### Clean
```bash
make clean
```

---

## 2) Project Summary
This project implements an automated **PnR + STA** flow for a **Structured ASIC** fabric:
- Phase 1: Parse/validate design + build data structures
- Phase 2: Greedy placement + Simulated Annealing (HPWL-driven) + visualization
- Phase 3: CTS + power-down ECO + final netlist generation
- Phase 4: DEF generation + netlist renaming + OpenROAD routing
- Phase 5: STA scripts + reporting (setup/hold/skew)

---

## 3) Requirements Met (Deliverables)

## Phase 1 (Validate / Data Structures): All requirements met
✅ `build/<design>/data_structures.json`  
✅ `build/<design>/<design>_validation.rpt`  
✅ Fabric Utilization Report printed with **0 validation errors**

---

## Phase 2 (Placement: Greedy + SA): All requirements met
✅ `build/<design>/<design>.map` *(greedy placement)*  
✅ `build/<design>/<design>_sa.map` *(SA-refined placement)*  
✅ `build/<design>/<design>_density.png` *(placement density heatmap)*  
✅ `build/<design>/<design>_net_length_hist.png` *(net length histogram)*  
✅ `sa_knob_analysis.png` *(required SA knob analysis plot)*

---

## Phase 3 (CTS + ECO): All requirements met
✅ `build/<design>/<design>_cts.map`  
✅ `build/<design>/<design>_final.v` *(post-CTS/ECO final netlist)*  
✅ `build/<design>/<design>_cts_vis.png` *(CTS visualization output)*

---

## Phase 4 (Routing): Partially met
✅ `build/<design>/<design>_fixed.def` *(make_def met)*  
✅ `build/<design>/<design>_renamed.v` *(rename.v met)*  
✅ `src/route.tcl` *(route.tcl met / invoked)*  

❌ Routing did not finish successfully (congestion / GRT error), so final routed outputs are missing/incomplete:
- ⚠️ `build/<design>/<design>.spef` *(not present in current build folder)*  
- ⚠️ `build/<design>/<design>_layout.png` *(not present)*  
- ⚠️ `build/<design>/<design>_congestion.png` *(not present — only `<design>_congestion.rpt` exists)*  

---

## Phase 5 (STA): Partially met
✅ `src/sta.tcl` *(sta.tcl met / invoked)*  

❌ STA did not pass / required STA outputs are missing in current build folder:
- ❌ `build/<design>/<design>.sdc` *(not present)*  
- ❌ `build/<design>/<design>_setup.rpt` *(not present)*  
- ❌ `build/<design>/<design>_slack.png` *(not present)*  
- ❌ `build/<design>/<design>_critical_path.png` *(not present)*  

---

## 4) SA Knob Analysis (Required)

### Plot
  <img width="2382" height="1580" alt="image" src="https://github.com/user-attachments/assets/8970588d-fea6-4644-a5ea-4ff263af145c" />


Based on the knob analysis results (Pareto trade-off between HPWL and runtime), we recommend the following **default** SA settings:

- **`T_initial`**: `4_000_000`
- **`alpha`**: `0.80`
- **`num_temp_steps`**: `250`
- **`moves_per_temp`**: `1000`
- **`P_refine`**: `0.90`
- **`W_initial`**: `0.30`
- **`beta`**: `0.90`
- **`seed`**: `42` (for reproducibility)

#### Rationale

- **Quality:** Across the sweep, `alpha = 0.80` consistently produced the best (or near-best) HPWL compared to more aggressive cooling (higher `alpha`) that can “freeze” too early.
- **Stability/Refinement:** A higher `P_refine` (0.90) improved HPWL by spending more moves in local improvement/refinement once the search is in a good region.
- **Exploration window:** `W_initial = 0.30` with `beta = 0.90` maintained enough early exploration without making the search too random late in the schedule.
- **Runtime vs QoR trade-off:** Increasing `num_temp_steps` improves HPWL but increases runtime. `num_temp_steps = 250` is a good **default** because it captures most of the HPWL gains seen at larger step counts (e.g., 350/500) while keeping runtime reasonable.

> Note: If runtime is the primary constraint, a “fast” preset would use `num_temp_steps = 60`. If maximum QoR is the primary goal, increasing to `num_temp_steps = 350–500` can further reduce HPWL at additional runtime cost. 
## 5) Regression Suite Comparison Dashboard

| Design Name | Util % | Placer Alg. | HPWL (mm) | WNS (ns) | TNS (ns) |
|---|---:|---|---:|---:|---:|
| Arith | 0.40% | Greedy+SA | 12.82 | N/A | N/A |
| aes_128 | 75.70% | Greedy+SA | 12487725.800 | N/A | N/A |
| soc | 62.01% | Greedy+SA | 23529099.160 | N/A | N/A |
| 6502 | 2.55% | Greedy+SA | 243.71 | N/A | N/A |
| Z80 | ..% | Greedy+SA |  | 1256.984 | N/A |
**Notes**
- **Util %** is computed from the Fabric Utilization Report: total used instances / total available fabric slots.
- **WNS/TNS** are listed as **N/A** here because STA outputs (`*_setup.rpt`) are not present in the current build artifacts.

---

## 6) Analysis

### 6.1 Does the placer scale well with high utilization?
- The flow supports both Greedy and SA refinement and produces consistent placement artifacts and visuals.
- A full scaling study across multiple utilization points requires running the regression suite across additional designs (e.g., UART/FPU/etc.) and recording runtime + HPWL per design.

### 6.2 Do high-congestion designs correlate with worse WNS/TNS?
- Routing congestion is reported by OpenROAD (`build/arith/arith_congestion.rpt`), and routing errors can prevent convergence.
- When routing does not converge, STA quality is typically degraded (or STA deliverables may be missing), because post-route parasitics/paths cannot be fully extracted.

### 6.3 Why do specific designs fail timing?
- For this snapshot, STA deliverables are not present in `build/arith/`, so we cannot report exact worst paths (critical path overlay / slack histogram).
- The most likely root cause is routing non-convergence due to congestion, which prevents producing a clean post-route netlist/DEF/SPEF set for signoff STA.

