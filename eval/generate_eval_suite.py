"""
eval/generate_eval_suite.py

Generates 10 realistic C++ benchmark test cases for Blast Radius evaluation harness.
"""

import os
import json

TEST_CASES = {
    "case1_default_param_change": {
        "repo_files": {
            "src/network.cpp": """#include "network.h"

int get_connection_timeout_ms(int multiplier = 5) {
    return multiplier * 1000;
}
""",
            "src/client.cpp": """#include "network.h"

void connect_socket() {
    int timeout = get_connection_timeout_ms();
    // Caller expects 5000ms default; 0ms causes immediate failure
    if (timeout <= 0) {
        throw "Connection failed immediately";
    }
}
"""
        },
        "diff": """--- a/src/network.cpp
+++ b/src/network.cpp
@@ -3,3 +3,3 @@
-int get_connection_timeout_ms(int multiplier = 5) {
+int get_connection_timeout_ms(int multiplier = 0) {
     return multiplier * 1000;
 }
""",
        "ground_truth": {
            "case_id": "case1_default_param_change",
            "has_contract_break": True,
            "expected_affected_functions": ["connect_socket", "get_connection_timeout_ms"],
            "minimum_severity": "medium",
            "notes": "Default timeout changed from 5000ms to 0ms breaking caller assumption"
        }
    },
    "case2_return_by_ref_lifetime": {
        "repo_files": {
            "src/user_manager.cpp": """#include "user_manager.h"
#include <string>

std::string get_formatted_username(int id) {
    return "User_" + std::to_string(id);
}
""",
            "src/service.cpp": """#include "user_manager.h"
#include <iostream>

void process_user(int id) {
    const std::string& name = get_formatted_username(id);
    std::cout << "Processing: " << name << std::endl;
}
"""
        },
        "diff": """--- a/src/user_manager.cpp
+++ b/src/user_manager.cpp
@@ -4,3 +4,4 @@
-std::string get_formatted_username(int id) {
-    return "User_" + std::to_string(id);
+const std::string& get_formatted_username(int id) {
+    std::string temp = "User_" + std::to_string(id);
+    return temp;
 }
""",
        "ground_truth": {
            "case_id": "case2_return_by_ref_lifetime",
            "has_contract_break": True,
            "expected_affected_functions": ["process_user", "get_formatted_username"],
            "minimum_severity": "high",
            "notes": "Returning reference to local stack temporary creates dangling reference in caller"
        }
    },
    "case3_removed_null_check": {
        "repo_files": {
            "src/parser.cpp": """#include "parser.h"

int parse_header_length(const char* buffer) {
    if (!buffer) {
        return -1;
    }
    return (int)buffer[0];
}
""",
            "src/handler.cpp": """#include "parser.h"

void handle_request(const char* data) {
    // Caller may pass nullptr on empty request
    int len = parse_header_length(data);
    if (len < 0) return;
}
"""
        },
        "diff": """--- a/src/parser.cpp
+++ b/src/parser.cpp
@@ -3,4 +3,2 @@
 int parse_header_length(const char* buffer) {
-    if (!buffer) {
-        return -1;
-    }
     return (int)buffer[0];
 }
""",
        "ground_truth": {
            "case_id": "case3_removed_null_check",
            "has_contract_break": True,
            "expected_affected_functions": ["handle_request", "parse_header_length"],
            "minimum_severity": "high",
            "notes": "Removed nullptr guard causing segmentation fault when caller passes null"
        }
    },
    "case4_changed_exception_type": {
        "repo_files": {
            "src/validator.cpp": """#include "validator.h"
#include <stdexcept>

void validate_payload(int size) {
    if (size <= 0) {
        throw std::invalid_argument("Size must be positive");
    }
}
""",
            "src/event_loop.cpp": """#include "validator.h"
#include <stdexcept>

void dispatch_event(int size) {
    try {
        validate_payload(size);
    } catch (const std::invalid_argument& e) {
        // Handles invalid input gracefully
        return;
    }
}
"""
        },
        "diff": """--- a/src/validator.cpp
+++ b/src/validator.cpp
@@ -5,3 +5,3 @@
     if (size <= 0) {
-        throw std::invalid_argument("Size must be positive");
+        throw std::runtime_error("Size must be positive");
     }
 }
""",
        "ground_truth": {
            "case_id": "case4_changed_exception_type",
            "has_contract_break": True,
            "expected_affected_functions": ["dispatch_event", "validate_payload"],
            "minimum_severity": "medium",
            "notes": "Exception type changed from std::invalid_argument to std::runtime_error escaping catch block"
        }
    },
    "case5_mutating_argument": {
        "repo_files": {
            "src/transform.cpp": """#include "transform.h"
#include <vector>

void process_buffer(std::vector<int>& items) {
    // Read-only processing previously
    for (int x : items) {
        // inspect
    }
}
""",
            "src/pipeline.cpp": """#include "transform.h"
#include <vector>

void pipeline_stage() {
    std::vector<int> cached = {1, 2, 3};
    process_buffer(cached);
    // Caller assumes cached remains intact
    int first = cached[0];
}
"""
        },
        "diff": """--- a/src/transform.cpp
+++ b/src/transform.cpp
@@ -4,3 +4,4 @@
 void process_buffer(std::vector<int>& items) {
-    for (int x : items) {
+    for (size_t i = 0; i < items.size(); ++i) {
+        items[i] = 0; // Mutates buffer unexpectedly
     }
 }
""",
        "ground_truth": {
            "case_id": "case5_mutating_argument",
            "has_contract_break": True,
            "expected_affected_functions": ["pipeline_stage", "process_buffer"],
            "minimum_severity": "high",
            "notes": "Function now mutates input vector in-place violating caller immutability expectations"
        }
    },
    "case6_safe_internal_refactor": {
        "repo_files": {
            "src/math_ops.cpp": """#include "math_ops.h"

int compute_square_sum(int a, int b) {
    int val1 = a * a;
    int val2 = b * b;
    return val1 + val2;
}
""",
            "src/render.cpp": """#include "math_ops.h"

int render_frame(int x, int y) {
    return compute_square_sum(x, y);
}
"""
        },
        "diff": """--- a/src/math_ops.cpp
+++ b/src/math_ops.cpp
@@ -3,4 +3,2 @@
 int compute_square_sum(int a, int b) {
-    int val1 = a * a;
-    int val2 = b * b;
-    return val1 + val2;
+    return (a * a) + (b * b);
 }
""",
        "ground_truth": {
            "case_id": "case6_safe_internal_refactor",
            "has_contract_break": False,
            "expected_affected_functions": [],
            "minimum_severity": "low",
            "notes": "Safe refactor simplifying math expression without semantic changes"
        }
    },
    "case7_thread_safety_static_state": {
        "repo_files": {
            "src/counter.cpp": """#include "counter.h"

int get_next_request_id(int base) {
    return base + 1;
}
""",
            "src/worker.cpp": """#include "counter.h"

void worker_task(int thread_id) {
    // Multi-threaded worker calling counter concurrently
    int id = get_next_request_id(thread_id * 100);
}
"""
        },
        "diff": """--- a/src/counter.cpp
+++ b/src/counter.cpp
@@ -3,3 +3,4 @@
 int get_next_request_id(int base) {
-    return base + 1;
+    static int counter = 0;
+    return ++counter;
 }
""",
        "ground_truth": {
            "case_id": "case7_thread_safety_static_state",
            "has_contract_break": True,
            "expected_affected_functions": ["worker_task", "get_next_request_id"],
            "minimum_severity": "high",
            "notes": "Replaced stateless function with unsynchronized static state causing data races"
        }
    },
    "case8_buffer_off_by_one": {
        "repo_files": {
            "src/serializer.cpp": """#include "serializer.h"

void copy_bytes(char* dest, const char* src, int count) {
    for (int i = 0; i < count; ++i) {
        dest[i] = src[i];
    }
}
""",
            "src/packet.cpp": """#include "serializer.h"

void serialize_packet(const char* payload, int len) {
    char buffer[64];
    copy_bytes(buffer, payload, len);
}
"""
        },
        "diff": """--- a/src/serializer.cpp
+++ b/src/serializer.cpp
@@ -3,3 +3,3 @@
 void copy_bytes(char* dest, const char* src, int count) {
-    for (int i = 0; i < count; ++i) {
+    for (int i = 0; i <= count; ++i) {
         dest[i] = src[i];
 }
""",
        "ground_truth": {
            "case_id": "case8_buffer_off_by_one",
            "has_contract_break": True,
            "expected_affected_functions": ["serialize_packet", "copy_bytes"],
            "minimum_severity": "high",
            "notes": "Off-by-one boundary error in copy loop writes past allocated caller buffer"
        }
    },
    "case9_safe_doc_and_comment": {
        "repo_files": {
            "src/logger.cpp": """#include "logger.h"
#include <iostream>

void log_status(const char* msg) {
    std::cout << "[STATUS] " << msg << std::endl;
}
""",
            "src/app.cpp": """#include "logger.h"

void run_app() {
    log_status("Application initialized.");
}
"""
        },
        "diff": """--- a/src/logger.cpp
+++ b/src/logger.cpp
@@ -3,3 +3,4 @@
+// Logs status messages to standard stdout
 void log_status(const char* msg) {
-    std::cout << "[STATUS] " << msg << std::endl;
+    std::cout << "[STATUS] " << msg << std::endl; // preserved behavior
 }
""",
        "ground_truth": {
            "case_id": "case9_safe_doc_and_comment",
            "has_contract_break": False,
            "expected_affected_functions": [],
            "minimum_severity": "low",
            "notes": "Safe comment and documentation addition"
        }
    },
    "case10_integer_truncation": {
        "repo_files": {
            "src/clock.cpp": """#include "clock.h"
#include <cstdint>

uint64_t get_timestamp_us() {
    return 1700000000000000ULL;
}
""",
            "src/metrics.cpp": """#include "clock.h"
#include <cstdint>

uint64_t calculate_elapsed(uint64_t start_time) {
    uint64_t now = get_timestamp_us();
    return now - start_time;
}
"""
        },
        "diff": """--- a/src/clock.cpp
+++ b/src/clock.cpp
@@ -3,3 +3,3 @@
-uint64_t get_timestamp_us() {
+uint32_t get_timestamp_us() {
     return 1700000000000000ULL;
 }
""",
        "ground_truth": {
            "case_id": "case10_integer_truncation",
            "has_contract_break": True,
            "expected_affected_functions": ["calculate_elapsed", "get_timestamp_us"],
            "minimum_severity": "high",
            "notes": "Return type truncated from 64-bit to 32-bit integer causing timestamp wrap-around"
        }
    }
}

def generate():
    base_dir = os.path.join(os.path.dirname(__file__), "test_cases")
    os.makedirs(base_dir, exist_ok=True)
    
    for case_id, data in TEST_CASES.items():
        case_dir = os.path.join(base_dir, case_id)
        repo_dir = os.path.join(case_dir, "repo")
        os.makedirs(repo_dir, exist_ok=True)
        
        # Write repo files
        for rel_path, content in data["repo_files"].items():
            full_path = os.path.join(repo_dir, rel_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
                
        # Write diff
        diff_path = os.path.join(case_dir, "pr.diff")
        with open(diff_path, "w", encoding="utf-8") as f:
            f.write(data["diff"])
            
        # Write ground truth
        gt_path = os.path.join(case_dir, "ground_truth.json")
        with open(gt_path, "w", encoding="utf-8") as f:
            json.dump(data["ground_truth"], f, indent=2)
            
    print(f"[+] Successfully generated {len(TEST_CASES)} evaluation benchmark test cases!")

if __name__ == "__main__":
    generate()
