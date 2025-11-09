# Fabric Cells Parser

This script parses `fabric_cells.yaml` and `fabric.yaml` to:
- Count how many **physical cell types** exist in the fabric
- Produce a JSON file (`fabric_cells.json`) with tile/cell structure
- Output a text report (`type_counts.txt`) listing cell type counts

---
## ✅ Requirements
- Python 3.8+
- Install dependencies:

```sh
pip install pyyaml
```

---
## 📁 Required Files (same directory as script)
```
fabric_cells_parser.py   ← (the script)
fabric_cells.yaml        ← input file containing placed cells
fabric.yaml              ← input file defining template → physical cell mapping
```

---
## ▶️ How to Run
From terminal / command prompt:

```sh
python fabric_cells_parser.py
```

---
## 📄 Output Files
| Output File | Description |
|-------------|-------------|
| `type_counts.txt` | Count of each physical cell type |
| `fabric_cells.json` | Structured JSON of tiles and cells |

---
## 🚧 Notes
- If `width_sites` is missing in `fabric.yaml`, the script prints a warning.
- Any cell names without template matching will be skipped.

---
## Example Output (`type_counts.txt`)
```
sky130_fd_sc_hd__nand2_2: 1340
sky130_fd_sc_hd__inv_1: 800
...
```

---
If you have issues, ensure the YAML formats match the expected structure.

