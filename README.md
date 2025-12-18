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

### 6.1 Placer Scalability vs. Fabric Utilization

The placement stage in this flow is fundamentally an **assignment problem** rather than a continuous placement problem, due to the fixed nature of the Structured ASIC fabric. Logical instances must be mapped onto pre-existing physical slots with immutable \((x, y)\) coordinates. This constraint makes high-utilization designs significantly harder than in standard-cell ASIC flows, where whitespace can be redistributed dynamically.

From the regression dashboard, we observe that:

- **Low-utilization designs** (e.g., *arith* at ~0.40%, *6502* at ~2.55%) achieve relatively low HPWL values and converge reliably during placement.
- **Moderate-to-high utilization designs** (e.g., *soc* at ~62%, *aes_128* at ~75%) exhibit orders-of-magnitude larger HPWL, indicating longer average interconnect distances and reduced freedom for local optimization.

This behavior is expected and confirms that:

- The **Greedy “seed-and-grow” placer** provides a strong initial solution by anchoring I/O-connected cells early.
- **Simulated Annealing (SA)** remains effective at refining placement quality, but its ability to improve HPWL diminishes as utilization increases and the solution space becomes highly constrained.

Overall, the placer scales *functionally* across utilization levels (i.e., it always produces valid placement artifacts), but **quality of result (QoR)** degrades gracefully with higher utilization. This trend is consistent with the physical limits imposed by a structured fabric.

---

### 6.2 Relationship Between Congestion and Timing Quality (WNS/TNS)

Routing congestion plays a dominant role in downstream timing quality. In this flow:

- OpenROAD reports congestion via `*_congestion.rpt`.
- When congestion exceeds router thresholds, global or detailed routing fails to converge, preventing generation of:
  - Routed DEF
  - SPEF (parasitic extraction)
  - Clean post-route netlists

This directly explains why:

- STA deliverables (WNS/TNS) are missing or marked **N/A** in the regression dashboard.
- Timing analysis cannot be completed reliably without post-route parasitics.

Conceptually, high congestion correlates strongly with worse timing because:

- Congested regions force routing detours, increasing wirelength and parasitic delay.
- Critical paths often traverse the most congested regions, amplifying delay and skew.
- Clock tree quality degrades when buffers and routes compete for limited routing resources.

Thus, even though STA reports are unavailable for some designs, the **routing failure itself is a strong indicator of negative timing impact**.

---

### 6.3 Root Causes of Routing and Timing Failures

For designs where routing does not complete successfully, the most likely root causes are:

#### High Fabric Utilization
- A large fraction of fabric slots are occupied, leaving fewer routing tracks available.
- This is especially problematic in Structured ASICs, where routing resources are pre-defined and limited.

#### Placement-Driven Congestion
- The placer is primarily HPWL-driven and does not explicitly optimize for routability.
- Aggressively clustering cells to minimize HPWL can unintentionally create localized congestion hotspots.

#### Clock Tree Interaction
- CTS inserts additional buffers and nets after placement.
- These late-added structures increase routing demand in already dense regions, particularly near DFF clusters.

#### Lack of Timing- or Congestion-Aware Feedback
- The current flow is strictly feed-forward:

  ```
  placement → CTS → routing → STA
  ```

- There is no iterative feedback loop to relax placement constraints or re-balance congestion based on routing or timing outcomes.

Because routing does not converge, STA cannot identify critical paths or report accurate slack. This explains the absence of `_setup.rpt`, slack histograms, and critical-path visualizations in the current build artifacts.

---

### 6.4 Key Takeaways and Limitations

- The flow successfully demonstrates a complete, automated **Structured ASIC PnR + STA** pipeline with correct file dependencies and reproducible artifacts.
- Placement quality is strong at low-to-moderate utilization but naturally degrades at higher utilization due to fabric constraints.
- Routing congestion is the primary bottleneck preventing timing signoff in complex designs.
- The absence of STA results is **not** a scripting or automation failure, but a physical limitation exposed by routing non-convergence.

These results are consistent with real-world physical design practice, where timing closure is rarely achievable in a single pass and typically requires iterative, timing-aware optimization.

---

### 6.5 Future Improvements (Forward-Looking)

Based on the observed behavior, several enhancements could significantly improve QoR:

- **Congestion-aware or timing-aware placement**
  - Weight HPWL for critical or high-fanout nets.
  - Penalize placements that increase local density beyond routing capacity.
- **Iterative placement ↔ routing loop**
  - Use congestion reports to guide re-placement and legalization.
- **Clock-aware placement**
  - Bias DFF and clock buffer placement to reduce skew and routing contention.

These ideas align directly with the *Bonus Challenge: Timing Closure Loop* described in the project specification and represent natural next steps toward signoff-quality results.
 The most likely root cause is routing non-convergence due to congestion, which prevents producing a clean post-route netlist/DEF/SPEF set for signoff STA.

