Write `main.vl`, a program run as `vela run main.vl N` (N at least 10).

It counts the prime numbers below N in ten parts: part i, for i from 0 to
9, is the numbers from i*N/10 up to but not including (i+1)*N/10, with `/`
rounding down. It prints `total P`, where P is the number of primes below
N, then one line `i: C` per part, C being the number of primes in it. For
N = 100:

    total 25
    0: 4
    1: 4
    ...

The ten parts must be counted in parallel, with the `tasks` module.
