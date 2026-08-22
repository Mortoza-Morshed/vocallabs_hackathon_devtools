#include "counter.h"

void worker_task(int thread_id) {
    // Multi-threaded worker calling counter concurrently
    int id = get_next_request_id(thread_id * 100);
}
