// Full dynamic JSON parsing, including unused nested fields. No third-party packages.
package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"strconv"
)

func integer(v any) (int64, bool) {
	n, ok := v.(json.Number)
	if !ok {
		return 0, false
	}
	i, err := n.Int64()
	return i, err == nil
}

func respond(line []byte) string {
	failure := "{\"error\":\"request\"}"
	d := json.NewDecoder(bytes.NewReader(line))
	d.UseNumber()
	var value any
	if d.Decode(&value) != nil {
		return failure
	}
	var extra any
	if d.Decode(&extra) != io.EOF {
		return failure
	}
	obj, ok := value.(map[string]any)
	if !ok {
		return failure
	}
	id, ok := integer(obj["id"])
	if !ok {
		return failure
	}
	threshold, ok := integer(obj["threshold"])
	if !ok {
		return failure
	}
	values, ok := obj["values"].([]any)
	if !ok {
		return failure
	}
	var count, sum, maximum int64
	for _, value := range values {
		n, ok := integer(value)
		if !ok {
			return failure
		}
		if n >= threshold {
			next := sum + n
			if (n > 0 && next < sum) || (n < 0 && next > sum) {
				return failure
			}
			sum = next
			if count == 0 || n > maximum {
				maximum = n
			}
			count++
		}
	}
	maxText := "null"
	if count > 0 {
		maxText = strconv.FormatInt(maximum, 10)
	}
	return fmt.Sprintf("{\"id\":%d,\"count\":%d,\"sum\":%d,\"max\":%s}", id, count, sum, maxText)
}

func main() {
	if len(os.Args) != 3 {
		panic("expected FILE ROUNDS")
	}
	rounds, err := strconv.Atoi(os.Args[2])
	if err != nil || rounds < 1 {
		panic("invalid rounds")
	}
	data, err := os.ReadFile(os.Args[1])
	if err != nil {
		panic(err)
	}
	lines := bytes.Split(data, []byte{'\n'})
	if len(lines[len(lines)-1]) == 0 {
		lines = lines[:len(lines)-1]
	}
	out := bufio.NewWriterSize(os.Stdout, 65536)
	for r := 0; r < rounds; r++ {
		for _, line := range lines {
			if _, err := fmt.Fprintln(out, respond(bytes.TrimSuffix(line, []byte{'\r'}))); err != nil {
				panic(err)
			}
		}
	}
	if err := out.Flush(); err != nil {
		panic(err)
	}
}
