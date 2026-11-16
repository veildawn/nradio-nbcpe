#!/usr/bin/ucode
// MT5700M-CN ODU transport from the factory atsd/freq.json implementation:
// TCP 192.168.8.1:20249, plain AT commands terminated by one carriage return.
// Run under `timeout 40 ucode ...`; default stdout is a complete read-only
// snapshot or empty. Explicit --slot / --switch modes are described below.
import * as socket from 'socket';

const HOST = '192.168.8.1';
const PORT = 20249;
const DEVICE = 'wan';
const IO_TIMEOUT = 2000;
const CONTROL_TIMEOUT = 5000;
const MAX_REPLY = 16384;
// No user-supplied command or endpoint is accepted. DSAMBR=1 reads subscribed
// AMBR for context 1; it does not change the APN or initiate a data connection.
const COMMANDS = [
	['AT+CFUN?', true], ['AT+CPIN?', false], ['AT+CIMI', false],
	['AT^ICCID?', false], ['AT+COPS?', false], ['AT^HCSQ?', true],
	['AT+CEREG?', false], ['AT+C5GREG?', false], ['AT^SCICHG?', false],
	['AT^CHIPTEMP?', false], ['AT^MONSC', false], ['AT^HFREQINFO?', false],
	['AT+CGEQOSRDP', false], ['AT^DSAMBR=1', false], ['AT+CGPADDR', false],
	['AT+GSN', false], ['AT+CGACT?', false], ['AT^SYSCFGEX?', false],
	['AT^NWTIME?', false]
];
// Factory cpesel aliases 0=external and 4=internal, with usim=SCICHG.first+1.
// These are the only configuration writes exposed, and only by --switch.
const SLOT_COMMANDS = {
	external: 'AT^SCICHG=0,1',
	internal: 'AT^SCICHG=1,0'
};

let operation = length(ARGV) ? ARGV[0] : '';
let target = ARGV[1];
let reboot_sent = false;

function now_ms() {
	let t = clock(true);
	return t[0] * 1000 + int(t[1] / 1000000);
}

let sweep_deadline = now_ms() + 38000;

function wait_event(sock, wanted, deadline) {
	let now = now_ms();
	let left = deadline - now;
	if (sweep_deadline - now < left)
		left = sweep_deadline - now;
	if (left <= 0)
		die('modem response timeout');
	let events = socket.poll(left, [sock, wanted]);
	if (events == null)
		die('socket poll failed');
	if (!length(events))
		die('modem response timeout');
	// POLLIN can accompany POLLHUP when the peer closes after a complete reply.
	// Consume that final readable data before treating hangup as an error.
	if (!(events[0][1] & wanted))
		die('modem connection closed');
}

function connect_modem(sock) {
	// Bind before connect so an overlapping LAN subnet cannot receive AT queries.
	if (!sock.setopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, DEVICE))
		die('cannot bind modem socket to wan');
	if (!sock.connect(HOST, PORT)) {
		// A nonblocking connect normally returns EINPROGRESS. SO_ERROR plus
		// peername also reject immediate errors without hardcoding Linux errno.
		wait_event(sock, socket.POLLOUT, now_ms() + IO_TIMEOUT);
		if (sock.getopt(socket.SOL_SOCKET, socket.SO_ERROR) !== 0 || !sock.peername())
			die('cannot connect to modem AT service');
	}
}

