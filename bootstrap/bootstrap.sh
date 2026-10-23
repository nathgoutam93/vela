#!/bin/sh
# Build Vela from the seed, with nothing but a C compiler, and check the
# fixed point: the compiler, compiling its own source, writes exactly the C
# it was built from.
#
#     sh bootstrap/bootstrap.sh            build build/vela and check
#     sh bootstrap/bootstrap.sh --update   also refresh the seed after a change to stage1/
#
# bootstrap/vela1.c is the seed: the C that Stage 1 (stage1/, the compiler
# written in Vela) writes for itself. Generation 1 is built from it by the C
# compiler; generation 2 from generation 1's C; generation 3 from
# generation 2's. Generations 2 and 3 must write byte-identical C.
#
# VELA_CC picks the C compiler (default cc).
set -e
# Everything runs from the repository root with relative paths: the C
# records source positions (for panics) as "stage1/lexer.vl:12:5", so an
# absolute path would make the output depend on where the repository is.
cd "$(dirname "$0")/.."
cc=${VELA_CC:-cc}
build=build
mkdir -p "$build"

compile() {  # compile C_FILE EXE
    $cc -std=c11 -O2 -pthread -I runtime "$1" runtime/vela_rt.c -o "$2"
}

echo "generation 1: the seed, compiled by $cc"
compile bootstrap/vela1.c "$build/vela-gen1"
"$build/vela-gen1" c stage1/main.vl > "$build/gen1.c"

echo "generation 2: built from generation 1's C"
compile "$build/gen1.c" "$build/vela-gen2"
"$build/vela-gen2" c stage1/main.vl > "$build/gen2.c"

echo "generation 3: built from generation 2's C"
compile "$build/gen2.c" "$build/vela-gen3"
"$build/vela-gen3" c stage1/main.vl > "$build/gen3.c"

if ! cmp -s "$build/gen2.c" "$build/gen3.c"; then
    echo "NOT a fixed point: generations 2 and 3 write different C (see build/gen2.c, build/gen3.c)" >&2
    exit 1
fi
echo "fixed point: generations 2 and 3 write identical C ($(wc -l < "$build/gen3.c") lines)"

if ! cmp -s bootstrap/vela1.c "$build/gen3.c"; then
    if [ "$1" = "--update" ]; then
        cp "$build/gen3.c" bootstrap/vela1.c
        echo "the seed is updated"
    else
        echo "the seed is out of date: stage1/ changed since it was made; run with --update" >&2
        exit 1
    fi
else
    echo "the seed is up to date"
fi
mv "$build/vela-gen3" "$build/vela"
rm -f "$build/vela-gen1" "$build/vela-gen2" "$build/gen1.c" "$build/gen2.c" "$build/gen3.c"
echo "built build/vela"
