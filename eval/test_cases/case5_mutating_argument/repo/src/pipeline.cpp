#include "transform.h"
#include <vector>

void pipeline_stage() {
    std::vector<int> cached = {1, 2, 3};
    process_buffer(cached);
    // Caller assumes cached remains intact
    int first = cached[0];
}
