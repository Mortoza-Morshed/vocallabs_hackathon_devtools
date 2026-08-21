#include <iostream>

double compute_rate(double amount, double discount_factor) {
    if (discount_factor <= 0) return -1.0;
    return amount * discount_factor;
}

double apply_invoice_discount(double total) {
    double rate = compute_rate(total, 0.0); // Expects positive return value
    return total - rate;
}
