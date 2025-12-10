if { [info exists ::env(DESIGN_NAME)] } {
    set design_name $::env(DESIGN_NAME)
} else {
    puts "Error: DESIGN_NAME environment variable not set."
    exit 1
}

set build_dir "build/${design_name}"
set platform_dir "tech" 

read_lef "${platform_dir}/sky130_fd_sc_hd.tlef"

read_lef "${platform_dir}/sky130_macros.lef"

read_liberty "${platform_dir}/sky130_fd_sc_hd__tt_025C_1v80.lib"

read_verilog "${build_dir}/${design_name}_renamed.v"
link_design ${design_name}

read_def -floorplan_initialize "${build_dir}/${design_name}_fixed.def"

make_tracks li1 -x_offset 0.230 -x_pitch 0.460 -y_offset 0.170 -y_pitch 0.340
make_tracks met1 -x_offset 0.170 -x_pitch 0.340 -y_offset 0.170 -y_pitch 0.340
make_tracks met2 -x_offset 0.230 -x_pitch 0.460 -y_offset 0.230 -y_pitch 0.460
make_tracks met3 -x_offset 0.340 -x_pitch 0.680 -y_offset 0.340 -y_pitch 0.680
make_tracks met4 -x_offset 0.460 -x_pitch 0.920 -y_offset 0.460 -y_pitch 0.920
make_tracks met5 -x_offset 1.700 -x_pitch 3.400 -y_offset 1.700 -y_pitch 3.400

global_route -congestion_report_file "${build_dir}/${design_name}_congestion.rpt" -verbose

detailed_route -output_drc "${build_dir}/${design_name}_drc.rpt"

extract_parasitics -ext_model_file "${platform_dir}/rcx_patterns.rules"

write_spef "${build_dir}/${design_name}.spef"

read_def -floorplan_initialize "${build_dir}/${design_name}_fixed.def"
