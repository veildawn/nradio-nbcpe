#!/usr/bin/env python3
"""Dump NRADIO NBCPE (WT9111) eMMC partitions via FileBrowser raw API.

Reads block devices /dev/mmcblk0[pN] in Range chunks (resumable).
Skips p9 (user-data partition) by default; also saves the GPT header
(first 1 MiB of /dev/mmcblk0) so the layout can be restored.
"""
import http.client
import json
import os
import sys
import time
import urllib.request

ROUTER = "192.168.10.1"
FB_PORT = 8989
TOKEN_FILE = "nradio-backup/fb_login_resp.txt"
OUT_DIR = "nradio-backup/firmware"
CHUNK = 4 * 1024 * 1024  # 4 MiB per request

# name -> size in bytes (from sysfs, sector = 512B)
PARTS = {
    "gpt":      ("dev/mmcblk0", 1 * 1024 * 1024),        # protective MBR + GPT
    "mmcblk0p1": ("dev/mmcblk0p1", 34 * 512),
    "mmcblk0p2": ("dev/mmcblk0p2", 1024 * 512),
    "mmcblk0p3": ("dev/mmcblk0p3", 2048 * 512),
    "mmcblk0p4": ("dev/mmcblk0p4", 2048 * 512),
    "mmcblk0p5": ("dev/mmcblk0p5", 4096 * 512),
    "mmcblk0p6": ("dev/mmcblk0p6", 65536 * 512),
    "mmcblk0p7": ("dev/mmcblk0p7", 524288 * 512),
    "mmcblk0p8": ("dev/mmcblk0p8", 262144 * 512),
    "mmcblk0p10": ("dev/mmcblk0p10", 524288 * 512),
    # p9 (user data, 6715 MB) intentionally skipped
}

token = open(TOKEN_FILE).read().strip().strip('"')


def fetch_range(path: str, start: int, end: int, retries: int = 5):
    """Fetch one byte range from FileBrowser raw API."""
    url = f"http://{ROUTER}:{FB_PORT}/api/raw/{path}"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"X-Auth": token, "Range": f"bytes={start}-{end}"})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
                if len(data) == end - start + 1:
                    return data
                # short read: retry the missing tail
                if len(data) > 0:
                    rest = fetch_range(path, start + len(data), end, retries)
                    return data + rest if rest else None
        except Exception as e:
            print(f"    retry {attempt+1} @{start}: {e}", file=sys.stderr)
            time.sleep(1.5 * (attempt + 1))
    return None


def dump(name: str, path: str, size: int) -> bool:
    out = os.path.join(OUT_DIR, f"{name}.bin")
    done = 0
    if os.path.exists(out):
        done = os.path.getsize(out)
        if done >= size:
            print(f"[skip] {name} already complete ({done} bytes)")
            return True
        print(f"[resume] {name} from offset {done}")
    mode = "ab" if done else "wb"
    t0 = time.time()
    with open(out, mode) as f:
        while done < size:
            end = min(done + CHUNK, size) - 1
            data = fetch_range(path, done, end)
            if data is None:
                print(f"[FAIL] {name} @{done}", file=sys.stderr)
                return False
            f.write(data)
            done += len(data)
            rate = done / max(time.time() - t0, 0.1) / 1024 / 1024
            print(f"  {name}: {done}/{size} bytes ({rate:.1f} MB/s)", flush=True)
    print(f"[ok] {name}: {done} bytes saved")
    return True


def login():
    body = json.dumps({"username": "admin", "password": "admin"}).encode()
    req = urllib.request.Request(
        f"http://{ROUTER}:{FB_PORT}/api/login", data=body,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        tok = r.read().decode().strip().strip('"')
    open(TOKEN_FILE, "w").write(tok)
    return tok


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    # refresh token first (they expire)
    global token
    token = login()
    print(f"token refreshed: {token[:25]}...")
    only = sys.argv[1:] or list(PARTS)
    ok = True
    for name in only:
        path, size = PARTS[name]
        ok = dump(name, path, size) and ok
    print("ALL DONE" if ok else "FINISHED WITH ERRORS")


if __name__ == "__main__":
    main()
