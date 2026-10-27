// The compiler is a program like any other: its JSON is the json package,
// in this repository, so the compiler builds with no network.
package vela
use json ../../packages/json
// Its passes recurse through expressions, and generated code can nest
// tens of thousands deep (a + b + c + ...); the system's 8 MB main stack
// holds a few thousand. The stack is reserved, and used only as needed.
stack 1G
