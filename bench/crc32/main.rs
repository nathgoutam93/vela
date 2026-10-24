// Reflected CRC-32: the same table and streaming update as Vela and C.
fn main(){
    let args:Vec<String>=std::env::args().collect();
    let n:usize=args.get(1).map(|x|x.parse().unwrap()).unwrap_or(4194304);
    let rounds:usize=args.get(2).map(|x|x.parse().unwrap()).unwrap_or(32);
    let data=vec![b'a';n];let mut table=[0u32;256];
    for i in 0..table.len(){let mut c=i as u32;for _ in 0..8{c=if c&1!=0{(c>>1)^0xedb88320}else{c>>1};}table[i]=c;}
    let mut result=0u32;
    for _ in 0..rounds{let mut c=!result;for b in &data{c=(c>>8)^table[((c^u32::from(*b))&255)as usize];}result=!c;}
    println!("{}",result);
}
