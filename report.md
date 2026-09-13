---
title: XNF solver evaluation
families:
  tseitin_n_k:
    label: Tseitin formulas in CNF
    desc: >-
      Unsatisfiable parity formulas on random k-regular n-vertex graphs, generated with
      `cnfgen`. Grid: (20,k) for k=3..10 and (n,4) for n=10,20,...,1280, five graphs each.
      Provably hard for Resolution; the headline family of the Xorcle paper. Given to every
      solver as CNF, as in that paper.
  pebbling_lifted_h_k:
    label: Pebbling formulas lifted by k-XORs
    desc: >-
      Pebbling formulas on pyramid graphs of height h=60..150, each variable replaced by the
      XOR of k fresh variables (k=2,4,6,8). Solvable by unit propagation alone in XNF.
  random_kxnf_n:
    label: Random k-XNFs
    desc: >-
      k=2..5, n=11..20, clause count tuned so roughly half the instances are satisfiable.
  restricted_kxnf_n:
    label: Restricted random k-XNFs
    desc: >-
      A random k-XNF restricted by N/2 random affine equations, k=2..5, N=22,24,...,40.
  2xnf-ascon:
    label: Ascon-128 (2-Xornado suite)
    desc: >-
      400 satisfiable instances from key-recovery attacks on round-reduced Ascon-128,
      rounds 2/3/4, from the `2xnf_sat_solving` repository.
  2xnf-rand:
    label: Random 2-XNF (unsat-mixed)
    desc: >-
      400 random 2-XNF instances, n=21..40, m=3n, from the 2-Xornado paper's benchmark set.
  2xnf-rand_sat:
    label: Random 2-XNF (satisfiable)
    desc: >-
      400 random 2-XNF instances guaranteed satisfiable, same parameters as above.
  ascon:
    label: Ascon (Xorricane suite, Benchmark 6.5)
    desc: >-
      50 satisfiable instances from state-recovery attacks on Ascon-128, from the
      Xorricane-paper release. Distinct from the 2-Xornado Ascon set.
  bivium:
    label: Bivium (Xorricane Benchmark 6.6)
    desc: >-
      50 satisfiable state-recovery instances on the Bivium stream cipher.
  ctc:
    label: CTC2 (Xorricane Benchmark 6.7)
    desc: >-
      50 satisfiable key-recovery instances on the CTC2 block cipher.
  rand_l2xnf_ld:
    label: Random linear system with 2-XNF constraints (Benchmark 6.3)
    desc: >-
      n/2 random linear equations plus n random 2-XNF clauses, n=61..110.
  rand_qp_type_I:
    label: Multivariate quadratic, Type I (Benchmark 6.4)
    desc: >-
      Random quadratic systems with m=2n, at least one solution, n=11..35.
  rand_qp_type_IV:
    label: Multivariate quadratic, Type IV (Benchmark 6.4)
    desc: >-
      Random quadratic systems with n=floor(1.5m), n=11..35.
---

## Solvers {#solvers}

Four solvers, each given the encoding it is designed for (Tseitin excepted, which is CNF
for all of them). CryptoMiniSat is a CNF-XOR
CDCL solver; Xorcle and Xorricane are XNF CDCL solvers (disjunctions of parity
constraints); Bosphorus combines algebraic and logical reasoning over ANF.

::: scroll
{{solver_table}}
:::

### What CryptoMiniSat needed {#cms-needed}

CryptoMiniSat's defaults are tuned for general CNF, and on these families they discard
almost all of the linear structure before search begins: `--maxnummatrices` defaults to 5
where lifted pebbling builds 11476 simultaneous matrices, and `--maxmatrixrows` defaults
to 2000 where a single Bivium matrix is 10809 rows. The command line above lifts those
cutoffs, which is what makes this a measurement of the CNF-XOR path rather than the plain
CNF one.

Lifting them was not enough on its own — the solver had not been run in that regime
before, and three changes were required. All are in the pinned revision used here:

