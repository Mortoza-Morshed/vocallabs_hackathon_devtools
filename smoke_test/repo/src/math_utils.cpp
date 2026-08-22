#include "math_utils.h"

double compute_velocity(double base, double multiplier) {
    if (multiplier <= 0.0) {
        return 0.0;
    }
    return base * multiplier;
}
