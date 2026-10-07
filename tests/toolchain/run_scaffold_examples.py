#!/usr/bin/env python3
"""Generate the ipcraft-spec examples with the scaffold engine and run them through the real tools.

For every example and HDL language this script:
  1. copies the example into a work directory and runs ``ipcraft generate --pack builtin-ipcraft
     --target quartus,vivado`` in place,
  2. runs the generated cocotb testbench (GHDL for VHDL, Icarus for SystemVerilog),
  3. runs Quartus Analysis & Synthesis (``--quartus-full`` adds Fitter/Assembler),
  4. runs Vivado out-of-context synthesis.

Usage:
    python tests/toolchain/run_scaffold_examples.py [--examples a,b] [--langs vhdl,systemverilog]
           [--steps sim,quartus,vivado] [--work DIR] [--quartus-full]

Tools are looked up on PATH (``make``, ``ghdl``/``iverilog``, ``quartus_sh``, ``vivado``).
Exit status is non-zero when any step fails; a summary table is printed at the end.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EXAMPLES = REPO / "ipcraft-spec" / "examples"

QUARTUS_COMPILE_TCL = """\
load_package flow
set altera_dir [lindex $argv 0]
set project_name [lindex $argv 1]
set full [lindex $argv 2]
cd $altera_dir
set rc [catch {
    project_open $project_name -revision [get_current_revision $project_name]
    execute_module -tool map
    if {$full} {
        execute_module -tool fit
        execute_module -tool asm
        catch {execute_module -tool sta}
    }
    project_close
} err]
if {$rc != 0} { puts "FAIL: $err"; catch {project_close}; exit 1 }
puts "PASS: $project_name"
"""


def run(cmd, cwd, log, timeout=3600, env=None):
    t0 = time.monotonic()
    with open(log, "w") as fh:
        try:
            p = subprocess.run(cmd, cwd=cwd, stdout=fh, stderr=subprocess.STDOUT, timeout=timeout, env=env)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            fh.write("\nTIMEOUT\n")
            rc = 124
    return rc, time.monotonic() - t0


def log_errors(log: Path, pattern: str) -> list:
    """Error lines a tool printed even when it exited 0."""
    if not log.exists():
        return []
    rx = re.compile(pattern)
    return [l.strip() for l in log.read_text(errors="replace").splitlines() if rx.search(l)]


def cocotb_failures(tb_dir: Path) -> int:
    """Number of failed/errored test cases reported in results.xml (-1 when missing)."""
    res = tb_dir / "results.xml"
    if not res.exists():
        return -1
    root = ET.parse(res).getroot()
    bad = 0
    for tc in root.iter("testcase"):
        if tc.find("failure") is not None or tc.find("error") is not None:
            bad += 1
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--examples", default="")
    ap.add_argument("--langs", default="vhdl,systemverilog")
    ap.add_argument("--steps", default="sim,quartus,vivado")
    ap.add_argument("--work", default=str(REPO / "build" / "scaffold-examples"))
    ap.add_argument("--quartus-full", action="store_true")
    args = ap.parse_args()

    examples = [d for d in sorted(EXAMPLES.iterdir()) if d.is_dir() and list(d.glob("*.ip.yml"))]
    if args.examples:
        wanted = set(args.examples.split(","))
        examples = [d for d in examples if d.name in wanted]
    steps = set(args.steps.split(","))
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    compile_tcl = work / "run_compile.tcl"
    compile_tcl.write_text(QUARTUS_COMPILE_TCL)

    results = []
    for ex in examples:
        ip_src = next(ex.glob("*.ip.yml"))
        for lang in args.langs.split(","):
            d = work / f"{ex.name}-{lang}"
            shutil.rmtree(d, ignore_errors=True)
            shutil.copytree(ex, d)
            ip = d / ip_src.name
            row = {"example": ex.name, "lang": lang}
            rc, _ = run(["uv", "run", "--project", str(REPO), "ipcraft", "generate", str(ip), "--lang", lang,
                         "--pack", "builtin-ipcraft", "--target", "quartus,vivado", "--out", str(d)], d, d / "generate.log")
            row["generate"] = "ok" if rc == 0 else "FAIL"
            if rc != 0:
                results.append(row)
                continue
            name = ip_src.name[: -len(".ip.yml")]
            if "sim" in steps:
                tb = d / "tb"
                sim = "ghdl" if lang == "vhdl" else "icarus"
                rc, dt = run(["make", "-C", str(tb), f"SIM={sim}", "WAVES=0"], d, d / "sim.log", timeout=1800)
                fails = cocotb_failures(tb)
                row["sim"] = "ok" if rc == 0 and fails == 0 else f"FAIL(rc={rc},fails={fails})"
            altera = d / "altera"
            if "quartus" in steps:
                proj_tcl = next(altera.glob("*_project.tcl"), None)
                rc, _ = run(["quartus_sh", "-t", proj_tcl.name], altera, d / "quartus_project.log") if proj_tcl else (1, 0)
                if rc == 0:
                    qpf = next(altera.glob("*.qpf"))
                    rc, dt = run(["quartus_sh", "-t", str(compile_tcl), str(altera), qpf.stem,
                                  "1" if args.quartus_full else "0"], altera, d / "quartus_compile.log")
                errs = log_errors(d / "quartus_compile.log", r"^\s*Error \(") + log_errors(d / "quartus_project.log", r"^\s*Error \(")
                row["quartus"] = "ok" if rc == 0 and not errs else f"FAIL(rc={rc},errors={len(errs)})"
            if "vivado" in steps:
                xil = d / "xilinx"
                ooc = next(xil.glob("*_run_ooc.tcl"), None)
                rc, dt = run(["vivado", "-mode", "batch", "-source", ooc.name, "-nojournal", "-nolog", "-tclargs", "4"],
                             xil, d / "vivado.log") if ooc else (1, 0)
                errs = log_errors(d / "vivado.log", r"^(ERROR|CRITICAL WARNING):")
                row["vivado"] = "ok" if rc == 0 and not errs else f"FAIL(rc={rc},errors={len(errs)})"
            results.append(row)
            print(row, flush=True)

    cols = ["example", "lang", "generate", "sim", "quartus", "vivado"]
    print("\n" + " | ".join(cols))
    bad = False
    for r in results:
        print(" | ".join(str(r.get(c, "-")) for c in cols))
        bad = bad or any(str(r.get(c, "ok")).startswith("FAIL") for c in cols[2:])
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
