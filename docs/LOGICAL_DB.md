# Logical Design Database (Phase 1) — Spec v1.0

## 1. Purpose 
- Define a clean and readable internal format for logical_db.json.
- This file is derived from Yosys <design>_mapped.json and serves as the canonical design database used in Phase 1 validation and all later phases of the toolflow.

## 2. Scope
- Extracting gates, pins, ports, and bit-level connectivity.
- Defining a normalized instance/port structure.
- Computing per-type cell counts for capacity validation.
- Recording basic design metadata.

## 3. Output Location
- build/`<design>`/`<design>`_logical_db.json

## 4. Structure of logical_db.json
- version: Schema version.
- design: Design name.
- top: Top module name.
- library: Standard-cell library tag used by the design.
- source: Provenance information (design file path, script generator).
- instances: All cell instances and their pin connections.
- ports: All top I/O ports and their bit connections.
- type_counts: Summary of cell type frequencies (used in validation).
- stats: Double check numbers.

### 4.1 Instances 

Each entry describes one gate instance extracted from the mapped Yosys design.

#### **Required Fields**
- **`type`** Standard-cell type name (string).  
- **`pins`** Mapping from pin name to list of bit IDs.  
- **`attrs`** Optional metadata (e.g., `is_seq`, `is_buffer`).  

#### **Pin Representation**
> **Every pin must map to a list of integer bit IDs (even for single-bit pins).**

This ensures consistent handling of scalar and bus pins.

#### **Example**
```json
"$abc$10000": {
  "type": "sky130_fd_sc_hd__or2_2",
  "pins": { "A": [124], "B": [125], "X": [126] },
  "attrs": { "is_seq": false, "is_buffer": false }
}
```

### 4.2 Ports 

Top-level inputs, outputs, and inouts of the design.

#### **Required Fields**
- **`direction`** `"input"`, `"output"`, or `"inout"`.  
- **`bits`** list of bit IDs.  
- **`attrs`** Optional metadata (e.g., `is_seq`, `is_buffer`).  


#### **Example**
```json
"clk":   { "direction": "input",  "bits": [2],  "attrs": { "is_clock": true } },
"rst_n": { "direction": "input",  "bits": [3],  "attrs": { "is_reset": true } },
"out_0": { "direction": "output", "bits": [84], "attrs": {} }
```

### 4.3 Type Counts and Stats

#### Type Counts
The `type_counts` table must exactly match the histogram of all instance types:

#### **Example**
```json
"type_counts": {
  "sky130_fd_sc_hd__or2_2": 2,
  "sky130_fd_sc_hd__clkinv_2": 1
}
```
Used in Phase 1 to verify fabric cell availability.

#### Stats

#### **Example summary metrics:**
```json
"stats": {
  "num_instances": 3,
  "num_unique_types": 2,
  "num_ports": 3,
  "num_bits_referenced": 7
}
```

## 5. Validation
Validate using the JSON Schema in `docs/logical_db.schema.json`:
```bash
python -m jsonschema \
    -i build/<design>/<design>_logical_db.json \
    docs/logical_db.schema.json
```
A valid Logical DB must produce no errors.

## 6. Versioning

- Current spec version: "1.0"
- Increment this version when structural or semantic changes are introduced.

