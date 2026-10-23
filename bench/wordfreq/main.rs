// word-frequency in Rust: the same algorithm as main.vl, with the standard
// HashMap keyed by slices of the text.
use std::collections::HashMap;
use std::env;
use std::fs;

fn main() {
    let path = match env::args().nth(1) {
        Some(p) => p,
        None => {
            println!("usage: wordfreq TEXT");
            std::process::exit(2);
        }
    };
    let text = fs::read(&path).expect("cannot read the input");
    let mut counts: HashMap<&[u8], u64> = HashMap::new();
    let mut total = 0;
    for w in text.split(|&c| c == b' ' || c == b'\n') {
        if !w.is_empty() {
            *counts.entry(w).or_insert(0) += 1;
            total += 1;
        }
    }
    let before = |a: &[u8], b: &[u8]| counts[a] > counts[b] || counts[a] == counts[b] && a < b;
    let mut top: Vec<&[u8]> = Vec::new();
    for &w in counts.keys() {
        if top.len() < 10 || before(w, top[top.len() - 1]) {
            if top.len() == 10 {
                top[9] = w;
            } else {
                top.push(w);
            }
            let mut j = top.len() - 1;
            while j > 0 && before(top[j], top[j - 1]) {
                top.swap(j, j - 1);
                j -= 1;
            }
        }
    }
    println!("words {}", total);
    println!("unique {}", counts.len());
    for w in top {
        println!("{} {}", String::from_utf8_lossy(w), counts[w]);
    }
}
