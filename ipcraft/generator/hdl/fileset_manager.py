"""FileSet management mixin for ``IpCoreProjectGenerator``."""

from pathlib import Path
from typing import Dict, List, Optional

import yaml

from ipcraft.model.fileset import File, FileSet, FileType


class FileSetManagerMixin:
    """Mixin for synchronizing generated files with ``fileSets`` in IP YAML."""

    def update_ipcore_filesets(
        self,
        ip_core_path: str,
        generated_files: Dict[str, str],
        include_regs: bool = False,
        vendor: str = "none",
        include_testbench: bool = False,
    ) -> bool:
        """Update ``fileSets`` section in the IP YAML based on generated files."""
        from ipcraft.parser.yaml.ip_yaml_parser import YamlIpCoreParser

        ip_path = Path(ip_core_path)
        if not ip_path.exists():
            return False

        parser = YamlIpCoreParser()
        ip_core = parser.parse_file(ip_path)
        name = ip_core.vlnv.name.lower()

        expected_filesets = self._build_filesets_from_generated(
            name, generated_files, include_regs, vendor, include_testbench
        )

        if self._filesets_match(ip_core.file_sets, expected_filesets):
            return False

        with open(ip_path, "r") as f:
            yaml_content = f.read()

        yaml_data = yaml.safe_load(yaml_content)
        filesets_dict = [
            {
                "name": fs.name,
                "description": fs.description,
                "files": [{"path": file.path, "type": file.type.value} for file in fs.files],
            }
            for fs in expected_filesets
        ]

        yaml_data["fileSets"] = filesets_dict

        with open(ip_path, "w") as f:
            yaml.dump(yaml_data, f, default_flow_style=False, sort_keys=False, indent=2)

        return True

    def _build_filesets_from_generated(
        self,
        name: str,
        generated_files: Dict[str, str],
        include_regs: bool,
        vendor: str,
        include_testbench: bool,
    ) -> List[FileSet]:
        """Build ``FileSet`` objects from generated file dictionary."""
        filesets: List[FileSet] = []

        rtl_files = [File(path=f"rtl/{name}_pkg.vhd", type=FileType.VHDL)]
        if include_regs:
            rtl_files.append(File(path=f"rtl/{name}_regs.vhd", type=FileType.VHDL))
        rtl_files.append(File(path=f"rtl/{name}_core.vhd", type=FileType.VHDL))

        if f"rtl/{name}_axil.vhd" in generated_files:
            rtl_files.append(File(path=f"rtl/{name}_axil.vhd", type=FileType.VHDL))
        elif f"rtl/{name}_avmm.vhd" in generated_files:
            rtl_files.append(File(path=f"rtl/{name}_avmm.vhd", type=FileType.VHDL))

        rtl_files.append(File(path=f"rtl/{name}.vhd", type=FileType.VHDL))
        filesets.append(FileSet(name="RTL_Sources", description="RTL Sources", files=rtl_files))

        if include_testbench:
            sim_files = [
                File(path=f"tb/{name}_test.py", type=FileType.PYTHON),
                File(path="tb/Makefile", type=FileType.UNKNOWN),
            ]
            filesets.append(
                FileSet(
                    name="Simulation_Resources", description="Simulation Files", files=sim_files
                )
            )

        if vendor != "none":
            integration_files: List[File] = []
            if vendor in ["intel", "both"]:
                integration_files.append(File(path=f"intel/{name}_hw.tcl", type=FileType.TCL))
            if vendor in ["xilinx", "both"]:
                integration_files.append(File(path="xilinx/component.xml", type=FileType.XML))
                xgui_files = [
                    file_path
                    for file_path in generated_files.keys()
                    if file_path.startswith("xilinx/xgui/") and file_path.endswith(".tcl")
                ]
                if xgui_files:
                    integration_files.append(File(path=xgui_files[0], type=FileType.TCL))

            if integration_files:
                filesets.append(
                    FileSet(
                        name="Integration",
                        description="Platform Integration Files",
                        files=integration_files,
                    )
                )

        return filesets

    def _filesets_match(self, existing: Optional[List[FileSet]], expected: List[FileSet]) -> bool:
        """Return ``True`` when existing ``fileSets`` already match expected values."""
        if not existing and not expected:
            return True
        if not existing or len(existing) != len(expected):
            return False

        existing_dict = {fs.name: fs for fs in existing}
        for exp_fs in expected:
            if exp_fs.name not in existing_dict:
                return False

            exist_fs = existing_dict[exp_fs.name]
            if len(exist_fs.files) != len(exp_fs.files):
                return False

            exist_files = {(f.path, f.type) for f in exist_fs.files}
            exp_files = {(f.path, f.type) for f in exp_fs.files}
            if exist_files != exp_files:
                return False

        return True
