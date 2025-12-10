# 1. Define the clock
# Replace 'clk' with the actual clock port name in your Verilog if different.
# Period 40.0 ns corresponds to 25 MHz (as suggested in the project PDF).
create_clock -name clk -period 40.0 [get_ports clk]

# 2. Set Input/Output Delays
# These constrain how much time external signals take to arrive or leave.
# A safe default is often 20-30% of the clock period.
set_input_delay  -max 10.0 -clock clk [all_inputs]
set_input_delay  -min 0.0  -clock clk [all_inputs]

set_output_delay -max 10.0 -clock clk [all_outputs]
set_output_delay -min 0.0  -clock clk [all_outputs]