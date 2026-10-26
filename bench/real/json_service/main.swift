// Full standalone parser matching the C/Rust/Vela corpus: last duplicate wins.
import Foundation
indirect enum Value {
    case null, bool, real, string
    case integer(Int64), array([Value]), object([([UInt8], Value)])
}
struct Reader {
    let data: [UInt8]
    var at = 0
    func peek() -> UInt8? { at < data.count ? data[at] : nil }
    mutating func space() { while let b = peek(), b == 32 || b == 9 || b == 10 || b == 13 { at += 1 } }
    mutating func take(_ b: UInt8) -> Bool {
        if peek() == b { at += 1; return true }; return false
    }
    mutating func hex4() -> UInt32? {
        var value: UInt32 = 0
        for _ in 0..<4 {
            guard let b = peek() else { return nil }
            let digit: UInt32
            switch b {
            case 48...57: digit = UInt32(b - 48)
            case 65...70: digit = UInt32(b - 65 + 10)
            case 97...102: digit = UInt32(b - 97 + 10)
            default: return nil
            }
            value = value * 16 + digit; at += 1
        }
        return value
    }
    mutating func string() -> [UInt8]? {
        guard take(34) else { return nil }
        var output: [UInt8] = []
        while let b = peek() {
            at += 1
            switch b {
            case 34: return output
            case 0...31: return nil
            case 92:
                guard let escaped = peek() else { return nil }; at += 1
                switch escaped {
                case 34, 92, 47: output.append(escaped)
                case 98: output.append(8)
                case 102: output.append(12)
                case 110: output.append(10)
                case 114: output.append(13)
                case 116: output.append(9)
                case 117:
                    guard var cp = hex4() else { return nil }
                    if cp >= 0xd800 && cp < 0xdc00 && at + 2 <= data.count && data[at] == 92 && data[at + 1] == 117 {
                        let back = at; at += 2
                        guard let low = hex4() else { return nil }
                        if low >= 0xdc00 && low < 0xe000 { cp = 0x10000 + (cp - 0xd800) * 1024 + low - 0xdc00 }
                        else { at = back }
                    }
                    if cp >= 0xd800 && cp < 0xe000 { cp = 0xfffd }
                    guard let scalar = Unicode.Scalar(cp) else { return nil }
                    output.append(contentsOf: String(scalar).utf8)
                default: return nil
                }
            default: output.append(b)
            }
        }
        return nil
    }
    mutating func digits() -> Bool {
        let start = at
        while let b = peek(), b >= 48 && b <= 57 { at += 1 }
        return at > start
    }
    mutating func literal(_ text: [UInt8], _ value: Value) -> Value? {
        guard at + text.count <= data.count, data[at..<(at + text.count)].elementsEqual(text) else { return nil }
        at += text.count; return value
    }
    mutating func value(_ depth: Int) -> Value? {
        guard depth <= 500, let b = peek() else { return nil }
        switch b {
        case 34: guard string() != nil else { return nil }; return .string
        case 91:
            at += 1; space(); var items: [Value] = []
            if take(93) { return .array(items) }
            while true {
                space(); guard let v = value(depth + 1) else { return nil }; items.append(v); space()
                if take(93) { return .array(items) }; guard take(44) else { return nil }
            }
        case 123:
            at += 1; space(); var items: [([UInt8], Value)] = []
            if take(125) { return .object(items) }
            while true {
                space(); guard let key = string() else { return nil }; space(); guard take(58) else { return nil }; space()
                guard let v = value(depth + 1) else { return nil }; items.append((key, v)); space()
                if take(125) { return .object(items) }; guard take(44) else { return nil }
            }
        case 45, 48...57:
            let start = at; _ = take(45)
            if !take(48) && !digits() { return nil }
            var whole = true
            if take(46) { whole = false; guard digits() else { return nil } }
            if take(101) || take(69) {
                whole = false; if !take(43) { _ = take(45) }; guard digits() else { return nil }
            }
            if whole, let n = Int64(String(decoding: data[start..<at], as: UTF8.self)) { return .integer(n) }
            return .real
        case 116: return literal([116, 114, 117, 101], .bool)
        case 102: return literal([102, 97, 108, 115, 101], .bool)
        case 110: return literal([110, 117, 108, 108], .null)
        default: return nil
        }
    }
}
func get(_ fields: [([UInt8], Value)], _ key: [UInt8]) -> Value? {
    for (name, value) in fields.reversed() { if name == key { return value } }; return nil
}
func respond(_ line: [UInt8]) -> String {
    let failure = "{\"error\":\"request\"}"
    var reader = Reader(data: line); reader.space()
    let document = reader.value(0); reader.space()
    guard reader.at == line.count, case let .object(fields) = document,
          case let .integer(id) = get(fields, [105, 100]),
          case let .integer(threshold) = get(fields, [116, 104, 114, 101, 115, 104, 111, 108, 100]),
          case let .array(values) = get(fields, [118, 97, 108, 117, 101, 115]) else { return failure }
    var count = 0
    var sum: Int64 = 0
    var maximum: Int64? = nil
    for value in values {
        guard case let .integer(n) = value else { return failure }
        if n >= threshold {
            let (next, overflow) = sum.addingReportingOverflow(n)
            if overflow { return failure }; sum = next
            maximum = maximum.map { max($0, n) } ?? n; count += 1
        }
    }
    let maxText = maximum.map(String.init) ?? "null"
    return "{\"id\":\(id),\"count\":\(count),\"sum\":\(sum),\"max\":\(maxText)}"
}
guard CommandLine.arguments.count == 3,
      let rounds = Int(CommandLine.arguments[2]), rounds > 0 else { fatalError("expected FILE ROUNDS") }
let data = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))
var lines = data.split(separator: 10, omittingEmptySubsequences: false)
if lines.last?.isEmpty == true { lines.removeLast() }
let requests = lines.map { Array($0.last == 13 ? $0.dropLast() : $0[...]) }
var output = Data()
for _ in 0..<rounds {
    for line in requests {
        output.append(contentsOf: (respond(line) + "\n").utf8)
        if output.count >= 65536 { try FileHandle.standardOutput.write(contentsOf: output); output.removeAll(keepingCapacity: true) }
    }
}
try FileHandle.standardOutput.write(contentsOf: output)
