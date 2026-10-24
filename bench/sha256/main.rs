// SHA-256, FIPS 180-4. Same schedule and round loop as Vela and C.
const K:[u32;64]=[0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2];
fn rotr(x:u32,n:u32)->u32 { (x>>n)|(x<<(32-n)) }
fn digest(data:&[u8])->[u32;8] {
    let mut state:[u32;8]=[0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
    let mut words=[0u32;64];
    let padded=((data.len()+9+63)/64)*64;
    let bit_length=(data.len() as u64)<<3;
    for block in 0..padded/64 {
        for i in 0..64 {
            if i<16 {
                let mut word=0u32;
                for j in 0..4 {
                    let at=block*64+i*4+j;
                    let b=if at<data.len(){data[at] as u32}else if at==data.len(){128}else if at>=padded-8{((bit_length>>((padded-1-at)*8))&255)as u32}else{0};
                    word=(word<<8)|b;
                }
                words[i]=word;
            }else{
                let x=words[i-15];let y=words[i-2];
                let s0=rotr(x,7)^rotr(x,18)^(x>>3);
                let s1=rotr(y,17)^rotr(y,19)^(y>>10);
                words[i]=words[i-16].wrapping_add(s0).wrapping_add(words[i-7]).wrapping_add(s1);
            }
        }
        let [mut a,mut b,mut c,mut d,mut e,mut f,mut g,mut h]=state;
        for i in 0..64 {
            let s1=rotr(e,6)^rotr(e,11)^rotr(e,25);
            let choice=(e&f)^(!e&g);
            let t1=h.wrapping_add(s1).wrapping_add(choice).wrapping_add(K[i]).wrapping_add(words[i]);
            let s0=rotr(a,2)^rotr(a,13)^rotr(a,22);
            let majority=(a&b)^(a&c)^(b&c);
            let t2=s0.wrapping_add(majority);
            h=g;g=f;f=e;e=d.wrapping_add(t1);d=c;c=b;b=a;a=t1.wrapping_add(t2);
        }
        for (i,v) in [a,b,c,d,e,f,g,h].iter().enumerate(){state[i]=state[i].wrapping_add(*v);}
    }
    state
}
fn main(){
    let args:Vec<String>=std::env::args().collect();
    let n:usize=args.get(1).map(|x|x.parse().unwrap()).unwrap_or(1048576);
    let rounds:usize=args.get(2).map(|x|x.parse().unwrap()).unwrap_or(32);
    let data=vec![b'a';n];let mut result=String::new();
    for _ in 0..rounds{let mut input=result.into_bytes();input.extend_from_slice(&data);result=digest(&input).iter().map(|x|format!("{:08x}",x)).collect();}
    println!("{}",result);
}
