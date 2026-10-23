// binary-trees in Rust: the same algorithm as main.vl, a Box per node
// (None is a leaf), as idiomatic Rust writes it.
use std::env;

struct Tree {
    left: Option<Box<Tree>>,
    right: Option<Box<Tree>>,
}

fn make(depth: i64) -> Box<Tree> {
    if depth == 0 {
        return Box::new(Tree { left: None, right: None });
    }
    Box::new(Tree { left: Some(make(depth - 1)), right: Some(make(depth - 1)) })
}

fn check(t: &Option<Box<Tree>>) -> i64 {
    match t {
        None => 0,
        Some(n) => 1 + check(&n.left) + check(&n.right),
    }
}

fn main() {
    let n: i64 = env::args().nth(1).and_then(|s| s.parse().ok()).unwrap_or(10);
    let min_depth = 4;
    let max_depth = if min_depth + 2 > n { min_depth + 2 } else { n };
    let stretch = max_depth + 1;
    println!("stretch tree of depth {} check: {}", stretch, check(&Some(make(stretch))));
    let long_lived = Some(make(max_depth));
    let mut depth = min_depth;
    while depth <= max_depth {
        let iterations = 1i64 << (max_depth - depth + min_depth);
        let mut sum = 0;
        for _ in 0..iterations {
            sum = sum + check(&Some(make(depth)));
        }
        println!("{} trees of depth {} check: {}", iterations, depth, sum);
        depth = depth + 2;
    }
    println!("long lived tree of depth {} check: {}", max_depth, check(&long_lived));
}
