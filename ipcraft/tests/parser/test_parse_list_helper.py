import pytest
from ipcraft.parser.yaml.ip_yaml_parser import YamlIpCoreParser
from ipcraft.parser.yaml.errors import ParseError
from pathlib import Path


class TestParseListHelper:
    def setup_method(self):
        self.parser = YamlIpCoreParser()
        self.dummy_path = Path("/test/dummy.yml")

    def test_parse_list_success(self):
        data = [{"v": 1}, {"v": 2}]
        result = self.parser._parse_list(
            data, "item", lambda d: d["v"], self.dummy_path
        )
        assert result == [1, 2]

    def test_parse_list_error_includes_index(self):
        data = [{"v": 1}, {"bad": "no_key"}]
        with pytest.raises(ParseError, match=r"item\[1\]"):
            self.parser._parse_list(data, "item", lambda d: d["v"], self.dummy_path)

    def test_parse_list_empty(self):
        result = self.parser._parse_list([], "item", lambda d: d, self.dummy_path)
        assert result == []
