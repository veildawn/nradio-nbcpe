"""Exercise LED decisions without writing the host's hardware interfaces."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'board/files/usr/sbin/nbcpe-leds').read_text()
NR = '+CPIN: READY\n+CEREG: 2,1\n+C5GREG: 2,1,"76010D",11\n^HCSQ: "NR",57,221,30\n'
LTE = '+CPIN: READY\n+CEREG: 2,5\n+C5GREG: 2,2\n^HCSQ: "LTE",60,55,100,20\n'


class LEDTests(unittest.TestCase):
    def run_leds(self, raw=NR, age=5, error='', carrier='1', radios='true\ntrue', enabled='1', board='nradio,nbcpe'):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            leds = folder / 'leds'
            for name in ('wifi', 'cmode4', 'cmode5', 'status'):
                led = leds / ('blue:' + name)
                led.mkdir(parents=True)
                (led / 'brightness').write_text('1\n')
                (led / 'trigger').write_text('none [timer]\n')
            (folder / 'raw').write_text(raw)
            (folder / 'error').write_text(error)
            (folder / 'carrier').write_text(carrier + '\n')
            source = SOURCE.replace('. /lib/functions.sh', '')
            source = source.replace('/sys/class/leds', str(leds))
            source = source.replace('/tmp/mt5700.ethernet.raw', str(folder / 'raw'))
            source = source.replace('/tmp/mt5700.ethernet.error', str(folder / 'error'))
            source = source.replace('/sys/class/net/wan/carrier', str(folder / 'carrier'))
            stubs = '''
board_name() { printf '%s\n' "$BOARD"; }
date() { if [ "$1" = '-r' ]; then printf '%s\n' "$MTIME"; else echo 2000000000; fi; }
ubus() { echo '{}'; }
jsonfilter() { cat >/dev/null; printf '%s\n' "$RADIOS"; }
uci() { printf '%s\n' "$ENABLED"; }
'''
            env = dict(os.environ, BOARD=board, MTIME=str(2000000000 - age), RADIOS=radios, ENABLED=enabled)
            result = subprocess.run(['sh', '-c', stubs + source], capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, '')
            states = {name: (leds / ('blue:' + name) / 'brightness').read_text().strip()
                      for name in ('wifi', 'cmode4', 'cmode5', 'status')}
            # Startup, failsafe and flashing indication must retain ownership.
            self.assertEqual(states['status'], '1')
            self.assertEqual((leds / 'blue:status/trigger').read_text(), 'none [timer]\n')
            return states

    def test_nr_and_lte_use_the_actual_gpio_led_names(self):
        states = self.run_leds()
        self.assertEqual((states['cmode5'], states['cmode4']), ('1', '0'))
        states = self.run_leds(raw=LTE)
        self.assertEqual((states['cmode5'], states['cmode4']), ('0', '1'))

    def test_wifi_is_on_for_either_radio_without_a_client(self):
        self.assertEqual(self.run_leds(radios='false\ntrue')['wifi'], '1')
        self.assertEqual(self.run_leds(radios='true\nfalse')['wifi'], '1')
        self.assertEqual(self.run_leds(radios='false\nfalse')['wifi'], '0')
        self.assertEqual(self.run_leds(radios='')['wifi'], '0')

    def test_failed_or_stale_sampling_clears_cellular_lights(self):
        for changes in ({'age': 91}, {'age': -1}, {'error': 'AT unavailable'}, {'carrier': '0'}, {'enabled': '0'}, {'raw': ''}):
            with self.subTest(changes=changes):
                states = self.run_leds(**changes)
                self.assertEqual((states['cmode5'], states['cmode4']), ('0', '0'))
                self.assertEqual(states['wifi'], '1')
        self.assertEqual(self.run_leds(age=90)['cmode5'], '1')

    def test_signal_without_ready_sim_and_registration_does_not_light(self):
        for raw in ('^HCSQ: "NR",50,200,30\n', NR.replace('READY', 'SIM PIN'),
                    NR.replace('2,1', '2,2'), NR + '+CPIN: SIM PIN\n',
                    NR + '+CEREG: 2,2\n+C5GREG: 2,2\n'):
            with self.subTest(raw=raw):
                states = self.run_leds(raw=raw)
                self.assertEqual((states['cmode5'], states['cmode4']), ('0', '0'))

    def test_other_boards_are_not_touched(self):
        self.assertEqual(self.run_leds(board='unrelated,board', raw=''),
                         {'wifi': '1', 'cmode4': '1', 'cmode5': '1', 'status': '1'})


if __name__ == '__main__':
    unittest.main()
