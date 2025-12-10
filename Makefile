SHELL  := /usr/bin/env bash
PYTHON := python

# ---------------------------------------------------------
# Design + paths
# ---------------------------------------------------------
DESIGN ?= 6502

BUILD_DIR     := build/$(DESIGN)
FABRIC_DB     := build/fabric/fabric_db.json
MAPPED_JSON   := designs/$(DESIGN)_mapped.json
MAP_FILE      := $(BUILD_DIR)/$(DESIGN).map
MAP_FILE_SA      := $(BUILD_DIR)/$(DESIGN)_sa.map
MAP_FILE_CTS      := $(BUILD_DIR)/$(DESIGN)_cts.map
FINAL_NETLIST := $(BUILD_DIR)/$(DESIGN)_final.v

RENAMED_NET   := $(BUILD_DIR)/$(DESIGN)_renamed.v
FIXED_DEF     := $(BUILD_DIR)/$(DESIGN)_fixed.def
SPEF_FILE     := $(BUILD_DIR)/$(DESIGN).spef

SDC_SRC       :=  tech/design.sdc
SDC_BUILD     := $(BUILD_DIR)/$(DESIGN).sdc

STA_SETUP_RPT := $(BUILD_DIR)/$(DESIGN)_setup.rpt

ROUTE_TCL     := src/route.tcl
STA_TCL       := src/sta.tcl

VALIDATE_STAMP := $(BUILD_DIR)/.validate.ok
DEPS_FILE := requirements.txt

PHASE1_SCRIPTS := \
    src/fabric_cells_parser.py \
    src/fabric_cells_by_type.py \
    src/parse_design.py \
    src/netlistGraph.py \
    src/validator.py \
    src/visualize.py

PLACER_SCRIPTS := \
    src/placer.py \
    src/greedyPlacementVisualization.py \
    src/visualize_graphs.py

ECO_SCRIPTS := \
    src/eco_generator.py \
    src/generate_verilog.py \
    src/generate_pd_eco.py \
    src/animated_eco_pd.py \
    src/visualize_cts.py

.PHONY: all deps validate place eco route sta clean

# ---------------------------------------------------------
# all: full flow through STA
# ---------------------------------------------------------
all: sta

# ---------------------------------------------------------
# deps: pip install
# ---------------------------------------------------------
deps:
	@echo "=== Installing Python dependencies (if $(DEPS_FILE) exists) ==="
	@if [ -f "$(DEPS_FILE)" ]; then \
		$(PYTHON) -m pip install -r "$(DEPS_FILE)"; \
	else \
		echo "No $(DEPS_FILE) found; please install dependencies manually."; \
	fi

# ---------------------------------------------------------
# Phase 1: validate
# ---------------------------------------------------------
validate: $(VALIDATE_STAMP)

$(VALIDATE_STAMP): $(MAPPED_JSON) $(PHASE1_SCRIPTS)
	@mkdir -p "$(BUILD_DIR)"

	@echo "========================================"
	@echo " Phase 1 flow"
	@echo " Design       : $(DESIGN)"
	@echo "========================================"
	@echo

	@echo "[1/6] Running fabric_cells_parser.py..."
	@$(PYTHON) src/fabric_cells_parser.py

	@echo
	@echo "[2/6] Running fabric_cells_by_type.py..."
	@$(PYTHON) src/fabric_cells_by_type.py

	@echo
	@echo "[3/6] Running parse_design.py..."
	@$(PYTHON) src/parse_design.py \
	  --mapped-json "designs/$(DESIGN)_mapped.json" \
	  --design "$(DESIGN)" \
	  --outdir "build"

	@echo
	@echo "[4/6] Running netlistGraph.py..."
	@$(PYTHON) src/netlistGraph.py --design "$(DESIGN)"

	@echo
	@echo "[5/6] Running validator.py..."
	@$(PYTHON) src/validator.py "$(DESIGN)"

	@echo
	@echo "[6/6] Running visualize.py..."
	@$(PYTHON) src/visualize.py \
	  --fabric-db "$(FABRIC_DB)" \
	  --out "build/fabric/fabric_layout.png"

	@echo
	@echo "========================================"
	@echo " Phase 1 flow completed for design: $(DESIGN)"
	@echo "========================================"

	@touch "$@"

# ---------------------------------------------------------
# Phase 2: place
# ---------------------------------------------------------
place: $(MAP_FILE)

$(MAP_FILE): $(VALIDATE_STAMP) $(MAPPED_JSON) $(PLACER_SCRIPTS)
	@mkdir -p "$(BUILD_DIR)"

	@echo "========================================"
	@echo " Phase 2 (Placement) flow"
	@echo " Design       : $(DESIGN)"
	@echo "========================================"
	@echo

	@echo "[1/3] Running placer.py (greedy + SA)..."
	@$(PYTHON) src/placer.py --design "$(DESIGN)"

	@echo
	@echo "[2/3] Running greedyPlacementVisualization.py..."
	@$(PYTHON) src/greedyPlacementVisualization.py \
	  --design "$(DESIGN)" \
	  --data "build/$(DESIGN)/data_structures.json" \
	  --fabric "$(FABRIC_DB)" \
	  --output "build/$(DESIGN)/placement_animation.gif"

	@echo
	@echo "[3/3] Running visualize_graphs.py (density + net HPWL hist)..."
	@$(PYTHON) src/visualize_graphs.py \
	  --data-structures "build/$(DESIGN)/data_structures_sa.json" \
	  --placement-map   "$(MAP_FILE_SA)" \
	  --design-name     "$(DESIGN)" \
	  --out-density     "build/$(DESIGN)/$(DESIGN)_density.png" \
	  --out-net-length  "build/$(DESIGN)/$(DESIGN)_net_length_hist.png"

	@echo
	@echo "========================================"
	@echo " Placement flow completed for design: $(DESIGN)"
	@echo "========================================"

