# Specification: `package_ip.tcl` Generator for Vivado Custom IP

## Purpose

Create one production-quality Tcl script, `package_ip.tcl`, that **fully regenerates a packaged Vivado custom IP directory from source**, including:

- `component.xml`
- `xgui/`
- copied or referenced source files under the packaged IP root
- refreshed IP metadata, checksums, and integrity checks

The generated script must treat the packaged IP directory as a **deterministic build artifact**, not a hand-edited source tree. AMD documents that IP Packager generates both `component.xml` in the IP root and the XGUI customization Tcl file in `<IP root>/xgui/`.[web:29][web:62]

## Goal

The developer shall deliver a single Tcl entrypoint that can be executed in Vivado batch mode to rebuild the packaged IP from design sources without any GUI steps.[web:59][web:60]

The script must support CI/CD use, clean regeneration, and repeatable results across machines using the same Vivado version.[web:60][web:66]

## Scope

The script is intended for **custom RTL IP packaged for Vivado IP Catalog**. It shall support the common case of:

- Verilog, SystemVerilog, and VHDL RTL sources
- XDC constraints if the IP requires them
- optional simulation-only sources
- optional block-design-derived packaging only if explicitly enabled
- metadata needed for a usable IP Catalog entry

The script is not required to generate new RTL, design the AXI register map automatically, or reverse-engineer an arbitrary existing `component.xml` file.

## Core principle

The source of truth shall be **text sources plus Tcl**, not the generated `component.xml`. AMD states that `component.xml` and the XGUI Tcl file are outputs from IP Packager.[web:29][web:62]

The generated `package_ip.tcl` script must therefore:

- derive the packaged IP from source files and script parameters
- regenerate the IP directory from scratch or update an existing package safely
- avoid any manual edits to `component.xml`

## Invocation

The script must run non-interactively in batch mode.

Example invocation:

```bash
vivado -mode batch -source package_ip.tcl -tclargs \
  --part xczu7ev-ffvc1156-2-e \
  --ip-name my_core \
  --vendor mycompany.com \
  --library user \
  --version 1.0 \
  --root-dir ./packaged_ip/my_core \
  --src-dir ./rtl \
  --xdc-dir ./xdc \
  --top my_core_top
```

The script may also support execution through `make package` or CI wrappers, but `package_ip.tcl` must remain the real implementation boundary.

## Functional requirements

### Inputs

The script shall accept, either through `-tclargs` or a clearly isolated config block at the top of the file:

- target part
- IP name
- top module/entity name
- vendor, library, name, version (VLNV fields)
- display name
- description
- taxonomy, default `/UserIP`
- root output directory for packaged IP
- one or more RTL source directories or file lists
- optional constraint directories or file lists
- optional simulation source directories or file lists
- optional board/family metadata
- optional previous package reuse mode versus force-clean mode

The script should fail fast if required inputs are missing.

### Output directory behavior

The script shall support two explicit modes:

| Mode | Behavior |
|---|---|
| Clean package | Remove and fully recreate the packaged IP directory before packaging |
| Update package | Reopen an existing package when `component.xml` exists, merge project changes, bump revision if requested, and resave |

If update mode is implemented, it shall use `ipx::open_core`, merge changed files and ports where appropriate, and then regenerate outputs before save, as shown in real packaging examples.[web:60][web:64]

If clean mode is selected, the script shall create a fresh temporary Vivado project, add sources, and call `ipx::package_project -root_dir ...` to generate a new IP package.[web:59][web:60]

### Temporary project

The script shall create a temporary Vivado project exclusively for packaging. This project is an implementation detail and must not become the source of truth.[web:59]

Requirements:

- place the temp project under a disposable build directory such as `.build/package_ip/`
- use `create_project -force`
- set the requested target part
- add design sources and constraints
- update compile order before packaging
- optionally set `source_mgmt_mode` if needed for reliable source capture, as seen in journal examples.[web:61]

### Packaging flow

The script shall implement the following logical packaging sequence:

1. Create/open temporary project and add sources.[web:59]
2. Update compile order.
3. Package current project with `ipx::package_project -root_dir ...` for new packages, or open existing core with `ipx::open_core` for update mode.[web:60]
4. Set required core metadata on `ipx::current_core`.
5. Merge project changes for files and ports when updating an existing package.[web:60][web:64]
6. Optionally apply interface inference or explicit bus-interface metadata if the IP requires it.
7. Generate XGUI files with `ipx::create_xgui_files`.[web:59][web:60]
8. Refresh checksums with `ipx::update_checksums`.[web:59][web:60]
9. Run `ipx::check_integrity` and fail the build on errors.[web:59][web:63]
10. Save the packaged core with `ipx::save_core`.[web:59][web:60]

