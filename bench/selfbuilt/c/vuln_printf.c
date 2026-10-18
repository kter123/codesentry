/* EXPECT: vulnerable | CWE-134 用户输入作为格式串 */
#include <stdio.h>

void greet(char *name) {
    printf(name);
}
