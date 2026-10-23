// n-body in C: the same algorithm as main.vl, operation for operation.
#include <math.h>
#include <stdio.h>
#include <stdlib.h>

typedef struct { double x, y, z, vx, vy, vz, mass; } Body;

#define PI 3.141592653589793
#define SOLAR_MASS (4.0 * PI * PI)
#define DAYS_PER_YEAR 365.24

static Body body(double x, double y, double z, double vx, double vy, double vz, double mass) {
    Body b = {x, y, z, vx * DAYS_PER_YEAR, vy * DAYS_PER_YEAR, vz * DAYS_PER_YEAR, mass * SOLAR_MASS};
    return b;
}

static void offset_momentum(Body *bodies, int n) {
    double px = 0.0, py = 0.0, pz = 0.0;
    for (int i = 0; i < n; i++) {
        px += bodies[i].vx * bodies[i].mass;
        py += bodies[i].vy * bodies[i].mass;
        pz += bodies[i].vz * bodies[i].mass;
    }
    bodies[0].vx = 0.0 - px / SOLAR_MASS;
    bodies[0].vy = 0.0 - py / SOLAR_MASS;
    bodies[0].vz = 0.0 - pz / SOLAR_MASS;
}

static double energy(const Body *bodies, int n) {
    double e = 0.0;
    for (int i = 0; i < n; i++) {
        Body b = bodies[i];
        e = e + 0.5 * b.mass * (b.vx * b.vx + b.vy * b.vy + b.vz * b.vz);
        for (int j = i + 1; j < n; j++) {
            Body o = bodies[j];
            double dx = b.x - o.x, dy = b.y - o.y, dz = b.z - o.z;
            e = e - b.mass * o.mass / sqrt(dx * dx + dy * dy + dz * dz);
        }
    }
    return e;
}

static void advance(Body *bodies, int n, double dt) {
    for (int i = 0; i < n; i++) {
        for (int j = i + 1; j < n; j++) {
            double dx = bodies[i].x - bodies[j].x;
            double dy = bodies[i].y - bodies[j].y;
            double dz = bodies[i].z - bodies[j].z;
            double d2 = dx * dx + dy * dy + dz * dz;
            double mag = dt / (d2 * sqrt(d2));
            double mj = bodies[j].mass * mag;
            bodies[i].vx = bodies[i].vx - dx * mj;
            bodies[i].vy = bodies[i].vy - dy * mj;
            bodies[i].vz = bodies[i].vz - dz * mj;
            double mi = bodies[i].mass * mag;
            bodies[j].vx = bodies[j].vx + dx * mi;
            bodies[j].vy = bodies[j].vy + dy * mi;
            bodies[j].vz = bodies[j].vz + dz * mi;
        }
    }
    for (int i = 0; i < n; i++) {
        bodies[i].x = bodies[i].x + dt * bodies[i].vx;
        bodies[i].y = bodies[i].y + dt * bodies[i].vy;
        bodies[i].z = bodies[i].z + dt * bodies[i].vz;
    }
}

static void print_fixed9(double x) {
    double a = x;
    const char *sign = "";
    if (x < 0.0) {
        a = 0.0 - x;
        sign = "-";
    }
    long long scaled = (long long)(a * 1000000000.0 + 0.5);
    printf("%s%lld.%09lld\n", sign, scaled / 1000000000, scaled % 1000000000);
}

int main(int argc, char **argv) {
    long n = argc > 1 ? atol(argv[1]) : 1000;
    Body bodies[5] = {
        body(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0),
        body(4.84143144246472090e+00, -1.16032004402742839e+00, -1.03622044471123109e-01,
             1.66007664274403694e-03, 7.69901118419740425e-03, -6.90460016972063023e-05, 9.54791938424326609e-04),
        body(8.34336671824457987e+00, 4.12479856412430479e+00, -4.03523417114321381e-01,
             -2.76742510726862411e-03, 4.99852801234917238e-03, 2.30417297573763929e-05, 2.85885980666130812e-04),
        body(1.28943695621391310e+01, -1.51111514016986312e+01, -2.23307578892655734e-01,
             2.96460137564761618e-03, 2.37847173959480950e-03, -2.96589568540237556e-05, 4.36624404335156298e-05),
        body(1.53796971148509165e+01, -2.59193146099879641e+01, 1.79258772950371181e-01,
             2.68067772490389322e-03, 1.62824170038242295e-03, -9.51592254519715870e-05, 5.15138902046611451e-05),
    };
    offset_momentum(bodies, 5);
    print_fixed9(energy(bodies, 5));
    for (long i = 0; i < n; i++) advance(bodies, 5, 0.01);
    print_fixed9(energy(bodies, 5));
    return 0;
}
