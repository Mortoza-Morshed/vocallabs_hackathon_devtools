#include "validator.h"
#include <stdexcept>

void dispatch_event(int size) {
    try {
        validate_payload(size);
    } catch (const std::invalid_argument& e) {
        // Handles invalid input gracefully
        return;
    }
}
