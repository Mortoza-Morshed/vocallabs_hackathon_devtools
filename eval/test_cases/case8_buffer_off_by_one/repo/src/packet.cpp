#include "serializer.h"

void serialize_packet(const char* payload, int len) {
    char buffer[64];
    copy_bytes(buffer, payload, len);
}
