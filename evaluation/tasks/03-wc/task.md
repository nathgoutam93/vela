Write `main.vl`, a program that reads all of its standard input and prints
one line: the number of lines, words and bytes it read, separated by single
spaces, as `wc` does.

- Lines: the number of newline characters (`\n`).
- Words: the number of maximal runs of characters that are not a space,
  a tab or a newline.
- Bytes: the number of bytes.

For the input `hello world\nbye\n` it prints `2 3 16`. The input may be
larger than memory you would want to read in one piece; read it in parts.
