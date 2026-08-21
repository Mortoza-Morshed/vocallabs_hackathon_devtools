#include "network.h"

int get_connection_timeout_ms(int multiplier = 5) {
    return multiplier * 1000;
}
