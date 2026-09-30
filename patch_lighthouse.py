#!/usr/bin/env python3
"""
driver_lighthouse.dll (SteamVR, win64) "freeze universe" patcher.

Patches (default):
  P2  MoveBase: skip refinement of base poses that already have a pose-to-global
      ("Moving base %08X ... because of relationship with ..." never happens)
  P3  SetTilt : keep the universe tilt loaded from lighthousedb.json instead of
      recomputing it from the base station's blended tilt observation each session
Optional:
  --no-save    Save(): never write lighthousedb.json (freeze on disk)
  --no-tiltobs AddTiltObservation(): never blend new HMD tilt observations into a base
  --restore    copy the .orig backup back over the DLL

Usage:
  python3 patch_lighthouse.py <path\\to\\driver_lighthouse.dll> [--no-save] [--no-tiltobs] [--restore]

The build is detected by sha256, or, failing that, by checking that every patch site of a
known build holds either its original or its patched bytes. Unknown builds are refused
"""
import sys, os, shutil, hashlib, struct

DESC = {
    "P2":  "MoveBase: both-bases-global refinement branch -> jmp to epilogue",
    "P3a": "SetTilt: NOP store of recomputed tilt pitch/roll",
    "P3b": "SetTilt: NOP store of recomputed tilt score",
    "P4":  "CLighthouseDB::Save -> ret",
    "P1":  "AddTiltObservation -> ret",
}
DEFAULT_IDS = ["P2", "P3a", "P3b"]

# patches: id -> (file_offset, original_hex, patched_hex)
BUILDS = [
    {
        "label": "driver_lighthouse.dll, build shipped 2026-09-16 (driver_lighthouse_20260916.dll)",
        "sha256": "eb6545c837f9d8bc780499a08e201636a1155bad58ea5206daa02830e85b1e36",
        "patches": {
            "P2":  (0x5c5ea, "f30f106e20", "e995040000"),  # VA 0x18005d1ea -> jmp 0x18005d684
            "P3a": (0x62743, "f20f114638", "9090909090"),  # VA 0x180063343
            "P3b": (0x6274b, "894640",     "909090"),      # VA 0x18006334b
            "P4":  (0x62e70, "48895c2410", "c390909090"),  # VA 0x180063a70
            "P1":  (0x5d280, "48895c2418", "c390909090"),  # VA 0x18005de80
        },
    },
    {
        "label": "driver_lighthouse.dll, build shipped 2026-09-13",
        "sha256": "5e477db767d07d9071317e2df124acecbee151329a5400d3ecdac5d4eb849c9a",
        "patches": {
            "P2":  (0x5c72a, "f30f106e20", "e995040000"),  # VA 0x18005d32a -> jmp 0x18005d7c4
            "P3a": (0x62883, "f20f114638", "9090909090"),  # VA 0x180063483
            "P3b": (0x6288b, "894640",     "909090"),      # VA 0x18006348b
            "P4":  (0x62fb0, "48895c2410", "c390909090"),  # VA 0x180063bb0
            "P1":  (0x5d3c0, "48895c2418", "c390909090"),  # VA 0x18005dfc0
        },
    },
]

def sha256(b): return hashlib.sha256(b).hexdigest()

def fix_checksum(buf):
    """Recompute the PE optional-header checksum (Windows ignores it for user DLLs, but keep it valid)."""
    pe_off = struct.unpack_from("<I", buf, 0x3c)[0]
    cs_off = pe_off + 4 + 20 + 64
    buf[cs_off:cs_off+4] = b"\0\0\0\0"
    total, n = 0, len(buf)
    for i in range(0, n - (n % 2), 2):
        total += struct.unpack_from("<H", buf, i)[0]
        total = (total & 0xffff) + (total >> 16)
    if n % 2: total += buf[-1]
    total = (total & 0xffff) + (total >> 16)
    total = (total + (total >> 16)) & 0xffff
    struct.pack_into("<I", buf, cs_off, (total + n) & 0xffffffff)

def site_state(buf, off, orig, new):
    cur = bytes(buf[off:off+len(orig)])
    return "orig" if cur == orig else "patched" if cur == new else cur.hex()

def detect_build(buf, h):
    for b in BUILDS:
        if b["sha256"] == h:
            return b, "sha256 match"
    cands = [b for b in BUILDS
             if all(site_state(buf, off, bytes.fromhex(o), bytes.fromhex(n)) in ("orig", "patched")
                    for off, o, n in b["patches"].values())]
    if len(cands) == 1:
        return cands[0], "all patch sites match (already patched, or an identical layout)"
    if not cands:
        print("Unknown build: sha256", h)
        print("No known build's patch sites match. Re-derive the offsets (see PATCH_NOTES.md) before patching.")
    else:
        print("Ambiguous: several known builds match this file's patch sites. Refusing to guess.")
    sys.exit(1)

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    unknown = flags - {"--no-save", "--no-tiltobs", "--restore"}
    if len(args) != 1 or unknown:
        print(__doc__); sys.exit(2)
    path = args[0]
    bak = path + ".orig"
    if "--restore" in flags:
        if not os.path.exists(bak): print("no backup found:", bak); sys.exit(1)
        shutil.copy2(bak, path); print("restored from", bak); return

    buf = bytearray(open(path, "rb").read())
    h = sha256(buf)
    print(f"input sha256: {h}")
    build, how = detect_build(buf, h)
    print(f"build: {build['label']}  [{how}]")

    ids = list(DEFAULT_IDS)
    if "--no-save" in flags: ids.append("P4")
    if "--no-tiltobs" in flags: ids.append("P1")

    todo = []
    for pid in ids:
        off, o, n = build["patches"][pid]
        orig, new = bytes.fromhex(o), bytes.fromhex(n)
        st = site_state(buf, off, orig, new)
        if st == "orig": todo.append((pid, off, new))
        elif st == "patched": print(f"already applied: {pid} {DESC[pid]}")
        else:
            print(f"MISMATCH at {off:#x} for {pid}: found {st} expected {o}. Aborting."); sys.exit(1)
    if not todo:
        print("nothing to do"); return
    if not os.path.exists(bak):
        shutil.copy2(path, bak); print("backup written:", bak)
    for pid, off, new in todo:
        buf[off:off+len(new)] = new
        print(f"applied: {pid} {DESC[pid]} @ {off:#x}")
    fix_checksum(buf)
    open(path, "wb").write(buf)
    print(f"output sha256: {sha256(buf)}")
    print("done. Restart SteamVR and check vrserver.txt: no 'Moving base' lines, identical 'Setting universe tilt' values each session.")

if __name__ == "__main__":
    main()
