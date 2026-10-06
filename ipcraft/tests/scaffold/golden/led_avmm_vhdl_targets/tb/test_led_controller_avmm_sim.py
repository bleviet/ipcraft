"""cocotb tests for led_controller_avmm, wrapped as individual pytest functions.

Each function here maps 1-to-1 to a @cocotb.test() in led_controller_avmm_test.py,
so VS Code's Testing panel and ``pytest tb/`` both show them as separate tests.

Run all tests:            pytest tb/
Run one test:             pytest tb/ -k test_register_access
Use a different simulator: SIM=icarus pytest tb/

The HDL is compiled once by the ``sim_runner`` fixture in conftest.py.
"""

def test_register_access(sim_runner):
    """Read/write all registers via the AVMM bus interface."""
    sim_runner("test_register_access")

