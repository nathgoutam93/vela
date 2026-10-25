use std::env;
use std::ffi::{c_int, c_uint, c_ulong};
use std::fs;

#[link(name = "z")]
unsafe extern "C" {
    fn compressBound(source_len: c_ulong) -> c_ulong;
    fn compress2(dest: *mut u8, dest_len: *mut c_ulong, source: *const u8,
                 source_len: c_ulong, level: c_int) -> c_int;
    fn uncompress(dest: *mut u8, dest_len: *mut c_ulong, source: *const u8,
                  source_len: c_ulong) -> c_int;
    fn adler32(adler: c_ulong, buf: *const u8, len: c_uint) -> c_ulong;
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = env::args().skip(1);
    let path = args.next().ok_or("expected input path")?;
    let rounds: usize = args.next().ok_or("expected rounds")?.parse()?;
    if args.next().is_some() || rounds == 0 {
        return Err("expected path and positive rounds".into());
    }
    let data = fs::read(path)?;
    if data.len() > u32::MAX as usize {
        return Err("input exceeds the benchmark's zlib limit".into());
    }
    for _ in 0..rounds {
        // Use the same system zlib, level, allocation lifetime and full
        // decompression check as the C and Vela references.
        let mut packed = vec![0u8; unsafe { compressBound(data.len() as c_ulong) } as usize];
        let mut packed_len = packed.len() as c_ulong;
        let rc = unsafe {
            compress2(packed.as_mut_ptr(), &mut packed_len, data.as_ptr(),
                      data.len() as c_ulong, 6)
        };
        if rc != 0 { return Err(format!("compress2 returned {rc}").into()); }
        let mut restored = vec![0u8; data.len()];
        let mut restored_len = restored.len() as c_ulong;
        let rc = unsafe {
            uncompress(restored.as_mut_ptr(), &mut restored_len, packed.as_ptr(), packed_len)
        };
        if rc != 0 || restored_len as usize != data.len() || restored != data {
            return Err("zlib round trip mismatch".into());
        }
        let packed_adler = unsafe { adler32(1, packed.as_ptr(), packed_len as c_uint) };
        let restored_adler = unsafe { adler32(1, restored.as_ptr(), restored_len as c_uint) };
        println!("{packed_len}\n{packed_adler}\n{restored_adler}");
    }
    Ok(())
}
