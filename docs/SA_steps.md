# Big Picture

The algorithm starts from a valid placement map (instances → slots) and tries to reduce the total HPWL (half-perimeter wirelength) of the netlist by repeatedly making small perturbations (moves), accepting some worse moves to escape local minima, and gradually reducing the search scope (window) and temperature so it converges. This follows the general simulated annealing (SA) technique.

---

## Data Structures Feeding into SA

Here are the key structures and how they plug into the algorithm:

- **`instances` (`logical.instances`)**  
  Each logical cell with type and pins.

- **`slot_info`**  
  Mapping of each physical slot → `(x, y)` coordinates (and other info).

- **`slots_by_phys_type`**  
  Groups of slot names by physical cell type.

- **`initial_placement`**  
  Initial map from each logical instance → a slot name.

- **`net_to_insts`**  
  Derived from `instances`, mapping each bit-ID (net) → set of instance names that connect to that net.

- **`inst_type` + `type_to_insts`**  
  Derived mapping of each instance → its cell type, and each cell type → list of instances of that type.

- **`free_slots_by_type`**  
  Derived list of currently unused slots for each cell type.

- **`die_bbox`**  
  `(min_x, max_x, min_y, max_y)` of all slot coordinates; used to define the “window” for explore moves.

All these feed into the SA loop so that the algorithm knows:

- which moves are legal (type-compatible),
- the cost of the current solution (via HPWL),
- and how to limit the search region (via window size).

---

## Move Set

Two types of moves are used:

- **Refine move (`swap`)**  
  Picks two instances of the same cell type and swaps their slots.  
  → Doesn’t change which slots are used, just permutes assignments.

- **Explore move (`move_to_free_slot`)**  
  Picks one instance of a given type and moves it from its current slot to another *free* slot of the same type.  
  Optionally restricted to a geographic “window” around the instance’s current coordinate (window size = \(W_k\) fraction of die width/height).

By mixing these two moves, the algorithm can both **fine-tune** (swap) and **explore larger changes** (move to a free slot).

---

## Cooling Schedule & Window Schedule

- **Temperature schedule:**

  \[
  T_k = T_{\text{initial}} \times \alpha^{k}
  \]

  where \(k\) is the temperature step \((0 \le k < \text{num\_temp\_steps})\).

- **Window schedule:**

  \[
  W_k = W_{\text{initial}} \times \beta^{k}
  \]

  So early in the run, \(W_k\) is large (explore moves can go far); later in the run it shrinks (moves become local).

- **`moves_per_temp`**: number of move-attempts at each temperature level.  
- **`P_refine`**: probability of choosing a refine vs. explore move at each attempt.

These knobs control **exploration vs. exploitation**:

- early: high temperature + large window → broad exploration,  
- later: low temperature + small window → fine tuning around good solutions.

---

## Acceptance Rule

For each proposed move:

1. Compute the new cost = total HPWL of current placement **after** the move.
2. Compute \(\Delta = \text{new\_cost} - \text{current\_cost}\).
3. Apply:

   - If \(\Delta \le 0\): the move decreases (or keeps) the cost → **always accept**.
   - Else (\(\Delta > 0\)): the move worsens cost → **accept with probability**
     \[
     p = \exp\left(-\frac{\Delta}{T_k}\right)
     \]
     where \(T_k\) is the current temperature.

4. If move is **rejected** → revert the move (swap back or move back).

This acceptance rule allows uphill moves early (when \(T\) is large) to help escape local minima, but gradually becomes stricter as \(T\) shrinks. This is standard SA behavior.

---

## SA Main Loop (Step-by-Step)

1. **Pre-compute derived structures**

   - Compute `net_to_insts`, `inst_type`, `type_to_insts`, `free_slots_by_type`, `die_bbox`.

2. **Initialize**

   - Set `placement = initial_placement`.
   - Compute `current_cost = compute_total_hpwl(placement, ...)`.
   - Initialize:
     - `best_cost = current_cost`
     - `best_placement = placement`.

3. **Annealing over temperature steps**

   For \(k = 0\) to `num_temp_steps − 1`:

   1. Set \(T_k\) and \(W_k\) according to the schedules.
   2. Repeat `moves_per_temp` times:
      - With probability `P_refine`, attempt a **swap** move;  
        else attempt a **move_to_free_slot**.
      - If the chosen move type is impossible (e.g., no free slots of that type), **fall back** to the other move type.
      - After proposing a move, compute `new_cost`.
      - Apply the **acceptance rule**:
        - If accepted:
          - Update `current_cost = new_cost`.
          - If `current_cost < best_cost`:
            - Update `best_cost` and `best_placement`.
        - If rejected:
          - Revert the move.
   3. Optionally, log progress every `report_interval`.

4. **Finalize**

   - After all temperature steps, return `best_placement` and `best_cost`.
   - Write the best placement map to the output file.

---
