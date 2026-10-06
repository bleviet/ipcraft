import os
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from register_model import RegisterModel, load_manifest


_MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "verification_manifest.json")
manifest = load_manifest(_MANIFEST_PATH)
model = RegisterModel(manifest)
_LANE_COUNT = manifest["bus"]["byteEnable"]["value"]["laneCount"]
_FULL_BYTE_ENABLE = (1 << _LANE_COUNT) - 1
_ADDRESS_LIMIT = 1 << 4
_RANDOM_SEED = 0x175


def _resolved_int(value, context):
    """Convert a bus value to int and fail explicitly if it contains X/Z."""
    if isinstance(value, (bytes, bytearray)):
        return int.from_bytes(value, "little")
    resolvable = getattr(value, "is_resolvable", True)
    if callable(resolvable):
        resolvable = resolvable()
    assert resolvable, f"{context}: read returned an unknown value: {value}"
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise AssertionError(f"{context}: read returned an unknown value: {value}") from error


def _assert_readback(actual, expected, context):
    actual_int = _resolved_int(actual, context)
    assert actual_int == expected, (
        f"{context}: expected 0x{expected:0{_LANE_COUNT * 2}X}, "
        f"got 0x{actual_int:0{_LANE_COUNT * 2}X}"
    )


class AvalonTransport:
    """Avalon-MM transport adapter for the shared semantic scoreboard."""

    def __init__(self, dut):
        self.dut = dut
        self.address_signal = getattr(dut, "avs_address")
        self.write_data_signal = getattr(dut, "avs_writedata")
        self.read_data_signal = getattr(dut, "avs_readdata")
        self.byte_enable = getattr(dut, "avs_byteenable", None)
        self.byte_enable_active_low = False
        self.write_signal = getattr(dut, "avs_write")
        self.write_asserted = 1
        self.write_deasserted = 0
        self.read_signal = getattr(dut, "avs_read")
        self.read_asserted = 1
        self.read_deasserted = 0
        self.wait_request = getattr(dut, "avs_waitrequest", None)
        self.wait_request_asserted = 1
        self.read_data_valid = getattr(dut, "avs_readdatavalid", None)
        self.read_data_valid_asserted = 1
        self.supports_byte_enable = self.byte_enable is not None

    async def write(self, addr, value, byte_enable=_FULL_BYTE_ENABLE):
        self.address_signal.value = addr
        self.write_data_signal.value = value
        if self.byte_enable is not None:
            self.byte_enable.value = (
                _FULL_BYTE_ENABLE ^ byte_enable if self.byte_enable_active_low else byte_enable
            )
        else:
            assert byte_enable == _FULL_BYTE_ENABLE, "Avalon-MM byteenable is not connected"
        self.write_signal.value = self.write_asserted
        await RisingEdge(self.dut.clk)
        if self.wait_request is not None:
            while self.wait_request.value == self.wait_request_asserted:
                await RisingEdge(self.dut.clk)
        self.write_signal.value = self.write_deasserted

    async def read(self, addr):
        self.address_signal.value = addr
        self.read_signal.value = self.read_asserted
        await RisingEdge(self.dut.clk)
        if self.wait_request is not None:
            while self.wait_request.value == self.wait_request_asserted:
                await RisingEdge(self.dut.clk)
        self.read_signal.value = self.read_deasserted
        if self.read_data_valid is not None:
            while self.read_data_valid.value != self.read_data_valid_asserted:
                await RisingEdge(self.dut.clk)
        else:
            await RisingEdge(self.dut.clk)
        return self.read_data_signal.value


async def _reset_dut(dut):
    dut.reset.value = 1
    await Timer(100, unit="ns")
    dut.reset.value = 0
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    model.reset()


async def _check_all_readable(transport, scenario):
    for reg in model.readable_registers():
        actual = await transport.read(reg["offset"])
        _assert_readback(actual, model.expected_read(reg["offset"]), f"{scenario}/{reg['name']}")


