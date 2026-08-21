#include "clock.h"
#include <cstdint>

uint64_t calculate_elapsed(uint64_t start_time) {
    uint64_t now = get_timestamp_us();
    return now - start_time;
}
