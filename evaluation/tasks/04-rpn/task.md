Write the module `rpn.vl` with one public function:

    pub fn eval(expr: Str) -> Result[Int, Str]

It evaluates an expression in reverse Polish notation: tokens separated by
one or more spaces, each either a whole number (`12`, `-3`) or one of the
operators `+`, `-`, `*` and `/` (division of whole numbers, rounding toward
zero). An operator takes the two values before it: `3 4 -` is -1.

It returns `Ok` with the value, or `Err` with exactly one of these messages:

- `empty` when there are no tokens;
- `not enough operands` when an operator has fewer than two values;
- `division by zero`;
- `unknown token 'T'`, where T is the token, for anything else;
- `too many values` when more than one value is left at the end.

Other code will use it as `import rpn` and `rpn.eval("3 4 +")`.
