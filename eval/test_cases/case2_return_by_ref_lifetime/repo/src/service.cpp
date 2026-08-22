#include "user_manager.h"
#include <iostream>

void process_user(int id) {
    const std::string& name = get_formatted_username(id);
    std::cout << "Processing: " << name << std::endl;
}
