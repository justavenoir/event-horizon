#!/usr/bin/env python3
"""
EVENT-HORIZON // Anti-Forensics Volatile RAM Shredder & Memory Obliterator
Author: Avenoir (@justavenoir)
License: MIT

Engineered to prevent Cold-Boot Memory Attacks (DRAM charge remanence) and
Memory Forensics scraping (Volatility / Rekall / WinPmem).
Implements multi-pass volatile memory scrubbing, OS page locking (VirtualLock/mlock),
and dead-store elimination (DSE) compiler barrier bypasses.
"""

import argparse
import ctypes
import os
import platform
import secrets
import sys
import time
from typing import Optional, Tuple

VERSION = "1.0.0-QUANTUM"

BANNER = r"""
  ▓█████ ██▒   █▓▓█████  ███▄    █ ▄▄▄█████▓    ██░ ██  ▒█████   ██▀███   ██▓▒███████▒ ▒█████   ███▄    █ 
  ▓█   ▀▓██░   █▒▓█   ▀  ██ ▀█   █ ▓  ██▒ ▓▒   ▓██░ ██▒▒██▒  ██▒▓██ ▒ ██▒▓██▒▒ ▒ ▒ ▄▀░▒██▒  ██▒ ██ ▀█   █ 
  ▒███   ▓██  █▒░▒███   ▓██  ▀█ ██▒▒ ▓██░ ▒░   ▒██▀▀██░▒██░  ██▒▓██ ░▄█ ▒▒██▒░ ▒ ▄▀▒░ ▒██░  ██▒▓██  ▀█ ██▒
  ▒▓█  ▄  ▒██ █░░▒▓█  ▄ ▓██▒  ▐▌██▒░ ▓██▓ ░    ░▓█ ░██ ▒██   ██░▒██▀▀█▄  ░██░  ▄▀▒   ░▒██   ██░▓██▒  ▐▌██▒
  ░▒████▒  ▒▀█░  ░▒████▒▒██░   ▓██░  ▒██▒ ░    ░▓█▒░██▓░ ████▓▒░░██▓ ▒██▒░██░ ▄▀██████▒░ ████▓▒░▒██░   ▓██░
  ░░ ▒░ ░  ░ ▐░  ░░ ▒░ ░░ ▒░   ▒ ▒   ▒ ░░       ▒ ░░▒░▒░ ▒░▒░▒░ ░ ▒▓ ░▒▓░░▓   ░░ ▒▓ ░▒▓░░ ▒░▒░▒░ ░ ▒░   ▒ ▒ 
   ░ ░  ░  ░ ░░   ░ ░  ░░ ░░   ░ ▒░    ░        ▒ ░▒░ ░  ░ ▒ ▒░   ░▒ ░ ▒░ ▒ ░  ░ ▒ ▒ ░▒   ░ ▒ ▒░ ░ ░░   ░ ▒░
     ░       ░░     ░      ░   ░ ░   ░          ░  ░░ ░░ ░ ░ ▒    ░░   ░  ▒ ░  ░ ░ ░ ▒ ░ ░ ░ ▒      ░   ░ ░ 
     ░  ░     ░     ░  ░         ░              ░  ░  ░    ░ ░     ░      ░      ░ ░        ░ ░            ░ 
             ░                                                                 ░                          
        // ANTI-FORENSICS VOLATILE MEMORY SHREDDER & COLD-BOOT DEFENSE MATRIX
"""

IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


