# Data Structure Reference – Placement & SA

## Naming / Conventions

- **Instance names:** long Yosys IDs  
  Example: `"$abc$9276$auto$blifparse.cc:396:parse_blif$10859"`
- **Net IDs:** integers (e.g., `1199`, `1202`, …)
- **Fabric slots:** strings  
  Example: `"T16Y1__R0_BUF_0"`

---

# 1. Logical Netlist Structures

## 1.1 `logical_db`

**Name:** `logical_db`  

**Type / Shape:**
```python
logical_db: dict[str, dict]
```

Each instance record:
```python
logical_db[inst_name] = {
    "type": str,                    # sky130 cell, e.g. "sky130_fd_sc_hd__nand2_2"
    "pins": dict[str, list[int]],   # pin_name -> list of net IDs (ints)
    "attrs": dict,
    "params": dict,
}
```

**Example:**
```python
logical_db["$abc$...$10859"] = {
    "type": "sky130_fd_sc_hd__nand2_2",
    "pins": {
        "A": [1124],
        "B": [1198],
        "Y": [1199],
    },
    "attrs": {
        "is_seq": False,
        "is_buffer": False,
    },
    "params": {},
}
```

**Purpose:**  
Master description of logical cells (instances) and what nets they connect to.  

**Source of:**
- `cell_type`
- `inst_to_nets`
- `net_to_pins` (in combination with ports info)

---

## 1.2 `netlist_graph`

**Name:** `netlist_graph`  

**Type / Shape:**
```python
netlist_graph: dict[str, list[str]]
# instance -> list of neighboring instances
```

**Example:**
```python
netlist_graph["$abc$...$9994"] = [
    "$abc$...$10000",
    "$abc$...$10482",
]
netlist_graph["$abc$...$9999"] = [
    "$abc$...$10000",
]
```

**Purpose:**
- Captures instance-to-instance adjacency (graph view)
- Mainly used by the greedy placer (1A) to:
  - Find neighbors when “growing” placement
  - Implement “most-connected unplaced cell” heuristics

> Not used directly for HPWL (HPWL uses nets).

---

# 2. Fabric Structures

## 2.1 `fabric_db`

**Name:** `fabric_db`  

**Type / Shape:**
```python
fabric_db: list[dict]
```

Each slot record:
```python
slot_record = {
    "name": str,                # "T16Y1__R0_BUF_0"
    "type": str,                # logical type: "BUF", "NAND2", "DFF", ...
    "x": float,
    "y": float,
    "orient": str,              # "N", "FS", etc.
    "tile": str,                # e.g. "T16Y1"
    "width_sites": int,
    "physical_cell_type": str,  # actual sky130 cell, e.g. "sky130_fd_sc_hd__clkbuf_4"
}
```

**Example:**
```python
{
  "name": "T16Y1__R0_BUF_0",
  "type": "BUF",
  "x": 455.8,
  "y": 15.88,
  "orient": "N",
  "tile": "T16Y1",
  "width_sites": 6,
  "physical_cell_type": "sky130_fd_sc_hd__clkbuf_4",
}
```

**Purpose:**  
Describes the physical fabric slots we can place into.

**Source of:**
- `slot_coords`
- `slot_type`
- `slots_by_type`

---

## 2.2 `slot_coords`

**Name:** `slot_coords`  

**Type / Shape:**
```python
slot_coords: dict[str, tuple[float, float]]
# slot_name -> (x, y)
```

**Example:**
```python
slot_coords["T16Y1__R0_BUF_0"] = (455.8, 15.88)
```

**Purpose:**
- Maps each slot to its physical coordinates

**Used by:**
- Greedy placer (barycenter, nearest-slot search)
- SA for updating instance coordinates
- HPWL (via `cell_coords`)

---

## 2.3 `slot_type`

**Name:** `slot_type`  

**Type / Shape:**
```python
slot_type: dict[str, str]
# slot_name -> type, e.g. "BUF", "NAND2"
```

**Example:**
```python
slot_type["T16Y1__R0_BUF_0"] = "BUF"
```

**Purpose:**
- Ensures instances are placed only into compatible slot types  

