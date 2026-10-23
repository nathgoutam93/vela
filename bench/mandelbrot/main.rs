// mandelbrot in Rust: the same algorithm as main.vl.
use std::env;

fn main() {
    let n: i64 = env::args().nth(1).and_then(|s| s.parse().ok()).unwrap_or(200);
    let size = n as f64;
    let mut count = 0;
    for y in 0..n {
        let ci = 2.0 * y as f64 / size - 1.0;
        for x in 0..n {
            let cr = 2.0 * x as f64 / size - 1.5;
            let (mut zr, mut zi) = (0.0f64, 0.0f64);
            let mut inside = true;
            for _ in 0..50 {
                let tr = zr * zr - zi * zi + cr;
                let ti = 2.0 * zr * zi + ci;
                zr = tr;
                zi = ti;
                if zr * zr + zi * zi > 4.0 {
                    inside = false;
                    break;
                }
            }
            if inside {
                count = count + 1;
            }
        }
    }
    println!("{}", count);
}
