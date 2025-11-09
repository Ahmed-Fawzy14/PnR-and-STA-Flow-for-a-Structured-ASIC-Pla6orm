# Netlist Graph Generator

This script reads JSON design files from `./designs` and generates a **netlist adjacency graph** in JSON format. Each output file shows:

```
driver_cell → [ sink_cells... ]
```

---

## ✅ Requirements

* Python 3.8+

No extra libraries needed — uses only built‑in modules.

---

## 📁 Required Folder Structure

```
netlistGraph.py          ← (the script)
/designs                 ← folder containing design JSON files
    design1.json
    design2.json
/graphs                  ← (auto‑created) output folder for generated graphs
```

---

## ▶️ How to Run

From terminal or command prompt:

```sh
python netlistGraph.py
```

The script will:

1. Scan `./designs` for `.json` files.
2. Parse each design's module.
3. Build driver → sinks netlist relationships.
4. Save results into `./graphs/NAME_netlist_graph.json`.

---

## 📄 Output Example

Input (`design.json`):

```
A drives net 12
B and C read net 12
```

Output (`design_netlist_graph.json`):

```
{
    "A": ["B", "C"]
}
```

---

## 🚧 Notes

* If `./designs` has no JSON files, the script prints a message and stops.
* Output files are created automatically inside `./graphs`.
* Existing outputs are overwritten if names match.

---