**Used by:**
- Greedy placer to pick legal slots
- SA to enforce type-correct swaps

---

## 2.4 `slots_by_type`

**Name:** `slots_by_type`  

**Type / Shape:**
```python
slots_by_type: dict[str, list[str]]
# type -> list of slot names
```

**Example:**
```python
slots_by_type = {
    "BUF": [
        "T16Y1__R0_BUF_0",
        "T16Y1__R1_BUF_0",
        "T16Y1__R3_BUF_0",
        "T17Y1__R0_BUF_0",
        # ...
    ],
    "NAND2": [
        "T10Y3__R0_NAND2_0",
        "T10Y3__R0_NAND2_1",
        # ...
    ],
}
```

**Purpose:**
- Fast way to get available slots of a given cell type  

**Used by:**
- Greedy placer (choose a nearby free legal slot)
- Potentially SA (if type-constrained moves are needed)

---

# 3. Derived Netlist Structures for Placement / SA

## 3.1 `cell_type`

**Name:** `cell_type`  

**Type / Shape:**
```python
cell_type: dict[str, str]
# instance -> normalized type, e.g. "NAND2", "DFF", "BUF"
```

**Example:**
```python
cell_type["$abc$...$10859"] = "NAND2"
cell_type["$abc$...$10861"] = "OR2"
```

**Purpose:**  
Normalization layer between:
- Yosys cell names (`sky130_fd_sc_hd__nand2_2`) and  
- Fabric types (`"NAND2"`, `"OR2"`, `"DFF"`, `"BUF"`, etc.)

**Used by:**
- Greedy placer when picking correct slot types
- SA to validate swaps

---

## 3.2 `inst_to_nets`

**Name:** `inst_to_nets`  

**Type / Shape:**
```python
inst_to_nets: dict[str, set[int]]
# instance -> set of net IDs
```

**Example source:**
```python
logical_db["$abc$...$10859"]["pins"] = {
    "A": [1124],
    "B": [1198],
    "Y": [1199],
}
```

**Derived result:**
```python
inst_to_nets["$abc$...$10859"] = {1124, 1198, 1199}
```

**Purpose:**
- Lists all nets an instance touches  

**Used by:**
- Greedy grow stage (connectivity / “already placed neighbors”)  
- SA to find affected nets when swapping two instances (for ΔHPWL)

---

## 3.3 `net_to_pins`

**Name:** `net_to_pins`  

**Type / Shape:**
```python
net_to_pins: dict[int, list[tuple[str, str | None]]]
# net_id -> list of (inst_or_pin_name, pin_name_or_None)
```

**Example:**
```python
net_to_pins[1199] = [
    ("$abc$...$10859", "Y"),    # output of NAND2
    ("$abc$...$10861", "A"),    # input of OR2
    ("pin_GPIO0", None),        # top-level pin driving/receiving this net
]
```

**Purpose:**
- Provides the full list of pins and instances on each net  

**Core structure for:**
- HPWL per net  
- Total HPWL  
- ΔHPWL in SA

---

# 4. Pin Structures

## 4.1 `pin_coords`

**Name:** `pin_coords`  

**Type / Shape:**
```python
pin_coords: dict[str, tuple[float, float]]
# "pin_<PORTNAME>" -> (x, y)
```

**Example:**
```python
pin_coords = {
    "pin_GPIO0": (5.0,   250.0),
    "pin_GPIO7": (495.0, 260.0),
    "pin_CLK":   (250.0,   5.0),
}
```

**Purpose:**
- Gives physical locations of top-level I/O pins  

**Used by:**
- Greedy placer “seed” stage (place cells near their I/O pins)  
- HPWL and ΔHPWL (nets touching I/Os)

---

# 5. Placement / SA Structures

These are produced by Task 1A (greedy) and mutated by Task 1B (SA).

## 5.1 `placement`

**Name:** `placement`  

**Type / Shape:**
```python
placement: dict[str, str]
# instance -> slot_name
```

**Example:**
```python
placement = {
    "$abc$...$10859": "T10Y3__R0_NAND2_0",
    "$abc$...$10860": "T10Y3__R0_NAND2_1",
    "$abc$...$10861": "T12Y2__R1_OR2_0",
}
```

