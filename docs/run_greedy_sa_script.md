# How to Run the Placement Flow (Greedy and SA)

This project provides a full placement pipeline:

1. **Generate data structures**  
2. **Run the greedy placer**  
3. **Run simulated annealing (SA)**  
4. **Produce final optimized placement map**

All of this is automated using:

```
scripts/run_greedy_sa.sh
```

---

## 1. Basic Usage

To run the entire flow for a design (e.g., `6502`) with default SA parameters:

```bash
bash scripts/run_greedy_sa.sh 6502
```

This will generate:

- `build/6502/data_structures.json`
- `build/6502/6502.map` (greedy placement)
- `build/6502/6502_sa.map` (simulated annealing optimized placement)

---

## 2. Running with Custom SA Parameters

The script allows you to override simulated annealing knobs:

| Parameter | Meaning                                      |
|----------|----------------------------------------------|
| `--num-temp-steps` | Number of temperature levels                 |
| `--moves-per-temp` | Moves attempted per temp level               |
| `--T-initial` | Starting temperature                         |
| `--alpha` | Cooling rate per step                        |
| `--P-refine` | Probability of “Refine” vs “Explore” move (P_explore = 1 - P_refine) |
| `--W-initial` | Initial window size (fraction of die)        |
| `--beta` | Window cooling rate                          |
| `--seed` | RNG seed                                     |

### Example:

```bash
bash scripts/run_greedy_sa.sh 6502   --num-temp-steps 60   --moves-per-temp 1000   --T-initial 200   --alpha 0.95   --P-refine 0.7   --W-initial 0.5   --beta 0.95   --seed 42
```

---

## 3. Output Files

After running the script:

📄 **Greedy placement:**  
`build/<design>/<design>.map`

📄 **Simulated annealing placement:**  
`build/<design>/<design>_sa.map`

📄 **Generated data structures:**  
`build/<design>/data_structures.json`

---

## 4. Requirements:

The project directory structure:

```
build/<design>/<design>_logical_db.json
build/fabric/fabric_db.json
src/dataStructuresGenerator.py
src/greedyPlacer.py
src/simulated_annealing.py
scripts/run_greedy_sa.sh
```

---

## 🛠5. Notes

- The script will stop on any error (`set -euo pipefail`).
- SA runtime depends on chosen parameters:
  - Slower cooling (**higher alpha**) → better quality, longer runtime.
  - More moves per temperature → better quality, longer runtime.
- The final placement after SA is always stored in:  
  **`<design>_sa.map`**
