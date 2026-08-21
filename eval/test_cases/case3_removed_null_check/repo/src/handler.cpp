#include "parser.h"

void handle_request(const char* data) {
    // Caller may pass nullptr on empty request
    int len = parse_header_length(data);
    if (len < 0) return;
}