**Purpose:**
- Core mapping from logical cells to physical slots  
- Output of 1A, input to 1B  
- Written to disk as `<design>.map` (after greedy and again after SA)

---

## 5.2 `reverse`

**Name:** `reverse`  
**Owner:** Task 1A (greedy)  

**Type / Shape:**
```python
reverse: dict[str, str]
# slot_name -> instance (or absent/None if unused)
```

**Example:**
```python
reverse = {
    "T10Y3__R0_NAND2_0": "$abc$...$10859",
    "T10Y3__R0_NAND2_1": "$abc$...$10860",
    "T12Y2__R1_OR2_0":   "$abc$...$10861",
}
```

**Purpose:**
- Fast lookup of which cell is in a given slot  

**Used by:**
- Greedy placer to check if a slot is free  
- SA to pick two slots/instances to swap

---

## 5.3 `cell_coords`

**Name:** `cell_coords`  

**Type / Shape:**
```python
cell_coords: dict[str, tuple[float, float]]
# instance -> (x, y)
```

**Example:**
```python
cell_coords["$abc$...$10859"] = slot_coords["T10Y3__R0_NAND2_0"]  # (100.2, 35.6)
cell_coords["$abc$...$10861"] = slot_coords["T12Y2__R1_OR2_0"]    # (140.0, 80.0)
```

**Purpose:**
- Actual physical coordinates of each placed instance  

**Used by:**
- HPWL and ΔHPWL  
- Greedy grow stage (barycenter)  
- SA every time we evaluate a move

---

# 6. HPWL Using These Structures (Quick Summary)

For any `net_id`:

1. Get all pins:  
   ```python
   pins = net_to_pins[net_id]
   ```
2. For each `(inst_or_pin, _)` in `pins`:
   - If `inst_or_pin.startswith("pin_")` → use `pin_coords[inst_or_pin]`
   - Else → use `cell_coords[inst_or_pin]`

3. Compute HPWL:

```python
xs = [x for (x, _) in coords]
ys = [y for (_, y) in coords]

HPWL_net = (max(xs) - min(xs)) + (max(ys) - min(ys))
```

Total HPWL:
```python
total_hpwl = sum(HPWL_net(net_id) for net_id in net_to_pins)
```

---

# 7. `DesignContext` Wrapper (Not Required)

## 7.1 What is `DesignContext`?

A lightweight Python (data) class that *groups all shared structures* into a single object.

Instead of:
```python
greedy_place(
    logical_db,
    fabric_db,
    inst_to_nets,
    net_to_pins,
    slot_coords,
    slot_type,
    slots_by_type,
    pin_coords,
    placement,
    reverse,
    cell_coords,
)
```

You could do:
```python
greedy_place(ctx)
simulated_annealing(ctx)
```

Where `ctx` is a `DesignContext` instance.

## 7.2 Example Definition

```python
from dataclasses import dataclass
from typing import Dict, List, Tuple, Set


@dataclass
class DesignContext:
    # Raw / parsed
    logical_db: dict
    fabric_db: list

    # Derived netlist
    inst_to_nets: Dict[str, Set[int]]
    net_to_pins: Dict[int, list]
    cell_type: Dict[str, str]

    # Fabric-derived
    slot_coords: Dict[str, Tuple[float, float]]
    slot_type: Dict[str, str]
    slots_by_type: Dict[str, List[str]]

    # Pins
    pin_coords: Dict[str, Tuple[float, float]]

    # Placement / SA
    placement: Dict[str, str]
    reverse: Dict[str, str]
    cell_coords: Dict[str, Tuple[float, float]]
```

Then somewhere in your setup code:
```python
ctx = DesignContext(
    logical_db=logical_db,
    fabric_db=fabric_db,
    inst_to_nets=inst_to_nets,
    net_to_pins=net_to_pins,
    cell_type=cell_type,
    slot_coords=slot_coords,
    slot_type=slot_type,
    slots_by_type=slots_by_type,
    pin_coords=pin_coords,
    placement=placement,
    reverse=reverse,
    cell_coords=cell_coords,
)
```