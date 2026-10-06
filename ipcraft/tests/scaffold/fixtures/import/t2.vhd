entity avmm_thing is
  port (
    clock : in std_logic;
    reset : in std_logic;
    avs_address : in std_logic_vector(3 downto 0);
    avs_read_n : in std_logic;
    avs_write_n : in std_logic;
    avs_writedata : in std_logic_vector(31 downto 0);
    avs_readdata : out std_logic_vector(31 downto 0);
    avs_waitrequest_n : out std_logic;
    avs_readdatavalid : out std_logic;
    avs_byteenable : in std_logic_vector(3 downto 0);
    led : out std_logic_vector(7 downto 0)
  );
end avmm_thing;
