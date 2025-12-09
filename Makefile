# Makefile for PnR + PD-ECO + Verilog + Visualization flow

PYTHON      ?= python3
SRC_DIR     := src
BUILD_DIR   := build
FABRIC_DIR  := $(BUILD_DIR)/fabric

# --------- Top-level design (override on command line) ----------
DESIGN      ?= 6502

# --------- Key files for this design ----------
# Yosys mapped JSON lives under designs/
MAPPED_JSON      := designs/$(DESIGN)_mapped.json          # INPUT – must exist
LOGICAL_DB       := $(BUILD_DIR)/$(DESIGN)/$(DESIGN)_logical_db.json
NETLIST_GRAPH    := $(BUILD_DIR)/$(DESIGN)/$(DESIGN)_mapped_netlist_graph.json

# Greedy / ECO / Verilog data structures
DS_GREEDY        := $(BUILD_DIR)/$(DESIGN)/data_structures.json

# Greedy + SA maps
GREEDY_MAP       := $(BUILD_DIR)/$(DESIGN)/$(DESIGN).map
SA_DS            := $(BUILD_DIR)/$(DESIGN)/sa_data_structures.json
SA_MAP           := $(BUILD_DIR)/$(DESIGN)/$(DESIGN)_sa.map

# ECO outputs
ECO_GRAPH        := $(BUILD_DIR)/$(DESIGN)/$(DESIGN)_mapped_netlist_graph_after_pd_eco.json
ECO_UNUSED       := $(BUILD_DIR)/$(DESIGN)/$(DESIGN)_pd_unused_instances.json
ECO_TIEINFO      := $(BUILD_DIR)/$(DESIGN)/$(DESIGN)_pd_tielo_source.json
ECO_REPORT       := $(BUILD_DIR)/$(DESIGN)/$(DESIGN)_power_down_eco_report.txt

# Verilog outputs
VERILOG_PD       := $(BUILD_DIR)/$(DESIGN)/$(DESIGN)_pd_eco_netlist.v
VERILOG_RENAMED  := $(BUILD_DIR)/$(DESIGN)/$(DESIGN)_renamed.v

# Fabric (with pins merged in)
FABRIC_DB        := $(FABRIC_DIR)/fabric_db.json

# Visualization
PD_PLOT          := $(BUILD_DIR)/$(DESIGN)/$(DESIGN)_pd_eco_plot.png
PD_GIF           := $(BUILD_DIR)/$(DESIGN)/$(DESIGN)_pd_eco_anim.gif

# SA knobs (can be overridden)
SA_NUM_TEMP_STEPS ?= 60
SA_MOVES_PER_TEMP ?= 1000
SA_T_INITIAL      ?= 200.0
SA_ALPHA          ?= 0.95
SA_P_REFINE       ?= 0.7
SA_W_INITIAL      ?= 0.5
SA_BETA           ?= 0.95

.PHONY: all flow place sa eco verilog rename visualize fabric logical clean

# Default: run the whole flow up to renamed Verilog + static ECO plot
all: flow

flow: $(VERILOG_RENAMED) $(PD_PLOT)

# ----------------------------------------------------------------------
# Fabric + pins → build/fabric/fabric_db.json
# ----------------------------------------------------------------------
$(FABRIC_DB): fabric_cells.yaml fabric.yaml pins.yaml \
              $(SRC_DIR)/fabricCellsParser.py $(SRC_DIR)/pins_parser.py
	@echo "=== Building fabric_db.json (fabric + pins) ==="
	mkdir -p $(FABRIC_DIR)
	$(PYTHON) $(SRC_DIR)/fabricCellsParser.py
	$(PYTHON) $(SRC_DIR)/pins_parser.py
	# fabricCellsParser + pins_parser write 'fabric_cells.json' in CWD
	mv fabric_cells.json $(FABRIC_DB)

fabric: $(FABRIC_DB)

# ----------------------------------------------------------------------
# Logical DB from mapped JSON
#   INPUT: designs/<design>_mapped.json  (from Yosys)
# ----------------------------------------------------------------------
$(LOGICAL_DB): $(MAPPED_JSON) $(SRC_DIR)/parse_design.py
	@echo "=== Building logical_db for $(DESIGN) ==="
	$(PYTHON) $(SRC_DIR)/parse_design.py \
	    --mapped-json $< \
	    --design $(DESIGN) \
	    --outdir $(BUILD_DIR)

logical: $(LOGICAL_DB)

# ----------------------------------------------------------------------
# Netlist graph (driver -> sinks) for ECO + dataStructuresGenerator
#   netlistGraph.py scans ./designs and writes ./build/<name>_netlist_graph.json
# ----------------------------------------------------------------------
$(NETLIST_GRAPH): $(MAPPED_JSON) $(SRC_DIR)/netlistGraph.py
	@echo "=== Building driver→sinks netlist graph for $(DESIGN) ==="
	mkdir -p $(BUILD_DIR)/$(DESIGN)
	$(PYTHON) $(SRC_DIR)/netlistGraph.py
	mv $(BUILD_DIR)/$(DESIGN)_mapped_netlist_graph.json $(NETLIST_GRAPH)

# ----------------------------------------------------------------------
# data_structures.json for Greedy + ECO + Verilog
#   dataStructuresGenerator.py expects:
#     build/<design>/<design>_mapped_netlist_graph.json
#     build/<design>/<design>_logical_db.json
#     build/fabric/fabric_db.json
#   and writes build/<design>/data_structures.json
# ----------------------------------------------------------------------
$(DS_GREEDY): $(NETLIST_GRAPH) $(LOGICAL_DB) $(FABRIC_DB) $(SRC_DIR)/dataStructuresGenerator.py
	@echo "=== Building greedy/ECO data_structures.json for $(DESIGN) ==="
	$(PYTHON) $(SRC_DIR)/dataStructuresGenerator.py --design $(DESIGN)

