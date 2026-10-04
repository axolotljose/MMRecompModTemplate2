#!/usr/bin/env python3
"""mm_nrm_pack.py - assemble a loadable .nrm from a linked mod ELF, with no external tool.

A Zelda64: Recompiled code mod is a zip holding `mod.json` (the manifest), `mod_syms.bin` (the mod
symbol file the loader parses first) and `mod_binary.bin` (the MIPS image), plus optional extra files
such as the thumbnail. Upstream `RecompModTool` produces these from a linked ELF; this script does the
same job so the template has no prebuilt-binary dependency, which matters because that binary is a
GitHub release asset and release-asset downloads are not always reachable from a build sandbox.

Every byte-level rule here mirrors `N64Recomp/src/mod_symbols.cpp` (the v1 format the loader reads) and
the collection pass in `N64Recomp/RecompModTool/main.cpp`:

  * header is `N64RSYMS`, version 1, then ten u32 counts, then the string table, then the records;
  * a mod section record is (flags, file_offset, vram, rom_size, bss_size, num_funcs, num_relocs) and
    is followed by its function table ((offset, size) u32 pairs) and its relocation table
    ((offset, type, target, vrom) u32 quadruples);
  * the string table is the names concatenated with a single trailing NUL, and names are referenced by
    (start, size), so the NUL is cosmetic;
  * dependencies are (4 bytes of reserved/padding, name_start, name_size);
  * imports are (name_start, name_size, dependency_index) and their call sites carry a relocation of
    vrom 0xFFFFFFFE whose target is the import index - import sections themselves contribute no
    functions and no relocations, because their thunks are dummy code;
  * self relocations use vrom 0x80000000 | section_index with target = offset inside that section, so
    the loader can rebase the image wherever it landed;
  * a hook record is (func_index, game_section_vrom, game_vram, flags) where func_index points at the
    hook function inside the mod's own function table.

`--elf`/`--meta` are the normal path: the linker emits both the image and the records
(`mm_mips_link.py --pack-json`), because only the linker knows how each relocation was resolved.

Self-test (run by `make check`):

    python3 tools/mm_nrm_pack.py --selftest release/mm_recomp_glacio_village.nrm <other.nrm>...

which parses a real, loader-accepted package, re-serialises it and requires the bytes to be identical.
That is what makes this trustworthy as a substitute for the upstream tool.

Usage:
    mm_nrm_pack.py --elf build/mod.elf --meta build/mod.pack.json --mod-toml mod.toml \
                   --out build/mod.nrm --extra thumb.png=assets/thumb.png
    mm_nrm_pack.py --manifest-from-toml mod.toml [-o build/mod.json]
    mm_nrm_pack.py --selftest file.nrm [file.nrm ...]
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mm_nrm_inspect import parse_syms  # noqa: E402

MAGIC = b"N64RSYMS"
SELF_SECTION_FLAG = 0x80000000
IMPORT_VROM = 0xFFFFFFFE

# Manifest keys that pass straight from [manifest] into mod.json.
MANIFEST_KEYS = ("id", "version", "display_name", "description", "short_description", "game_id",
                 "minimum_recomp_version")


def build_string_table(names):
    """Concatenate names, one trailing NUL, and return (blob, offset-per-name)."""
    blob = bytearray()
    offsets = []
    for name in names:
        offsets.append(len(blob))
        blob += name.encode("utf-8")
    if names:
        blob += b"\x00"
    return bytes(blob), offsets


def write_syms(syms):
    """Serialise the structure mm_nrm_inspect.parse_syms produces, byte for byte."""
    deps = syms.get("dependencies", [])
    imports = syms.get("imports", [])
    dep_events = syms.get("dependency_events", [])
    replacements = syms.get("replacements", [])
    exports = syms.get("exports", [])
    callbacks = syms.get("callbacks", [])
    events = syms.get("events", [])
    hooks = syms.get("hooks", [])
    sections = syms.get("sections", [])
    strings = syms.get("strings", b"")

    out = bytearray()
    out += MAGIC
    out += struct.pack("<I", syms.get("version", 1))
    out += struct.pack("<10I", len(sections), len(deps), len(imports), len(dep_events),
                       len(replacements), len(exports), len(callbacks), len(events), len(hooks),
                       len(strings))
    out += strings
    for sec in sections:
        out += struct.pack("<7I", sec["flags"], sec["file_offset"], sec["vram"], sec["rom_size"],
                           sec["bss_size"], len(sec["funcs"]), len(sec["relocs"]))
        for func in sec["funcs"]:
            out += struct.pack("<2I", func[0], func[1])
        for reloc in sec["relocs"]:
            out += struct.pack("<4I", *reloc[:4])
    for dep in deps:
        # (reserved bytes, name_start, name_size); a file parsed by parse_syms always carries the
        # reserved bytes verbatim, so round-tripping a real package is exact.
        if len(dep) == 3 and isinstance(dep[0], (bytes, bytearray)):
            out += dep[0] + struct.pack("<2I", dep[1], dep[2])
        else:  # synthesised by syms_from_meta: no reserved value to preserve
            out += struct.pack("<I", 0) + struct.pack("<2I", dep[1], dep[2])
    for imp in imports:
        out += struct.pack("<3I", *imp[:3])
    for ev in dep_events:
        out += struct.pack("<3I", *ev[:3])
    for rep in replacements:
        out += struct.pack("<4I", *rep[:4])
    for exp in exports:
        out += struct.pack("<3I", *exp[:3])
    for cb in callbacks:
        out += struct.pack("<2I", *cb[:2])
    for ev in events:
        out += struct.pack("<2I", *ev[:2])
    for hook in hooks:
        out += struct.pack("<4I", *hook[:4])
    out += b"\x00" * int(syms.get("trailing_bytes", 0))
    return bytes(out)


def syms_from_meta(meta):
    """Turn the linker's --pack-json records into the structure write_syms expects."""
    dep_names = list(meta["deps"])
    import_names = [name for name, _dep in meta["imports"]]
    strings, offsets = build_string_table(dep_names + import_names)

    deps = [(0, offsets[i], len(name)) for i, name in enumerate(dep_names)]
    dep_index = {name: i for i, name in enumerate(dep_names)}
    imports = []
    for j, (name, dep) in enumerate(meta["imports"]):
        idx = dep_index.get(dep)
        if idx is None:
            raise SystemExit(f"error: import {name} depends on unregistered dependency {dep}")
        imports.append((offsets[len(dep_names) + j], len(name.encode()), idx))

    sections = [{
        "flags": 0,
        "file_offset": 0,
        "vram": meta["image_base"],
        "rom_size": meta["rom_size"],
        "bss_size": meta["bss_size"],
        "funcs": [tuple(f) for f in meta["funcs"]],
        "relocs": [tuple(r) for r in meta["relocs"]],
    }]
    return {
        "version": 1,
        "strings": strings,
        "sections": sections,
        "dependencies": deps,
        "imports": imports,
        "dependency_events": [],
        "replacements": [],
        "exports": [],
        "callbacks": [],
        "events": [],
        "hooks": [tuple(h) for h in meta["hooks"]],
        "trailing_bytes": 0,
    }


