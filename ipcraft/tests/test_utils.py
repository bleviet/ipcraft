import pytest
from enum import Enum
from ipcraft.utils import normalize_bus_type_key, bus_type_to_generator_code, enum_value


class TestBusTypeMapping:
    @pytest.mark.parametrize(
        "input_val, expected",
        [
            ("AXI4L", "AXI4L"),
            ("axil", "AXI4L"),
            ("axi4-lite", "AXI4L"),
            ("AXILITE", "AXI4L"),
            ("AVALON_MM", "AVALON_MM"),
            ("avmm", "AVALON_MM"),
            ("AVALON-MM", "AVALON_MM"),
            ("UNKNOWN", "UNKNOWN"),
        ],
    )
    def test_normalize_bus_type_key(self, input_val, expected):
        assert normalize_bus_type_key(input_val) == expected

    @pytest.mark.parametrize(
        "input_val, expected",
        [
            ("AXI4L", "axil"),
            ("axil", "axil"),
            ("AVALON_MM", "avmm"),
            ("avmm", "avmm"),
            ("axi4-lite", "axil"),
            ("UNKNOWN", "axil"),  # fallback
        ],
    )
    def test_bus_type_to_generator_code(self, input_val, expected):
        assert bus_type_to_generator_code(input_val) == expected


class Color(str, Enum):
    RED = "red"
    BLUE = "blue"


class TestEnumValue:
    def test_with_enum(self):
        assert enum_value(Color.RED) == "red"

    def test_with_string(self):
        assert enum_value("plain_string") == "plain_string"

    def test_with_int(self):
        assert enum_value(42) == "42"