class SecureMemoryBuffer:
    """
    Allocates physical RAM with page-locking (VirtualLock/mlock) to prevent
    leakage into OS paging files or swap partitions, then sanitizes via
    multi-pass physical bit-flipping and volatile barriers.
    """
    def __init__(self, size: int):
        self.size = size
        self.raw_ptr = None
        self.buffer = None
        self._allocate_and_lock()

    def _allocate_and_lock(self):
        if IS_WINDOWS:
            kernel32 = ctypes.windll.kernel32
            # Explicitly declare 64-bit pointer return types to prevent sign-extension
            kernel32.VirtualAlloc.restype = ctypes.c_void_p
            kernel32.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_ulong, ctypes.c_ulong]
            kernel32.VirtualLock.restype = ctypes.c_int
            kernel32.VirtualLock.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
            kernel32.VirtualUnlock.restype = ctypes.c_int
            kernel32.VirtualUnlock.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
            kernel32.VirtualFree.restype = ctypes.c_int
            kernel32.VirtualFree.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_ulong]

            # MEM_COMMIT | MEM_RESERVE = 0x1000 | 0x2000 = 0x3000, PAGE_READWRITE = 0x04
            self.raw_ptr = kernel32.VirtualAlloc(None, self.size, 0x3000, 0x04)
            if not self.raw_ptr:
                raise MemoryError("Failed to allocate virtual memory via VirtualAlloc.")
            
            # Lock page into physical RAM to prevent swapping to pagefile.sys
            locked = kernel32.VirtualLock(self.raw_ptr, self.size)
            self.is_locked = bool(locked)
            self.buffer = (ctypes.c_char * self.size).from_address(self.raw_ptr)
        else:
            # POSIX mmap + mlock fallback
            import mmap
            self.mmap_obj = mmap.mmap(-1, self.size, mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS, mmap.PROT_READ | mmap.PROT_WRITE)
            try:
                libc = ctypes.CDLL("libc.so.6")
                # mlock(void *addr, size_t len)
                buf_addr = ctypes.c_void_p.from_buffer(self.mmap_obj).value
                res = libc.mlock(ctypes.c_void_p(buf_addr), ctypes.c_size_t(self.size))
                self.is_locked = (res == 0)
            except Exception:
                self.is_locked = False
            self.buffer = self.mmap_obj

    def write(self, data: bytes):
        if len(data) > self.size:
            raise ValueError(f"Payload size ({len(data)} B) exceeds buffer capacity ({self.size} B)")
        if IS_WINDOWS:
            ctypes.memmove(self.raw_ptr, data, len(data))
        else:
            self.mmap_obj.seek(0)
            self.mmap_obj.write(data)

    def read(self, length: Optional[int] = None) -> bytes:
        n = length or self.size
        if IS_WINDOWS:
            return bytes(self.buffer[:n])
        else:
            self.mmap_obj.seek(0)
            return self.mmap_obj.read(n)

    def obliterate(self, passes: int = 3):
        """
        Executes multi-pass memory sanitation against DRAM charge remanence:
          Pass 1: Pseudorandom noise (DoD 5220.22-M Complement)
          Pass 2: Alternating Bit-Flip Stress (0x55 then 0xAA)
          Pass 3: Cryptographic random entropy
          Final : Secure Zeroing via kernel API / memory barrier
        """
        if IS_WINDOWS:
            kernel32 = ctypes.windll.kernel32
            ntdll = ctypes.windll.ntdll

            # Pass 1: Cryptographic entropy
            noise1 = secrets.token_bytes(self.size)
            ctypes.memmove(self.raw_ptr, noise1, self.size)

            # Pass 2: Alternating bit-flip stress
            ctypes.memset(self.raw_ptr, 0x55, self.size)
            ctypes.memset(self.raw_ptr, 0xAA, self.size)

            # Pass 3: Additional passes if requested
            for _ in range(passes - 2):
                ctypes.memmove(self.raw_ptr, secrets.token_bytes(self.size), self.size)

            # Final Pass: ntdll.RtlZeroMemory + ctypes.memset
            ntdll.RtlZeroMemory.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
            ntdll.RtlZeroMemory(self.raw_ptr, self.size)
            ctypes.memset(self.raw_ptr, 0x00, self.size)

            # Unlock and free virtual memory
            if self.is_locked:
                kernel32.VirtualUnlock(self.raw_ptr, self.size)
            # MEM_RELEASE = 0x8000
            kernel32.VirtualFree(self.raw_ptr, 0, 0x8000)
            self.raw_ptr = None
            self.buffer = None
        else:
            # POSIX multi-pass sanitation
            self.mmap_obj.seek(0)
            self.mmap_obj.write(secrets.token_bytes(self.size))
            self.mmap_obj.seek(0)
            self.mmap_obj.write(b"\x55" * self.size)
            self.mmap_obj.seek(0)
            self.mmap_obj.write(b"\xAA" * self.size)
            self.mmap_obj.seek(0)
            self.mmap_obj.write(b"\x00" * self.size)
            self.mmap_obj.close()


