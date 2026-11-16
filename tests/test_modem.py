"""Regression fixtures for the shell AT parser and nonblocking status path."""
from pathlib import Path
import os
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'board/files/usr/sbin/mt5700-status').read_text()


class ModemTests(unittest.TestCase):
    def test_ethernet_dispatch_never_enters_usb_power_manager(self):
        source = (ROOT / 'board/files/usr/sbin/mt5700-bringup').read_text()
        source = source.replace('. /lib/functions.sh', '').replace('. /usr/share/libubox/jshn.sh', '')
        with tempfile.TemporaryDirectory() as tmp:
            helper = Path(tmp) / 'monitor'
            helper.write_text('printf "ethernet %s\\n" "$1"\n')
            source = source.replace('/usr/sbin/mt5700-ethernet', str(helper))
            stubs = 'board_name() { echo nradio,nbcpe; }\nuci() { echo ethernet; }\n'
            result = subprocess.run(['sh', '-c', stubs + source, 'manager', '--once'], capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout, 'ethernet --once\n')
            self.assertEqual(result.stderr, '')

    def test_ethernet_defaults_do_not_create_phantom_usb_interfaces(self):
        source = (ROOT / 'board/files/etc/uci-defaults/99-nradio-nbcpe-wwan').read_text()
        source = source.replace('. /lib/functions.sh', '')
        with tempfile.TemporaryDirectory() as tmp:
            calls = Path(tmp) / 'uci-calls'
            stubs = '''
board_name() { echo nradio,nbcpe; }
uci() {
    case "$*" in
    *'get mt5700.modem.transport') echo ethernet ;;
    set*|commit*|add_list*) printf '%s\n' "$*" >> "$CALLS" ;;
    *) return 1 ;;
    esac
}
'''
            subprocess.run(['sh', '-c', stubs + source], env=dict(os.environ, CALLS=str(calls)), check=True)
            changes = calls.read_text()
            self.assertIn('network.wan.label=', changes)
            self.assertNotIn('wwan', changes)
            self.assertNotIn('dhcp.', changes)
            self.assertNotIn('firewall.', changes)

    def parse(self, raw):
        start = SOURCE.index('CFUN="" CPIN=')
        end = SOURCE.index('\nreg_stat()', start)
        code = 'RAW=' + shlex.quote(raw) + '\n' + SOURCE[start:end]
        fields = ['CFUN', 'CPIN', 'IMSI', 'ICCID', 'COPS', 'CSQ', 'HCSQ', 'HCSQV', 'CEREG', 'C5GREG', 'SCICHG', 'CHIPTEMP', 'IMEI']
        code += "\nprintf '%s\\n' " + ' '.join('"$' + f + '"' for f in fields)
        res = subprocess.run(['sh', '-c', code], capture_output=True, text=True, check=True)
        return dict(zip(fields, res.stdout.splitlines()))

    def test_nr_sweep_with_urcs_and_last_response_wins(self):
        result = self.parse('''AT+CPIN?
+CPIN: SIM PIN
OK
+CPIN: READY
460060123456789
^ICCID: 89860601234567890000
+COPS: 0,2,"46006",11
^HCSQ: "NR",54,170,26
+CEREG: 2,1,"0001","1234",7
+C5GREG: 2,1,"0001","1234",11
^SCICHG: 1,0
^CHIPTEMP: 65535,610,730
+CFUN: 1
867123456789012
OK''')
        self.assertEqual(result['CPIN'], 'READY')
        self.assertEqual(result['IMSI'], '460060123456789')
        self.assertEqual(result['IMEI'], '867123456789012')
        self.assertEqual(result['ICCID'], '89860601234567890000')
        self.assertEqual((result['HCSQ'], result['HCSQV']), ('NR', '54,170,26'))
        self.assertEqual(result['CHIPTEMP'], '65535,610,730')
        self.assertEqual(result['SCICHG'], '1,0')

    def test_empty_no_service_and_lte(self):
        self.assertEqual(self.parse('ERROR\nOK')['CPIN'], '')
        self.assertEqual(self.parse('^HCSQ: "NOSERVICE"')['HCSQV'], '')
        result = self.parse('^HCSQ: "LTE",60,55,100,20\n+CSQ: 18,99')
        self.assertEqual(result['CSQ'], '18 99')
        self.assertEqual(result['HCSQV'], '60,55,100,20')

    def test_absent_external_sim_is_not_an_unknown_transport_failure(self):
        result = self.parse('AT+CPIN?\n+CME ERROR: 10\nAT^HCSQ?\n^HCSQ: "NOSERVICE"\nOK')
        self.assertEqual(result['CPIN'], 'NOT INSERTED')
        result = self.parse('AT+CPIN?\n+CPIN: READY\nOK\nAT+CIMI\n+CME ERROR: 10')
        self.assertEqual(result['CPIN'], 'READY')

    def test_web_status_never_invokes_gcom_for_stale_snapshot(self):
        with tempfile.TemporaryDirectory(prefix='nradio-status-') as tmp:
            path = Path(tmp)
            prefix = SOURCE[:SOURCE.index('# ---- parse raw AT burst')]
            prefix = prefix.replace('. /lib/functions.sh', '').replace('. /usr/share/libubox/jshn.sh', '')
            prefix = prefix.replace('[ "$(board_name)" = "nradio,nbcpe" ] || exit 0', '')
            prefix = prefix.replace('/tmp/mt5700.status.raw', str(path / 'raw'))
            # Substitute only the hardware discovery, leaving the AT decision intact.
            prefix = prefix.replace('\nfind_modem_usb\n', '\nfind_modem_usb() { :; }\n')
            stubs = '''
uci() { case "$*" in *mt5700.modem.transport*) echo usb ;; *) echo /dev/null ;; esac; }
lock() { return 0; }
ubus() { echo '{"pending": false}'; }
gcom() { echo called >> "$TEST_MARKER"; printf 'OK\\n'; }
timeout() { shift; "$@"; }
'''
            env = dict(os.environ, TEST_MARKER=str(path / 'calls'))
            script = path / 'status'
            script.write_text(stubs + prefix + '\nprintf "%s\\n" "$SOURCE"\n')
            snapshot = path / 'raw'
            snapshot.write_text('OK\n')
            os.utime(snapshot, (1, 1))
            subprocess.run(['sh', str(script)], env=env, capture_output=True, check=True)
            self.assertFalse((path / 'calls').exists())
            subprocess.run(['sh', str(script), '--refresh'], env=env, capture_output=True, check=True)
            self.assertEqual((path / 'calls').read_text(), 'called\n')


if __name__ == '__main__':
    unittest.main()
