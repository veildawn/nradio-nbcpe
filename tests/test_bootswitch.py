"""Exercise slot switching with the factory ubenv output format and failures."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BootswitchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / "slot"
        self.state.write_text("1\n")
        self.calls = self.root / "writes"
        tool = self.root / "ubenv"
        tool.write_text('''#!/bin/sh
case "$2" in
3)
    [ ! -f "$TEST_ROOT/bad-env" ] || exit 1
    printf 'baudrate=115200\\nbootdelay=2\\nboot_system=%s\\nipaddr=192.168.1.1\\nserverip=192.168.1.88\\n' "$(cat "$TEST_ROOT/slot")"
    ;;
1)
    [ ! -f "$TEST_ROOT/bad-read" ] || exit 1
    printf 'boot_system = %s\\n' "$(cat "$TEST_ROOT/slot")"
    ;;
0)
    printf '%s\\n' "$*" >> "$TEST_ROOT/writes"
    [ ! -f "$TEST_ROOT/fail-write" ] || exit 1
    [ -f "$TEST_ROOT/no-write" ] || printf '%s\\n' "$6" > "$TEST_ROOT/slot"
    ;;
esac
''')
        tool.chmod(0o755)
        blkid = self.root / "blkid"
        blkid.write_text("#!/bin/sh\nprintf '/dev/mmcblk0p2\\n'\n")
        blkid.chmod(0o755)
        source = (ROOT / "board/files/usr/sbin/nbcpe-bootswitch").read_text()
        source = source.replace("UBENV=/usr/bin/ubenv", f"UBENV={tool}")
        # No hardware writes: only the device-node existence check is stubbed.
        source = source.replace('[ -b "$(blkid', '[ -n "$(blkid')
        self.script = self.root / "bootswitch"
        self.script.write_text(source)
        self.env = dict(os.environ, TEST_ROOT=str(self.root),
                        PATH=str(self.root) + ":" + os.environ["PATH"])

    def call(self, command, ok=True):
        result = subprocess.run(["sh", str(self.script), command], env=self.env,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def test_factory_format_status_and_verified_round_trip(self):
        self.assertEqual(self.call("status"), "boot_system=1 (openwrt-second-system)\n")
        self.assertIn("Updated boot_system=0", self.call("to-factory"))
        self.assertEqual(self.call("status"), "boot_system=0 (factory-system)\n")
        self.assertIn("Updated boot_system=1", self.call("to-openwrt"))
        self.assertEqual(self.calls.read_text().splitlines(),
                         ["-o 0 -s boot_system -v 0", "-o 0 -s boot_system -v 1"])

    def test_already_selected_slot_does_not_write(self):
        self.assertIn("already 1", self.call("to-openwrt"))
        self.assertFalse(self.calls.exists())

    def test_invalid_environment_cannot_write(self):
        (self.root / "bad-env").touch()
        self.assertIn("sanity check failed", self.call("to-factory", ok=False))
        self.assertFalse(self.calls.exists())

    def test_failed_read_cannot_write_or_report_success(self):
        (self.root / "bad-read").touch()
        self.call("status", ok=False)
        self.call("to-factory", ok=False)
        self.assertFalse(self.calls.exists())

    def test_invalid_slot_cannot_write(self):
        self.state.write_text("7\n")
        self.call("status", ok=False)
        self.call("to-factory", ok=False)
        self.assertFalse(self.calls.exists())

    def test_write_failure_and_readback_mismatch_are_errors(self):
        (self.root / "fail-write").touch()
        self.assertIn("write failed", self.call("to-factory", ok=False))
        (self.root / "fail-write").unlink()
        (self.root / "no-write").touch()
        self.assertIn("read-back mismatch", self.call("to-factory", ok=False))
