#!/usr/bin/env bash
set -euo pipefail

# Phase 1 driver:
# 1) fabric_cells_parser.py      (build fabric_db_1.json, type counts)
# 2) fabric_cells_by_type.py     (group cells by logical type: TAP, NAND, ...)
# 3) parse_design.py             (parse logical netlist / design data)
# 4) netlistGraph.py             (build graph representation)
# 5) validator.py                (sanity checks on graph/fabric/design)
# 6) visualize.py                (any Phase 1 visualization)
#
# Usage:
#   ./scripts/run_phase1.sh          # default design = 6502
#   ./scripts/run_phase1.sh arith    # or any other design name

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &>/dev/null && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

# Default design is 6502 unless overridden as $1
DESIGN="${1:-6502}"

echo "========================================"
echo " Phase 1 flow"
echo " Project root : ${PROJECT_ROOT}"
echo " Design       : ${DESIGN}"
echo "========================================"
echo

cd "$PROJECT_ROOT"

# 1) Build fabric DB (cells + pins)
echo "[1/6] Running fabric_cells_parser.py..."
python src/fabric_cells_parser.py

# 2) Group cells by logical type (TAP, NAND, ...)
echo
echo "[2/6] Running fabric_cells_by_type.py..."
python src/fabric_cells_by_type.py

# 3) Parse design (mapped Yosys JSON -> logical DB)
#    Input:  build/<design>/<design}_mapped.json
#    Output: build/<design>/<design>_logical_db.json
echo
echo "[3/6] Running parse_design.py..."
python src/parse_design.py \
  --mapped-json "designs/${DESIGN}_mapped.json" \
  --design "${DESIGN}" \
  --outdir "build"

# 4) Build netlist graph
echo
echo "[4/6] Running netlistGraph.py..."
python src/netlistGraph.py \
  --design "${DESIGN}"

# 5) Validate consistency between design, graph, and fabric
echo
echo "[5/6] Running validator.py..."
python src/validator.py "${DESIGN}"

# 6) Visualize results
echo
echo "[6/6] Running visualize.py..."
python src/visualize.py \
  --fabric-db "build/fabric/fabric_db.json" \
  --out "build/fabric/fabric_layout.png"

echo
echo "========================================"
echo " Phase 1 flow completed for design: ${DESIGN}"
echo "========================================"