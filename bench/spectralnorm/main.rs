// spectral-norm in Rust: the same algorithm as main.vl.
use std::env;

fn eval_a(i: i64, j: i64) -> f64 {
    1.0 / ((i + j) * (i + j + 1) / 2 + i + 1) as f64
}

fn times(v: &[f64], out: &mut [f64]) {
    let n = v.len();
    for i in 0..n {
        let mut sum = 0.0;
        for j in 0..n {
            sum = sum + eval_a(i as i64, j as i64) * v[j];
        }
        out[i] = sum;
    }
}

fn times_transposed(v: &[f64], out: &mut [f64]) {
    let n = v.len();
    for i in 0..n {
        let mut sum = 0.0;
        for j in 0..n {
            sum = sum + eval_a(j as i64, i as i64) * v[j];
        }
        out[i] = sum;
    }
}

fn times_ata(v: &[f64], out: &mut [f64], tmp: &mut [f64]) {
    times(v, tmp);
    times_transposed(tmp, out);
}

fn fixed9(x: f64) -> String {
    let (a, sign) = if x < 0.0 { (0.0 - x, "-") } else { (x, "") };
    let scaled = (a * 1000000000.0 + 0.5) as i64;
    format!("{}{}.{:09}", sign, scaled / 1000000000, scaled % 1000000000)
}

fn main() {
    let n: usize = env::args().nth(1).and_then(|s| s.parse().ok()).unwrap_or(100);
    let mut u = vec![1.0; n];
    let mut v = vec![0.0; n];
    let mut tmp = vec![0.0; n];
    for _ in 0..10 {
        times_ata(&u, &mut v, &mut tmp);
        times_ata(&v, &mut u, &mut tmp);
    }
    let (mut vbv, mut vv) = (0.0, 0.0);
    for i in 0..n {
        vbv = vbv + u[i] * v[i];
        vv = vv + v[i] * v[i];
    }
    println!("{}", fixed9((vbv / vv).sqrt()));
}
