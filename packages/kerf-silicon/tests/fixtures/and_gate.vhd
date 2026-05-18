-- and_gate.vhd — simple 2-input AND gate
-- IEEE 1076-2008 subset

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;

entity and_gate is
    port (
        a   : in  std_logic;
        b   : in  std_logic;
        y   : out std_logic
    );
end entity and_gate;

architecture rtl of and_gate is
begin
    y <= a and b;
end architecture rtl;
