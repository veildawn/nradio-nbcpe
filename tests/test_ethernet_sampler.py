"""Run the real ucode sampler against a deterministic socket peer.

Set UCODE to a host ucode executable, or install ucode in PATH. The socket
boundary is replaced; command selection, deadlines, framing and publication
logic are the production code, running in the actual ucode interpreter.
"""
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'board/files/usr/share/nradio-nbcpe/mt5700-ethernet.uc'
LOCAL_UCODE = ROOT / 'work/ucode-host/ucode'
UCODE = os.environ.get('UCODE') or shutil.which('ucode')
if not UCODE and LOCAL_UCODE.is_file():
    UCODE = str(LOCAL_UCODE)

PEER = r'''
let elapsed = 0;
let created = 0;
let selected = scenario == 'slot_external' ? 'external' : 'internal';
let slot_reads = 0;
function clock(monotonic) {
    if (!monotonic) die('sampler must use monotonic time');
    return [int(elapsed / 1000), (elapsed % 1000) * 1000000];
}
let socket = {
    AF_INET: 2, SOCK_STREAM: 1, SOCK_NONBLOCK: 2048,
    SOL_SOCKET: 1, SO_BINDTODEVICE: 25, SO_ERROR: 4,
    POLLIN: 1, POLLOUT: 4, MSG_NOSIGNAL: 16384,
    create: function(family, kind) {
        if (family != 2 || kind != 2049) die('socket must be nonblocking IPv4 TCP');
        created++;
        let s = { bound: false, connecting: true, request: '', chunks: [] };
        s.setopt = function(level, option, value) {
            if (level != 1 || option != 25 || value != 'wan') die('bad device binding');
            s.bound = true;
            return scenario != 'bind_failure';
        };
        s.connect = function(host, port) {
            if (!s.bound || host != '192.168.8.1' || port != 20249)
                die('wrong endpoint or connect before device binding');
            return null;
        };
        s.getopt = function(level, option) { return scenario == 'refused' ? 111 : 0; };
        s.peername = function() { return scenario == 'no_peer' ? null : {address: '192.168.8.1'}; };
        s.send = function(data, flags) {
            if (flags != 16384) die('missing SIGPIPE protection');
            if (scenario == 'send_failure') return null;
            let n = length(data);
            if (scenario == 'short_send' && n > 2) n = 2;
            s.request += substr(data, 0, n);
            if (substr(s.request, -1) == '\r') {
                let command = substr(s.request, 0, length(s.request) - 1);
                warn('SENT ' + command + '\n');
                if (scenario == 'control_error_scichg' && command == 'AT^SCICHG=0,1')
                    s.chunks = ['\r\nERROR\r\n'];
                else if (scenario == 'control_error_hvsst0' && command == 'AT^HVSST=1,0')
                    s.chunks = ['\r\n+CME ERROR: 3\r\n'];
                else if (scenario == 'control_error_hvsst1' && command == 'AT^HVSST=1,1')
                    s.chunks = ['\r\nERROR\r\n'];
                else if (scenario == 'control_eof_hvsst0' && command == 'AT^HVSST=1,0')
                    s.chunks = [''];
                else if (scenario == 'control_timeout_hvsst0' && command == 'AT^HVSST=1,0')
                    s.chunks = [];
                else if (scenario == 'control_error_reboot' && command == 'AT+CFUN=1,1')
                    s.chunks = ['\r\nERROR\r\n'];
                else if (scenario == 'reboot_eof' && command == 'AT+CFUN=1,1')
                    s.chunks = [''];
                else if (scenario == 'reboot_timeout' && command == 'AT+CFUN=1,1')
                    s.chunks = [];
                else if (command == 'AT^SCICHG?') {
                    slot_reads++;
                    if (scenario == 'slot_invalid')
                        s.chunks = ['\r\n^SCICHG: 2,0\r\nOK\r\n'];
                    else if (scenario == 'slot_ambiguous')
                        s.chunks = ['\r\n^SCICHG: 1,0\r\n^SCICHG: 0,1\r\nOK\r\n'];
                    else if (scenario == 'slot_equal_pair')
                        s.chunks = ['\r\n^SCICHG: 1,1\r\nOK\r\n'];
                    else if (scenario == 'readback_timeout' && slot_reads == 2)
                        s.chunks = [];
                    else
                        s.chunks = ['\r\n^SCI', 'CHG: ' + (selected == 'external' ? '0,1' : '1,0') + '\r\nO', 'K\r\n'];
                }
                else if (command == 'AT^SCICHG=0,1' || command == 'AT^SCICHG=1,0') {
                    if (scenario != 'readback_mismatch')
                        selected = command == 'AT^SCICHG=0,1' ? 'external' : 'internal';
                    s.chunks = ['\r\nOK\r\n'];
                }
                else if (scenario == 'error_optional' && command == 'AT+C5GREG?')
                    s.chunks = ['\r\n+CME ER', 'ROR: 4\r\n'];
                else if (scenario == 'no_sim' && command == 'AT+CPIN?')
                    s.chunks = ['\r\n+CME ERROR: 10\r\n'];
                else if (scenario == 'error_required' && command == 'AT^HCSQ?')
                    s.chunks = ['\r\nERROR\r\n'];
                else if (scenario == 'truncated' && command == 'AT^MONSC')
                    s.chunks = ['\r\n^MONSC: NR,460,01', ''];
                else if (scenario == 'oversized' && command == 'AT^MONSC')
                    s.chunks = [sprintf('%17000s', 'x')];
                else if (scenario == 'false_ok' && command == 'AT^MONSC')
                    s.chunks = ['\r\n^INFO: BOOK\r\n', ''];
                else if (scenario == 'nul' && command == 'AT^MONSC')
                    s.chunks = ['\r\n^INFO: ab\u0000cd\r\nOK\r\n'];
                else
                    s.chunks = ['\r\n', command, '\r\n+VALUE: 1\r\nO', 'K\r', '\n'];
            }
            return n;
        };
        s.recv = function(size) {
            if (size != 4096) die('unexpected receive limit');
            return shift(s.chunks);
        };
        s.close = function() { warn('CLOSED\n'); return true; };
        return s;
    },
    poll: function(timeout, spec) {
        if (timeout <= 0 || timeout > (length(ARGV) ? 5000 : 2000)) die('unbounded poll');
        let s = spec[0];
        if (s.connecting) {
            if (scenario == 'connect_timeout') { elapsed += timeout; return []; }
            s.connecting = false;
            return [[s, 4]];
        }
        if (spec[1] == 4) return [[s, 4]];
        if (scenario == 'response_timeout' && created == 4) { elapsed += timeout; return []; }
        if (scenario == 'slow_fragments') elapsed += 750;
        else elapsed += 1;
        if (scenario == 'poll_failure') return null;
        if (scenario == 'hangup') return [[s, 16]];
        if (!length(s.chunks)) { elapsed += timeout; return []; }
        return [[s, 1 | 16]];
    }
};
'''


