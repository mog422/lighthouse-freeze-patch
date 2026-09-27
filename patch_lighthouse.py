#!/usr/bin/env python3
"""
driver_lighthouse.dll (SteamVR, win64) "freeze universe" patcher.

Patches (default):
  P2  MoveBase: skip refinement of base poses that already have a pose-to-global
      ("Moving base %08X ... because of relationship with ..." never happens)
  P3  SetTilt : keep the universe tilt loaded from lighthousedb.json instead of
      recomputing it from the base station's blended tilt observation each session
Optional:
  --no-save   Save(): never write lighthousedb.json (freeze on disk)
  --no-tiltobs AddTiltObservation(): never blend new HMD tilt observations into a base

Usage:
  python3 patch_lighthouse.py <path\\to\\driver_lighthouse.dll> [--no-save] [--no-tiltobs] [--restore]
"""
import sys, os, shutil, hashlib, struct

ORIG_SHA256 = "5e477db767d07d9071317e2df124acecbee151329a5400d3ecdac5d4eb849c9a"

# (name, file_offset, original_bytes, patched_bytes)
PATCHES_DEFAULT = [
    ("P2 MoveBase both-global branch -> jmp epilogue (0x18005d32a)",
     0x5c72a, bytes.fromhex("f30f106e20"), bytes.fromhex("e995040000")),
    ("P3 SetTilt: NOP store of recomputed tilt pitch/roll (0x180063483)",
     0x62883, bytes.fromhex("f20f114638"), bytes.fromhex("9090909090")),
    ("P3 SetTilt: NOP store of recomputed tilt score (0x18006348b)",
     0x6288b, bytes.fromhex("894640"), bytes.fromhex("909090")),
]
PATCHES_NO_SAVE = [
    ("P4 CLighthouseDB::Save -> ret (0x180063bb0)",
     0x62fb0, bytes.fromhex("48895c2410"), bytes.fromhex("c390909090")),
]
PATCHES_NO_TILTOBS = [
    ("P1 AddTiltObservation -> ret (0x18005dfc0)",
     0x5d3c0, bytes.fromhex("48895c2418"), bytes.fromhex("c390909090")),
]

def sha256(b): return hashlib.sha256(b).hexdigest()

def fix_checksum(buf):
    """Recompute PE checksum in the optional header (harmless if wrong, but keep it tidy)."""
    pe_off = struct.unpack_from("<I", buf, 0x3c)[0]
    cs_off = pe_off + 4 + 20 + 64          # OptionalHeader.CheckSum (same offset for PE32/PE32+)
    buf[cs_off:cs_off+4] = b"\0\0\0\0"
    total = 0
    n = len(buf)
    for i in range(0, n - (n % 2), 2):
        total += struct.unpack_from("<H", buf, i)[0]
        total = (total & 0xffff) + (total >> 16)
    if n % 2: total += buf[-1]
    total = (total & 0xffff) + (total >> 16)
    total = (total + (total >> 16)) & 0xffff
    struct.pack_into("<I", buf, cs_off, (total + n) & 0xffffffff)

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if len(args) != 1:
        print(__doc__); sys.exit(2)
    path = args[0]
    bak = path + ".orig"
    if "--restore" in flags:
        if not os.path.exists(bak): print("no backup found:", bak); sys.exit(1)
        shutil.copy2(bak, path); print("restored from", bak); return

    buf = bytearray(open(path, "rb").read())
    h = sha256(buf)
    print(f"input sha256: {h}")
    patches = list(PATCHES_DEFAULT)
    if "--no-save" in flags: patches += PATCHES_NO_SAVE
    if "--no-tiltobs" in flags: patches += PATCHES_NO_TILTOBS

    # verify every site first (accept already-patched sites so re-running is idempotent)
    todo = []
    for name, off, orig, new in patches:
        cur = bytes(buf[off:off+len(orig)])
        if cur == orig: todo.append((name, off, orig, new))
        elif cur == new: print(f"already applied: {name}")
        else:
            print(f"MISMATCH at {off:#x} for {name}: found {cur.hex()} expected {orig.hex()}")
            print("This DLL is a different build; do not patch blindly. Aborting."); sys.exit(1)
    if h != ORIG_SHA256 and ORIG_SHA256 != "__ORIG_SHA256__" and not any(bytes(buf[o:o+len(n)])==n for _,o,_,n in patches):
        print("WARNING: sha256 differs from the analysed build, but all patch sites matched. Continuing.")
    if not todo:
        print("nothing to do"); return
    if not os.path.exists(bak):
        shutil.copy2(path, bak); print("backup written:", bak)
    for name, off, orig, new in todo:
        buf[off:off+len(new)] = new
        print(f"applied: {name}")
    fix_checksum(buf)
    open(path, "wb").write(buf)
    print(f"output sha256: {sha256(buf)}")
    print("done. Restart SteamVR. Check vrserver.txt for the absence of 'Moving base' lines.")

if __name__ == "__main__":
    main()
