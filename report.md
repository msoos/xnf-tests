---
title: XNF solver evaluation
families:
  tseitin_n_k:
    label: Tseitin formulas in CNF
    desc: >-
      Unsatisfiable parity formulas on random k-regular n-vertex graphs, generated with
      `cnfgen`. Grid: (20,k) for k=3..10 and (n,4) for n=10,20,...,1280, five graphs each.
      Provably hard for Resolution; the headline family of the Xorcle paper.
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

Four solvers, each given the encoding it is designed for. CryptoMiniSat is a CNF-XOR
CDCL solver; Xorcle and Xorricane are XNF CDCL solvers (disjunctions of parity
constraints); Bosphorus combines algebraic and logical reasoning over ANF.

::: scroll
{{solver_table}}
:::

### What CryptoMiniSat needed

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

### The improved CryptoMiniSat

The `cms-improved` series is a newer CryptoMiniSat,
[`b79d6193a`](https://github.com/msoos/cryptominisat/commit/b79d6193a), against
[`3970aaf24`](https://github.com/msoos/cryptominisat/commit/3970aaf24) for `cms` — and it needs
none of the tuning above, because the limits it used to trip over are gone and the CNF-XOR path
now carries its own weight on defaults. Over the 895 instances where the two builds were given the
identical file, it solves 718 against 697 and cuts PAR2 from 96.1 s to 83.7 s, with the gains
concentrated where the linear structure is doing the work: random k-XNF 37 → 40 (PAR2 33.5 s →
2.3 s), restricted k-XNF 37 → 40 (31.0 s → 2.3 s), Bivium 34 → 39 (131.8 s → 93.5 s), MQ Type I
30 → 34 and the random linear + 2-XNF family 40 → 43. It loses nothing anywhere except lifted
pebbling, where both solve all 40 and the newer build is 1.3 s slower on average.

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

CDF of solving time over all families. Bosphorus is excluded here because it was not run
on every family — only on the Ascon and Xorricane-paper suites — as is the
XOR-detection-off CryptoMiniSat configuration, which ran only on Bivium. CryptoMiniSat
appears twice: it was run on both a CNF-XOR and a plain CNF encoding of six families, so
each line takes that encoding where it exists and the family's only encoding elsewhere.
Both cover all {{total_instances}} instances.

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
doing pure resolution.
:::

::: note
**Bivium CNF-XOR encoding.** CryptoMiniSat solves 1/50 on the shipped `.xcnf` but 34/50 on
the plain `.cnf`. This is not an encoding-class effect: the CNF-XOR files were produced by
re-translating from XNF, which inherits the XNF's wide linerals and leaves the XOR system
far denser than the one CryptoMiniSat recovers for itself. See [Why CryptoMiniSat does
best on the plain CNF](#encodings). For this family the `.cnf` column is the meaningful
one.
:::

::: note
**Xorcle memory use.** Xorcle has the highest peak memory of any solver here — 9.9 GB,
against 6.5 GB for CryptoMiniSat and 1.8 GB for Xorricane — and eight of its runs exceeded
4 GB, versus three for CryptoMiniSat and none for any other solver. The pressure is
concentrated in lifted pebbling (2.1 GB average, 9.9 GB peak), where it limits how many
Xorcle runs can be scheduled in parallel, a practical cost the solved counts do not show.
:::
