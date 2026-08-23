# Reproducing the XNF solver evaluations

## The papers

| Paper | Authors | Venue / year | Solver | Code |
|---|---|---|---|---|
| [XOR Local Search for Boolean Brent Equations](https://cca.informatik.uni-freiburg.de/papers/NawrockiLiuFroehlichHeuleBiere-SAT21.pdf) | Nawrocki, Liu, Fröhlich, Heule, Biere | SAT 2021 | xnfSAT | [Vtec234/xnfsat](https://github.com/Vtec234/xnfsat) |
| [SAT Solving Using XOR-OR-AND Normal Forms](https://arxiv.org/pdf/2311.00733) | Andraschko, Danner, Kreuzer (Passau) | 2024 | 2-Xornado | [j-danner/2xnf_sat_solving](https://github.com/j-danner/2xnf_sat_solving) |
| [Conflict-Driven SAT Solving using XOR-OR-AND Normal Forms](https://dl.acm.org/doi/epdf/10.1613/jair.1.20298) | Danner, Kreuzer (Passau) | JAIR 86:46, 2026 | Xorricane | [j-danner/Xorricane-paper](https://github.com/j-danner/Xorricane-paper) |
| [Extending CDCL to disjunctions of parity equations](https://arxiv.org/pdf/2605.15002) | Beame, Sun (U. Washington) | 2026 | Xorcle | [glenn-sun/xorcle](https://github.com/glenn-sun/xorcle) |

The PDFs are committed here so the benchmark definitions and claimed results stay next to
the code that reproduces them.

## The solvers

| Solver | Reads | Role |
|---|---|---|
| [CryptoMiniSat](https://github.com/msoos/cryptominisat) | CNF-XOR, CNF | CNF-XOR CDCL with Gauss-Jordan elimination; the baseline |
| [Xorcle](https://github.com/glenn-sun/xorcle) | XNF, CNF | CDCL extended to disjunctions of parity equations |
| [Xorricane](https://github.com/j-danner/Xorricane) | XNF | CDCL over XNF |
| [xnfSAT](https://github.com/Vtec234/xnfsat) | XNF | stochastic local search with native XOR support |
| [Bosphorus](https://github.com/meelgroup/bosphorus) | ANF | algebraic (XL, ElimLin) plus logical reasoning |


## CryptoMiniSat changes needed for these benchmarks

CryptoMiniSat could not efficiently run some of these families. These changes were
necessary for proper performance:

| Commit | Change | Needed for |
|---|---|---|
| [`068a3fd79`](https://github.com/msoos/cryptominisat/commit/068a3fd79) | fix crash when `--maxnummatrices` exceeds 1000 | lifted pebbling, matrix multiplication |
| [`bef479cef`](https://github.com/msoos/cryptominisat/commit/bef479cef) | avoid O(num_matrices) per-literal work in Gauss-Jordan elimination | lifted pebbling, matrix multiplication |
| [`3970aaf24`](https://github.com/msoos/cryptominisat/commit/3970aaf24) | raise `MAX_XOR_RECOVER_SIZE` from 8 to 12 | Tseitin at k = 9, 10 |
| [`14f689a14`](https://github.com/msoos/cryptominisat/commit/14f689a14) | library setters for the matrix limits and startup simplification | Bosphorus, which drives CryptoMiniSat as a library |


**Many matrices.** Two families build far more Gauss-Jordan matrices than anything CryptoMiniSat
had been exercised on. Counting the largest number held at once per instance:

| Family | Max matrices | Instances over 20 |
|---|---|---|
| lifted pebbling | 11476 | 40/40 |
| matrix multiplication | 737 | 10/10 |
| everything else | ≤ 12 | 0 |

At those counts the old code crashed outright above 1000 matrices, and the per-literal work in
propagation was linear in the number of matrices — quadratic overall. Both had to be fixed before
the pebbling family would run at all.

**The options matter as much as the code.** On benchmarks where XOR constraints dominate,
CryptoMiniSat's defaults are tuned for general CNF and discard almost all of the linear structure
before search begins. `run_all_cms.py` therefore runs it as:

```
--sls 0 --autodisablegauss 0 --presimp 1 --maxmatrixrows 100000 --maxmatrixcols 100000
--maxnummatrices 1000000 --minmatrixrows 1 --maxxorsize 12
```

| Option | Default | Why |
|---|---|---|
| `--maxnummatrices 1000000` | 5 | pebbling needs 11476 matrices; the default keeps 5 and drops the rest |
| `--maxmatrixrows 100000` | 2000 | one bivium matrix is 10809 rows; the default discards it |
| `--maxmatrixcols 100000` | 1000 | the same matrix is 11190 columns wide |
| `--minmatrixrows 1` | 3 | keeps the many tiny matrices that lifted pebbling produces |
| `--autodisablegauss 0` | on | stops Gauss-Jordan being switched off mid-run on a usefulness heuristic |
| `--maxxorsize 12` | 7 | Tseitin at k = 8, 9, 10 has constraints that wide |
| `--presimp 1` | off | XOR recovery happens during simplification, so it must run before search |
| `--sls 0` | on | local search cannot use the XOR structure and only costs time here |

Without these, most of the recovered XORs never reach a matrix and the comparison measures
CryptoMiniSat's CNF path rather than its CNF-XOR one.

**Wide XOR constraints.** A Tseitin formula on a k-regular graph has one parity constraint of
degree exactly k per vertex, so recovering them needs a size limit of at least k. The runtime
default is `--maxxorsize 7`, but the compile-time ceiling `MAX_XOR_RECOVER_SIZE` was 8, which made
k = 9 and k = 10 unreachable at any setting. With the ceiling raised and `--maxxorsize 12` passed
in `run_all.sh`, CryptoMiniSat recovers 9- and 10-wide constraints and solves all 75 instances;
before, it solved 60 and timed out on every k ≥ 8 instance.

### Bosphorus changes needed for these benchmarks

Bosphorus uses CryptoMiniSat as a library rather than a binary, so none of the command-line
options above reach it. It was given the same configuration through the API by
[`a5dddab`](https://github.com/meelgroup/bosphorus/commit/a5dddab), which adds the `--solve-xnf`
flag that `run_all_bosphorus.py` passes:

```cpp
solver.set_sls(0);
solver.set_find_xors(true);
solver.set_allow_otf_gauss();
solver.set_max_num_matrices(1000000);
solver.set_min_matrix_rows(1);
solver.set_simplify_at_startup(1);
```

## Getting the code

Everything external is a submodule, and several of them have submodules of their own, so
the recursive flag is not optional:

```bash
git clone https://github.com/msoos/xnf-tests
cd xnf-tests
git submodule update --init --recursive
```

## Building

```bash
(cd cryptominisat && mkdir -p build && cd build && cmake .. && make -j$(nproc))
(cd xorcle && make -j$(nproc))
(cd Xorricane && cmake . && make xorricane -j$(nproc))
(cd xnfsat && ./configure.sh && make -j$(nproc))
(cd xnfsat/cnf2xnf && ./configure && make -j$(nproc))
(cd bosphorus && mkdir -p build && cd build && cmake .. && make -j$(nproc))
```

The runner scripts look for each binary at its default in-tree location; pass
`--cms`, `--xorcle`, `--xorricane`, `--xnfsat` or `--bosphorus` to point elsewhere.

## Getting the benchmarks

None of the instance files are committed — they are generated or downloaded from the
original sources, as per the papers' definitions.

**Xorcle's synthetic families** (Tseitin, lifted pebbling, random and restricted k-XNF) are
generated from the paper's parameters. Needs `cnfgen` and `networkx`:

```bash
pip install cnfgen networkx
(cd xorcle && python3 tools/generate_xnf_tests.py)
```

**The 2-Xornado suites** (Ascon, random 2-XNF) ship zipped inside their submodule:

```bash
(cd 2xnf_sat_solving/benchmark/ascon && for z in *.zip; do unzip -qn "$z"; done)
(cd 2xnf_sat_solving/benchmark/rand  && for z in *.zip; do unzip -qn "$z"; done)
```

**The Xorricane suites** (Ascon, Bivium, CTC2, random linear + 2-XNF, two MQ families) are
release assets, about 550 MB zipped:

```bash
gh release download -R j-danner/Xorricane-paper -p '*.zip' -D xorricane-bench
(cd xorricane-bench && for z in *.zip; do mkdir -p "${z%.zip}" && unzip -qn "$z" -d "${z%.zip}"; done)
```

**The matrix-multiplication challenges** ship as CNF inside their submodule; nothing to do.

## Converting the encodings

Each solver is given the format it was designed for, and most suites already ship it.
Three gaps have to be filled first:

```bash
# the Xorricane release ships no CNF-XOR for the two MQ families
./xnf_to_xcnf.py -q -j $(nproc) xorricane-bench/rand_qp_type_I/*.xnf \
                                xorricane-bench/rand_qp_type_IV/*.xnf

# a second CNF-XOR encoding, built from the 2-XNF rather than the XNF
./xnf_to_xcnf.py -q -j $(nproc) --suffix .2xcnf xorricane-bench/*/*.2xnf

# matrix-challenges ships CNF only: recover the XNF, then rewrite its x-lines
# as linerals, which is the only XNF dialect Xorcle's parser accepts
for f in $(find matrix-challenges -name '*.cnf'); do
  ./xnfsat/cnf2xnf/cnf2xnf "$f" "${f%.cnf}.xnf"
done
./xcnf_to_xnf.py -q -j $(nproc) $(find matrix-challenges -name '*.xnf')
```

Every encoding of an instance sits beside it, distinguished by extension, so a solver is
pointed at one with `--ext`:

| Extension | Format | Read by |
|---|---|---|
| `.cnf` | plain CNF, XORs blasted | CryptoMiniSat, Xorcle |
| `.xcnf`, `.cnf-xor` | CNF-XOR, `x`-prefixed lines | CryptoMiniSat |
| `.2xcnf` | CNF-XOR built from the 2-XNF | CryptoMiniSat |
| `.xnf` | XNF, `+` linerals | Xorcle, Xorricane, xnfSAT |
| `.lxnf` | XNF with `x`-lines rewritten as linerals | Xorcle |
| `.anf` | algebraic normal form | Bosphorus |

## Running the solvers

```bash

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
```

This is the long part — many hours, five solvers over every family at a 180 s timeout
(360 s for the matrix-multiplication instances). Each run writes a `.out-<solver>` and a
`.timeout-<solver>` beside its instance, the latter holding `/usr/bin/time -v` output, so
an interrupted sweep resumes with `--skip-existing`. `backup.sh` then copies just those
logs into `backup/`, keeping the directory structure.

## The report

```bash
./get_data_to_sqlite.py
./create_graphs.py
./make_report.py
```

`get_data_to_sqlite.py` parses every log into `data.sqlite`, one row per solver-instance
pair with wall clock, CPU time, peak RSS, exit status and result. `create_graphs.py` writes
CDF plots and PAR2 tables into `pics/` as PNG, PDF and SVG, alongside the CSV data behind
each curve. `make_report.py` assembles **`report.html`**: a single self-contained page
covering what was run, how each benchmark family was generated, which encoding each solver
saw, the plots, the PAR2 tables and the caveats.

## The raw logs

Every run's output is committed as `logs.tar.xz` — 12950 files, 543 MB of text compressed to
25 MB. It holds a `.out-<solver>` (the solver's own output) and a `.timeout-<solver>`
(`/usr/bin/time -v`: wall clock, CPU time, peak RSS, exit status) for each solver-instance
pair, in the same directory layout the benchmarks use:

```bash
mkdir -p backup && tar -xf logs.tar.xz -C backup
```

`data.sqlite` is committed too, so the plots and the report can be rebuilt without running a
single solver — clone, then run the three commands under [The report](#the-report). The logs
are there for anything the database does not capture: conflict counts, XOR recovery
statistics, Gauss-Jordan matrix dimensions, restart behaviour.

## The other scripts

| Script | Purpose |
|---|---|
| `xnf_to_xcnf.py` | XNF to CNF-XOR, in the Xorricane paper's encoding |
| `xcnf_to_xnf.py` | CNF-XOR `x`-lines to XNF linerals, which Xorcle needs |
| `convert_all.py` | batch wrapper around Xorcle's own converter |
| `check_runs.py` | summarise outcomes across all logs and flag memory-outs |
| `backup.sh` | copy just the logs into `backup/`, preserving paths |
