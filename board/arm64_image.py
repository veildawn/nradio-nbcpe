"""Check the ARM64 boot protocol before wrapping an Image in a FIT."""

import struct


KERNEL_LOAD_ADDRESS = 0x48000000


def validate_load_address(header: bytes, address: int) -> None:
    # https://www.kernel.org/doc/html/next/arm64/booting.html
    # Image must be text_offset bytes after a 2 MiB aligned base address.
    if len(header) < 64 or header[56:60] != b"ARM\x64":
        raise ValueError("Kernel does not have a valid ARM64 Image header")
    text_offset, image_size = struct.unpack_from("<QQ", header, 8)
    if not image_size:
        text_offset = 0x80000  # Legacy (pre-v3.17) Image header.
    if address < text_offset or (address - text_offset) % 0x200000:
        raise ValueError(
            f"Kernel load address {address:#x} does not match ARM64 "
            f"text_offset {text_offset:#x} plus a 2 MiB aligned base"
        )
