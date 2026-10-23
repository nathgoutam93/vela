`ledger.vl` records deposits and withdrawals. Add a third kind of event,
a fee with an amount and a reason:

    Fee(Int, Str)

- `balance` subtracts a fee's amount.
- `describe` writes a fee as `fee 5 (monthly)`.
- `parse` reads `fee 5 monthly`: the word `fee`, the amount, then the
  reason, which is the rest of the line and may have spaces in it
  (`fee 2 late payment` has the reason `late payment`). A fee with no
  reason is a bad line, as is any line `parse` cannot read, with the same
  message as now.

Deposits and withdrawals must work as before.
