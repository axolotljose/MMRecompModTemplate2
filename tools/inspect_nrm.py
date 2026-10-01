#!/usr/bin/env python3
"""
Lists what a packaged mod (.nrm) asks the Zelda 64: Recompiled runtime for when it loads.

The build tool only checks that every name resolves. It cannot tell you what the *runtime* will have to do at load time, and
the expensive part is hooks: for every hooked game function the runtime has to regenerate that function from the ROM with its
live recompiler, and if that fails the mod does not load ("code mod loading internal error", with no mod id).
This script parses mod_syms.bin (format v1, see N64Recomp/src/mod_symbols.cpp) and prints the hooked functions by name.

    tools/inspect_nrm.py dist/lilith_lullaby_white_rose.nrm [path/to/mm.us.rev1.syms.toml] [--allow-hooks Name,Name,...]

With the symbol file the hooks are shown by name, otherwise by address.

--allow-hooks makes the script fail (exit status 1) if the mod hooks any game function that is not in the list. tools/build_linux.sh
uses it so that adding a hook is a conscious decision: a first version of this mod hooked five functions and, in the game, one of
them (most likely the EnTest7 overlay function, the only one no shipping mod hooks) could not be regenerated, which stopped the
whole mod from loading. Exit status is also 1 if the file cannot be parsed.
"""
import re
import struct
import sys
import zipfile


def parse(syms: bytes):
    if syms[:8] != b"N64RSYMS":
        raise ValueError("not an N64Recomp mod symbol file (bad magic)")
    version = struct.unpack_from("<I", syms, 8)[0]
    if version != 1:
        raise ValueError(f"unsupported mod symbol file version {version}")
    off = 12
    names = ("sections", "dependencies", "imports", "dep_events", "replacements", "exports", "callbacks", "events", "hooks",
             "string_size")
    counts = dict(zip(names, struct.unpack_from("<10I", syms, off)))
    off += 40
    strings = syms[off:off + counts["string_size"]]
    off += counts["string_size"]

    def text(start, size):
        return strings[start:start + size].decode()

    sections = []
    for _ in range(counts["sections"]):
        flags, file_off, vram, rom_size, bss, nfuncs, nrelocs = struct.unpack_from("<7I", syms, off)
        off += 28 + 8 * nfuncs + 16 * nrelocs
        sections.append(dict(vram=vram, rom_size=rom_size, funcs=nfuncs, relocs=nrelocs))

    def table(fmt, count):
        nonlocal off
        size = struct.calcsize(fmt)
        rows = [struct.unpack_from(fmt, syms, off + i * size) for i in range(count)]
        off += size * count
        return rows

    # DependencyV1 is { u8 reserved; u32 start; u32 size } and the compiler pads it to 12 bytes.
    deps = [text(s, n) for (_, s, n) in table("<III", counts["dependencies"])]
    imports = [(text(s, n), deps[d]) for (s, n, d) in table("<III", counts["imports"])]
    dep_events = [(text(s, n), deps[d]) for (s, n, d) in table("<III", counts["dep_events"])]
    replacements = table("<IIII", counts["replacements"])
    exports = [text(s, n) for (_, s, n) in table("<III", counts["exports"])]
    callbacks = [dep_events[e] for (e, _) in table("<II", counts["callbacks"])]
    provided = [text(s, n) for (s, n) in table("<II", counts["events"])]
    hooks = [dict(rom=r, vram=v, at_return=bool(f & 1)) for (_, r, v, f) in table("<IIII", counts["hooks"])]
    return dict(sections=sections, deps=deps, imports=imports, events_used=callbacks, replacements=replacements,
                exports=exports, provided_events=provided, hooks=hooks, counts=counts)


def load_symbol_names(path):
    """vram -> function name for the game's symbol file (overlay vrams repeat across overlays, keyed with the section rom too)."""
    names = {}
    text = open(path, newline="").read().replace("\r", "")
    for block in text.split("[[section]]")[1:]:
        rom = re.search(r"^\s*rom = (0x[0-9A-Fa-f]+)", block, re.M)
        if not rom:
            continue
        rom = int(rom.group(1), 16)
        for m in re.finditer(r'name = "([^"]+)", vram = (0x[0-9A-Fa-f]+)', block):
            names[(rom, int(m.group(2), 16))] = m.group(1)
    return names


def main():
    args = sys.argv[1:]
    allowed = None
    if "--allow-hooks" in args:
        i = args.index("--allow-hooks")
        if i + 1 >= len(args):
            print("error: --allow-hooks needs a comma separated list", file=sys.stderr)
            return 2
        allowed = {n for n in args[i + 1].split(",") if n}
        del args[i:i + 2]
    if not args:
        print(__doc__)
        return 2
    nrm = args[0]
    if allowed is not None and len(args) < 2:
        print("error: --allow-hooks needs the symbol file too, to turn hook addresses into names", file=sys.stderr)
        return 2
    with zipfile.ZipFile(nrm) as z:
        syms = z.read("mod_syms.bin")
    info = parse(syms)
    names = load_symbol_names(args[1]) if len(args) > 1 else {}

    print(f"{nrm}: mod_syms.bin v1, {info['counts']['sections']} section(s), "
          f"{sum(s['funcs'] for s in info['sections'])} functions")
    print(f"\nGame functions the runtime must REGENERATE from the ROM to hook them ({len(info['hooks'])} hook(s)):")
    if not info["hooks"]:
        print("    none: nothing is regenerated at load time")
    for h in sorted(info["hooks"], key=lambda h: (h["rom"], h["vram"], h["at_return"])):
        name = names.get((h["rom"], h["vram"]), "?")
        print(f"    {'return' if h['at_return'] else 'entry ':6}  {name:<28} vram 0x{h['vram']:08X}  section rom 0x{h['rom']:08X}")
    print(f"\nEvents it listens to ({len(info['events_used'])}), resolved by the base game, no code regeneration:")
    for ev, dep in info["events_used"]:
        print(f"    {ev}  (from '{dep}')")
    print(f"\nImports ({len(info['imports'])}): " + (", ".join(f"{n} (from '{d}')" for n, d in info["imports"]) or "none"))
    print(f"Function replacements/patches: {len(info['replacements'])}   Exports: {len(info['exports'])}   "
          f"Mod dependencies: {[d for d in info['deps'] if d not in ('*', '.')] or 'none'}")

    if allowed is not None:
        hooked = {names.get((h["rom"], h["vram"]), f"0x{h['vram']:08X}") for h in info["hooks"]}
        unexpected = sorted(hooked - allowed)
        if unexpected:
            print(f"\nERROR: the mod hooks game functions that are not on the allowed list: {', '.join(unexpected)}\n"
                  f"  Every hooked function has to be regenerated from the ROM when the mod loads, and if one cannot be the whole\n"
                  f"  mod fails with 'code mod loading internal error'. Prefer an event the game raises (recomp_on_play_init,\n"
                  f"  recomp_after_play_update, ...). If you really need the hook, add it to LIL_ALLOWED_HOOKS in tools/build_linux.sh\n"
                  f"  and test it in the game.", file=sys.stderr)
            return 1
        print(f"\nHook check: OK (hooks only {', '.join(sorted(hooked)) or 'nothing'}).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, struct.error, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
