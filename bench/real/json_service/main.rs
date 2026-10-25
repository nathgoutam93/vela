use std::env;
use std::fs;
use std::io::{self, Write};

// A standalone JSON-lines service. Keep a full parser: the workload includes
// nested unused fields, escaped keys, duplicate keys, and malformed requests.
enum Value {
    Null,
    Bool,
    Integer(i64),
    Real,
    String,
    Array(Vec<Value>),
    Object(Vec<(Vec<u8>, Value)>),
}

struct Reader<'a> {
    data: &'a [u8],
    at: usize,
}

impl Reader<'_> {
    fn peek(&self) -> Option<u8> { self.data.get(self.at).copied() }
    fn space(&mut self) {
        while matches!(self.peek(), Some(b' ' | b'\t' | b'\r' | b'\n')) { self.at += 1; }
    }
    fn take(&mut self, byte: u8) -> bool {
        if self.peek() == Some(byte) { self.at += 1; true } else { false }
    }
    fn hex4(&mut self) -> Option<u32> {
        let mut value = 0;
        for _ in 0..4 {
            let digit = (self.peek()? as char).to_digit(16)?;
            value = value * 16 + digit;
            self.at += 1;
        }
        Some(value)
    }
    fn string(&mut self) -> Option<Vec<u8>> {
        if !self.take(b'"') { return None; }
        let mut out = Vec::new();
        loop {
            let byte = self.peek()?;
            self.at += 1;
            match byte {
                b'"' => return Some(out),
                0..=31 => return None,
                b'\\' => {
                    let escaped = self.peek()?;
                    self.at += 1;
                    match escaped {
                        b'"' | b'\\' | b'/' => out.push(escaped),
                        b'b' => out.push(8),
                        b'f' => out.push(12),
                        b'n' => out.push(b'\n'),
                        b'r' => out.push(b'\r'),
                        b't' => out.push(b'\t'),
                        b'u' => {
                            let mut cp = self.hex4()?;
                            if (0xd800..0xdc00).contains(&cp)
                                && self.data.get(self.at..self.at + 2) == Some(b"\\u") {
                                let back = self.at;
                                self.at += 2;
                                let low = self.hex4()?;
                                if (0xdc00..0xe000).contains(&low) {
                                    cp = 0x10000 + (cp - 0xd800) * 1024 + low - 0xdc00;
                                } else { self.at = back; }
                            }
                            if (0xd800..0xe000).contains(&cp) { cp = 0xfffd; }
                            let mut encoded = [0; 4];
                            out.extend_from_slice(char::from_u32(cp)?.encode_utf8(&mut encoded).as_bytes());
                        }
                        _ => return None,
                    }
                }
                _ => out.push(byte),
            }
        }
    }
    fn digits(&mut self) -> bool {
        let start = self.at;
        while matches!(self.peek(), Some(b'0'..=b'9')) { self.at += 1; }
        self.at != start
    }
    fn value(&mut self, depth: usize) -> Option<Value> {
        if depth > 500 { return None; }
        match self.peek()? {
            b'"' => { self.string()?; Some(Value::String) }
            b'[' => {
                self.at += 1;
                self.space();
                let mut items = Vec::new();
                if self.take(b']') { return Some(Value::Array(items)); }
                loop {
                    self.space();
                    items.push(self.value(depth + 1)?);
                    self.space();
                    if self.take(b']') { return Some(Value::Array(items)); }
                    if !self.take(b',') { return None; }
                }
            }
            b'{' => {
                self.at += 1;
                self.space();
                let mut items = Vec::new();
                if self.take(b'}') { return Some(Value::Object(items)); }
                loop {
                    self.space();
                    let key = self.string()?;
                    self.space();
                    if !self.take(b':') { return None; }
                    self.space();
                    let value = self.value(depth + 1)?;
                    items.push((key, value));
                    self.space();
                    if self.take(b'}') { return Some(Value::Object(items)); }
                    if !self.take(b',') { return None; }
                }
            }
            b'-' | b'0'..=b'9' => {
                let start = self.at;
                self.take(b'-');
                if !self.take(b'0') && !self.digits() { return None; }
                let mut whole = true;
                if self.take(b'.') {
                    whole = false;
                    if !self.digits() { return None; }
                }
                if self.take(b'e') || self.take(b'E') {
                    whole = false;
                    if !self.take(b'+') { self.take(b'-'); }
                    if !self.digits() { return None; }
                }
                if whole {
                    let number = std::str::from_utf8(&self.data[start..self.at]).ok()?;
                    if let Ok(value) = number.parse::<i64>() { return Some(Value::Integer(value)); }
                }
                Some(Value::Real)
            }
            b't' if self.data.get(self.at..self.at + 4) == Some(b"true") => {
                self.at += 4; Some(Value::Bool)
            }
            b'f' if self.data.get(self.at..self.at + 5) == Some(b"false") => {
                self.at += 5; Some(Value::Bool)
            }
            b'n' if self.data.get(self.at..self.at + 4) == Some(b"null") => {
                self.at += 4; Some(Value::Null)
            }
            _ => None,
        }
    }
}

fn get<'a>(items: &'a [(Vec<u8>, Value)], name: &[u8]) -> Option<&'a Value> {
    items.iter().rev().find(|(key, _)| key == name).map(|(_, value)| value)
}

fn respond(line: &[u8], output: &mut impl Write) -> io::Result<()> {
    let mut reader = Reader { data: line, at: 0 };
    reader.space();
    let document = reader.value(0);
    reader.space();
    let result = (|| {
        if reader.at != line.len() { return None; }
        let Value::Object(fields) = document.as_ref()? else { return None; };
        let Value::Integer(id) = get(fields, b"id")? else { return None; };
        let Value::Integer(threshold) = get(fields, b"threshold")? else { return None; };
        let Value::Array(values) = get(fields, b"values")? else { return None; };
        let mut count = 0;
        let mut sum: i64 = 0;
        let mut maximum: Option<i64> = None;
        for value in values {
            let Value::Integer(value) = value else { return None; };
            if value >= threshold {
                sum = sum.checked_add(*value)?;
                maximum = Some(maximum.map_or(*value, |m| m.max(*value)));
                count += 1;
            }
        }
        Some((*id, count, sum, maximum))
    })();
    match result {
        Some((id, count, sum, Some(maximum))) =>
            writeln!(output, "{{\"id\":{id},\"count\":{count},\"sum\":{sum},\"max\":{maximum}}}"),
        Some((id, count, sum, None)) =>
            writeln!(output, "{{\"id\":{id},\"count\":{count},\"sum\":{sum},\"max\":null}}"),
        None => writeln!(output, "{{\"error\":\"request\"}}"),
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = env::args().skip(1);
    let path = args.next().ok_or("expected input path")?;
    let rounds: usize = args.next().ok_or("expected rounds")?.parse()?;
    if args.next().is_some() || rounds == 0 {
        return Err("expected path and positive rounds".into());
    }
    let input = fs::read(path)?;
    let mut output = io::BufWriter::with_capacity(65536, io::stdout().lock());
    for _ in 0..rounds {
        let mut rest = input.as_slice();
        while !rest.is_empty() {
            let end = rest.iter().position(|&byte| byte == b'\n').unwrap_or(rest.len());
            let mut line = &rest[..end];
            if line.last() == Some(&b'\r') { line = &line[..line.len() - 1]; }
            respond(line, &mut output)?;
            rest = if end < rest.len() { &rest[end + 1..] } else { &[] };
        }
    }
    Ok(())
}
