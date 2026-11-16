"""Reject FIT load addresses that violate the input kernel's boot protocol."""

import struct
import unittest

from board.arm64_image import KERNEL_LOAD_ADDRESS, validate_load_address


# First 64 bytes of the Linux 6.18.60 Image from the recovery build, whose
# text_offset is zero. The stock kernel's historical 0x80000 offset is not
# applicable to this Image.
IMAGE_HEADER = bytes.fromhex(
    "1f2003d50d1c341400000000000000000000f500000000000a00000000000000"
    "00000000000000000000000000000000000000000000000041524d6400000000"
)


class Arm64ImageTests(unittest.TestCase):
    def test_current_kernel_accepts_aligned_address(self):
        validate_load_address(IMAGE_HEADER, KERNEL_LOAD_ADDRESS)

    def test_previous_fit_address_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "text_offset 0x0"):
            validate_load_address(IMAGE_HEADER, 0x48080000)

    def test_nonzero_text_offset_must_be_respected(self):
        header = bytearray(IMAGE_HEADER)
        struct.pack_into("<Q", header, 8, 0x80000)
        validate_load_address(header, 0x48080000)
        with self.assertRaises(ValueError):
            validate_load_address(header, KERNEL_LOAD_ADDRESS)

    def test_legacy_header_uses_protocol_default(self):
        header = bytearray(IMAGE_HEADER)
        struct.pack_into("<Q", header, 16, 0)
        validate_load_address(header, 0x48080000)
        with self.assertRaises(ValueError):
            validate_load_address(header, KERNEL_LOAD_ADDRESS)

    def test_truncated_or_wrong_format_kernel_is_rejected(self):
        for header in (IMAGE_HEADER[:63], b"\0" * 64):
            with self.subTest(header=header), self.assertRaises(ValueError):
                validate_load_address(header, KERNEL_LOAD_ADDRESS)


if __name__ == "__main__":
    unittest.main()
