#include "network.h"

void connect_socket() {
    int timeout = get_connection_timeout_ms();
    // Caller expects 5000ms default; 0ms causes immediate failure
    if (timeout <= 0) {
        throw "Connection failed immediately";
    }
}
