`dedupe.vl` removes repeated strings from an array, keeping the first of
each in its place. It is correct, but far too slow for large arrays: it
must handle 100,000 strings in well under a second. Make it fast, keeping
its name, its type and what it returns.
