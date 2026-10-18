package main

import (
	"net/http"
	"os/exec"
)

func handler(w http.ResponseWriter, r *http.Request) {
	// CVE 模式：CWE-78 OS Command Injection——用户输入直接 exec
	host := r.URL.Query().Get("host")
	cmd := exec.Command("ping", "-c", "1", host) // sink：line 11
	out, _ := cmd.Output()
	_, _ = w.Write(out)
}
