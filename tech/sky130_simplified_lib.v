`timescale 1ns/1ps

// ---------------------------------------------------------------------
// Basic combinational cells
// ---------------------------------------------------------------------

// 2-input NAND
module sky130_fd_sc_hd__nand2_2 (
    input  A,
    input  B,
    output Y
);
    assign Y = ~(A & B);
endmodule

// 2-input OR
module sky130_fd_sc_hd__or2_2 (
    input  A,
    input  B,
    output X
);
    assign X = A | B;
endmodule

// 2-input AND
module sky130_fd_sc_hd__and2_2 (
    input  A,
    input  B,
    output X
);
    assign X = A & B;
endmodule

// Clock inverter
module sky130_fd_sc_hd__clkinv_2 (
    input  A,
    output Y
);
    assign Y = ~A;
endmodule

// Clock buffer
module sky130_fd_sc_hd__clkbuf_4 (
    input  A,
    output Y
);
    assign Y = A;
endmodule

// Constant high/low cell
// LO should be used as tie-low (what your PD-ECO is using),
// HI is a constant 1 if needed.
module sky130_fd_sc_hd__conb_1 (
    output HI,
    output LO
);
    assign HI = 1'b1;
    assign LO = 1'b0;
endmodule

// ---------------------------------------------------------------------
// Sequential cell: dfbbp_1 (D-FF with async set/reset, simplified)
// ---------------------------------------------------------------------

module sky130_fd_sc_hd__dfbbp_1 (
    output reg Q,
    output     Q_N,
    input      D,
    input      CLK,
    input      SET_B,    // active-low set
    input      RESET_B   // active-low reset
);
    always @(posedge CLK or negedge RESET_B or negedge SET_B) begin
        if (!RESET_B) begin
            Q <= 1'b0;
        end else if (!SET_B) begin
            Q <= 1'b1;
        end else begin
            Q <= D;
        end
    end

    assign Q_N = ~Q;
endmodule

// ---------------------------------------------------------------------
// Physical-only cells: no logical effect in RTL sim
// ---------------------------------------------------------------------

// Well / power tap – no logic pins
module sky130_fd_sc_hd__tapvpwrvgnd_1 ();
endmodule

// Decap cells – no logic pins
module sky130_fd_sc_hd__decap_3 ();
endmodule

module sky130_fd_sc_hd__decap_4 ();
endmodule

// Filler cell – no logic pins
module sky130_fd_sc_hd__fill_1 ();
endmodule
