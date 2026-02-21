import pytest
from ipcraft.model.bus_library import BusLibrary, get_bus_library


class TestBusLibrarySingleton:
    """Verify single-loading behavior and raw dict accessors."""

    def test_singleton_returns_same_instance(self):
        lib1 = get_bus_library()
        lib2 = get_bus_library()
        assert lib1 is lib2

    def test_get_raw_bus_dict_structure(self):
        lib = get_bus_library()
        axi4l = lib.get_raw_bus_dict("AXI4L")
        assert "busType" in axi4l
        assert "ports" in axi4l
        assert isinstance(axi4l["ports"], list)
        assert all("name" in p for p in axi4l["ports"])

    def test_get_raw_bus_dict_unknown_type(self):
        lib = get_bus_library()
        result = lib.get_raw_bus_dict("NONEXISTENT")
        assert result == {}

    def test_get_all_raw_dicts_matches_list(self):
        lib = get_bus_library()
        all_dicts = lib.get_all_raw_dicts()
        assert set(all_dicts.keys()) == set(lib.list_bus_types())


class TestGeneratorUsesBusLibrary:
    """Verify generator no longer loads YAML independently."""

    def test_generator_accepts_bus_library(self):
        from ipcraft.generator.hdl.ipcore_project_generator import IpCoreProjectGenerator
        lib = get_bus_library()
        gen = IpCoreProjectGenerator(bus_library=lib)
        assert gen.bus_definitions == lib.get_all_raw_dicts()

    def test_detector_accepts_bus_library(self):
        from ipcraft.parser.hdl.bus_detector import BusInterfaceDetector
        lib = get_bus_library()
        detector = BusInterfaceDetector(bus_library=lib)
        assert detector.bus_definitions == lib.get_all_raw_dicts()
