// fasta in Rust: the same algorithm as main.vl.
use std::env;
use std::io::{self, BufWriter, Write};

const ALU: &[u8] = b"GGCCGGGCGCGGTGGCTCACGCCTGTAATCCCAGCACTTTGGGAGGCCGAGGCGGGCGGATCACCTGAGGTCAGGAGTTCGAGACCAGCCTGGCCAACATGGTGAAACCCCGTCTCTACTAAAAATACAAAAATTAGCCGGGCGTGGTGGCGCGCGCCTGTAATCCCAGCTACTCGGGAGGCTGAGGCAGGAGAATCGCTTGAACCCGGGAGGCGGAGGTTGCAGTGAGCCGAGATCGCGCCACTGCACTCCAGCCTGGGCGACAGAGCGAGACTCCGTCTCAAAAA";

fn next_random(seed: &mut i64, max: f64) -> f64 {
    *seed = (*seed * 3877 + 29573) % 139968;
    max * *seed as f64 / 139968.0
}

fn cumulative(probs: &[f64]) -> Vec<f64> {
    let mut sum = 0.0;
    probs.iter().map(|p| { sum = sum + p; sum }).collect()
}

fn repeat_fasta(out: &mut impl Write, header: &str, s: &[u8], n: usize) {
    writeln!(out, "{}", header).unwrap();
    let k = s.len();
    let (mut pos, mut left) = (0, n);
    let mut line_buf = [0u8; 61];
    while left > 0 {
        let line = left.min(60);
        for i in 0..line {
            line_buf[i] = s[pos];
            pos = pos + 1;
            if pos == k {
                pos = 0;
            }
        }
        line_buf[line] = b'\n';
        out.write_all(&line_buf[..line + 1]).unwrap();
        left = left - line;
    }
}

fn random_fasta(out: &mut impl Write, header: &str, letters: &[u8], cum: &[f64], n: usize, seed: &mut i64) {
    writeln!(out, "{}", header).unwrap();
    let m = letters.len();
    let mut left = n;
    let mut line_buf = [0u8; 61];
    while left > 0 {
        let line = left.min(60);
        for j in 0..line {
            let r = next_random(seed, 1.0);
            let mut i = 0;
            while i < m - 1 && r >= cum[i] {
                i = i + 1;
            }
            line_buf[j] = letters[i];
        }
        line_buf[line] = b'\n';
        out.write_all(&line_buf[..line + 1]).unwrap();
        left = left - line;
    }
}

fn main() {
    let n: usize = env::args().nth(1).and_then(|s| s.parse().ok()).unwrap_or(1000);
    let iub = cumulative(&[0.27, 0.12, 0.12, 0.27, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02]);
    let homo = cumulative(&[0.3029549426680, 0.1979883004921, 0.1975473066391, 0.3015094502008]);
    let stdout = io::stdout();
    let mut out = BufWriter::new(stdout.lock());
    let mut seed = 42;
    repeat_fasta(&mut out, ">ONE Homo sapiens alu", ALU, 2 * n);
    random_fasta(&mut out, ">TWO IUB ambiguity codes", b"acgtBDHKMNRSVWY", &iub, 3 * n, &mut seed);
    random_fasta(&mut out, ">THREE Homo sapiens frequency", b"acgt", &homo, 5 * n, &mut seed);
}