### Mandatory generated artifacts

On successful completion, the script must guarantee that the packaged IP root contains at minimum:

- `component.xml`
- `xgui/`
- categorized source content as generated by IP Packager

AMD documents `component.xml` in the IP root and the XGUI Tcl file in `<IP root>/xgui/` as standard outputs of the packager.[web:29][web:62]

### Metadata requirements

The script shall set, at minimum, these core properties if provided:

- name
- vendor
- library
- version
- display name
- description
- taxonomy
- core revision
- supported families where relevant

At least one example in public packaging scripts sets `core_revision` and `supported_families` directly on the current core before generating XGUI and saving.[web:60]

### File classification

The script shall classify files intentionally rather than relying blindly on tool defaults whenever possible.

Minimum expectations:

- synthesizable RTL included in synthesis-capable file groups
- XDC constraints included only when appropriate for IP packaging
- simulation-only sources isolated from synthesis files when present
- optional documentation/logo assets added only if explicitly requested

A public example shows auxiliary assets being added to dedicated IP file groups and marked with specific types such as `LOGO`.[web:59]

### Integrity and failure policy

The script shall be strict.

It must fail with a non-zero Vivado exit status when any of the following happens:

- missing top module/entity
- no source files found
- `ipx::check_integrity` reports errors
- `component.xml` was not produced
- `xgui/` was not produced when XGUI generation is expected

Warnings may be printed, but packaging success requires explicit validation of the generated outputs.

### Logging

The script shall print clear progress markers to stdout so CI logs are readable. Required stages:

- parse arguments
- discover sources
- create temp project
- package IP
- apply metadata
- generate XGUI
- integrity check
- save core
- verify outputs
- done

Error messages must name the missing file, invalid argument, or failing IP-XACT step.

## Non-functional requirements

### Reproducibility

The script shall be deterministic for a fixed:

- Vivado version
- source tree
- Tcl script revision
- argument set

The spec shall instruct the developer not to rely on GUI state, manually edited temporary projects, or absolute developer-machine paths inside the packaged IP. AMD notes that associated files are relative to the `component.xml` location.[web:29][web:62]

### Path discipline

The script shall normalize paths and prefer repository-relative inputs. It must avoid leaking workstation-specific absolute paths into the final package wherever Vivado settings allow.

This matters because the packaged IP is expected to move between machines, repositories, and CI runners.[web:29]

### Vivado version awareness

The script shall print `version -short` at startup and optionally enforce an allowed-version list. Production build systems in the field commonly gate behavior on Vivado version because packaging behavior and generated outputs can vary by release.[web:66]

### CI suitability

The script shall run headless, with no prompts, on Linux CI runners with Vivado installed. It must not depend on a desktop GUI session.[web:59][web:60]

## Script architecture requirements

The delivered `package_ip.tcl` implementation shall be structured into small procedures.

Minimum required procedures:

- `parse_args` — decode `-tclargs`
- `require_arg` — validate required parameters
- `discover_files` — gather RTL/XDC/sim files
- `create_temp_project` — create disposable project and add sources
- `package_new_core` — invoke `ipx::package_project`
- `open_existing_core` — invoke `ipx::open_core` for update mode
- `apply_core_metadata` — set VLNV and descriptive properties
- `merge_changes_if_needed` — run `ipx::merge_project_changes` for files and ports when updating.[web:60][web:64]
- `generate_packaging_outputs` — create XGUI, update checksums, integrity-check, save core.[web:59][web:60]
- `verify_packaged_outputs` — assert presence of `component.xml` and `xgui/`
- `cleanup_temp_project` — close project and optionally remove temp build directory

The script should keep all configuration data in dictionaries or named variables rather than spreading literals throughout the file.

## Required implementation details

### Argument interface

The script should support long-form flags, for example:

- `--part`
- `--ip-name`
- `--vendor`
- `--library`
- `--version`
- `--display-name`
- `--description`
- `--taxonomy`
- `--root-dir`
- `--src-dir`
- `--src-file`
- `--xdc-dir`
- `--sim-dir`
- `--top`
- `--update`
- `--clean`
- `--core-revision`

It may additionally support a config Tcl file input such as `--config ./ip_config.tcl`, but that must be optional.

### Source discovery

The script shall support both:

- explicit file lists
- recursive directory scanning by extension

