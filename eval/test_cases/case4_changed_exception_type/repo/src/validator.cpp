#include "validator.h"
#include <stdexcept>

void validate_payload(int size) {
    if (size <= 0) {
        throw std::invalid_argument("Size must be positive");
    }
}
