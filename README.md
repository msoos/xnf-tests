# Reproducing the XNF solver evaluations

XNF — *XOR-OR-AND normal form* — generalises CNF by letting each literal be a XOR of
literals (a *lineral*), so a clause is a disjunction of parity equations. Several papers
have proposed solvers for it, each with its own benchmark suite and its own comparison
against CNF and CNF-XOR solvers.

This repository puts all of those evaluations on one machine, one set of benchmarks and one
harness, so the results can be compared directly rather than across four papers with four
different setups. It runs five solvers over roughly 1700 instances in fourteen families,
collects every run into a SQLite database, and produces cactus plots, PAR2 tables and a
single self-contained HTML report.

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

None of the instance files are committed — they are generated or downloaded.

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
./run_all.sh
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
cactus plots and PAR2 tables into `pics/` as PNG, PDF and SVG, alongside the CSV data behind
each curve. `make_report.py` assembles **`report.html`**: a single self-contained page
covering what was run, how each benchmark family was generated, which encoding each solver
saw, the plots, the PAR2 tables and the caveats.

## The other scripts

| Script | Purpose |
|---|---|
| `xnf_to_xcnf.py` | XNF to CNF-XOR, in the Xorricane paper's encoding |
| `xcnf_to_xnf.py` | CNF-XOR `x`-lines to XNF linerals, which Xorcle needs |
| `convert_all.py` | batch wrapper around Xorcle's own converter |
| `check_runs.py` | summarise outcomes across all logs and flag memory-outs |
| `backup.sh` | copy just the logs into `backup/`, preserving paths |
