// n-body in Rust: the same algorithm as main.vl, operation for operation.
use std::env;

#[derive(Clone, Copy)]
struct Body { x: f64, y: f64, z: f64, vx: f64, vy: f64, vz: f64, mass: f64 }

const PI: f64 = 3.141592653589793;
const SOLAR_MASS: f64 = 4.0 * PI * PI;
const DAYS_PER_YEAR: f64 = 365.24;

fn body(x: f64, y: f64, z: f64, vx: f64, vy: f64, vz: f64, mass: f64) -> Body {
    Body { x, y, z, vx: vx * DAYS_PER_YEAR, vy: vy * DAYS_PER_YEAR, vz: vz * DAYS_PER_YEAR, mass: mass * SOLAR_MASS }
}

fn offset_momentum(bodies: &mut [Body]) {
    let (mut px, mut py, mut pz) = (0.0, 0.0, 0.0);
    for b in bodies.iter() {
        px = px + b.vx * b.mass;
        py = py + b.vy * b.mass;
        pz = pz + b.vz * b.mass;
    }
    bodies[0].vx = 0.0 - px / SOLAR_MASS;
    bodies[0].vy = 0.0 - py / SOLAR_MASS;
    bodies[0].vz = 0.0 - pz / SOLAR_MASS;
}

fn energy(bodies: &[Body]) -> f64 {
    let mut e = 0.0;
    let n = bodies.len();
    for i in 0..n {
        let b = bodies[i];
        e = e + 0.5 * b.mass * (b.vx * b.vx + b.vy * b.vy + b.vz * b.vz);
        for j in i + 1..n {
            let o = bodies[j];
            let (dx, dy, dz) = (b.x - o.x, b.y - o.y, b.z - o.z);
            e = e - b.mass * o.mass / (dx * dx + dy * dy + dz * dz).sqrt();
        }
    }
    e
}

fn advance(bodies: &mut [Body], dt: f64) {
    let n = bodies.len();
    for i in 0..n {
        for j in i + 1..n {
            let dx = bodies[i].x - bodies[j].x;
            let dy = bodies[i].y - bodies[j].y;
            let dz = bodies[i].z - bodies[j].z;
            let d2 = dx * dx + dy * dy + dz * dz;
            let mag = dt / (d2 * d2.sqrt());
            let mj = bodies[j].mass * mag;
            bodies[i].vx = bodies[i].vx - dx * mj;
            bodies[i].vy = bodies[i].vy - dy * mj;
            bodies[i].vz = bodies[i].vz - dz * mj;
            let mi = bodies[i].mass * mag;
            bodies[j].vx = bodies[j].vx + dx * mi;
            bodies[j].vy = bodies[j].vy + dy * mi;
            bodies[j].vz = bodies[j].vz + dz * mi;
        }
    }
    for b in bodies.iter_mut() {
        b.x = b.x + dt * b.vx;
        b.y = b.y + dt * b.vy;
        b.z = b.z + dt * b.vz;
    }
}

fn fixed9(x: f64) -> String {
    let (a, sign) = if x < 0.0 { (0.0 - x, "-") } else { (x, "") };
    let scaled = (a * 1000000000.0 + 0.5) as i64;
    format!("{}{}.{:09}", sign, scaled / 1000000000, scaled % 1000000000)
}

fn main() {
    let n: i64 = env::args().nth(1).and_then(|s| s.parse().ok()).unwrap_or(1000);
    let mut bodies = [
        body(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0),
        body(4.84143144246472090e+00, -1.16032004402742839e+00, -1.03622044471123109e-01,
             1.66007664274403694e-03, 7.69901118419740425e-03, -6.90460016972063023e-05, 9.54791938424326609e-04),
        body(8.34336671824457987e+00, 4.12479856412430479e+00, -4.03523417114321381e-01,
             -2.76742510726862411e-03, 4.99852801234917238e-03, 2.30417297573763929e-05, 2.85885980666130812e-04),
        body(1.28943695621391310e+01, -1.51111514016986312e+01, -2.23307578892655734e-01,
             2.96460137564761618e-03, 2.37847173959480950e-03, -2.96589568540237556e-05, 4.36624404335156298e-05),
        body(1.53796971148509165e+01, -2.59193146099879641e+01, 1.79258772950371181e-01,
             2.68067772490389322e-03, 1.62824170038242295e-03, -9.51592254519715870e-05, 5.15138902046611451e-05),
    ];
    offset_momentum(&mut bodies);
    println!("{}", fixed9(energy(&bodies)));
    for _ in 0..n {
        advance(&mut bodies, 0.01);
    }
    println!("{}", fixed9(energy(&bodies)));
}
