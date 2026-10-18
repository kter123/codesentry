# EXPECT: vulnerable | CWE-78 命令注入
import subprocess

def ping(host):
    return subprocess.run(f"ping -c 1 {host}", shell=True, capture_output=True)
