#[derive(Clone, Copy)]
struct Slot { index: i64, generation: i64 }
#[derive(Clone, Copy)]
struct Node { left: Slot, right: Slot }
struct Arena { data: Vec<Node>, generation: i64 }
impl Arena {
    fn new(cap: usize) -> Self { Self { data: Vec::with_capacity(cap), generation: 0 } }
    fn reset(&mut self) { self.data.clear(); self.generation += 1; }
    fn get(&self, slot: Slot) -> Node {
        assert!(slot.generation == self.generation && slot.index >= 0);
        self.data[slot.index as usize]
    }
}
fn make(arena: &mut Arena, depth: i64) -> Slot {
    let mut left = Slot { index: -1, generation: arena.generation };
    let mut right = left;
    if depth > 0 { left = make(arena, depth - 1); right = make(arena, depth - 1); }
    let slot = Slot { index: arena.data.len() as i64, generation: arena.generation };
    arena.data.push(Node { left, right }); slot
}
fn check(arena: &Arena, slot: Slot) -> u64 {
    if slot.index < 0 { return 0; }
    let n = arena.get(slot);
    1u64.wrapping_add(check(arena, n.left)).wrapping_add(check(arena, n.right))
}
fn main() {
    let depth: i64 = std::env::args().nth(1).map(|s| s.parse().unwrap()).unwrap_or(16);
    assert!((0..=20).contains(&depth)); let depth = depth.max(6);
    let mut scratch = Arena::new((1usize << (depth + 2)) - 1);
    let stretch = make(&mut scratch, depth + 1); println!("{}", check(&scratch, stretch)); scratch.reset();
    let mut permanent = Arena::new((1usize << (depth + 1)) - 1);
    let root = make(&mut permanent, depth);
    for d in (4..=depth).step_by(2) {
        let iterations = 1i64 << (depth - d + 4); let mut sum = 0u64;
        for _ in 0..iterations { let tree = make(&mut scratch, d); sum = sum.wrapping_add(check(&scratch, tree)); scratch.reset(); }
        println!("{}", sum);
    }
    println!("{}", check(&permanent, root));
}
