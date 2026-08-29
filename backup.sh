#!/bin/bash
# Copy only the solver logs (.out-* / .timeout-*) into backup/, keeping paths: ./backup.sh
set -euo pipefail

SRC=(
    xorcle/tests/generated
    xorricane-bench
    2xnf_sat_solving/benchmark
)

mkdir -p backup
rsync -amR --info=stats2 \
    --include='*/' --include='*.out-*' --include='*.timeout-*' --exclude='*' \
    "${SRC[@]}" backup/
