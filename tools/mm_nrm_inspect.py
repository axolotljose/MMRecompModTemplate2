#!/usr/bin/env python3
"""mm_nrm_inspect.py - parse and print a Zelda64 Recompile mod (.nrm) file.

Reads the mod manifest (mod.json), the binary mod symbol file (N64RSYMS v1, see
N64Recomp's src/mod_symbols.cpp) and the mod binary, then reports:
  * every section's vram, rom size and bss size,
  * every function in the mod,
  * patches, exports, imports, hooks, events and callbacks,
  * every relocation and what it points at.

The build uses this to verify a produced .nrm without needing the game: the same
structures that the runtime's `parse_mod_symbols` walks are decoded here, so a
file that parses cleanly is a file the loader can also read.

Note: the symbol file is written by memcpy'ing host structs, so it is
little-endian (x86/ARM hosts).

Usage:
    python3 tools/mm_nrm_inspect.py build/mm_glacio_diana.nrm
    python3 tools/mm_nrm_inspect.py build/mm_glacio_diana.nrm --relocs --funcs
"""

from __future__ import annotations

import argparse
import json
import struct
import zipfile
from pathlib import Path

RELOC_NAMES = {
    0: "R_MIPS_NONE", 1: "R_MIPS_16", 2: "R_MIPS_32", 3: "R_MIPS_REL32", 4: "R_MIPS_26",
    5: "R_MIPS_HI16", 6: "R_MIPS_LO16", 7: "R_MIPS_GPREL16",
}
SECTION_SELF_FLAG = 0x80000000
SECTION_IMPORT_VROM = 0xFFFFFFFE
SECTION_EVENT_VROM = 0xFFFFFFFD
SECTION_ABSOLUTE = 0xFFFFFFFF
SECTION_REFERENCE_BASE = 0x10000  # reference sections are recorded by their game vrom


class Reader:
    def __init__(self, blob: bytes, offset=0):
        self.blob = blob
        self.off = offset

    def raw(self, count):
        if self.off + count > len(self.blob):
            raise ValueError("mod symbol file truncated")
        out = self.blob[self.off:self.off + count]
        self.off += count
        return out

    def u32(self):
        return struct.unpack("<I", self.raw(4))[0]

    def u8(self):
        return self.raw(1)[0]

    @property
    def remaining(self):
        return len(self.blob) - self.off


def parse_syms(blob: bytes):
    """Decode an N64RSYMS v1 mod symbol file into plain Python structures."""
    if blob[:8] != b"N64RSYMS":
        raise ValueError(f"bad mod symbol magic {blob[:8]!r}")
    version = struct.unpack_from("<I", blob, 8)[0]
    if version != 1:
        raise ValueError(f"unsupported symbol file version {version}")
    r = Reader(blob, 12)
    (num_sections, num_dependencies, num_imports, num_dependency_events, num_replacements,
     num_exports, num_callbacks, num_provided_events, num_hooks, string_data_size) = \
        struct.unpack("<10I", r.raw(40))
    strings = r.raw(string_data_size)
    out = {
        "version": version,
        "strings": strings,
        "sections": [],
        "dependencies": [],
        "imports": [],
        "dependency_events": [],
        "replacements": [],
        "exports": [],
        "callbacks": [],
        "events": [],
        "hooks": [],
    }
    for _ in range(num_sections):
        flags, file_offset, vram, rom_size, bss_size, num_funcs, num_relocs = struct.unpack("<7I", r.raw(28))
        funcs = [struct.unpack("<2I", r.raw(8)) for _ in range(num_funcs)]
        relocs = [struct.unpack("<4I", r.raw(16)) for _ in range(num_relocs)]
        out["sections"].append({"flags": flags, "file_offset": file_offset, "vram": vram,
                                "rom_size": rom_size, "bss_size": bss_size, "funcs": funcs,
                                "relocs": relocs})
    for _ in range(num_dependencies):
        # DependencyV1 is { bool reserved/padding (4 bytes), char* name (start, size) }, so the
        # leading 4 bytes are kept verbatim: the writer needs them to reproduce a file byte for byte.
        prefix = r.raw(4)
        dep = struct.unpack("<2I", r.raw(8))
        out["dependencies"].append((prefix, dep[0], dep[1]))
    for _ in range(num_imports):
        out["imports"].append(struct.unpack("<3I", r.raw(12)))
    for _ in range(num_dependency_events):
        out["dependency_events"].append(struct.unpack("<3I", r.raw(12)))
    for _ in range(num_replacements):
        out["replacements"].append(struct.unpack("<4I", r.raw(16)))
    for _ in range(num_exports):
        out["exports"].append(struct.unpack("<3I", r.raw(12)))
    for _ in range(num_callbacks):
        out["callbacks"].append(struct.unpack("<2I", r.raw(8)))
    for _ in range(num_provided_events):
        out["events"].append(struct.unpack("<2I", r.raw(8)))
    for _ in range(num_hooks):
        out["hooks"].append(struct.unpack("<4I", r.raw(16)))
    out["trailing_bytes"] = r.remaining
    return out


