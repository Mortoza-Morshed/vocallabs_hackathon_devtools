#include "parser.h"

int parse_header_length(const char* buffer) {
    if (!buffer) {
        return -1;
    }
    return (int)buffer[0];
}
