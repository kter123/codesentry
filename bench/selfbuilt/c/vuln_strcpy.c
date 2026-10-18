/* EXPECT: vulnerable | CWE-120 无界 strcpy */
#include <string.h>

void copy(char *src) {
    char buf[64];
    strcpy(buf, src);
}