def _unmapped_addresses():
    word_bytes = _LANE_COUNT
    mapped = {reg["offset"] for reg in model.registers}
    if _ADDRESS_LIMIT < word_bytes:
        return []
    if not mapped:
        return [0]

    boundary = max(mapped) + word_bytes
    top = ((_ADDRESS_LIMIT - word_bytes) // word_bytes) * word_bytes
    candidate_addresses = {0, top}
    for address in mapped:
        candidate_addresses.add(address - word_bytes)
        candidate_addresses.add(address + word_bytes)
    candidates = sorted(
        address
        for address in candidate_addresses
        if 0 <= address <= top and address not in mapped
    )
    if not candidates:
        return []
    gap = next((addr for addr in candidates if addr < boundary), candidates[0])
    edge = next((addr for addr in reversed(candidates) if addr >= boundary), candidates[-1])
    return list(dict.fromkeys([gap, edge]))


def _check_oracle_priority_policy():
    """Check the oracle policy; DUT arbitration is covered by the RTL behavior suites."""
    priority_model = RegisterModel(manifest)
    for reg in priority_model.registers:
        for field in reg["fields"]:
            if field["writeEffect"] == "clearOnOne":
                priority_model.apply_write(
                    reg["offset"],
                    field["mask"],
                    hardware_set_mask=field["mask"],
                )
                assert priority_model.state[reg["offset"]] & field["mask"] == field["mask"]
            elif field["writeEffect"] == "setOnOne":
                priority_model.apply_write(
                    reg["offset"],
                    field["mask"],
                    hardware_clear_mask=field["mask"],
                )
                assert priority_model.state[reg["offset"]] & field["mask"] == 0


@cocotb.test()
async def test_register_semantics(dut):
    """Run directed and deterministic-randomized semantic register checks."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    _check_oracle_priority_policy()
    transport = AvalonTransport(dut)

    # Reset and RO/reserved-bit behaviour.
    await _reset_dut(dut)
    await _check_all_readable(transport, "reset")

    # One pass covers RW, observable RO preservation, WO transactions, W1C,
    # self-clearing fields, mixed-access registers, and every expanded array
    # element described by the manifest.
    directed_value = 0xA5A5A5A5 & model.word_mask
    for reg in model.writable_registers():
        await transport.write(reg["offset"], directed_value)
        model.apply_write(reg["offset"], directed_value)
        if reg["readableMask"]:
            actual = await transport.read(reg["offset"])
            _assert_readback(
                actual,
                model.expected_read(reg["offset"]),
                f"directed/{reg['name']}",
            )

    # Partial byte-enable write through the same adapter and oracle.
    if transport.supports_byte_enable and _LANE_COUNT > 1:
        candidates = model.observable_writable_registers()
        if candidates:
            await _reset_dut(dut)
            reg = candidates[0]
            byte_enable = 0x1
            partial_value = 0x5A
            await transport.write(reg["offset"], partial_value, byte_enable)
            model.apply_write(reg["offset"], partial_value, byte_enable)
            actual = await transport.read(reg["offset"])
            _assert_readback(
                actual,
                model.expected_read(reg["offset"]),
                f"byte-enable/{reg['name']}",
            )

    # Generated wrappers define unmapped and boundary reads as zero.
    for address in _unmapped_addresses():
        actual = await transport.read(address)
        _assert_readback(actual, 0, f"unmapped/0x{address:X}")

    # Reproducible randomized traffic. The seed is included in every failure.
    await _reset_dut(dut)
    rng = random.Random(_RANDOM_SEED)
    writable = model.writable_registers()
    for step in range(max(16, len(writable) * 2)):
        if not writable:
            break
        reg = rng.choice(writable)
        value = rng.getrandbits(model.data_width)
        try:
            await transport.write(reg["offset"], value)
            model.apply_write(reg["offset"], value)
            if reg["readableMask"]:
                actual = await transport.read(reg["offset"])
                _assert_readback(
                    actual,
                    model.expected_read(reg["offset"]),
                    f"random seed=0x{_RANDOM_SEED:X} step={step} reg={reg['name']}",
                )
        except Exception as error:
            raise AssertionError(
                f"random sequence failed: seed=0x{_RANDOM_SEED:X}, "
                f"step={step}, register={reg['name']}"
            ) from error


