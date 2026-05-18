-- uart_rx.vhd — simple UART receiver with a 4-state FSM
-- States: IDLE, START, DATA, STOP
-- IEEE 1076-2008 subset

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;

entity uart_rx is
    generic (
        BAUD_DIV : integer := 868   -- 100 MHz / 115200
    );
    port (
        clk      : in  std_logic;
        rst      : in  std_logic;
        rx       : in  std_logic;
        data_out : out std_logic_vector(7 downto 0);
        data_vld : out std_logic
    );
end entity uart_rx;

architecture rtl of uart_rx is

    -- FSM state type
    type rx_state_t is (IDLE, START, DATA, STOP);

    signal state     : rx_state_t := IDLE;
    signal baud_cnt  : integer range 0 to 1023 := 0;
    signal bit_idx   : integer range 0 to 7 := 0;
    signal rx_shift  : std_logic_vector(7 downto 0) := X"00";
    signal data_reg  : std_logic_vector(7 downto 0) := X"00";
    signal vld_reg   : std_logic := '0';

begin

    data_out <= data_reg;
    data_vld <= vld_reg;

    rx_fsm : process(clk)
    begin
        if rising_edge(clk) then
            vld_reg <= '0';

            if rst = '1' then
                state    <= IDLE;
                baud_cnt <= 0;
                bit_idx  <= 0;
            else
                case state is
                    when IDLE =>
                        if rx = '0' then
                            -- Falling edge detected — possible start bit
                            state    <= START;
                            baud_cnt <= BAUD_DIV / 2;
                        end if;

                    when START =>
                        if baud_cnt = 0 then
                            if rx = '0' then
                                -- Confirmed start bit; move to DATA
                                state    <= DATA;
                                baud_cnt <= BAUD_DIV - 1;
                                bit_idx  <= 0;
                            else
                                -- Glitch — go back to idle
                                state <= IDLE;
                            end if;
                        else
                            baud_cnt <= baud_cnt - 1;
                        end if;

                    when DATA =>
                        if baud_cnt = 0 then
                            rx_shift <= rx & rx_shift(7 downto 1);
                            baud_cnt <= BAUD_DIV - 1;
                            if bit_idx = 7 then
                                state   <= STOP;
                                bit_idx <= 0;
                            else
                                bit_idx <= bit_idx + 1;
                            end if;
                        else
                            baud_cnt <= baud_cnt - 1;
                        end if;

                    when STOP =>
                        if baud_cnt = 0 then
                            data_reg <= rx_shift;
                            vld_reg  <= '1';
                            state    <= IDLE;
                        else
                            baud_cnt <= baud_cnt - 1;
                        end if;

                end case;
            end if;
        end if;
    end process rx_fsm;

end architecture rtl;
