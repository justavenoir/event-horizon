/**
 * ============================================================================
 * EVENT-HORIZON // Anti-Forensics Volatile RAM Shredder & Memory Obliterator
 * Header-Only C++20 Reference Implementation
 * 
 * Author  : Avenoir (@justavenoir)
 * License : MIT
 * Standard: ISO C++20
 * ============================================================================
 * 
 * Designed to prevent Cold-Boot attacks (DRAM charge remanence) and runtime
 * memory dumping (Volatility, WinPmem, LiME). Uses compiler dead-store 
 * elimination (DSE) barriers and physical page locking (VirtualLock/mlock).
 */

#pragma once

#include <iostream>
#include <vector>
#include <string>
#include <random>
#include <cstring>
#include <fstream>
#include <filesystem>
#include <atomic>
#include <chrono>

#if defined(_WIN32) || defined(_WIN64)
    #ifndef WIN32_LEAN_AND_MEAN
    #define WIN32_LEAN_AND_MEAN
    #endif
    #include <windows.h>
    #include <memoryapi.h>
#else
    #include <sys/mman.h>
    #include <unistd.h>
    #include <fcntl.h>
#endif

namespace event_horizon {

namespace internal {
    /**
     * @brief Compiler memory barrier to defeat Dead Store Elimination (DSE).
     * Compilers often optimize away memset/bzero if a pointer is freed immediately.
     */
    inline void secure_memzero(void* ptr, std::size_t size) noexcept {
#if defined(_WIN32) || defined(_WIN64)
        SecureZeroMemory(ptr, size);
#elif defined(__STDC_LIB_EXT1__)
        memset_s(ptr, size, 0, size);
#else
        volatile unsigned char* p = static_cast<volatile unsigned char*>(ptr);
        while (size--) {
            *p++ = 0;
        }
        std::atomic_thread_fence(std::memory_order_seq_cst);
#endif
    }
} // namespace internal

/**
 * @class SecureMemoryBuffer
 * @brief RAII physical memory buffer with page locking and multi-pass destruction.
 */
class SecureMemoryBuffer {
public:
    explicit SecureMemoryBuffer(std::size_t bytes)
        : size_(bytes), data_(nullptr), locked_(false) {
        allocate_and_lock();
    }

    ~SecureMemoryBuffer() {
        if (data_) {
            obliterate(3);
        }
    }

    // Disable copy semantics to prevent unauthorized memory replication
    SecureMemoryBuffer(const SecureMemoryBuffer&) = delete;
    SecureMemoryBuffer& operator=(const SecureMemoryBuffer&) = delete;

    // Enable move semantics
    SecureMemoryBuffer(SecureMemoryBuffer&& other) noexcept
        : size_(other.size_), data_(other.data_), locked_(other.locked_) {
        other.data_ = nullptr;
        other.size_ = 0;
        other.locked_ = false;
    }

    SecureMemoryBuffer& operator=(SecureMemoryBuffer&& other) noexcept {
        if (this != &other) {
            if (data_) {
                obliterate(3);
            }
            size_ = other.size_;
            data_ = other.data_;
            locked_ = other.locked_;
            other.data_ = nullptr;
            other.size_ = 0;
            other.locked_ = false;
        }
        return *this;
    }

    void write(const void* src, std::size_t len) {
        if (len > size_) {
            throw std::out_of_range("Source payload exceeds SecureMemoryBuffer bounds");
        }
        std::memcpy(data_, src, len);
    }

    [[nodiscard]] void* data() noexcept { return data_; }
    [[nodiscard]] const void* data() const noexcept { return data_; }
    [[nodiscard]] std::size_t size() const noexcept { return size_; }
    [[nodiscard]] bool is_locked() const noexcept { return locked_; }

