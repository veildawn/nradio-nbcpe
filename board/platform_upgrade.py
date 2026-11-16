"""Install the NBCPE eMMC second-system upgrade path in the Filogic platform script."""

BOARD = "nradio,nbcpe"


def patch_platform_upgrade(text: str) -> str:
    upgrade_anchor = '\tcase "$board" in\n'
    upgrade_start = text.index("platform_do_upgrade() {")
    index = text.index(upgrade_anchor, upgrade_start) + len(upgrade_anchor)
    upgrade = f"""\t{BOARD})
\t\t# eMMC second system: kernel FIT -> PARTLABEL=kernel_2nd,
\t\t# root -> PARTLABEL=rootfs_2nd (f2fs rootfs_data overlay grows in the
\t\t# partition tail, 64K aligned). The factory flasher installs both on the
\t\t# first flash; sysupgrade refreshes either member in place.
\t\texport CI_KERNPART=kernel_2nd
\t\texport CI_ROOTPART=rootfs_2nd
\t\temmc_do_upgrade "$1"
\t\t;;
"""
    if not text.startswith(upgrade, index):
        end = text.index("\n}", index)
        if f"\t{BOARD})\n" in text[index:end]:
            raise ValueError("Use a clean Filogic platform.sh for this board port.")
        text = text[:index] + upgrade + text[index:]

    for function, anchor in (
        ("platform_check_image", "\tnradio,c8-668gl)"),
        ("platform_copy_config", "\tnradio,c8-668gl|\\\n"),
    ):
        start = text.index(f"{function}() {{")
        index = text.index(anchor, start)
        entry = f"\t{BOARD}|\\\n"
        if not text[:index].endswith(entry):
            text = text[:index] + entry + text[index:]

    return text
