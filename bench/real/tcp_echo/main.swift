import Foundation
import Dispatch
#if canImport(Darwin)
import Darwin
#else
import Glibc
#endif

func require(_ ok: Bool, _ message: String) { if !ok { fatalError(message) } }
require(CommandLine.arguments.count == 5, "expected READY CLIENTS ROUNDS BYTES")
let clients = Int(CommandLine.arguments[2])!, rounds = Int(CommandLine.arguments[3])!, size = Int(CommandLine.arguments[4])!
require(clients > 0 && rounds > 0 && size > 0, "positive arguments")
signal(SIGPIPE, SIG_IGN)
#if canImport(Darwin)
let listener = socket(AF_INET, SOCK_STREAM, 0)
#else
let listener = socket(AF_INET, Int32(SOCK_STREAM.rawValue), 0)
#endif
require(listener >= 0, "socket")
var address = sockaddr_in()
address.sin_family = sa_family_t(AF_INET)
address.sin_addr.s_addr = inet_addr("127.0.0.1")
let bound = withUnsafePointer(to: &address) { p in
    p.withMemoryRebound(to: sockaddr.self, capacity: 1) { bind(listener, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) }
}
require(bound == 0 && listen(listener, Int32(clients)) == 0, "bind/listen")
var length = socklen_t(MemoryLayout<sockaddr_in>.size)
let named = withUnsafeMutablePointer(to: &address) { p in
    p.withMemoryRebound(to: sockaddr.self, capacity: 1) { getsockname(listener, $0, &length) }
}
require(named == 0, "getsockname")
try Data("\(UInt16(bigEndian: address.sin_port))\n".utf8).write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
var sockets: [Int32] = []
for _ in 0..<clients {
    let fd = accept(listener, nil, nil); require(fd >= 0, "accept")
    var timeout = timeval(tv_sec: 30, tv_usec: 0)
    require(setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, socklen_t(MemoryLayout<timeval>.size)) == 0, "read timeout")
    require(setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, socklen_t(MemoryLayout<timeval>.size)) == 0, "write timeout")
    sockets.append(fd)
}
close(listener)
let connections = sockets
DispatchQueue.concurrentPerform(iterations: clients) { index in
    let fd = connections[index]
    var data = [UInt8](repeating: 0, count: size)
    data.withUnsafeMutableBytes { buffer in
        for _ in 0..<rounds {
            var at = 0
            while at < size {
                let n = recv(fd, buffer.baseAddress!.advanced(by: at), size - at, 0)
                if n < 0 && errno == EINTR { continue }; require(n > 0, "recv"); at += n
            }
            at = 0
            while at < size {
                let n = send(fd, buffer.baseAddress!.advanced(by: at), size - at, 0)
                if n < 0 && errno == EINTR { continue }; require(n > 0, "send"); at += n
            }
        }
    }
    require(close(fd) == 0, "close")
}
print(clients * rounds * size)
