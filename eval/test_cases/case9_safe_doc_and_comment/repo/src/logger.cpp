#include "logger.h"
#include <iostream>

void log_status(const char* msg) {
    std::cout << "[STATUS] " << msg << std::endl;
}
