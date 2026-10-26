use std::{env, fs, io::{Read, Write}, net::TcpListener, thread, time::Duration};
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = env::args().collect(); assert_eq!(args.len(), 5);
    let clients: usize = args[2].parse()?; let rounds: usize = args[3].parse()?; let size: usize = args[4].parse()?;
    assert!(clients > 0 && rounds > 0 && size > 0);
    let listener = TcpListener::bind("127.0.0.1:0")?;
    fs::write(&args[1], format!("{}\n", listener.local_addr()?.port()))?;
    let mut sockets = Vec::new();
    for _ in 0..clients {
        let (s, _) = listener.accept()?;
        s.set_read_timeout(Some(Duration::from_secs(30)))?; s.set_write_timeout(Some(Duration::from_secs(30)))?;
        sockets.push(s);
    }
    drop(listener);
    let workers: Vec<_> = sockets.into_iter().map(|mut s| thread::spawn(move || {
        let mut data = vec![0u8; size];
        for _ in 0..rounds { s.read_exact(&mut data).unwrap(); s.write_all(&data).unwrap(); }
    })).collect();
    for worker in workers { worker.join().unwrap(); }
    println!("{}", clients * rounds * size); Ok(())
}
