// k-nucleotide in Rust: the same algorithm as main.vl, with the standard
// HashMap keyed by slices of the sequence.
use std::collections::HashMap;
use std::env;
use std::fs;

fn counts(seq: &[u8], k: usize) -> HashMap<&[u8], u64> {
    let mut m = HashMap::new();
    for i in 0..seq.len() + 1 - k {
        *m.entry(&seq[i..i + k]).or_insert(0) += 1;
    }
    m
}

fn main() {
    let path = match env::args().nth(1) {
        Some(p) => p,
        None => {
            println!("usage: knucleotide FASTA_OUTPUT");
            std::process::exit(2);
        }
    };
    let text = fs::read(&path).expect("cannot read the input");
    let mut seq = Vec::new();
    let mut in_three = false;
    for line in text.split(|&c| c == b'\n') {
        if !line.is_empty() && line[0] == b'>' {
            in_three = line.starts_with(b">THREE");
        } else if in_three {
            seq.extend(line.iter().map(|c| c.to_ascii_uppercase()));
        }
    }
    for k in 1..3 {
        let m = counts(&seq, k);
        let mut keys: Vec<&[u8]> = m.keys().copied().collect();
        keys.sort_by(|a, b| m[b].cmp(&m[a]).then(a.cmp(b)));
        for key in keys {
            println!("{} {}", String::from_utf8_lossy(key), m[key]);
        }
        println!();
    }
    for s in ["GGT", "GGTA", "GGTATT", "GGTATTTTAATT", "GGTATTTTAATTTATAGT"] {
        let m = counts(&seq, s.len());
        println!("{}\t{}", m.get(s.as_bytes()).copied().unwrap_or(0), s);
    }
}
