#!/usr/bin/env python3
"""Audit a packaged .nrm mod for load-time failures, especially on the Android port of
Zelda 64: Recompiled.

    python3 tools/check_mod.py build/mm_recomp_glacio_village.nrm
    python3 tools/check_mod.py mod.toml build/mod.nrm --strict

The checks are ordered by how likely they are to make a mod *refuse to load* (as opposed to
misbehave once loaded), because that is the failure mode people hit when moving a PC mod to the
mobile port: the loader prints nothing and the mod simply never appears as enabled.

Exit status: 0 clean, 1 on any FAIL, and with --strict also on any WARN.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import struct
import sys
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from mm_nrm_inspect import RELOC_NAMES, load_nrm, name_of  # noqa: E402

# The runtime version bundled with the Android port (linkzenic/Zelda64Recomp-Android pins
# linkzenic/N64ModernRuntime at this version). A mod asking for anything newer is refused by
# librecomp/src/mods.cpp without a visible error, which looks exactly like a broken mod.
ANDROID_RUNTIME_VERSION = (1, 2, 2)

# Base API functions the mobile port registers for every mod (harvested from
# N64ModernRuntime/librecomp/src/mod_config_api.cpp and the port's own overlay registrations).
# Anything outside this set that a mod imports has to be provided by a dependency mod instead.
KNOWN_BASE_IMPORTS = {
    "recomp_alloc",
    "recomp_free",
    "recomp_printf",
    "recomp_assert",
    "recomp_get_config_u32",
    "recomp_get_config_double",
    "recomp_get_string_option_index",
    "recomp_get_config_string",
    "recomp_free_config_string",
    "recomp_get_mod_version",
    "recomp_change_save_file",
    "recomp_get_save_file_path",
    "recomp_get_mod_folder_path",
    "recomp_get_mod_file_path",
    "recomp_is_dependency_met",
    "recomp_trigger_event",
}

# Relocation types the mod loader knows how to apply. An unsupported type in a packaged mod means
# the toolchain produced something the runtime cannot fix up.
# The mod runtime describes relocations with `RelocEntryType` (librecomp/include/librecomp/
# sections.h), which stops at R_MIPS_GPREL16: types outside 0..7 cannot even be stored in the
# symbol file, so they are silently dropped and the field keeps its link-time value. Inside that
# range, the live recompiler only consumes R_MIPS_32/26/HI16/LO16 (see LiveRecomp/live_generator.cpp
# and the R_MIPS_26 special case in librecomp/src/mods.cpp), so the rest are only safe if the code
# never actually relies on them.
LOADER_RELOC_TYPES = {1, 2, 3, 4, 5, 6, 7}
LIVE_RECOMPILER_RELOC_TYPES = {2, 4, 5, 6}

# MIPS range that the recompiled game lives in. A baked address in this range that has no
# relocation attached is an unlinked reference into the base game (typical cause: taking the
# address of a game symbol in a static initializer), which cannot be fixed up at load time.
GAME_RAM_START = 0x80000000
GAME_RAM_END = 0x81000000



class Report:
    def __init__(self):
        self.rows = []

    def add(self, level, check, message):
        self.rows.append((level, check, message))

    def ok(self, check, message):
        self.add("PASS", check, message)

    def warn(self, check, message):
        self.add("WARN", check, message)

    def fail(self, check, message):
        self.add("FAIL", check, message)

    def info(self, check, message):
        self.add("INFO", check, message)

    def render(self):
        order = {"FAIL": 0, "WARN": 1, "INFO": 2, "PASS": 3}
        for level, check, message in sorted(self.rows, key=lambda r: (order[r[0]], r[1])):
            print(f"{level:4s} {check:26s} {message}")
        counts = {level: sum(1 for r in self.rows if r[0] == level) for level in order}
        print(f"\n{counts['FAIL']} fail, {counts['WARN']} warn, {counts['PASS']} pass, "
              f"{counts['INFO']} info")
        return counts["FAIL"], counts["WARN"]


def parse_version(text):
    parts = re.match(r"^(\d+)\.(\d+)\.(\d+)", str(text))
    if not parts:
        return None
    return tuple(int(p) for p in parts.groups())


def load_reference_index(toml_path: pathlib.Path):
    """Return {vram: name} and {name: vram} for the functions in a [[section]] symbol file."""
    by_vram, by_name = {}, {}
    if not toml_path.is_file():
        return by_vram, by_name
    pattern = re.compile(r'\{\s*name\s*=\s*"([^"]+)"\s*,\s*vram\s*=\s*(0x[0-9A-Fa-f]+)')
    for name, vram in pattern.findall(toml_path.read_text(errors="replace")):
        value = int(vram, 16)
        by_vram[value] = name
        by_name.setdefault(name, value)
    return by_vram, by_name


def load_base_patched_names(patches_dir: pathlib.Path):
    """Names the target port replaces in the base game itself (RECOMP_PATCH in its patch sources).

    A mod may hook those functions but must not patch them, or it fails to load.
    """
    names = set()
    if not patches_dir.is_dir():
        return names
    for source in patches_dir.glob("*.c"):
        text = source.read_text(errors="replace")
        for match in re.finditer(r"RECOMP_PATCH\s+[A-Za-z_][\w]*\s*\*?\s*([A-Za-z_]\w*)\s*\(", text):
            names.add(match.group(1))
        for match in re.finditer(r"RECOMP_FORCE_PATCH\s+[A-Za-z_][\w]*\s*\*?\s*([A-Za-z_]\w*)\s*\(", text):
            names.add(match.group(1))
    return names


def check_manifest(manifest: dict, report: Report, config: dict | None, sources: list[pathlib.Path],
                   skip_config_source: bool = False):
    required = ["id", "version", "display_name", "description", "short_description", "authors",
                "game_id", "minimum_recomp_version"]
    missing = [key for key in required if key not in manifest]
    if missing:
        report.fail("manifest/keys", f"manifest is missing required key(s): {', '.join(missing)}")
    else:
        report.ok("manifest/keys", "all required manifest keys are present")

    game_id = manifest.get("game_id")
    if game_id == "mm":
        report.ok("manifest/game_id", "targets Majora's Mask (game_id = mm)")
    else:
        report.fail("manifest/game_id", f"game_id is {game_id!r}; the Android port ships MM mods as 'mm'")

    version = parse_version(manifest.get("minimum_recomp_version", ""))
    if version is None:
        report.fail("manifest/recomp_version",
                    f"minimum_recomp_version {manifest.get('minimum_recomp_version')!r} is not major.minor.patch")
    elif version > ANDROID_RUNTIME_VERSION:
        report.fail("manifest/recomp_version",
                    f"minimum_recomp_version {'.'.join(map(str, version))} is newer than the runtime bundled "
                    f"in the Android port ({'.'.join(map(str, ANDROID_RUNTIME_VERSION))}); the loader refuses the "
                    "mod with no visible error")
    else:
        report.ok("manifest/recomp_version",
                  f"minimum_recomp_version {'.'.join(map(str, version))} loads on the Android runtime "
                  f"{'.'.join(map(str, ANDROID_RUNTIME_VERSION))}")

    native = manifest.get("native_libraries") or []
    if native:
        report.fail("manifest/native_libraries",
                    f"declares native libraries ({', '.join(str(n) for n in native)}); the Android port cannot "
                    "load desktop .so/.dll payloads, so the mod only works on PC")
    else:
        report.ok("manifest/native_libraries", "no native libraries: pure .nrm, portable to Android")

    deps = manifest.get("dependencies") or []
    if deps:
        report.info("manifest/dependencies",
                    "depends on " + ", ".join(str(d) for d in deps) + " - install those or the mod will not load")

    schema = manifest.get("config_schema") or []
    options = schema.get("options") if isinstance(schema, dict) else None
    if not options:
        report.info("config/options", "no config options declared")
        options = []

    declared = set()
    for option in options:
        opt_id = option.get("id")
        kind = option.get("type")
        if not opt_id or not kind:
            report.fail("config/options", f"option {option!r} lacks an id or type")
            continue
        if opt_id in declared:
            report.fail("config/options", f"duplicate option id {opt_id!r}")
        declared.add(opt_id)
        if kind not in ("Enum", "Number", "String"):
            report.fail("config/type",
                        f"option {opt_id!r} has type {kind!r}; the runtime only understands Enum, Number and String")
            continue
        if kind == "Enum":
            choices = option.get("options") or []
            if not choices:
                report.fail("config/enum", f"enum option {opt_id!r} has no options")
            elif "default" in option and option["default"] not in choices:
                report.fail("config/enum",
                            f"enum option {opt_id!r} defaults to {option['default']!r} which is not one of "
                            f"{choices}; the loader rejects the mod (InvalidConfigSchemaDefault)")
        if kind == "Number":
            low, high = option.get("min"), option.get("max")
            default = option.get("default")
            if low is not None and high is not None and low > high:
                report.fail("config/number", f"number option {opt_id!r} has min > max")
            if default is not None and low is not None and high is not None and not (low <= default <= high):
                report.fail("config/number", f"number option {opt_id!r} default {default} is outside [{low}, {high}]")
    if options:
        report.ok("config/options", f"{len(options)} config option(s) validated")

    if sources and not skip_config_source:
        read_ids = set()
        mentioned = set()
        for source in sources:
            text = source.read_text(errors="replace")
            # An id counts as read when it is the first argument of a config getter, including a
            # project's own wrapper (e.g. a helper that clamps the result), which keeps call sites
            # like `Glacio_ConfigInt("trigger_radius", 60)` honest.
            read_ids |= set(re.findall(r'[Cc]onfig\w*\s*\(\s*"([A-Za-z_][A-Za-z_0-9]*)"', text))
            read_ids |= set(re.findall(r'recomp_get_config_\w+\s*\(\s*"([A-Za-z_][A-Za-z_0-9]*)"', text))
            mentioned |= set(re.findall(r'"([A-Za-z_][A-Za-z_0-9]*)"', text))
        undeclared = sorted(read_ids - declared)
        if undeclared:
            report.warn("config/used_ids",
                        "source reads option(s) that are not declared, so they always read back as 0: "
                        + ", ".join(undeclared))
        else:
            report.ok("config/used_ids", "every config id read by the sources is declared in mod.toml")
        unused = sorted(declared - mentioned)
        if unused:
            report.info("config/unused_ids", "declared but not read by the sources: " + ", ".join(unused))


def check_package(names, syms, binary, report: Report, config: dict | None,
                  reference_by_vram: dict, base_patched: set, toml_path=None):
    if "mod.json" not in names:
        report.fail("package/mod.json", "no manifest in the archive: the loader ignores this .nrm")
    else:
        report.ok("package/mod.json", "manifest present")

    if "mod_syms.bin" not in names:
        report.fail("package/mod_syms.bin", "no symbol file: the mod declares nothing to load")
    else:
        report.ok("package/mod_syms.bin", "symbol file present")

    if "mod_binary.bin" in names:
        report.ok("package/mod_binary.bin", f"live-recompiled code blob present ({len(binary)} bytes)")
    else:
        if any(section["rom_size"] for section in syms["sections"]):
            report.fail("package/mod_binary.bin", "symbol file describes code but mod_binary.bin is missing")
        else:
            report.warn("package/mod_binary.bin",
                        "no code blob: asset-only mod. Fine for textures/models, but the Android port's "
                        "offline-recompiled path (native code) is unavailable")

    if "thumb.png" in names or "thumb.dds" in names:
        report.ok("package/thumbnail", "mod menu thumbnail present")
    else:
        report.info("package/thumbnail", "no thumb.png/thumb.dds; the mod menu shows a placeholder")

    if syms["trailing_bytes"]:
        report.fail("syms/layout", f"{syms['trailing_bytes']} unexpected trailing byte(s) in mod_syms.bin "
                                  "(a loader version mismatch shows up like this)")
    else:
        report.ok("syms/layout", "symbol file parses with no leftover bytes")

    total = 0
    for index, section in enumerate(syms["sections"]):
        total += section["rom_size"] + section["bss_size"]
        if section["file_offset"] + section["rom_size"] > len(binary):
            report.fail("syms/sections",
                        f"section {index} spans 0x{section['file_offset']:x}..0x{section['file_offset'] + section['rom_size']:x} "
                        f"but the code blob is only 0x{len(binary):x} bytes")
        flags = section["flags"]
        fixed, global_load = flags & 1, flags & 2
        if fixed != global_load and (fixed or global_load):
            report.fail("syms/sections",
                        f"section {index} has flags {flags:#x}: the loader rejects a section that is fixed-address "
                        "without being globally loaded, and vice versa")
        if not fixed:
            report.info("syms/sections",
                        f"section {index} is relocatable (vram 0x{section['vram']:08x} is rebased at load time), "
                        "as live-recompiled mods must be")
    if syms["sections"]:
        report.ok("syms/sections", f"{len(syms['sections'])} section(s), 0x{total:x} bytes of image+bss")

    # Section addresses. The loader keeps a lookup table keyed by guest address and has fixed-address
    # paths that read a section's vram directly, so a mod that is linked outside the region every
    # other mod uses faults at boot instead of reporting a load error. Measured against the mods that
    # ship with the Android port: all of them link their first section at exactly 0x81000000.
    MOD_REGION_START, MOD_REGION_END = 0x81000000, 0x82000000
    total_funcs = 0
    for section in syms["sections"]:
        if not (MOD_REGION_START <= section["vram"] < MOD_REGION_END):
            report.fail("syms/section_vram",
                        f"section vram is 0x{section['vram']:08X}, outside the mod region "
                        f"[0x{MOD_REGION_START:08X}, 0x{MOD_REGION_END:08X}). Link with "
                        f"--base 0x80FFF000 --image-offset 0x1000 (mod.ld's RAMBASE); the mods the "
                        "Android port ships are all at 0x81000000. A wrong vram faults at boot rather "
                        "than producing a load error.")
        total_funcs += len(section.get("funcs", []))
    else:
        report.ok("syms/section_vram",
                  f"all {len(syms['sections'])} section(s) linked inside the mod region")

    # Hook and replacement records index the mod's own function table. Out of range is undefined
    # behaviour in the loader (it dereferences the index without a bounds check on some paths), so a
    # package that survives the mod tool can still take the app down at startup.
    out_of_range = [rec for rec in list(syms["hooks"]) + list(syms["replacements"])
                    if rec[0] >= total_funcs]
    if out_of_range:
        report.fail("syms/func_index",
                    f"{len(out_of_range)} hook/replacement record(s) point at function index "
                    f">= {total_funcs} (the number of functions in this package); the loader indexes "
                    "its function table with this value")
    elif syms["hooks"] or syms["replacements"]:
        report.ok("syms/func_index",
                  f"{len(syms['hooks'])} hook(s) and {len(syms['replacements'])} replacement(s) all "
                  f"reference a function that exists ({total_funcs} in the package)")

    # Shape heuristic: the live recompiler compiles one function at a time and rejects a few
    # relocation shapes with assert(false)/errored, which in a release build leaves a half-built
    # function that is then callable. Every mod in the ecosystem ships many small functions; a
    # single function spanning the whole image is the exotic input, so flag it.
    for index, section in enumerate(syms["sections"]):
        funcs = section.get("funcs", [])
        if len(funcs) == 1 and section["rom_size"] > 0x400:
            _offset, size = funcs[0]
            if size > section["rom_size"] * 3 // 4:
                report.warn("syms/function_shape",
                            f"section {index} is one {size:#x}-byte function covering most of the "
                            f"{section['rom_size']:#x}-byte image. Known-good mods ship many small "
                            "functions; consider -O1 or noinline on the helpers so the live "
                            "recompiler's per-function reloc handling sees an ordinary shape.")

    # Relocations: unsupported types, and pairs the loader expects to stay adjacent.
    bad_types = set()
    awkward_types = set()
    reloc_count = 0
    for section in syms["sections"]:
        for _off, type_, _target, _vrom in section["relocs"]:
            reloc_count += 1
            if type_ not in LOADER_RELOC_TYPES:
                bad_types.add(RELOC_NAMES.get(type_, str(type_)))
            elif type_ not in LIVE_RECOMPILER_RELOC_TYPES:
                awkward_types.add(RELOC_NAMES.get(type_, str(type_)))
    if bad_types:
        report.fail("syms/relocs",
                    "relocation type(s) outside the runtime's RelocEntryType enum (R_MIPS_NONE.."
                    "R_MIPS_GPREL16) cannot be stored at all, so those words keep their link-time "
                    "value: " + ", ".join(sorted(bad_types)) +
                    ". This is the -mabicalls/-G0 signature: recompile with -G0 -mno-abicalls -fno-pic.")
    elif awkward_types:
        report.warn("syms/relocs",
                    f"{reloc_count} relocation(s), but type(s) {', '.join(sorted(awkward_types))} are "
                    "not consumed by the live recompiler; verify the fields they target are never read "
                    "as addresses")
    else:
        report.ok("syms/relocs", f"{reloc_count} relocation(s), all of types the loader supports")

    # Baked absolute addresses without a relocation are the classic "loads on PC, dies elsewhere"
    # bug: the address was resolved by the linker against a base the loader does not use, so it can
    # never be fixed up. The usual cause is taking the address of a game symbol in a static
    # initializer instead of reading it at runtime.
    relocated = {}
    for sidx, section in enumerate(syms["sections"]):
        marks = relocated.setdefault(sidx, set())
        for off, _type, _target, _vrom in section["relocs"]:
            marks.add(off)
    stray = []
    ambiguous = []
    for sidx, section in enumerate(syms["sections"]):
        base = section["file_offset"]
        blob = binary[base:base + section["rom_size"]]
        marks = relocated.get(sidx, set())
        for word_index in range(0, len(blob) - 3, 4):
            if word_index in marks:
                continue
            value = struct.unpack_from(">I", blob, word_index)[0]
            if not (GAME_RAM_START <= value < GAME_RAM_END):
                continue
            # Words in [0x80000000, 0x81000000) also decode as MIPS memory instructions (opcode
            # 0x20..0x2B is lb/lh/lw/sb/... whose base register and offset can look like a pointer).
            # Treat it as an instruction when it has a real base register and a small displacement,
            # which is what compiler emitted loads look like, and as data otherwise.
            opcode = value >> 26
            base_reg = (value >> 21) & 0x1F
            imm = value & 0xFFFF
            if 0x20 <= opcode <= 0x2B and base_reg != 0 and imm < 0x400:
                ambiguous.append(f"{section['vram'] + word_index:#010x}")
                continue
            stray.append(f"{section['vram'] + word_index:#010x} = {value:#010x}")
    if ambiguous:
        report.info("binary/ambiguous_words",
                    f"{len(ambiguous)} word(s) look like an absolute game address but also decode as a "
                    "load/store with a small offset, so they were ignored: " + ", ".join(ambiguous[:6]))
    if stray:
        report.warn("binary/baked_addresses",
                    f"{len(stray)} word(s) hold an absolute game address with no relocation attached "
                    f"({', '.join(stray[:6])}); these break whenever the base game is recompiled at a "
                    "different address. Prefer resolving pointers at runtime over storing them in "
                    ".data/.rodata.")
    else:
        report.ok("binary/baked_addresses", "no unrelocated absolute game addresses baked into the image")

    # Imports must exist on the platform the mod claims to support.
    dependencies = [name_of(syms["strings"], dep_start, dep_size) for dep_start, dep_size in syms["dependencies"]]
    unknown = []
    for start, size, dep_index in syms["imports"]:
        import_name = name_of(syms["strings"], start, size)
        from_dependency = 0 <= dep_index < len(dependencies) and dependencies[dep_index] != "*"
        if import_name in KNOWN_BASE_IMPORTS or from_dependency:
            continue
        unknown.append(f"{import_name}{' (from ' + dependencies[dep_index] + ')' if from_dependency else ''}")
    if unknown:
        report.warn("api/imports",
                    "import(s) not known to be exported by the Android port: " + ", ".join(unknown) +
                    ". Verify each against the port's base exports, or the import resolves to nothing.")
    else:
        report.ok("api/imports", f"{len(syms['imports'])} import(s), all base-API or declared-dependency")

    # A package built from a different elf than the manifest points at is a whole class of "green
    # build, wrong binary" (stale artifacts, a shared build dir, a second manifest). The sizes have
    # to agree, because everything else about the package is derived from that image.
    if toml_path and toml_path.is_file() and binary:
        elf_ref = None
        for line in toml_path.read_text(errors="replace").splitlines():
            stripped = line.strip()
            if stripped.startswith("elf_path"):
                elf_ref = stripped.split("=", 1)[-1].strip().strip('"')
                break
        if elf_ref:
            elf_file = (toml_path.parent / elf_ref)
            if not elf_file.is_file():
                report.warn("package/elf_path", f"mod.toml points at {elf_ref} which does not exist")
            else:
                try:
                    from mm_elf32 import ElfFile, SHF_ALLOC, SHT_NOBITS, SHT_PROGBITS
                    elf = ElfFile.load(str(elf_file))
                    alloc = [x for x in elf.sections if (x.flags & SHF_ALLOC) and x.sh_type in (SHT_PROGBITS, SHT_NOBITS)]
                    elf_size = sum(x.size for x in alloc if x.sh_type == SHT_PROGBITS)
                    nrm_size = sum(section["rom_size"] for section in syms["sections"])
                    gap = abs(elf_size - nrm_size)
                    if gap > 128:
                        report.warn("package/elf_match",
                                    f"the packaged image is {nrm_size} bytes but {elf_ref} holds {elf_size} "
                                    f"bytes of allocatable sections: this .nrm was not built from that elf "
                                    "(stale build directory, or a manifest pointing at another build)")
                    else:
                        report.ok("package/elf_match",
                                  f"packaged image size matches {elf_ref} within {gap} bytes of alignment")
                except Exception as exc:  # noqa: BLE001 - the audit must stay useful if the elf is odd
                    report.info("package/elf_match", f"could not compare with {elf_ref}: {exc}")

    # Patches (replacements) must not collide with the port's own base patches.
    patch_names = []
    for func_index, _section_vrom, vram, flags in syms["replacements"]:
        name = reference_by_vram.get(vram, f"0x{vram:08x}")
        patch_names.append(name)
        if name in base_patched:
            report.fail("compat/patches",
                        f"the mod patches {name}(), which the target port already patches itself; such a mod "
                        "fails to load. Hook it instead (RECOMP_HOOK keeps working on patched functions).")
        if flags & 1:
            report.fail("compat/patches",
                        f"the mod force-patches {name}() (RECOMP_FORCE_PATCH); that skips the compatibility "
                        "check that protects other mods and the base patches")
    if base_patched:
        if patch_names:
            report.ok("compat/patches", f"{len(patch_names)} replaced function(s), none collide with the port's "
                                        f"{len(base_patched)} base patches")
        else:
            report.ok("compat/patches",
                      f"no function replacements at all: hook-only mod, compatible with every base patch "
                      f"({len(base_patched)} in this port) and with other mods")
    elif patch_names:
        report.warn("compat/patches",
                    f"mod patches {', '.join(patch_names)} but no patch list was available to check against "
                    "(pass --patches <dir> of the port's patches/*.c)")

    if syms["hooks"]:
        hook_names = [reference_by_vram.get(vram, f"0x{vram:08x}") for _f, _s, vram, _fl in syms["hooks"]]
        report.info("compat/hooks", f"{len(hook_names)} hook(s) on: " + ", ".join(hook_names))

    if syms["exports"]:
        export_names = [name_of(syms["strings"], start, size) for _func, start, size in syms["exports"]]
        report.info("compat/exports", f"exports: {', '.join(export_names) or '(none)'}")
    if syms["events"]:
        event_names = [name_of(syms["strings"], start, size) for start, size in syms["events"]]
        report.info("compat/events", f"provides events: {', '.join(event_names)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="*", help="mod.toml and/or mod.nrm to audit")
    parser.add_argument("--nrm", help="packaged mod to audit")
    parser.add_argument("--toml", help="mod.toml to audit")
    parser.add_argument("--src", default="src", help="mod source directory (default: src)")
    parser.add_argument("--reference-syms", default="Zelda64RecompSyms/mm.us.rev1.syms.toml")
    parser.add_argument("--patches", default=None,
                        help="directory of the port's base patches (e.g. ../android-repo/patches)")
    parser.add_argument("--strict", action="store_true", help="treat warnings as failures")
    parser.add_argument("--skip-config-source", action="store_true",
                        help="don't cross-check the config ids read by the sources (for builds of the same "
                             "sources that leave the config reads out, e.g. make PROBE=1)")
    args = parser.parse_args()

    nrm_path = pathlib.Path(args.nrm) if args.nrm else None
    toml_path = pathlib.Path(args.toml) if args.toml else None
    for text in args.paths:
        path = pathlib.Path(text)
        if path.suffix == ".nrm":
            nrm_path = nrm_path or path
        elif path.suffix == ".toml":
            toml_path = toml_path or path
    if nrm_path is None and toml_path is None:
        parser.error("nothing to check: pass a mod.toml and/or a .nrm")

    root = toml_path.parent if toml_path else (nrm_path.parent.parent if nrm_path else pathlib.Path("."))
    if toml_path is None and (root / "mod.toml").is_file():
        toml_path = root / "mod.toml"

    config = None
    if toml_path and toml_path.is_file():
        try:
            import tomllib  # Python 3.11+
            config = tomllib.loads(toml_path.read_text(errors="replace"))
        except ModuleNotFoundError:
            report_toml = None
            config = None  # tomllib missing: the .nrm manifest is checked instead, which is authoritative

    report = Report()
    sources = sorted((root / args.src).glob("*.c")) if (root / args.src).is_dir() else []
    if not sources and nrm_path:
        sources = sorted(pathlib.Path(args.src).glob("*.c"))

    reference_by_vram, _ = load_reference_index(root / args.reference_syms)
    if not reference_by_vram and nrm_path:
        reference_by_vram, _ = load_reference_index(pathlib.Path(args.reference_syms))
    base_patched = load_base_patched_names(pathlib.Path(args.patches)) if args.patches else set()

    manifest = None
    if nrm_path and nrm_path.is_file():
        with zipfile.ZipFile(nrm_path) as zf:
            names = zf.namelist()
            manifest = json.loads(zf.read("mod.json").decode("utf-8"))
        manifest_src = "package"
    elif config:
        manifest = dict(config.get("manifest", {}))
        manifest.setdefault("version", manifest.get("version", ""))
        manifest.setdefault("config_schema", options_to_schema(manifest.get("config_options", [])))
        names = []
        manifest_src = "mod.toml"
    if manifest is None:
        report.fail("input", "could not find a manifest: pass a built .nrm")
        return 1 if report.render()[0] else 1

    print(f"auditing manifest from {manifest_src}" + (f" and package {nrm_path.name}" if nrm_path else ""))
    check_manifest(manifest, report, config, sources, skip_config_source=args.skip_config_source)

    # The .nrm is what the loader reads, so it wins; a mod.toml that disagrees with it means the
    # package is stale and the shipped options are not the ones being edited.
    if manifest_src == "package" and config:
        toml_manifest = dict(config.get("manifest", {}))
        drift = []
        for key in ("name", "description", "version", "game_id", "minimum_recomp_version"):
            if key in toml_manifest and toml_manifest.get(key) != manifest.get(key):
                drift.append(f"{key}: mod.toml={toml_manifest.get(key)!r} package={manifest.get(key)!r}")
        toml_options = len(toml_manifest.get("config_options", []))
        packaged_schema = manifest.get("config_schema") or []
        packaged_options = (packaged_schema.get("options") if isinstance(packaged_schema, dict)
                            else packaged_schema) or []
        if toml_options != len(packaged_options):
            drift.append(f"config_options: mod.toml declares {toml_options}, package carries {len(packaged_options)}")
        if drift:
            report.fail("manifest/stale_package",
                        "mod.toml and the packaged manifest disagree: " + "; ".join(drift) +
                        ". Rebuild and repackage, or the options you edited are not the ones the loader sees.")
        else:
            report.ok("manifest/stale_package", "packaged manifest matches mod.toml")

    if nrm_path and nrm_path.is_file():
        _manifest, syms, binary, names = load_nrm(nrm_path)
        check_package(names, syms, binary, report, config, reference_by_vram, base_patched, toml_path)
    else:
        report.info("package", "no .nrm given: only the mod.toml manifest was audited")

    if not base_patched:
        report.info("compat/patches",
                    "base patch list not loaded: pass --patches <dir> containing the port's patches/*.c "
                    "to check for patch collisions")

    fails, warns = report.render()
    if args.strict and warns:
        print("--strict: warnings are errors")
        return 1
    return 1 if fails else 0


def options_to_schema(options):
    """mod.toml spells config options as [[manifest.config_options]]; the manifest json nests them."""
    return {"options": list(options)} if options else []


if __name__ == "__main__":
    sys.exit(main())
