Write `main.vl`, a program run as `vela run main.vl FILE`.

FILE is a CSV file whose first line is the header `name,amount`. Every
other line is a name and a whole number (which may be negative), separated
by a comma; spaces around either are allowed and ignored, and blank lines
are skipped.

The program prints, for each name, its total as `name: total`, in
alphabetical order of the names, then `total: T` for the sum of all
amounts. For example, for

    name,amount
    ann,10
    bob,5
    ann,-3

it prints

    ann: 7
    bob: 5
    total: 12

If a line is not a name and a whole number, the program prints
`line N: bad row` to standard error, where N is the line's number in the
file counting the header as line 1, prints nothing to standard output, and
exits with code 1. If the file cannot be read, it prints a message
containing `cannot read` to standard error and exits with code 1.
