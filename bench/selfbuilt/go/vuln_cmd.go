// EXPECT: vulnerable | CWE-78 用户输入直接进 exec.Command
package main

import (
	"os/exec"
)

func Run(input string) *exec.Cmd {
	return exec.Command("sh", "-c", input)
}
