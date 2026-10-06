library ieee; use ieee.std_logic_1164.all;
entity Fancy_Core is
  generic (
    DATA_W : positive range 8 to 64 := 32;
    NAME   : string := "My ""core"""; -- comment
    EN     : boolean := true;
    INIT   : std_logic_vector(7 downto 0) := x"AB";
    FLAG   : std_logic := '1';
    DEPTH, WIDTH : natural := 16
  );
  port (
    clk, rst_n : in std_logic;
    i_enable : in std_logic;
    o_data   : out std_logic_vector(DATA_W-1 downto 0);
    io_bidir : inout std_logic_vector(7 downto 0);
    cnt      : out std_logic_vector(integer(ceil(log2(real(DEPTH))))-1 downto 0);
    narrow   : in std_logic_vector(0 to 3);
    wide     : out std_logic_vector(DEPTH*2 - 1 downto 0);
    odd      : out std_logic_vector(WIDTH downto 0);
    s_axis_tdata  : in std_logic_vector(31 downto 0);
    s_axis_tvalid : in std_logic;
    s_axis_tready : out std_logic;
    s_axis_tlast  : in std_logic;
    m_axis_tdata  : out std_logic_vector(31 downto 0);
    m_axis_tvalid : out std_logic;
    m_axis_tready : in std_logic
  );
end entity Fancy_Core;
architecture rtl of Fancy_Core is begin end;