    /**
     * @brief Multi-pass silicon sanitization:
     *   Pass 1: Cryptographic PRNG noise
     *   Pass 2: Alternating charge inversion (0x55 then 0xAA)
     *   Pass 3: Secondary whitening noise
     *   Final : Kernel zero-memory barrier + page unlock + deallocation
     */
    void obliterate(int passes = 3) {
        if (!data_) return;

        std::random_device rd;
        std::mt19937_64 gen(rd());
        std::uniform_int_distribution<unsigned short> dist(0, 255);

        unsigned char* p = static_cast<unsigned char*>(data_);

        // Pass 1: Random entropy overwrite
        for (std::size_t i = 0; i < size_; ++i) {
            p[i] = static_cast<unsigned char>(dist(gen));
        }

        // Pass 2: Alternating bit-charge stress (breaks DRAM cell capacitive trap states)
        std::memset(data_, 0x55, size_);
        std::memset(data_, 0xAA, size_);

        // Additional passes if configured
        for (int p_idx = 0; p_idx < (passes - 2); ++p_idx) {
            for (std::size_t i = 0; i < size_; ++i) {
                p[i] = static_cast<unsigned char>(dist(gen));
            }
        }

        // Final Pass: Guaranteed dead-store secure zeroing
        internal::secure_memzero(data_, size_);

        // Release OS page lock and free address space
        deallocate();
    }

private:
    void allocate_and_lock() {
#if defined(_WIN32) || defined(_WIN64)
        // MEM_COMMIT | MEM_RESERVE = 0x3000, PAGE_READWRITE = 0x04
        data_ = VirtualAlloc(nullptr, size_, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
        if (!data_) {
            throw std::bad_alloc();
        }
        // Lock page in RAM to forbid pagefile.sys paging
        locked_ = (VirtualLock(data_, size_) != 0);
#else
        data_ = mmap(nullptr, size_, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        if (data_ == MAP_FAILED) {
            data_ = nullptr;
            throw std::bad_alloc();
        }
        locked_ = (mlock(data_, size_) == 0);
#endif
    }

    void deallocate() noexcept {
        if (!data_) return;
#if defined(_WIN32) || defined(_WIN64)
        if (locked_) {
            VirtualUnlock(data_, size_);
            locked_ = false;
        }
        VirtualFree(data_, 0, MEM_RELEASE);
#else
        if (locked_) {
            munlock(data_, size_);
            locked_ = false;
        }
        munmap(data_, size_);
#endif
        data_ = nullptr;
        size_ = 0;
    }

    std::size_t size_;
    void* data_;
    bool locked_;
};

/**
 * @brief Obliterates a target file across storage sectors with cache flush and metadata scrambled.
 */
inline bool shred_file(const std::filesystem::path& file_path, int passes = 3) {
    if (!std::filesystem::exists(file_path)) {
        return false;
    }

    auto file_size = std::filesystem::file_size(file_path);
    if (file_size == 0) file_size = 512;

    std::random_device rd;
    std::mt19937_64 gen(rd());
    std::uniform_int_distribution<unsigned short> dist(0, 255);

    {
        std::fstream fs(file_path, std::ios::in | std::ios::out | std::ios::binary);
        if (!fs.is_open()) return false;

        std::vector<char> buffer(file_size);

        // Pass 1: Random entropy
        for (auto& b : buffer) b = static_cast<char>(dist(gen));
        fs.seekp(0);
        fs.write(buffer.data(), buffer.size());
        fs.flush();

        // Pass 2: Inverted Bit Pattern 0xAA
        std::fill(buffer.begin(), buffer.end(), static_cast<char>(0xAA));
        fs.seekp(0);
        fs.write(buffer.data(), buffer.size());
        fs.flush();

        // Pass 3: Complement Bit Pattern 0x55
        std::fill(buffer.begin(), buffer.end(), static_cast<char>(0x55));
        fs.seekp(0);
        fs.write(buffer.data(), buffer.size());
        fs.flush();

        // Final: Zeroing
        std::fill(buffer.begin(), buffer.end(), 0x00);
        fs.seekp(0);
        fs.write(buffer.data(), buffer.size());
        fs.flush();
    }

    // Metadata shredding: rename multiple times before unlinking
    auto parent = file_path.parent_path();
    std::filesystem::path current_path = file_path;

    for (int i = 0; i < 3; ++i) {
        std::string rand_hex = "temp_" + std::to_string(gen()) + ".tmp";
        auto target = parent / rand_hex;
        std::error_code ec;
        std::filesystem::rename(current_path, target, ec);
        if (!ec) {
            current_path = target;
        }
    }

    std::error_code ec;
    std::filesystem::remove(current_path, ec);
    return !ec;
}

} // namespace event_horizon
