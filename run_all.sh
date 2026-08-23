#!/bin/bash

./run_all_cms.py       -t 180              xorcle/tests/generated
./run_all_cms.py       -t 180 --ext .cnf   2xnf_sat_solving/benchmark/ascon
./run_all_cms.py       -t 180 --ext .xcnf  2xnf_sat_solving/benchmark/ascon
./run_all_cms.py       -t 180 --ext .xcnf  2xnf_sat_solving/benchmark/rand
./run_all_cms.py       -t 180 --ext .xcnf  xorricane-bench
./run_all_cms.py       -t 180 --ext .cnf   xorricane-bench
./run_all_cms.py       -t 180 --ext .2xcnf xorricane-bench
./run_all_cms.py       -t 180 --ext .cnf   xorricane-bench/bivium \
                       --tag cms-noxor --cms-opts "--sls 0 --presimp 1 --xor 0"

./run_all_xorcle.py    -t 180 --ext .cnf   xorcle/tests/generated
./run_all_xorcle.py    -t 180 --ext .xnf   2xnf_sat_solving/benchmark/ascon
./run_all_xorcle.py    -t 180 --ext .xnf   2xnf_sat_solving/benchmark/rand
./run_all_xorcle.py    -t 180 --ext .xnf   xorricane-bench

./run_all_xorricane.py -t 180 --ext .cnf   xorcle/tests/generated
./run_all_xorricane.py -t 180 --ext .xnf   2xnf_sat_solving/benchmark/ascon
./run_all_xorricane.py -t 180 --ext .xnf   2xnf_sat_solving/benchmark/rand
./run_all_xorricane.py -t 180 --ext .xnf   xorricane-bench

./run_all_bosphorus.py -t 180 --ext .anf   2xnf_sat_solving/benchmark/ascon --bosphorus-opts "--el 0"
./run_all_bosphorus.py -t 180 --ext .anf   xorricane-bench --bosphorus-opts "--el 0"

./run_all_xnf.py       -t 360 --ext .xnf   matrix-challenges/challenge1
./run_all_cms.py       -t 360 --ext .cnf   matrix-challenges/challenge1
./run_all_xorcle.py    -t 360 --ext .lxnf  -j 2 matrix-challenges/challenge1 # memory-outs without -j 2
./run_all_xorricane.py -t 360 --ext .xnf   matrix-challenges/challenge1

./backup.sh