def manifest_from_toml(path):
    """[manifest] -> mod.json bytes. The upstream tool copies the table through, so this does too.

    `inputs` (elf path, symbol files, additional files) and `dependencies`' build-time parts are
    deliberately not copied: the loader's own `mod.json` schema has no such fields, and dependency
    names reach the package through the symbol file instead.
    """
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - py<3.11
        raise SystemExit("error: packaging from mod.toml needs Python 3.11+ (tomllib); "
                         "or pass --mod-json with a manifest you already have")
    data = tomllib.loads(Path(path).read_text(errors="replace"))
    manifest = data.get("manifest", {})
    out = {}
    for key in MANIFEST_KEYS:
        if key in manifest:
            out[key] = manifest[key]
    if "authors" in manifest:
        authors = manifest["authors"]
        out["authors"] = authors if isinstance(authors, list) else [authors]
    options = manifest.get("config_options") or []
    if options:
        out["config_schema"] = {"options": [dict(option) for option in options]}
    missing = [k for k in ("id", "version", "display_name", "description") if k not in out]
    if missing:
        raise SystemExit(f"error: mod.toml [manifest] is missing required field(s): {', '.join(missing)}")
    return (json.dumps(out, indent=4, sort_keys=True) + "\n").encode("utf-8")


def pack(elf_path, meta_path, out_path, manifest_bytes, extras, dump_dir=None):
    meta = json.loads(Path(meta_path).read_text())
    syms_bytes = write_syms(syms_from_meta(meta))
    elf = Path(elf_path).read_bytes()
    start = meta["image_file_offset"]
    size = meta["rom_size"]
    binary = elf[start:start + size]
    if len(binary) != size:
        raise SystemExit(f"error: image slice {len(binary)} != rom_size {size} in {elf_path}")
    # A mod whose bss is not zero-filled in the file is fine (the loader allocates it), but a
    # truncated slice is not; catching it here beats a fault at boot.
    if size == 0:
        raise SystemExit("error: empty mod image")

    entries = [("mod_syms.bin", syms_bytes), ("mod_binary.bin", binary), ("mod.json", manifest_bytes)]
    for arcname, src in extras:
        entries.append((arcname, Path(src).read_bytes()))

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, blob in entries:
            zf.writestr(name, blob)
    if dump_dir:
        Path(dump_dir).mkdir(parents=True, exist_ok=True)
        for name, blob in entries:
            (Path(dump_dir) / name).write_bytes(blob)
    counts = struct.unpack_from("<10I", syms_bytes, 12)
    print(f"{out_path.name}: {out_path.stat().st_size} bytes, "
          f"{counts[0]} section(s), {counts[0] and meta['funcs'] and len(meta['funcs']) or 0} function(s), "
          f"{len(meta['relocs'])} relocation(s), {counts[8]} hook(s), {counts[2]} import(s), "
          f"image {size:#x} + bss {meta['bss_size']:#x} at {meta['image_base']:#x}")
    return 0


