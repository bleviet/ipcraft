"""FileSet parsing mixin for ``YamlIpCoreParser``."""

from pathlib import Path
from typing import Any, Dict, List

import yaml
from pydantic import ValidationError

from ipcraft.model import File, FileSet, FileType

from .errors import ParseError


class FileSetParserMixin:
    """Mixin implementing file set parsing and import behavior."""

    def _parse_file_sets(self, data: List[Dict[str, Any]], file_path: Path) -> List[FileSet]:
        """Parse file set definitions, including imported file-set files."""
        file_sets = []
        for idx, fs_data in enumerate(data):
            try:
                if "import" in fs_data:
                    import_path = (file_path.parent / fs_data["import"]).resolve()
                    imported_fs = self._load_file_set_from_file(import_path)
                    file_sets.extend(imported_fs)
                    continue

                files = self._parse_files(fs_data.get("files", []), file_path)
                file_sets.append(
                    FileSet(
                        **self._filter_none(
                            {
                                "name": fs_data.get("name"),
                                "description": fs_data.get("description"),
                                "files": files if files else None,
                            }
                        )
                    )
                )
            except (KeyError, TypeError, ValueError, ValidationError) as e:
                raise ParseError(f"Error parsing fileSet[{idx}]: {e}", file_path)
        return file_sets

    def _load_file_set_from_file(self, file_path: Path) -> List[FileSet]:
        """Load file sets from an external YAML file."""
        if not file_path.exists():
            raise ParseError(f"FileSet file not found: {file_path}")

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ParseError(f"YAML syntax error in fileset file: {e}", file_path)

        if not isinstance(data, list):
            data = [data]

        return self._parse_file_sets(data, file_path)

    def _parse_files(self, data: List[Dict[str, Any]], file_path: Path) -> List[File]:
        """Parse file entries from a file set."""
        files = []
        for idx, file_data in enumerate(data):
            try:
                file_type_str = file_data.get("type", "unknown")
                try:
                    file_type = FileType(file_type_str)
                except ValueError:
                    file_type = FileType(file_type_str.upper())

                files.append(
                    File(
                        **self._filter_none(
                            {
                                "path": file_data.get("path"),
                                "type": file_type,
                                "description": file_data.get("description"),
                            }
                        )
                    )
                )
            except (KeyError, TypeError, ValueError, ValidationError) as e:
                raise ParseError(f"Error parsing file[{idx}]: {e}", file_path)
        return files