@unittest.skipUnless(UCODE, 'host ucode interpreter not available (set UCODE)')
class EthernetSamplerTests(unittest.TestCase):
    def run_sampler(self, scenario, *args):
        source = SOURCE.read_text().replace("import * as socket from 'socket';", '')
        if source.startswith('#!'):
            source = source.split('\n', 1)[1]
        with tempfile.TemporaryDirectory(prefix='nradio-ethernet-') as tmp:
            path = Path(tmp) / 'sampler.uc'
            path.write_text('let scenario = ' + json.dumps(scenario) + ';\n' + PEER + source)
            return subprocess.run([UCODE, str(path), *args], capture_output=True, text=True, timeout=5)

    def assert_no_snapshot(self, scenario):
        result = self.run_sampler(scenario)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stdout, '', result.stderr)
        self.assertIn('CLOSED', result.stderr)
        return result

    def test_fragmented_responses_and_final_readable_hangup(self):
        result = self.run_sampler('fragmented')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('\r', result.stdout)
        self.assertEqual(result.stdout.count('\nOK\n'), 19)
        self.assertEqual(result.stderr.count('CLOSED\n'), 19)
        sent = [line[5:] for line in result.stderr.splitlines() if line.startswith('SENT ')]
        self.assertEqual(sent, [
            'AT+CFUN?', 'AT+CPIN?', 'AT+CIMI', 'AT^ICCID?', 'AT+COPS?',
            'AT^HCSQ?', 'AT+CEREG?', 'AT+C5GREG?', 'AT^SCICHG?', 'AT^CHIPTEMP?',
            'AT^MONSC', 'AT^HFREQINFO?', 'AT+CGEQOSRDP', 'AT^DSAMBR=1',
            'AT+CGPADDR', 'AT+GSN', 'AT+CGACT?', 'AT^SYSCFGEX?', 'AT^NWTIME?',
        ])

    def test_short_sends_are_completed_without_duplicate_bytes(self):
        result = self.run_sampler('short_send')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr.count('SENT '), 19)
        self.assertEqual(result.stdout.count('\nOK\n'), 19)

    def test_optional_cme_error_keeps_other_fields(self):
        result = self.run_sampler('error_optional')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('+CME ERROR: 4', result.stdout)
        self.assertEqual(result.stdout.count('\nOK\n'), 18)

    def test_required_error_does_not_publish_prior_successes(self):
        result = self.assert_no_snapshot('error_required')
        self.assertIn('required modem query failed', result.stderr)

    def test_missing_sim_still_publishes_radio_status(self):
        result = self.run_sampler('no_sim')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('+CME ERROR: 10', result.stdout)
        self.assertIn('AT^HCSQ?', result.stdout)

    def test_failures_close_socket_and_never_publish_partial_snapshot(self):
        for scenario in ['bind_failure', 'refused', 'no_peer', 'connect_timeout',
                         'send_failure', 'response_timeout', 'poll_failure',
                         'hangup', 'truncated', 'oversized', 'false_ok', 'nul']:
            with self.subTest(scenario=scenario):
                self.assert_no_snapshot(scenario)

    def test_response_deadline_does_not_restart_for_each_fragment(self):
        result = self.assert_no_snapshot('slow_fragments')
        self.assertIn('timeout', result.stderr)

    @staticmethod
    def sent_commands(result):
        return [line[5:] for line in result.stderr.splitlines() if line.startswith('SENT ')]

    def test_slot_query_is_read_only_and_uses_factory_mapping(self):
        for scenario, expected in [('slot_external', 'external'), ('slot_internal', 'internal')]:
            result = self.run_sampler(scenario, '--slot')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, expected + '\n')
            self.assertEqual(self.sent_commands(result), ['AT^SCICHG?'])

    def test_switch_to_current_slot_never_writes_or_reboots(self):
        for scenario, target in [('slot_external', 'external'), ('slot_internal', 'internal')]:
            result = self.run_sampler(scenario, '--switch', target)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), dict(state='already', target=target,
                                                           slot=target, reboot='not-needed'))
            self.assertEqual(self.sent_commands(result), ['AT^SCICHG?'])

    def test_explicit_switch_writes_correct_fixed_sequence_and_verifies(self):
        for scenario, target, command in [('slot_internal', 'external', 'AT^SCICHG=0,1'),
                                          ('slot_external', 'internal', 'AT^SCICHG=1,0')]:
            result = self.run_sampler(scenario, '--switch', target)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), dict(state='restarting', target=target,
                                                           slot=target, reboot='acknowledged'))
            self.assertEqual(self.sent_commands(result), ['AT^SCICHG?', command,
                'AT^HVSST=1,0', 'AT^HVSST=1,1', 'AT^SCICHG?', 'AT+CFUN=1,1'])

    def test_invalid_cli_arguments_cannot_send_any_command(self):
        for args in [('--switch', 'auto'), ('--switch', 'external', 'AT+CFUN=0'),
                     ('--slot', 'extra'), ('AT+CFUN=0',), ('--switch',)]:
            result = self.run_sampler('slot_internal', *args)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(result.stdout, '')
            self.assertEqual(self.sent_commands(result), [])
            self.assertNotIn('CLOSED', result.stderr)  # no socket even opened

    def test_control_errors_stop_immediately(self):
        sequence = ['AT^SCICHG?', 'AT^SCICHG=0,1', 'AT^HVSST=1,0',
                    'AT^HVSST=1,1', 'AT^SCICHG?', 'AT+CFUN=1,1']
        for scenario, count in [('control_error_scichg', 2), ('control_error_reboot', 6)]:
            result = self.run_sampler(scenario, '--switch', 'external')
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(result.stdout, '')
            self.assertEqual(self.sent_commands(result), sequence[:count])

    def test_hvsst_error_is_optional_but_slot_readback_and_reset_still_run(self):
        for scenario in ['control_error_hvsst0', 'control_error_hvsst1']:
            result = self.run_sampler(scenario, '--switch', 'external')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), dict(state='restarting', target='external',
                                                           slot='external', reboot='acknowledged'))
            self.assertEqual(self.sent_commands(result), ['AT^SCICHG?', 'AT^SCICHG=0,1',
                'AT^HVSST=1,0', 'AT^HVSST=1,1', 'AT^SCICHG?', 'AT+CFUN=1,1'])

    def test_hvsst_transport_failure_still_aborts_without_reset(self):
        for scenario in ['control_eof_hvsst0', 'control_timeout_hvsst0']:
            result = self.run_sampler(scenario, '--switch', 'external')
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(result.stdout, '')
            self.assertEqual(self.sent_commands(result), ['AT^SCICHG?', 'AT^SCICHG=0,1',
                                                         'AT^HVSST=1,0'])

    def test_slot_must_be_unambiguous_before_any_write(self):
        for scenario in ['slot_invalid', 'slot_ambiguous', 'slot_equal_pair']:
            result = self.run_sampler(scenario, '--switch', 'external')
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(result.stdout, '')
            self.assertEqual(self.sent_commands(result), ['AT^SCICHG?'])

    def test_failed_readback_never_reboots(self):
        for scenario in ['readback_mismatch', 'readback_timeout']:
            result = self.run_sampler(scenario, '--switch', 'external')
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(result.stdout, '')
            self.assertEqual(self.sent_commands(result), ['AT^SCICHG?', 'AT^SCICHG=0,1',
                'AT^HVSST=1,0', 'AT^HVSST=1,1', 'AT^SCICHG?'])

    def test_reboot_transport_loss_is_uncertain_not_confirmed(self):
        for scenario in ['reboot_eof', 'reboot_timeout']:
            result = self.run_sampler(scenario, '--switch', 'external')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), dict(state='uncertain', target='external',
                                                           slot='external', reboot='unconfirmed'))
            self.assertEqual(self.sent_commands(result)[-1], 'AT+CFUN=1,1')


if __name__ == '__main__':
    unittest.main()
