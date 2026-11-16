# Shared MAC validation & factory base-MAC helpers for NRadio NBCPE (WT9111).
# The factory data lives on eMMC (not MTD):
#   PARTLABEL=bdinfo  ASCII "fac_mac = XX:XX:..." near the partition head
#   PARTLABEL=factory MT7981 WiFi EEPROM (MAC at offset 0x4)
#   mmc CID           last-resort stable per-board source
# Rejects empty, all-zero, broadcast and multicast/group-bit MACs.

[ -f /lib/functions/system.sh ] && ! command -v macaddr_canonicalize >/dev/null 2>&1 && . /lib/functions/system.sh

nbcpe_canon_mac() {
	if command -v macaddr_canonicalize >/dev/null 2>&1; then
		macaddr_canonicalize "$1" 2>/dev/null
	else
		printf '%s\n' "$1" | tr 'A-F' 'a-f'
	fi
}

nbcpe_mac_is_valid_unicast() {
	local mac o1
	mac=$(nbcpe_canon_mac "$1")
	case "$mac" in
	[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]) ;;
	*) return 1 ;;
	esac
	case "$mac" in
	00:00:00:00:00:00|ff:ff:ff:ff:ff:ff)
		return 1
		;;
	esac
	o1="${mac%%:*}"
	[ "$(( 0x$o1 & 1 ))" -eq 0 ]
}

nbcpe_block_dev() {
	blkid -t "PARTLABEL=$1" -o device 2>/dev/null
}

nbcpe_get_base_mac() {
	local mac dev

	# 1. bdinfo partition (PARTLABEL=bdinfo): ASCII "fac_mac = XX:..." header
	dev=$(nbcpe_block_dev bdinfo)
	if [ -n "$dev" ] && [ -b "$dev" ]; then
		mac=$(dd if="$dev" bs=512 count=2 2>/dev/null |
			sed -n 's/.*fac_mac[ :=]*\([0-9a-fA-F:]\{17\}\).*/\1/p' | head -n 1)
		if nbcpe_mac_is_valid_unicast "$mac"; then
			nbcpe_canon_mac "$mac"
			return 0
		fi
	fi

	# 2. WiFi EEPROM on the factory partition (MTK eeprom MAC @ 0x4)
	dev=$(nbcpe_block_dev factory)
	if [ -n "$dev" ] && [ -b "$dev" ]; then
		mac=$(dd if="$dev" bs=1 skip=4 count=6 2>/dev/null |
			od -An -tx1 2>/dev/null | tr -d ' \n' |
			sed 's/../&:/g; s/:$//')
		if nbcpe_mac_is_valid_unicast "$mac"; then
			nbcpe_canon_mac "$mac"
			return 0
		fi
	fi

	# 3. Stable fallback derived from the eMMC CID
	mac=$(macaddr_generate_from_mmc_cid mmcblk0 2>/dev/null)
	if nbcpe_mac_is_valid_unicast "$mac"; then
		nbcpe_canon_mac "$mac"
		return 0
	fi

	return 1
}
