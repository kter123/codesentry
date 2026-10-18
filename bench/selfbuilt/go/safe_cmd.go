// EXPECT: clean | 固定参数白名单
package main

import (
	"os/exec"
)

func Run() *exec.Cmd {
	return exec.Command("ping", "-c", "1", "127.0.0.1")
}
