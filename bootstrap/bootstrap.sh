#!/bin/sh
# Build Vela from the seed, with nothing but a C compiler, and check the
# fixed point: the compiler, compiling its own source, writes exactly the C
# it was built from.
#
#     sh bootstrap/bootstrap.sh            build build/vela and check
#     sh bootstrap/bootstrap.sh --update   also refresh the seed after a change to stage1/
#     sh bootstrap/bootstrap.sh --native   also check the native backend's fixed point (M11)
#
# bootstrap/vela1.c is the seed: the C that Stage 1 (stage1/, the compiler
# written in Vela) writes for itself. Generation 1 is built from it by the C
# compiler; generation 2 by generation 1, from stage1/; generation 3 by
# generation 2. Generations 2 and 3 must write byte-identical C.
#
# VELA_CC picks the C compiler (default cc).
set -e
update=false
native=false
for arg in "$@"; do
    case "$arg" in
        --update) update=true ;;
        --native) native=true ;;
        *) echo "usage: sh bootstrap/bootstrap.sh [--update] [--native]" >&2; exit 2 ;;
    esac
done
# Everything runs from the repository root with relative paths: the C
# records source positions (for panics) as "stage1/lexer.vl:12:5", so an
# absolute path would make the output depend on where the repository is.
cd "$(dirname "$0")/.."
cc=${VELA_CC:-cc}
build=build
platform_libs=
case "${OS:-}" in Windows_NT) platform_libs="-lws2_32 -lshell32" ;; esac
mkdir -p "$build"

compile() {  # compile C_FILE EXE
    $cc -std=c11 -O2 -pthread -I runtime "$1" runtime/vela_rt.c -lm $platform_libs -o "$2"
}

echo "generation 1: the seed, compiled by $cc"
compile bootstrap/vela1.c "$build/vela-gen1"

# `vela build` compiles the C it writes in parts at the same time (M13);
# the C is what `vela c` prints.
echo "generation 2: built by generation 1"
"$build/vela-gen1" build stage1/main.vl -o "$build/vela-gen2"
"$build/vela-gen2" c stage1/main.vl > "$build/gen2.c"

echo "generation 3: built by generation 2"
"$build/vela-gen2" build stage1/main.vl -o "$build/vela-gen3"
"$build/vela-gen3" c stage1/main.vl > "$build/gen3.c"

if ! cmp -s "$build/gen2.c" "$build/gen3.c"; then
    echo "NOT a fixed point: generations 2 and 3 write different C (see build/gen2.c, build/gen3.c)" >&2
    exit 1
fi
echo "fixed point: generations 2 and 3 write identical C ($(wc -l < "$build/gen3.c") lines)"

if ! cmp -s bootstrap/vela1.c "$build/gen3.c"; then
    if $update; then
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
rm -f "$build/vela-gen1" "$build/vela-gen2" "$build/gen2.c" "$build/gen3.c"
echo "built build/vela"

# The native backend: the compiler compiled to native host assembly by build/vela,
# then by itself; both must write the same assembly for the compiler.
if $native; then
    echo "native 1: built by build/vela with VELA_BACKEND=native"
    VELA_BACKEND=native "$build/vela" build stage1/main.vl -o "$build/vela-native1"
    "$build/vela-native1" asm stage1/main.vl > "$build/native1.s"
    echo "native 2: built by native 1"
    VELA_BACKEND=native "$build/vela-native1" build stage1/main.vl -o "$build/vela-native2"
    "$build/vela-native2" asm stage1/main.vl > "$build/native2.s"
    if ! cmp -s "$build/native1.s" "$build/native2.s"; then
        echo "NOT a native fixed point: see build/native1.s, build/native2.s" >&2
        exit 1
    fi
    echo "native fixed point: natives 1 and 2 write identical assembly ($(wc -l < "$build/native2.s") lines)"
    mv "$build/vela-native2" "$build/vela-native"
    rm -f "$build/vela-native1" "$build/native1.s" "$build/native2.s"
    echo "built build/vela-native"
fi
