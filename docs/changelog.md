# IPCraft Changelog

## 0.1.0-refactor
### High Priority: DRY Violations
- Unify Bus Definition Loading via `BusLibrary` Singleton (`ipcraft/model/bus_library.py`)
- Consolidate Bus Type Mapping Tables to central utility
- Extract `enum_value()` and `filter_none()` utilities to reduce boilerplate
- Extract generic list parser for yaml components

### Medium Priority: Readability & Maintainability
- Fix CLI Naming: Renamed `ipcore` to `ipcraft` internally
- Add mixin typing protocols (`ParserHostContext`) for parser mixins
- Clean up empty/placeholder modules (`converter/` directory destroyed)
- Standardize on `pathlib.Path` over `os.path`
- Remove over-defensive `getattr` chains in Generator
- Add specific exceptions for Bus I/O errors (`BusIOError`)
- Clean up unused imports in HDL parsers (pyparsing cleanup)
- Relocated `test_vhdl_ai_parser.py` into correct directory `tests/parser/hdl/`
- Fix `VhdlLlmParser` path hardcoding (uses `LLM_CORE_PATH` environment variable)

### Low Priority: Elegance Polish
- Remove redundant `count` validator from `ArrayConfig`
- Simplify `_find_by_name` with `next()`
- Cache `AddressBlock.end_address` range parsing using `@cached_property`
- Add `DeprecationWarning` to legacy bus aliases
- Remove no-op `_process_port_list` from `VHDLParser`
