package main

import (
	"fmt"
	"io"
	"net"
	"os"
	"strconv"
	"sync"
	"time"
)

func number(s string) int {
	n, err := strconv.Atoi(s)
	if err != nil || n < 1 {
		panic("positive argument")
	}
	return n
}
func main() {
	if len(os.Args) != 5 {
		panic("expected READY CLIENTS ROUNDS BYTES")
	}
	clients, rounds, size := number(os.Args[2]), number(os.Args[3]), number(os.Args[4])
	listener, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		panic(err)
	}
	port := listener.Addr().(*net.TCPAddr).Port
	if err := os.WriteFile(os.Args[1], []byte(fmt.Sprintf("%d\n", port)), 0600); err != nil {
		panic(err)
	}
	connections := make([]net.Conn, clients)
	for i := range connections {
		connections[i], err = listener.Accept()
		if err != nil {
			panic(err)
		}
		// Match the other servers' default Nagle setting; only clients set NODELAY.
		if err := connections[i].(*net.TCPConn).SetNoDelay(false); err != nil {
			panic(err)
		}
	}
	if err := listener.Close(); err != nil {
		panic(err)
	}
	var workers sync.WaitGroup
	for _, connection := range connections {
		workers.Add(1)
		go func(c net.Conn) {
			defer workers.Done()
			data := make([]byte, size)
			for i := 0; i < rounds; i++ {
				if err := c.SetDeadline(time.Now().Add(30 * time.Second)); err != nil {
					panic(err)
				}
				if _, err := io.ReadFull(c, data); err != nil {
					panic(err)
				}
				for at := 0; at < size; {
					n, err := c.Write(data[at:])
					if err != nil || n == 0 {
						panic("write failed")
					}
					at += n
				}
			}
			if err := c.Close(); err != nil {
				panic(err)
			}
		}(connection)
	}
	workers.Wait()
	fmt.Println(int64(clients) * int64(rounds) * int64(size))
}