| Commit | Change | Needed for |
|:------------|:--------------------------------|:-------------------|
| [`068a3fd79`](https://github.com/msoos/cryptominisat/commit/068a3fd79) | fix crash when `--maxnummatrices` exceeds 1000 | lifted pebbling |
| [`bef479cef`](https://github.com/msoos/cryptominisat/commit/bef479cef) | avoid O(num_matrices) per-literal work in Gauss-Jordan elimination | lifted pebbling |
| [`3970aaf24`](https://github.com/msoos/cryptominisat/commit/3970aaf24) | raise `MAX_XOR_RECOVER_SIZE` from 8 to 12 | Tseitin at k = 9, 10 |

The last one mattered because a Tseitin formula on a k-regular graph has one parity
constraint of degree exactly k, and the compile-time ceiling of 8 put k = 9 and k = 10 out
of reach at any runtime setting. With it raised, CryptoMiniSat solves 75/75 of that family
instead of 60/75.

### The improved CryptoMiniSat {#cms-improved}

`cms-improved` is [`b79d6193a`](https://github.com/msoos/cryptominisat/commit/b79d6193a), 70
commits after the [`3970aaf24`](https://github.com/msoos/cryptominisat/commit/3970aaf24) used for
`cms`. It runs with no options, as
[`4b82356e7`](https://github.com/msoos/cryptominisat/commit/4b82356e7) made the settings above its
defaults. Beyond that, Gauss-Jordan elimination was made cheaper, much of CaDiCaL's search was
brought across, and local search was replaced by xnfSAT, which uses the XOR structure.

## Bugs found in the XNF solvers {#bugs}

We wrote `xnf_fuzzer.py`, which extends CryptoMiniSat's CNF fuzzers, among them Brummayer's
FuzzSAT (Brummayer, Lonsing and Biere, SAT 2010), to XNF and 2-XNF. Each instance goes to Xorcle
(and Xorricane on 2-XNF) and, as CNF-XOR, to CryptoMiniSat: SAT answers are checked by
substitution, UNSAT ones by CryptoMiniSat's proof in `cake_xlrup`. We also fuzzed UBSan and
ASan builds of both solvers, and tried a few hand-written edge cases. Most of what turned up
is minor: crashes on degenerate inputs, assertions that only fire in Debug builds, and issues
behind non-default options. Two change the answer, both on unusual input: a variable repeated
inside a lineral, and tab-separated input. CryptoMiniSat gave no wrong answers on the same
instances; its own problems in this regime, listed [above](#cms-needed), were a crash and a
slowdown with many matrices. Each fix is one patch, whose commit message is the bug report.

### Xorcle: `bugs-xorcle/` {#bugs-xorcle}

| Patch | Bug | Impact |
|---|---|---|
| [`patch-1.diff`](https://github.com/msoos/xnf-tests/blob/main/bugs-xorcle/patch-1.diff) | a repeated variable in a lineral is OR-ed, not XOR-ed | wrong answer, on inputs that repeat a variable |
| [`patch-2.diff`](https://github.com/msoos/xnf-tests/blob/main/bugs-xorcle/patch-2.diff) | an empty input clause segfaults instead of giving UNSAT | crash on a degenerate input |
| [`patch-3.diff`](https://github.com/msoos/xnf-tests/blob/main/bugs-xorcle/patch-3.diff) | the proof checker rejects the `p xnf` header | proof checker script only |
| [`patch-4.diff`](https://github.com/msoos/xnf-tests/blob/main/bugs-xorcle/patch-4.diff) | the proof checker has the same OR/XOR parsing bug | proof checker script only |

### Xorricane: `bugs-xorricane/` {#bugs-xorricane}

| Patch | Bug | Impact |
|---|---|---|
| [`patch-1.diff`](https://github.com/msoos/xnf-tests/blob/main/bugs-xorricane/patch-1.diff) | `util` clause deletion writes out of bounds: segfault | crash, non-default `-delh util` only |
| [`patch-2.diff`](https://github.com/msoos/xnf-tests/blob/main/bugs-xorricane/patch-2.diff) | `avg_util` clause deletion (the default) reads uninitialised memory | undefined behaviour; no wrong answer seen |
| [`patch-3.diff`](https://github.com/msoos/xnf-tests/blob/main/bugs-xorricane/patch-3.diff) | every UNSAT answer calls `back()` on an empty list | undefined behaviour; aborts in Debug builds only |
| [`patch-4.diff`](https://github.com/msoos/xnf-tests/blob/main/bugs-xorricane/patch-4.diff) | an assertion dereferences a null pointer with `-no-lgj` | Debug builds with `-no-lgj` only |
| [`patch-5.diff`](https://github.com/msoos/xnf-tests/blob/main/bugs-xorricane/patch-5.diff) | Gauss elimination (`-il`) never reads the first matrix row | missed propagations; same answers |
| [`patch-6.diff`](https://github.com/msoos/xnf-tests/blob/main/bugs-xorricane/patch-6.diff) | the parser splits on spaces only: wrong answer on tabs, CRLF rejected | wrong answer on tab-separated input |
| [`patch-7.diff`](https://github.com/msoos/xnf-tests/blob/main/bugs-xorricane/patch-7.diff) | a late equivalence overwrites an existing one | assertion in Debug builds; release answer correct |
| [`patch-8.diff`](https://github.com/msoos/xnf-tests/blob/main/bugs-xorricane/patch-8.diff) | the empty XOR line `x 0` overflows the heap | crash on a degenerate input |
| [`patch-9.diff`](https://github.com/msoos/xnf-tests/blob/main/bugs-xorricane/patch-9.diff) | an assertion fails with `-rh lbd` when a learnt clause has LBD 0 | Debug builds only; release answer correct |

## Benchmarks {#benchmarks}

::: scroll
{{family_table}}
:::

## Encodings and conversion {#encodings}

The same formula appears in several formats; each solver reads the one it supports.
Conversions were done with these tools:

| Extension | Format | Produced by |
|:--------------|:----------------------|:---------------------|
| `.cnf` | plain CNF, XORs blasted | shipped with the benchmark |
| `.xcnf` / `.cnf-xor` | CNF-XOR | shipped, or `xnf_to_xcnf.py` |
| `.2xcnf` | CNF-XOR built from the 2-XNF | `xnf_to_xcnf.py` |
| `.xnf` | XNF, `+` linerals | shipped |
| `.2xnf` | 2-XNF, at most two linerals per clause | shipped with the benchmark |
| `.anf` | algebraic normal form | shipped with the benchmark |

The CNF-XOR encodings a benchmark does not ship were generated to match the one the
Xorricane paper uses, and reproduce all 200 shipped `.xcnf` files exactly — variable,
clause and xor-line counts all agree.

## Overall results {#overall}

**PAR2** is the SAT-competition penalised average runtime: the mean over attempted
instances of the solve time, with unsolved instances charged twice the timeout. Lower is
better. The *attempted* column makes the denominator explicit, since not every solver ran
on every family.

CDF of solving time over all families. Bosphorus is excluded here because it was only run
on the Ascon and Xorricane-paper suites. CryptoMiniSat appears twice: `cms` is the older
build with the options [above](#cms-needed), `cms-improved` the newer build with none. Where
`cms` was also run on a CNF-XOR encoding (Type I quadratic systems), this plot uses its plain
CNF run. Every line covers all {{total_instances}} instances.

![](pics/cdf_all.svg)

::: scroll
{{par2 cdf_all}}
:::

## Per-family results {#families}

{{per_family}}

## Caveats {#caveats}

::: note
**CryptoMiniSat XOR size limit.** With the default `--maxxorsize 7`, every Tseitin
instance with k ≥ 8 times out while every k ≤ 7 instance solves in 0.0 s — the parity
constraints have degree exactly k, so at k=8 none are recovered and the solver is left
doing pure resolution. The Xorcle paper points this limit out as well.
:::

::: note
**Bivium encoding.** On the Xorricane suites CryptoMiniSat is given the plain `.cnf`, not
the shipped `.xcnf`, and this choice favours it: on Bivium it solves 34/50 from the `.cnf`
but only 1/50 from the `.xcnf`. The CNF-XOR files are translated from the XNF and keep its
wide linerals, which gives a much denser XOR system than the one CryptoMiniSat recovers
from the CNF itself.
:::

::: note
**Memory on lifted pebbling.** With over ten thousand matrices or parity constraints per
instance, lifted pebbling is the memory-heavy family: peak RSS is 11.6 GB for `cms-improved`,
9.9 GB for Xorcle and 6.5 GB for `cms`, while Xorricane stays under 1 GB. This limits how many
runs can be scheduled in parallel, a practical cost the solved counts do not show.
:::