def selftest(paths):
    """Parse a real package's symbol file and require our writer to reproduce it byte for byte."""
    failed = 0
    for path in paths:
        path = Path(path)
        if not path.is_file():
            print(f"skip {path}: not found")
            continue
        try:
            with zipfile.ZipFile(path) as zf:
                blob = zf.read("mod_syms.bin")
        except (KeyError, zipfile.BadZipFile) as exc:
            print(f"FAIL {path.name}: cannot read mod_syms.bin ({exc})")
            failed += 1
            continue
        syms = parse_syms(blob)
        again = write_syms(syms)
        if again == blob:
            print(f"pass {path.name}: {len(blob)} bytes round-trip exactly "
                  f"({len(syms['sections'])} section(s), {len(syms['hooks'])} hook(s), "
                  f"{len(syms['imports'])} import(s))")
        else:
            first = next(i for i in range(max(len(again), len(blob))) if again[i:i + 1] != blob[i:i + 1])
            print(f"FAIL {path.name}: differs at byte {first} (wrote {len(again)}, original {len(blob)})")
            failed += 1
    return 1 if failed else 0


def main():
    ap = argparse.ArgumentParser(description="assemble a .nrm from a linked mod (no external tool)")
    ap.add_argument("--elf", help="linked mod ELF (mm_mips_link.py output)")
    ap.add_argument("--meta", help="packaging records written by mm_mips_link.py --pack-json")
    ap.add_argument("--out", help=".nrm to write")
    ap.add_argument("--mod-toml", help="generate the manifest from this mod.toml")
    ap.add_argument("--mod-json", help="use these manifest bytes instead of generating them")
    ap.add_argument("--extra", action="append", default=[],
                    help="arcname=source for additional files (e.g. thumb.png=assets/thumb.png)")
    ap.add_argument("--dump-dir", help="also write mod.json/mod_syms.bin/mod_binary.bin here")
    ap.add_argument("--manifest-from-toml", help="only convert a mod.toml to mod.json")
    ap.add_argument("-o", "--output", help="output path for --manifest-from-toml (default stdout)")
    ap.add_argument("--compare", help="with --manifest-from-toml: a .nrm whose mod.json must be equal")
    ap.add_argument("--selftest", nargs="+", metavar="NRM",
                    help="round-trip these real .nrm files through parse+write and require byte equality")
    args = ap.parse_args()

    if args.selftest:
        return selftest(args.selftest)

    if args.manifest_from_toml:
        blob = manifest_from_toml(args.manifest_from_toml)
        if args.compare:
            with zipfile.ZipFile(args.compare) as zf:
                other = json.loads(zf.read("mod.json").decode("utf-8"))
            mine = json.loads(blob.decode("utf-8"))
            if mine != other:
                diff = [k for k in set(list(mine) + list(other)) if mine.get(k) != other.get(k)]
                print(f"FAIL manifest differs from {args.compare} in: {', '.join(sorted(diff))}")
                return 1
            print(f"pass manifest generated from {args.manifest_from_toml} matches the one in "
                  f"{args.compare}")
        if args.output:
            Path(args.output).write_bytes(blob)
        else:
            sys.stdout.write(blob.decode("utf-8"))
        return 0

    for required in ("elf", "meta", "out"):
        if not getattr(args, required):
            ap.error(f"--{required} is required when packing (or use --selftest/--manifest-from-toml)")
    if args.mod_json:
        manifest_bytes = Path(args.mod_json).read_bytes()
    elif args.mod_toml:
        manifest_bytes = manifest_from_toml(args.mod_toml)
    else:
        ap.error("pass --mod-toml (to generate the manifest) or --mod-json (to use one as-is)")
    extras = []
    for spec in args.extra:
        if "=" not in spec:
            ap.error(f"--extra expects arcname=path, got {spec}")
        arc, src = spec.split("=", 1)
        extras.append((arc, src))
    return pack(args.elf, args.meta, args.out, manifest_bytes, extras, args.dump_dir)


if __name__ == "__main__":
    sys.exit(main())
