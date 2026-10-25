Write `main.vl`, a program run as `vela run main.vl N`.

It prints the numbers from 1 to N, one per line, except that multiples of
3 print `Fizz`, multiples of 5 print `Buzz`, and multiples of both print
`FizzBuzz`.

If there is not exactly one argument, or it is not a whole number of at
least 1, the program prints `usage: fizzbuzz N` to standard error and exits
with code 2, printing nothing to standard output.
