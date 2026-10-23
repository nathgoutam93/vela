`main.vl` and `store.vl` keep a stock file, with the commands `list` and
`add`. Add two more:

- `vela run main.vl FILE remove NAME N` takes N of NAME out of the stock.
  When the stock has fewer than N of it (or none), the program prints
  `not enough NAME` to standard error, exits with code 1 and leaves the
  file as it was. When none is left, the item's line goes from the file.
  On success it prints nothing.
- `vela run main.vl FILE total` prints the total quantity of all items.

`list` and `add` must keep working as they do.
