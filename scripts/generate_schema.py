import json
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from ipcraft.model.core import IpCore
from ipcraft.model.memory_map import MemoryMap


def generate_schema():
    output_dir = project_root / "ipcraft-spec" / "schemas"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate IpCore schema
    try:
        ip_core_schema = IpCore.model_json_schema(by_alias=True)
        with open(output_dir / "ip_core.schema.json", "w") as f:
            json.dump(ip_core_schema, f, indent=2)
            f.write("\n")
        print(f"Generated {output_dir / 'ip_core.schema.json'}")
    except Exception as e:
        print(f"Error generating IpCore schema: {e}")

    # Generate MemoryMap schema (for standalone *.mm.yml files)
    # mm.yml files are YAML arrays (list of MemoryMap objects)
    try:
        mem_map_item_schema = MemoryMap.model_json_schema(by_alias=True)
        mem_map_schema = {
            "type": "array",
            "description": "List of memory map definitions (*.mm.yml format)",
            "items": mem_map_item_schema,
        }
        with open(output_dir / "memory_map.schema.json", "w") as f:
            json.dump(mem_map_schema, f, indent=2)
            f.write("\n")
        print(f"Generated {output_dir / 'memory_map.schema.json'}")
    except Exception as e:
        print(f"Error generating MemoryMap schema: {e}")


if __name__ == "__main__":
    generate_schema()
