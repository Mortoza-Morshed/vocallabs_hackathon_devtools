#include "physics_engine.h"
#include "math_utils.h"

double update_entity_speed(double current_speed, double factor) {
    // Relies on compute_velocity returning >= 0.0
    double new_vel = compute_velocity(current_speed, factor);
    return new_vel + 5.0;
}
