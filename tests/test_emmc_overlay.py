"""Check eMMC second-system isolation before OpenWrt can mount a writable layer."""

from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest

from board.platform_upgrade import patch_platform_upgrade


ROOT = Path(__file__).resolve().parents[1]

FACTORY_LABELS = ("kernel", "rootfs", "u-boot-env", "factory", "bdinfo", "fip")


class EmmcOverlayTests(unittest.TestCase):
    def test_preinit_requires_second_system_root_and_factory_layout(self):
        guard = (ROOT / "board/files/lib/preinit/35_nradio_emmc_overlay").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp)
            # stub blkid: answers PARTLABEL queries from a table file
            (fixture / "blkid").write_text(textwrap.dedent(f'''\
                #!/bin/sh
                table="{fixture}/parts"
                while [ $# -gt 0 ]; do
                    case "$1" in
                    -t) label=${{2#PARTLABEL=}}; shift 2 ;;
                    -o|device) shift ;;
                    *) shift ;;
                    esac
                done
                [ -f "$table" ] && grep "^${{label:-none}}=" "$table" | cut -d= -f2
                exit 0
            '''))
            (fixture / "blkid").chmod(0o755)
            for original, filename in (
                ("/proc/self/mountinfo", "mountinfo"),
                ("/sys/class/block", "sys_block"),
                ("/dev/console", "console"),
                ("/tmp/failsafe", "failsafe"),
            ):
                guard = guard.replace(original, str(fixture / filename))
            guard = guard.replace("blkid ", f'"{fixture}/blkid" ')

            def run_case(root_dev, fs, parts):
                (fixture / "mountinfo").write_text(
                    f"17 0 {root_dev} / / ro - {fs} /dev/root ro\n"
                )
                (fixture / "parts").write_text("".join(parts))
                (fixture / "sys_block" / "mmcblk0p9").mkdir(parents=True, exist_ok=True)
                (fixture / "sys_block" / "mmcblk0p9" / "dev").write_text("179:9\n")
                (fixture / "failsafe").unlink(missing_ok=True)
                return subprocess.check_output(
                    [
                        "sh", "-c",
                        "board_name() { echo nradio,nbcpe; }\n"
                        "boot_hook_add() { :; }\n"
                        + f'PATH="{fixture}:$PATH"\n'
                        + guard
                        + '\nnradio_emmc_overlay_guard\nprintf "%s" "$FAILSAFE"',
                    ],
                    text=True,
                )

            all_parts = [f"{label}=/dev/mmcblk0pN\n" for label in FACTORY_LABELS]
            all_parts.insert(0, "rootfs_2nd=/dev/mmcblk0p9\n")

            # Happy path: squashfs on rootfs_2nd + full factory GPT layout
            self.assertEqual(run_case("179:9", "squashfs", all_parts), "")

            # Root filesystem not squashfs (e.g. factory ext4 boot)
            self.assertEqual(run_case("179:9", "ext4", all_parts), "true")

            # Booted from the factory rootfs partition instead of rootfs_2nd
            self.assertEqual(run_case("179:7", "squashfs", all_parts), "true")

            # rootfs_2nd partition missing entirely
            self.assertEqual(
                run_case("179:9", "squashfs", [f"{l}=/dev/mmcblk0pN\n" for l in FACTORY_LABELS]),
                "true",
            )

            # Factory GPT layout incomplete (bdinfo gone)
            partial = [f"{l}=/dev/mmcblk0pN\n" for l in ("rootfs_2nd", *FACTORY_LABELS[:-1])]
            self.assertEqual(run_case("179:9", "squashfs", partial), "true")

    def test_platform_upgrade_targets_second_system_partitions(self):
        T = "\t"
        platform_sh = (
            "platform_do_upgrade() {\n"
            f'{T}case "$board" in\n'
            f"{T}nradio,c8-668gl)\n"
            f"{T}{T};;\n"
            f"{T}esac\n"
            "}\n"
            "platform_check_image() {\n"
            f'{T}case "$board" in\n'
            f"{T}nradio,c8-668gl)\n"
            f"{T}{T};;\n"
            f"{T}esac\n"
            "}\n"
            "platform_copy_config() {\n"
            f'{T}case "$board" in\n'
            f"{T}nradio,c8-668gl|\\\n"
            f"{T}other,board)\n"
            f"{T}{T};;\n"
            f"{T}esac\n"
            "}\n"
        )
        patched = patch_platform_upgrade(platform_sh)
        self.assertIn('\tnradio,nbcpe)\n\t\t# eMMC second system: kernel FIT -> PARTLABEL=kernel_2nd', patched)
        self.assertIn('export CI_KERNPART=kernel_2nd\n\t\texport CI_ROOTPART=rootfs_2nd\n\t\temmc_do_upgrade "$1"', patched)
        self.assertIn('nradio,nbcpe|\\\n', patched)


if __name__ == "__main__":
    unittest.main()
