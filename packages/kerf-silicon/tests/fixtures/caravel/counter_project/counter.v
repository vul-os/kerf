// counter.v — 32-bit free-running counter user project for Caravel
// Exposes the full user_project_wrapper port interface.
//
// The counter increments on every wb_clk_i rising edge.
// The lower 32 bits are driven onto la_data_out[31:0].
// io_out[31:0] mirrors wbs_dat_o.
`default_nettype none

module user_counter (
`ifdef USE_POWER_PINS
    inout vccd1,
    inout vssd1,
`endif

    // Wishbone slave
    input  wire        wb_clk_i,
    input  wire        wb_rst_i,
    input  wire        wbs_stb_i,
    input  wire        wbs_cyc_i,
    input  wire        wbs_we_i,
    input  wire [3:0]  wbs_sel_i,
    input  wire [31:0] wbs_dat_i,
    input  wire [31:0] wbs_adr_i,
    output wire        wbs_ack_o,
    output wire [31:0] wbs_dat_o,

    // Logic analyser
    input  wire [127:0] la_data_in,
    output wire [127:0] la_data_out,
    input  wire [127:0] la_oenb,

    // GPIO
    input  wire [37:0] io_in,
    output wire [37:0] io_out,
    output wire [37:0] io_oeb,

    // Second clock
    input  wire        user_clock2,

    // Interrupts
    output wire [2:0]  user_irq
);

    reg [31:0] count;

    always @(posedge wb_clk_i) begin
        if (wb_rst_i)
            count <= 32'b0;
        else
            count <= count + 1;
    end

    // Wishbone: read-only register at any address
    assign wbs_ack_o = wbs_stb_i & wbs_cyc_i;
    assign wbs_dat_o = count;

    // Logic analyser output
    assign la_data_out = {96'b0, count};

    // GPIO: drive lower 8 bits of count on io_out[7:0]; all others 0
    assign io_out = {30'b0, count[7:0]};
    assign io_oeb = 38'b0;  // all outputs

    // No interrupts
    assign user_irq = 3'b0;

endmodule
`default_nettype wire
