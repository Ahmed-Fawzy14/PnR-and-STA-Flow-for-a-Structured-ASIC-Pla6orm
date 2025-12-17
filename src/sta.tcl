# sta.tcl

# 1. Setup Environment (Same as route.tcl)
if { [info exists ::env(DESIGN_NAME)] } {
    set design_name $::env(DESIGN_NAME)
} else {
    puts "Error: DESIGN_NAME environment variable not set."
    exit 1
}

set build_dir "build/${design_name}"
set platform_dir "tech" 

# 2. Read Library and Netlist
# Note: sta.tcl must load the LIB, _renamed.v, .spef, and .sdc 

read_lef "${platform_dir}/sky130_fd_sc_hd.tlef"
read_lef "${platform_dir}/sky130_macros.lef"

read_liberty "${platform_dir}/sky130_fd_sc_hd__tt_025C_1v80.lib"
read_verilog "${build_dir}/${design_name}_renamed.v"
link_design "mod_${design_name}"

# 3. Read Parasitics (extracted by route.tcl)
read_spef "${build_dir}/${design_name}.spef"

# 4. Read Constraints
read_sdc "${platform_dir}/design.sdc"

# 5. Reporting
puts "Reporting Setup..."
report_checks -path_delay max -format full_clock_expanded -fields {slew cap input_pins nets fanout} -no_line_splits > "${build_dir}/${design_name}_setup.rpt"

puts "Reporting Hold..."
report_checks -path_delay min -format full_clock_expanded -fields {slew cap input_pins nets fanout} -no_line_splits > "${build_dir}/${design_name}_hold.rpt"

puts "Reporting Skew..."
report_clock_skew > "${build_dir}/${design_name}_skew.rpt"
report_checks -summary > "${build_dir}/${design_name}_timing_summary.rpt"