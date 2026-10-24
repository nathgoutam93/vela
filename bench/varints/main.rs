// The same packed uint64 decoder and zero-copy tail as the C/Vela versions.
fn parse(data: &[u8]) -> (u64, usize, &[u8]) {
    let (mut checksum, mut count, mut position, mut last_start) = (0u64, 0, 0, 0);
    while position < data.len() {
        last_start = position;
        let mut value = 0u64; let mut complete = false;
        for group in 0..10 {
            assert!(position < data.len());
            let b = data[position]; position += 1;
            assert!(group != 9 || b <= 1);
            value |= u64::from(b & 127) << (group * 7);
            if b < 128 { complete = true; break; }
        }
        assert!(complete);
        checksum = checksum.wrapping_add(value); count += 1;
    }
    (checksum, count, &data[last_start..position])
}
fn main() {
    let args: Vec<String> = std::env::args().collect();
    let count: usize = args.get(1).map(|s| s.parse().unwrap()).unwrap_or(262144);
    let rounds: usize = args.get(2).map(|s| s.parse().unwrap()).unwrap_or(32);
    assert!(count > 0 && count <= 1048576);
    let mut data = Vec::with_capacity(count * 10);
    let mut state = 1u64;
    for _ in 0..count {
        state = state.wrapping_mul(6364136223846793005).wrapping_add(1);
        let mut value = state;
        while value >= 128 { data.push(((value & 127) | 128) as u8); value >>= 7; }
        data.push(value as u8);
    }
    let mut sum = 0u64;
    for r in 0..rounds {
        let (checksum, count, last) = parse(&data[r % data.len()..]);
        sum = sum.wrapping_add(checksum).wrapping_add(count as u64).wrapping_add(last.len() as u64);
    }
    println!("{}", sum);
}
