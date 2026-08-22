#include "user_manager.h"
#include <string>

std::string get_formatted_username(int id) {
    return "User_" + std::to_string(id);
}
