package main

import (
	"fmt"
	"os"
	"runtime"
	"strconv"
)

type tree struct{ left, right *tree }

func makeTree(depth int) *tree {
	if depth == 0 {
		return &tree{}
	}
	return &tree{makeTree(depth - 1), makeTree(depth - 1)}
}
func check(t *tree) int64 {
	if t == nil {
		return 0
	}
	return 1 + check(t.left) + check(t.right)
}
func main() {
	n := 10
	if len(os.Args) > 1 {
		var err error
		n, err = strconv.Atoi(os.Args[1])
		if err != nil {
			panic(err)
		}
	}
	if n < 6 {
		n = 6
	}
	fmt.Printf("stretch tree of depth %d check: %d\n", n+1, check(makeTree(n+1)))
	longLived := makeTree(n)
	for depth := 4; depth <= n; depth += 2 {
		iterations := 1 << (n - depth + 4)
		var sum int64
		for i := 0; i < iterations; i++ {
			sum += check(makeTree(depth))
		}
		fmt.Printf("%d trees of depth %d check: %d\n", iterations, depth, sum)
	}
	fmt.Printf("long lived tree of depth %d check: %d\n", n, check(longLived))
	runtime.KeepAlive(longLived)
}
