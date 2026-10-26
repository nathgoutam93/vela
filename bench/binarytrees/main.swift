// Recursive value enum, corresponding to Vela's Tree representation.
indirect enum Tree { case leaf; case node(Tree, Tree) }
func make(_ depth: Int) -> Tree {
    if depth == 0 { return .node(.leaf, .leaf) }
    return .node(make(depth - 1), make(depth - 1))
}
func check(_ tree: Tree) -> Int {
    switch tree {
    case .leaf: return 0
    case let .node(left, right): return 1 + check(left) + check(right)
    }
}
let n = max(6, CommandLine.arguments.count > 1 ? Int(CommandLine.arguments[1])! : 10)
print("stretch tree of depth \(n + 1) check: \(check(make(n + 1)))")
let longLived = make(n)
for depth in stride(from: 4, through: n, by: 2) {
    let iterations = 1 << (n - depth + 4)
    var sum = 0
    for _ in 0..<iterations { sum += check(make(depth)) }
    print("\(iterations) trees of depth \(depth) check: \(sum)")
}
print("long lived tree of depth \(n) check: \(check(longLived))")
