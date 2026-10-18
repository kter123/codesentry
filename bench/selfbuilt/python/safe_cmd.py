# EXPECT: clean | 列表参数无 shell
import subprocess

def ping(host):
    return subprocess.run(["ping", "-c", "1", host], capture_output=True)
