/**
 * EVENT-HORIZON // C++20 CLI Demonstration
 * Author: Avenoir (@justavenoir)
 */

#include "event_horizon.hpp"
#include <iostream>
#include <iomanip>

void render_hex(const unsigned char* data, std::size_t len) {
    for (std::size_t i = 0; i < len; i += 16) {
        std::cout << "    0x" << std::hex << std::setw(4) << std::setfill('0') << i << "  ";
        for (std::size_t j = 0; j < 16; ++j) {
            if (i + j < len) {
                std::cout << std::hex << std::setw(2) << std::setfill('0')
                          << static_cast<int>(data[i + j]) << " ";
            } else {
                std::cout << "   ";
            }
        }
        std::cout << " |";
        for (std::size_t j = 0; j < 16 && (i + j) < len; ++j) {
            char c = static_cast<char>(data[i + j]);
            std::cout << ((c >= 32 && c <= 126) ? c : '.');
        }
        std::cout << "|\n" << std::dec;
    }
}

int main(int argc, char* argv[]) {
    std::cout << "\n  EVENT-HORIZON [C++20 KERNEL DEFENSE]\n";
    std::cout << "  Multi-Pass Volatile Memory Sanitization Demo\n";
    std::cout << "  --------------------------------------------------------\n";

    std::string secret = "CLASSIFIED_SESSION_KEY_0x9A4F:aes256gcm_secret_payload";
    std::size_t size = secret.size() + 16;

    try {
        std::cout << "  [+] Allocating " << size << " bytes in locked physical RAM...\n";
        event_horizon::SecureMemoryBuffer sec_buf(size);

        std::cout << "      • Page Lock: " << (sec_buf.is_locked() ? "LOCKED (No Swap)" : "Active") << "\n";

        sec_buf.write(secret.data(), secret.size());
        std::cout << "\n  [MEMORY STATE BEFORE SHREDDING]:\n";
        render_hex(static_cast<const unsigned char*>(sec_buf.data()), secret.size());

        std::cout << "\n  [+] Triggering EVENT-HORIZON multi-pass silicon obliteration...\n";
        sec_buf.obliterate(3);

        std::cout << "  [✓] Memory forensically sanitized and unlocked.\n\n";
    } catch (const std::exception& ex) {
        std::cerr << "  [!] Exception: " << ex.what() << "\n";
        return 1;
    }

    return 0;
}
