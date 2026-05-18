-- counter.vhd — 8-bit synchronous counter with synchronous reset
-- IEEE 1076-2008 subset

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;

entity counter is
    generic (
        WIDTH : integer := 8
    );
    port (
        clk   : in  std_logic;
        rst   : in  std_logic;
        en    : in  std_logic;
        count : out std_logic_vector(7 downto 0)
    );
end entity counter;

architecture rtl of counter is

    signal count_reg : std_logic_vector(7 downto 0) := (others => '0');

begin

    -- Drive output
    count <= count_reg;

    -- Counter process
    cnt_proc : process(clk)
    begin
        if rising_edge(clk) then
            if rst = '1' then
                count_reg <= (others => '0');
            elsif en = '1' then
                count_reg <= std_logic_vector(unsigned(count_reg) + 1);
            end if;
        end if;
    end process cnt_proc;

end architecture rtl;