# ----------------------------------------------------------------------
# Greedy placement
# ----------------------------------------------------------------------
$(GREEDY_MAP): $(DS_GREEDY) $(SRC_DIR)/greedyPlacer.py
	@echo "=== Running Greedy placer for $(DESIGN) ==="
	$(PYTHON) $(SRC_DIR)/greedyPlacer.py \
	    --design $(DESIGN) \
	    --data $(DS_GREEDY) \
	    --output $@

place: $(GREEDY_MAP)

# ----------------------------------------------------------------------
# SA data structures (separate JSON so we don't clash with greedy one)
# ----------------------------------------------------------------------
$(SA_DS): $(LOGICAL_DB) $(FABRIC_DB) $(SRC_DIR)/dataStructuresGenerator_SA.py
	@echo "=== Building SA data_structures for $(DESIGN) ==="
	$(PYTHON) $(SRC_DIR)/dataStructuresGenerator_SA.py \
	    --logical-db $(LOGICAL_DB) \
	    --fabric-db $(FABRIC_DB) \
	    --out-json $@

# ----------------------------------------------------------------------
# Simulated Annealing placer (uses SA_DS + greedy map as initial)
# ----------------------------------------------------------------------
$(SA_MAP): $(SA_DS) $(GREEDY_MAP) $(SRC_DIR)/simulated_annealing.py
	@echo "=== Running Simulated Annealing for $(DESIGN) ==="
	$(PYTHON) $(SRC_DIR)/simulated_annealing.py \
	    --data-structures $(SA_DS) \
	    --initial-map $(GREEDY_MAP) \
	    --out-map $@ \
	    --num-temp-steps $(SA_NUM_TEMP_STEPS) \
	    --moves-per-temp $(SA_MOVES_PER_TEMP) \
	    --T-initial $(SA_T_INITIAL) \
	    --alpha $(SA_ALPHA) \
	    --P-refine $(SA_P_REFINE) \
	    --W-initial $(SA_W_INITIAL) \
	    --beta $(SA_BETA)

sa: $(SA_MAP)

# ----------------------------------------------------------------------
# ECO: tie unused cells to conb_1.LO (eco_generator.py)
# ----------------------------------------------------------------------
$(ECO_GRAPH): $(NETLIST_GRAPH) $(LOGICAL_DB) $(SRC_DIR)/eco_generator.py
	@echo "=== Running PD ECO for $(DESIGN) ==="
	$(PYTHON) $(SRC_DIR)/eco_generator.py --design $(DESIGN)

$(ECO_UNUSED) $(ECO_TIEINFO) $(ECO_REPORT): $(ECO_GRAPH)
	@true

eco: $(ECO_GRAPH)

# ----------------------------------------------------------------------
# Gate-level Verilog with PD-ECO applied
# ----------------------------------------------------------------------
$(VERILOG_PD): $(DS_GREEDY) $(ECO_GRAPH) $(SRC_DIR)/generate_verilog.py
	@echo "=== Generating PD-ECO Verilog netlist for $(DESIGN) ==="
	$(PYTHON) $(SRC_DIR)/generate_verilog.py --design $(DESIGN)

verilog: $(VERILOG_PD)

# ----------------------------------------------------------------------
# Rename instances in Verilog to match SA placement slots (rename.py)
# ----------------------------------------------------------------------
$(VERILOG_RENAMED): $(VERILOG_PD) $(SA_MAP) $(SRC_DIR)/rename.py
	@echo "=== Renaming instances in Verilog to match SA map for $(DESIGN) ==="
	$(PYTHON) $(SRC_DIR)/rename.py \
	    --design $(DESIGN) \
	    --map $(SA_MAP) \
	    --in-verilog $(VERILOG_PD) \
	    --out-verilog $@

rename: $(VERILOG_RENAMED)

# ----------------------------------------------------------------------
# Visualization: static PD-ECO scatter + animated GIF
# ----------------------------------------------------------------------
$(PD_PLOT): $(FABRIC_DB) $(SA_MAP) $(ECO_UNUSED) $(ECO_TIEINFO) $(DS_GREEDY) $(SRC_DIR)/animated_eco_pd.py
	@echo "=== Generating static PD-ECO plot for $(DESIGN) ==="
	$(PYTHON) $(SRC_DIR)/animated_eco_pd.py \
	    --design $(DESIGN) \
	    --fabric $(FABRIC_DB) \
	    --map $(SA_MAP) \
	    --unused $(ECO_UNUSED) \
	    --tieinfo $(ECO_TIEINFO) \
	    --data $(DS_GREEDY) \
	    --out $@

$(PD_GIF): $(FABRIC_DB) $(SA_MAP) $(ECO_UNUSED) $(ECO_TIEINFO) $(DS_GREEDY) $(SRC_DIR)/animated_eco_pd.py
	@echo "=== Generating animated PD-ECO GIF for $(DESIGN) ==="
	$(PYTHON) $(SRC_DIR)/animated_eco_pd.py \
	    --design $(DESIGN) \
	    --fabric $(FABRIC_DB) \
	    --map $(SA_MAP) \
	    --unused $(ECO_UNUSED) \
	    --tieinfo $(ECO_TIEINFO) \
	    --data $(DS_GREEDY) \
	    --out $(PD_PLOT) \
	    --gif $@ \
	    --animate

visualize: $(PD_PLOT)

# ----------------------------------------------------------------------
# Cleanup
# ----------------------------------------------------------------------
clean:
	@echo "=== Cleaning build artifacts ==="
	rm -rf $(BUILD_DIR) designs
