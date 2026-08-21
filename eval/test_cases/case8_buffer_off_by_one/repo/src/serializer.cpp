#include "serializer.h"

void copy_bytes(char* dest, const char* src, int count) {
    for (int i = 0; i < count; ++i) {
        dest[i] = src[i];
    }
}
