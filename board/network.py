"""Install NBCPE port and MAC defaults in their respective board setup functions."""

import re


def patch_board_network(text: str) -> str:
    blocks = {
        "mediatek_setup_interfaces": (
            '\t\tucidef_set_interfaces_lan_wan "lan1 lan2 lan3" "wan"\n'
        ),
        "mediatek_setup_macs": (
            "\t\t. /lib/functions/nradio-nbcpe.sh\n"
            "\t\tlan_mac=$(nbcpe_get_base_mac)\n"
            '\t\t[ -n "$lan_mac" ] && wan_mac=$(macaddr_add "$lan_mac" 1)\n'
            "\t\tlabel_mac=$lan_mac\n"
        ),
    }
    for function, body in blocks.items():
        start = text.index(function + "()")
        end = text.index("\n}", start)
        section = text[start:end]
        # Replace earlier injections, including the old MAC case that also
        # appended LAN ports after the generic interface case had run.
        section, count = re.subn(
            r"^\tnradio,nbcpe\)\n.*?^\t\t;;\n",
            "",
            section,
            flags=re.M | re.S,
        )
        if count > 1 or "\tnradio,nbcpe" in section:
            raise ValueError(f"Unexpected NBCPE cases in {function}")
        anchor = "\tcase $board in\n"
        if section.count(anchor) != 1:
            raise ValueError(f"Missing or ambiguous board switch in {function}")
        block = "\tnradio,nbcpe)\n" + body + "\t\t;;\n"
        section = section.replace(anchor, anchor + block, 1)
        text = text[:start] + section + text[end:]
    return text