function query(sock, command, required, timeout) {
	let deadline = now_ms() + timeout;
	let request = command + '\r';
	let sent = 0;
	while (sent < length(request)) {
		wait_event(sock, socket.POLLOUT, deadline);
		let n = sock.send(substr(request, sent), socket.MSG_NOSIGNAL);
		if (n == null || n <= 0)
			die('cannot send modem query');
		sent += n;
	}
	if (command == 'AT+CFUN=1,1')
		reboot_sent = true;

	let response = '';
	while (true) {
		wait_event(sock, socket.POLLIN, deadline);
		let chunk = sock.recv(4096);
		if (chunk == null || chunk == '')
			die('incomplete modem response');
		if (index(chunk, '\x00') >= 0)
			die('binary data in modem response');
		response += replace(chunk, /\r/g, '');
		if (length(response) > MAX_REPLY)
			die('modem response exceeds size limit');
		// Match a full result line, even when it is split over TCP packets.
		let terminal = match(response, /(^|\n)(OK|ERROR|\+CME ERROR:[^\n]*|\+CMS ERROR:[^\n]*)\n/);
		if (terminal) {
			if (required && terminal[2] != 'OK')
				die('required modem query failed: ' + command);
			return command + '\n' + response + '\n';
		}
	}
}

let active = null;

function exchange(command, required, timeout) {
	active = socket.create(socket.AF_INET, socket.SOCK_STREAM | socket.SOCK_NONBLOCK);
	if (!active)
		die('cannot create modem socket');
	connect_modem(active);
	let response = query(active, command, required, timeout);
	active.close();
	active = null;
	return response;
}

function read_slot() {
	let response = exchange('AT^SCICHG?', true, CONTROL_TIMEOUT);
	let slot = null;
	let lines = split(response, '\n');
	for (let i = 0; i < length(lines); i++) {
		if (substr(lines[i], 0, 8) != '^SCICHG:')
			continue;
		let fields = match(lines[i], /^\^SCICHG:[ \t]*([01])[ \t]*,[ \t]*([01])[ \t]*$/);
		if (!fields || slot != null || fields[1] == fields[2])
			die('invalid or ambiguous SIM slot response');
		slot = fields[1] == '0' ? 'external' : 'internal';
	}
	if (slot == null)
		die('SIM slot missing from modem response');
	return slot;
}

let output = '';
let verified_slot = null;
try {
	if (length(ARGV) == 0) {
		for (let i = 0; i < length(COMMANDS); i++)
			output += exchange(COMMANDS[i][0], COMMANDS[i][1], IO_TIMEOUT);
	}
	else if (operation == '--slot' && length(ARGV) == 1) {
		output = read_slot() + '\n';
	}
	else if (operation == '--switch' && length(ARGV) == 2 &&
		(target == 'internal' || target == 'external')) {
		verified_slot = read_slot();
		if (verified_slot == target) {
			output = sprintf('%J\n', {
				state: 'already', target, slot: verified_slot, reboot: 'not-needed'
			});
		}
		else {
			exchange(SLOT_COMMANDS[target], true, CONTROL_TIMEOUT);
			exchange('AT^HVSST=1,0', true, CONTROL_TIMEOUT);
			exchange('AT^HVSST=1,1', true, CONTROL_TIMEOUT);
			verified_slot = read_slot();
			if (verified_slot != target)
				die('SIM slot read-back does not match requested target');
			exchange('AT+CFUN=1,1', true, CONTROL_TIMEOUT);
			// Acknowledgement precedes the actual modem reboot. The caller must
			// wait for the AT service to return and independently read --slot.
			output = sprintf('%J\n', {
				state: 'restarting', target, slot: verified_slot, reboot: 'acknowledged'
			});
		}
	}
	else
		die('usage: mt5700-ethernet.uc [--slot | --switch internal|external]');
}
catch (e) {
	if (active)
		active.close();
	let message = e.message || ('' + e);
	if (operation == '--switch' && reboot_sent && match(message,
		/(modem response timeout|modem connection closed|incomplete modem response)/)) {
		// Loss of transport after sending CFUN may mean the reset started;
		// it does not prove it did. Never turn this into a confirmed switch.
		output = sprintf('%J\n', {
			state: 'uncertain', target, slot: verified_slot, reboot: 'unconfirmed'
		});
	}
	else {
		warn('mt5700-ethernet: ' + message + '\n');
		exit(1);
	}
}
print(output);