def name_of(strings, start, size):
    return strings[start:start + size].decode("utf-8", "replace")


def load_nrm(path):
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        manifest = json.loads(zf.read("mod.json").decode("utf-8"))
        syms = parse_syms(zf.read("mod_syms.bin"))
        binary = zf.read("mod_binary.bin") if "mod_binary.bin" in names else b""
    return manifest, syms, binary, names


def describe_reloc(syms, section, reloc):
    off, type_, target, vrom = reloc
    addr = section["vram"] + off
    if vrom == SECTION_IMPORT_VROM:
        detail = f"import symbol #{target}"
        if target < len(syms["imports"]):
            start, size, _dep = syms["imports"][target]
            detail += f" ({name_of(syms['strings'], start, size)})"
    elif vrom == SECTION_EVENT_VROM:
        detail = f"event symbol #{target}"
        if target < len(syms["events"]):
            start, size = syms["events"][target]
            detail += f" ({name_of(syms['strings'], start, size)})"
    elif vrom & SECTION_SELF_FLAG:
        idx = vrom & ~SECTION_SELF_FLAG
        detail = f"mod section {idx} + {target:#x}"
    else:
        detail = f"reference/game section vrom {vrom:#x} + {target:#x}"
    return f"{addr:#010x} {RELOC_NAMES.get(type_, type_):<13} {detail}"


def main():
    ap = argparse.ArgumentParser(description="inspect a Zelda64 recompress .nrm mod file")
    ap.add_argument("nrm")
    ap.add_argument("--relocs", action="store_true", help="dump every relocation")
    ap.add_argument("--funcs", action="store_true", help="dump every function")
    ap.add_argument("--manifest", action="store_true", help="print the raw manifest json")
    args = ap.parse_args()

    path = Path(args.nrm)
    manifest, syms, binary, names = load_nrm(path)
    strings = syms["strings"]

    print(f"=== {path.name} ===")
    print(f"zip entries: {', '.join(names)}")
    print(f"mod binary: {len(binary)} bytes; symbol file trailing bytes: {syms['trailing_bytes']}")
    print("--- manifest")
    for key, value in manifest.items():
        if key == "config_schema":
            opts = value.get("options", [])
            print(f"  config_schema options: {', '.join(o.get('id', '?') for o in opts)}")
        elif key == "description":
            print(f"  description: {str(value).strip()[:110]}...")
        else:
            print(f"  {key}: {value}")

    print("--- sections")
    for i, sec in enumerate(syms["sections"]):
        print(f"  [{i}] vram={sec['vram']:#010x} file_offset={sec['file_offset']:#x} "
              f"rom={sec['rom_size']:#x} bss={sec['bss_size']:#x} funcs={len(sec['funcs'])} "
              f"relocs={len(sec['relocs'])} flags={sec['flags']}")
        for j, (off, size) in enumerate(sec["funcs"]):
            if args.funcs or j < 3:
                print(f"        func[{j}] {sec['vram'] + off:#010x} size={size:#x}")
        if not args.funcs and len(sec["funcs"]) > 3:
            print(f"        ... {len(sec['funcs']) - 3} more functions")
    for title, items, fmt in [
        ("patches", syms["replacements"], lambda t: f"func #{t[0]} -> game section {t[1]} vram {t[2]:#010x} flags={t[3]}"),
        ("hooks", syms["hooks"], lambda t: f"func #{t[0]} on game section {t[1]} vram {t[2]:#010x} flags={t[3]}"),
        ("imports", syms["imports"], lambda t: f"{name_of(strings, t[0], t[1])!r} (dependency {t[2]})"),
        ("exports", syms["exports"], lambda t: f"{name_of(strings, t[1], t[2])!r} = func #{t[0]}"),
        ("provided events", syms["events"], lambda t: f"{name_of(strings, t[0], t[1])!r}"),
        ("callbacks", syms["callbacks"], lambda t: f"func #{t[1]} -> event #{t[0]}"),
        ("dependencies", syms["dependencies"], lambda t: f"{name_of(strings, t[0], t[1])!r}"),
    ]:
        print(f"--- {title} ({len(items)})")
        for item in items:
            print("  " + fmt(item))
    if args.relocs:
        for i, sec in enumerate(syms["sections"]):
            if not sec["relocs"]:
                continue
            print(f"--- relocations in section {i} ({len(sec['relocs'])})")
            for reloc in sec["relocs"]:
                print("  " + describe_reloc(syms, sec, reloc))
    if args.manifest:
        print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
