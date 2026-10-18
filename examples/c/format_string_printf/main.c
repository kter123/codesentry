#include <stdio.h>
#include <string.h>

void log_event(char *fmt) {
    // CVE 模式：CWE-134 Format String——用户输入直接作 printf 格式串
    printf(fmt); // sink：line 6
}

int main(int argc, char **argv) {
    if (argc > 1) {
        log_event(argv[1]);
    }
    return 0;
}
