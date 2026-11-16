"""Run the patched board functions and verify their emitted interface defaults."""

from pathlib import Path
import subprocess
import tempfile
import unittest

from board.network import patch_board_network


NETWORK = '''mediatek_setup_interfaces()
{
\tlocal board="$1"
\tcase $board in
\tother,board)
\t\tucidef_set_interfaces_lan_wan "lan1 lan2" "eth1"
\t\t;;
\t*)
\t\tucidef_set_interfaces_lan_wan "lan1 lan2 lan3 lan4" "wan"
\t\t;;
\tesac
}

mediatek_setup_macs()
{
\tlocal board="$1"
\tlocal lan_mac="" wan_mac="" label_mac=""
\tcase $board in
\tnradio,c8-668gl)
\t\tlan_mac=00:11:22:33:44:55
\t\t;;
\t*)
\t\tlan_mac=$(get_mac_from_nvmem)
\t\t;;
\tesac
\t[ -n "$lan_mac" ] && ucidef_set_interface_macaddr "lan" "$lan_mac"
\t[ -n "$wan_mac" ] && ucidef_set_interface_macaddr "wan" "$wan_mac"
\t[ -n "$label_mac" ] && ucidef_set_label_macaddr "$label_mac"
}
'''

LEGACY_CASE = '''\tnradio,nbcpe)
\t\tucidef_set_interfaces_lan_wan "lan1 lan2 lan3" "wan"
\t\t. /lib/functions/nradio-nbcpe.sh
\t\tlan_mac=$(nbcpe_get_base_mac)
\t\t[ -n "$lan_mac" ] && wan_mac=$(macaddr_add "$lan_mac" 1)
\t\tlabel_mac=$lan_mac
\t\t;;
'''


class BoardSetupTests(unittest.TestCase):
    def run_setup(self, source, board="nradio,nbcpe"):
        with tempfile.TemporaryDirectory() as tmp:
            helper = Path(tmp) / "nbcpe.sh"
            helper.write_text("nbcpe_get_base_mac() { echo fc:83:c6:13:f3:62; }\n")
            source = source.replace("/lib/functions/nradio-nbcpe.sh", str(helper))
            harness = '''
ucidef_set_interfaces_lan_wan() { printf 'ports: %s / %s\\n' "$1" "$2"; }
ucidef_set_interface_macaddr() { printf 'mac: %s %s\\n' "$1" "$2"; }
ucidef_set_label_macaddr() { printf 'label: %s\\n' "$1"; }
macaddr_add() {
    [ "$1" = fc:83:c6:13:f3:62 ] && [ "$2" = 1 ] || return 1
    echo fc:83:c6:13:f3:63
}
get_mac_from_nvmem() { echo 'unexpected generic NVMEM lookup' >&2; return 1; }
'''
            return subprocess.run(
                ["sh", "-c", harness + source + '\nmediatek_setup_interfaces "$1"\n'
                 'mediatek_setup_macs "$1"\n', "setup", board],
                text=True, capture_output=True,
            )

    def test_three_ports_configured_once_and_macs_set_separately(self):
        result = self.run_setup(patch_board_network(NETWORK))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout.splitlines(), [
            "ports: lan1 lan2 lan3 / wan",
            "mac: lan fc:83:c6:13:f3:62",
            "mac: wan fc:83:c6:13:f3:63",
            "label: fc:83:c6:13:f3:62",
        ])

    def test_repatch_removes_legacy_duplicate_interface_setup(self):
        legacy = NETWORK.replace("\tnradio,c8-668gl)", LEGACY_CASE + "\tnradio,c8-668gl)")
        patched = patch_board_network(legacy)
        self.assertEqual(patched, patch_board_network(NETWORK))
        self.assertEqual(patch_board_network(patched), patched)
        result = self.run_setup(patched)
        self.assertEqual(result.stdout.count("ports:"), 1)
        self.assertNotIn("lan4", result.stdout)

    def test_other_boards_keep_original_port_defaults(self):
        result = self.run_setup(patch_board_network(NETWORK), "other,board")
        self.assertEqual(result.stdout.splitlines(), ["ports: lan1 lan2 / eth1"])

    def test_missing_setup_switch_is_rejected(self):
        with self.assertRaises(ValueError):
            patch_board_network(NETWORK.replace("\tcase $board in", "\tcase $unknown in", 1))


if __name__ == "__main__":
    unittest.main()
