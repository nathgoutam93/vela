// fannkuch-redux in Rust: the same algorithm as main.vl.
use std::env;

fn main() {
    let n: usize = env::args().nth(1).and_then(|s| s.parse().ok()).unwrap_or(7);
    let mut perm1: Vec<usize> = (0..n).collect();
    let mut count = vec![0usize; n];
    let mut perm = vec![0usize; n];
    let (mut max_flips, mut checksum, mut perm_count): (i64, i64, i64) = (0, 0, 0);
    let mut r = n;
    loop {
        while r != 1 {
            count[r - 1] = r;
            r = r - 1;
        }
        perm.copy_from_slice(&perm1);
        let mut flips = 0;
        let mut k = perm[0];
        while k != 0 {
            let (mut i, mut j) = (0, k);
            while i < j {
                perm.swap(i, j);
                i = i + 1;
                j = j - 1;
            }
            flips = flips + 1;
            k = perm[0];
        }
        if flips > max_flips {
            max_flips = flips;
        }
        if perm_count % 2 == 0 {
            checksum = checksum + flips;
        } else {
            checksum = checksum - flips;
        }
        loop {
            if r == n {
                println!("{}\nPfannkuchen({}) = {}", checksum, n, max_flips);
                return;
            }
            let first = perm1[0];
            for i in 0..r {
                perm1[i] = perm1[i + 1];
            }
            perm1[r] = first;
            count[r] = count[r] - 1;
            if count[r] > 0 {
                break;
            }
            r = r + 1;
        }
        perm_count = perm_count + 1;
    }
}