# ---------------------------------------------------------
# Phase 3: eco
# ---------------------------------------------------------
eco: $(FINAL_NETLIST)

$(FINAL_NETLIST): $(MAP_FILE) $(ECO_SCRIPTS)
	@mkdir -p "$(BUILD_DIR)"

	@echo "========================================"
	@echo " Phase 3 (CTS + Power-down ECO) flow"
	@echo " Design       : $(DESIGN)"
	@echo "========================================"
	@echo

	@echo "[1/5] Running eco_generator.py (CTS + power-down ECO)..."
	@$(PYTHON) src/eco_generator.py --design "$(DESIGN)"

	@echo
	@echo "[2/5] Running generate_verilog.py..."
	@$(PYTHON) src/generate_verilog.py --design "$(DESIGN)"

	@echo
	@echo "[3/5] Running generate_pd_eco.py..."
	@$(PYTHON) src/generate_pd_eco.py --design "$(DESIGN)"

	@echo
	@echo "[4/5] Running animated_eco_pd.py..."
	@$(PYTHON) src/animated_eco_pd.py --design "$(DESIGN)" --animate

	@echo
	@echo "[5/5] Running visualize_cts.py..."
	@$(PYTHON) src/visualize_cts.py \
	  --fabric "build/fabric/fabric_db.json" \
	  --map "build/$(DESIGN)/$(DESIGN)_sa.map" \
	  --old_netlist "build/$(DESIGN)/$(DESIGN)_mapped_netlist_graph.json" \
	  --new_netlist "build/$(DESIGN)/$(DESIGN)_cts_mapped_netlist_graph.json" \
	  --out "build/$(DESIGN)/$(DESIGN)_cts_vis.png"

	@echo
	@echo "========================================"
	@echo " Phase 3 completed for design: $(DESIGN)"
	@echo "========================================"

	@test -f "$(FINAL_NETLIST)" || cp "build/$(DESIGN)/$(DESIGN)_pd_eco_netlist.v" "$(FINAL_NETLIST)"

# ---------------------------------------------------------
# Phase 4: route
# Order:
#   1) make_def.py   -> <design>_fixed.def
#   2) rename.py     -> <design>_renamed.v
#   3) openroad route.tcl -> <design>.spef
# ---------------------------------------------------------
route: $(SPEF_FILE)

$(FIXED_DEF): $(MAP_FILE) src/make_def.py
	@mkdir -p "$(BUILD_DIR)"
	@echo "========================================"
	@echo " Phase 4.1: Generating DEF with make_def.py"
	@echo " Design       : $(DESIGN)"
	@echo "========================================"
	@$(PYTHON) src/make_def.py --design "$(DESIGN)"

$(RENAMED_NET): $(FINAL_NETLIST) $(MAP_FILE) src/rename.py
	@mkdir -p "$(BUILD_DIR)"
	@echo "========================================"
	@echo " Phase 4.2: Renaming instances with rename.py"
	@echo " Design       : $(DESIGN)"
	@echo "========================================"
	@$(PYTHON) src/rename.py --design "$(DESIGN)"

$(SPEF_FILE): $(FIXED_DEF) $(RENAMED_NET) $(ROUTE_TCL)
	@mkdir -p "$(BUILD_DIR)"
	@echo "========================================"
	@echo " Phase 4.3: Routing with OpenROAD (route.tcl)"
	@echo " Design       : $(DESIGN)"
	@echo "========================================"
	@echo
	@DESIGN_NAME="$(DESIGN)" openroad -gui "$(ROUTE_TCL)"

# ---------------------------------------------------------
# Phase 5: sta
# Order:
#   1) (implicitly after route) .spef exists
#   2) copy SDC to build/<design>/
#   3) openroad sta.tcl -> <design>_setup.rpt, etc.
# ---------------------------------------------------------
sta: $(STA_SETUP_RPT)

$(SDC_BUILD): $(SDC_SRC)
	@mkdir -p "$(BUILD_DIR)"
	@cp "$(SDC_SRC)" "$(SDC_BUILD)"

$(STA_SETUP_RPT): $(SPEF_FILE) $(RENAMED_NET) $(SDC_BUILD) $(STA_TCL)
	@mkdir -p "$(BUILD_DIR)"
	@echo "========================================"
	@echo " Phase 5: STA with OpenROAD (sta.tcl)"
	@echo " Design       : $(DESIGN)"
	@echo "========================================"
	@echo
	@DESIGN_NAME="$(DESIGN)" openroad -exit "$(STA_TCL)"

	@echo
	@echo "========================================"
	@echo " Visualizing STA results (visualize_sta.py)"
	@echo "========================================"
	@$(PYTHON) src/visualize_sta.py \
	    --fabric "build/fabric/fabric_db.json" \
	  	--map "build/arith/arith_cts.map" \
	  	--setup_rpt "build/arith/arith_setup.rpt" \
	  	--out_histogram "build/arith/arith_sta_slack_hist.png" \
	  	--out_critical "build/arith/arith_sta_critical_path.png" \
	  	--width 2000 \
	  	--slot-w 0.46 \
	  	--slot-h 2.72

# ---------------------------------------------------------
# clean
# ---------------------------------------------------------
clean:
	@echo ">>> Cleaning build/"
	@rm -rf build