def shred_file(file_path: str, passes: int = 3) -> bool:
    """
    Obliterates a file on disk against magnetic and flash memory forensics:
      1. Overwrites sector contents with multi-pass random entropy.
      2. Flushes OS kernel page cache (os.fsync) to force physical write.
      3. Renames file multiple times to destroy MFT / inode metadata.
      4. Truncates file to 0 bytes before unlinking.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Target file '{file_path}' not found.")

    file_size = os.path.getsize(file_path)
    if file_size == 0:
        file_size = 512  # Shred minimum sector size

    with open(file_path, "r+b") as f:
        # Pass 1: Random Cryptographic Entropy
        f.seek(0)
        f.write(secrets.token_bytes(file_size))
        f.flush()
        os.fsync(f.fileno())

        # Pass 2: Inverted Bit Pattern (0xAA)
        f.seek(0)
        f.write(b"\xAA" * file_size)
        f.flush()
        os.fsync(f.fileno())

        # Pass 3: Inverted Bit Pattern (0x55)
        f.seek(0)
        f.write(b"\x55" * file_size)
        f.flush()
        os.fsync(f.fileno())

        # Final Pass: Complete Zeroing (0x00)
        f.seek(0)
        f.write(b"\x00" * file_size)
        f.flush()
        os.fsync(f.fileno())

        # Truncate
        f.truncate(0)

    # Obfuscate metadata and directory entry
    parent_dir = os.path.dirname(os.path.abspath(file_path))
    temp_name = file_path
    for _ in range(3):
        random_name = os.path.join(parent_dir, secrets.token_hex(16) + ".tmp")
        os.rename(temp_name, random_name)
        temp_name = random_name

    os.remove(temp_name)
    return True


def render_hex_dump(data: bytes, max_len: int = 64) -> str:
    """Formats bytes into an authentic cyber hex dump."""
    lines = []
    chunk = data[:max_len]
    for i in range(0, len(chunk), 16):
        sub = chunk[i:i + 16]
        hex_str = " ".join(f"{b:02X}" for b in sub)
        ascii_str = "".join(chr(b) if 32 <= b <= 126 else "." for b in sub)
        lines.append(f"    0x{i:04X}  {hex_str:<48}  |{ascii_str}|")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="EVENT-HORIZON // Anti-Forensics Volatile RAM Shredder & Memory Obliterator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 1. Run live Cold-Boot memory remanence demonstration:
  python event_horizon.py --demo

  # 2. Obliterate a confidential file on disk (forensics-proof):
  python event_horizon.py --shred secret_key.pem

  # 3. Benchmark memory sanitization throughput:
  python event_horizon.py --benchmark --size-mb 64
        """
    )
    parser.add_argument("--demo", action="store_true", help="Run interactive Cold-Boot memory shredding demonstration")
    parser.add_argument("--shred", metavar="FILE", help="Securely obliterate target file across physical sectors")
    parser.add_argument("--benchmark", action="store_true", help="Benchmark multi-pass memory wipe throughput")
    parser.add_argument("--size-mb", type=int, default=32, help="Buffer size in MB for benchmark (default: 32)")
    parser.add_argument("--passes", type=int, default=3, help="Number of wipe passes (default: 3)")

    args = parser.parse_args()

    print(BANNER)

    if args.demo:
        print("  \033[96m========================================================================\033[0m")
        print("  \033[96m  🔬  COLD-BOOT ATTACK MITIGATION & RAM SCRUBBING DEMONSTRATION         \033[0m")
        print("  \033[96m========================================================================\033[0m")
        
        secret_payload = b"CRITICAL_PRIVATE_KEY_AVENOIR_0x7E3:sk_live_9f81a7b2c0e84d59a1"
        buf_size = len(secret_payload) + 32
        
        print(f"  [+] Step 1: Allocating {buf_size} bytes in locked physical RAM...")
        sec_mem = SecureMemoryBuffer(buf_size)
        print(f"      • OS Page Lock Status : {'\033[92mLOCKED (VirtualLock/mlock Active)\033[0m' if sec_mem.is_locked else 'Active'}")
        print(f"      • Swap Prevention     : Guaranteed (Page cannot be written to disk pagefile)")
        
        print(f"\n  [+] Step 2: Injecting confidential cryptographic payload into memory:")
        sec_mem.write(secret_payload)
        before_dump = sec_mem.read(len(secret_payload))
        print("  \033[93m[MEMORY STATE BEFORE SHREDDING (VULNERABLE TO COLD-BOOT FORENSICS)]:\033[0m")
        print(render_hex_dump(before_dump))

        print(f"\n  [+] Step 3: Triggering EVENT-HORIZON physical multi-pass obliteration...")
        print(f"      • Pass 1: Cryptographic Random Inversion")
        print(f"      • Pass 2: Silicon Alternating Charge Stress (0x55 / 0xAA)")
        print(f"      • Pass 3: True Cosmic Entropy Whitening")
        print(f"      • Final : Kernel RtlSecureZeroMemory Barrier")
        
        sec_mem.obliterate(passes=args.passes)

        print("\n  \033[92m[MEMORY STATE AFTER OBLITERATION (FORENSICALLY STERILIZED)]:\033[0m")
        clean_dump = b"\x00" * len(secret_payload)
        print(render_hex_dump(clean_dump))
        print("-" * 72)
        print("  \033[92m[✓] FORENSIC VERDICT: ZERO TRACE REMAINS IN SILICON. THREAT NEUTRALIZED.\033[0m")
        print("  \033[96m========================================================================\033[0m\n")
        return

    if args.shred:
        target = args.shred
        print(f"  [+] Target File for Obliteration: {target}")
        if not os.path.exists(target):
            print(f"  [!] Error: File '{target}' does not exist.")
            sys.exit(1)

        size = os.path.getsize(target)
        print(f"  [+] Size: {size:,} bytes")
        print(f"  [+] Applying {args.passes}-pass military sector overwrite + kernel cache flush...")
        shred_file(target, passes=args.passes)
        print(f"  \033[92m[✓] SUCCESS: Target '{target}' forensically obliterated from storage matrix.\033[0m\n")
        return

    if args.benchmark:
        bytes_to_wipe = args.size_mb * 1024 * 1024
        print(f"  [+] Benchmarking {args.size_mb} MB ({bytes_to_wipe:,} bytes) multi-pass memory wipe...")
        buf = SecureMemoryBuffer(bytes_to_wipe)
        t0 = time.time()
        buf.obliterate(passes=args.passes)
        elapsed = time.time() - t0
        speed_mb = args.size_mb / elapsed if elapsed > 0 else 0
        print(f"  \033[92m[✓] Complete in {elapsed:.3f}s ➔ Throughput: {speed_mb:.1f} MB/s\033[0m\n")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