Supported source extensions should include at least:

- `.v`
- `.sv`
- `.vh`
- `.vhd`
- `.vhdl`
- `.xdc`

Simulation-only extensions may be identical but sourced from separate directories or filesets.

The script shall sort discovered file lists before adding them to the project to improve deterministic behavior.

### New-package behavior

For a fresh package, the script shall:

- create the output root if missing
- call `ipx::package_project -root_dir <root> -vendor <vendor> -library <library> -taxonomy <taxonomy> -force`
- set properties on `[ipx::current_core]`
- generate XGUI, update checksums, check integrity, and save core.[web:59][web:60]

### Update-package behavior

If update mode is enabled and `<root>/component.xml` already exists, the script shall:

- open the existing package with `ipx::open_core <root>/component.xml`
- optionally increment `core_revision`
- merge project changes for files and ports
- regenerate XGUI/checksums/integrity/save outputs.[web:60][web:64]

This is important so existing packaged IP can be refreshed instead of always destroyed, while still remaining script-driven.[web:60]

### Optional IP catalog refresh

The script may optionally support a post-step to expose the package in the current Vivado environment by setting `ip_repo_paths` and calling `update_ip_catalog`, which is how packaged IP becomes visible for reuse in a project.[web:33]

This behavior should be optional because CI packaging does not always need catalog refresh.

## Validation requirements

The developer must include the following validations in the script:

- verify the top-level design unit exists after sources are added
- verify source lists are non-empty
- verify `component.xml` exists after save
- verify `xgui/` exists and contains at least one Tcl file after `ipx::create_xgui_files`
- print the final packaged IP VLNV and root path

If integrity checks fail, the script must emit a useful error and stop.

## Repository assumptions

Assume a repository layout similar to:

```text
repo/
├── rtl/
├── xdc/
├── sim/
├── scripts/
│   └── package_ip.tcl
└── packaged_ip/
    └── my_core/
```

The implementation should not hardcode this layout, but should work well with it.

## Deliverables

The developer shall deliver:

1. `package_ip.tcl`
2. a short usage section at the top of the script
3. one example command line for local use
4. one example command line for CI use
5. clear error handling and exit codes

Optional but recommended:

- `Makefile` target `package-ip`
- a tiny `ip_config.tcl` example
- a CI snippet for GitLab CI or GitHub Actions

## Acceptance criteria

The work is accepted when all of the following are true:

- Running `vivado -mode batch -source package_ip.tcl ...` from a clean checkout produces a valid packaged IP directory.[web:59][web:60]
- The output contains `component.xml` and `xgui/` in the expected locations.[web:29][web:62]
- Re-running the command with unchanged inputs does not require GUI interaction and completes successfully.[web:59]
- Update mode correctly refreshes an existing package and preserves the intended IP identity while merging source/project changes.[web:60][web:64]
- The script exits non-zero on integrity failures or missing required outputs.[web:63]
- The script is readable, modular, and suitable for CI maintenance.

## Preferred engineering decisions

The following decisions are preferred unless a stronger project-specific reason exists:

- Use Tcl as the only real implementation language for packaging.
- Use one batch entrypoint instead of splitting packaging logic across many opaque helper scripts.
- Keep the packaged IP directory outside the temporary project directory.
- Treat temporary project content as disposable.
- Treat generated package contents as rebuildable artifacts.
- Keep metadata assignment explicit in the script instead of relying on hidden defaults.

## Notes for AXI-based IP

If the target IP is AXI4-Lite, AXI4-Stream, or AXI memory mapped, the script may need a second phase that explicitly defines or repairs bus interfaces, addressing metadata, user parameters, and driver-visible naming conventions. Public examples show packaging scripts often growing additional `ipx::*` customization logic beyond the base package-save flow.[web:59][web:64][web:67]

This is not a reason to weaken the base spec. Instead, the base script must be written so interface-specific customization can be added in one isolated procedure such as `customize_bus_interfaces`.

## Out of scope

The following are out of scope for this deliverable unless explicitly requested later:

- generating a full AXI register bank from a high-level YAML or JSON spec
- creating a Vitis kernel `.xo`
- generating software drivers
- reverse-converting arbitrary legacy packaged IP into clean source form
- packaging encrypted third-party IP with undocumented constraints

## Final design intent

The resulting `package_ip.tcl` should feel like a **build artifact generator**, not a journal dump from the Vivado GUI. It must be readable, parameterized, strict, CI-ready, and capable of rebuilding the packaged IP directory from real sources with one command.[web:56][web:60]
