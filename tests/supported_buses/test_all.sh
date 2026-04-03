#!/bin/bash
set -e

# Run standard script
python3 generate_ips.py

cd ../../
for core in axi4_lite axi4_full axi_stream avalon_mm avalon_st; do
    echo "========================================="
    echo " GENERATING $core"
    echo "========================================="
    rm -rf tests/supported_buses/${core}/rtl tests/supported_buses/${core}/intel tests/supported_buses/${core}/xilinx tests/supported_buses/${core}/tb
    uv run ipcraft generate tests/supported_buses/${core}.ip.yml --vendor both --output tests/supported_buses/${core}
    
    echo "========================================="
    echo " TESTING $core with Quartus"
    echo "========================================="
    docker run --rm -v $(pwd):/build raetro/quartus:23.1 /bin/bash -c "cd /build/tests/toolchain && make test-quartus IP_DIR=../supported_buses/${core} TOP_ENTITY=${core}"

    if command -v vivado &> /dev/null; then
        echo "========================================="
        echo " PACKAGING $core with Vivado native script"
        echo "========================================="
        (cd tests/supported_buses/${core}/xilinx && vivado -mode batch -journal package_ip.jou -log package_ip.log -source package_ip.tcl -tclargs --update)

        echo "========================================="
        echo " TESTING $core with Vivado summary schema"
        echo "========================================="
        (cd tests/toolchain && make test-vivado IP_DIR=../supported_buses/${core} TOP_ENTITY=${core})
    else
        echo "Skipping Vivado tests: 'vivado' command not found."
    fi
done

echo "ALL TESTS COMPLETED SUCCESSFULLY"
