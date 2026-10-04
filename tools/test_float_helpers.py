#!/usr/bin/env python3
"""Verify the two properties the mod's numeric code has to keep.

1. Accuracy: include/glacio_float.h re-implements the float operations the mod needs with integer
   arithmetic. tests/glacio_float_test.c compiles that same header for the host and compares every
   helper against real float arithmetic.

2. Loadability: the mod must not reference a single compiler runtime symbol. Mod code is resolved
   against the base game's exported symbols, and the N64 toolchain targets soft float, so one float
   operation emits `__addsf3` / `__fixsfsi` / `__floatsisf` ... which Majora's Mask does not export.
   The mod then refuses to load, which on the Android port looks like "the mod does nothing".

The second check runs the real MIPS compile through the Makefile so the flags stay in one place.

    python3 tools/test_float_helpers.py [--object build/src/glacio_village.c]
"""

import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from mm_elf32 import ElfFile  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent

# Symbols the loader provides to every mod (see the base API headers in Zelda64Recomp).
BASE_API = {
    "recomp_alloc",
    "recomp_free",
    "recomp_printf",
    "recomp_assert",
    "recomp_get_config_u32",
    "recomp_get_config_double",
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

# The usual offenders, named in the failure message so the fix is obvious.
LIBGCC_HINTS = ("__addsf3", "__subsf3", "__mulsf3", "__divsf3", "__fixsfsi", "__floatsisf",
                "__ltsf2", "__gtsf2", "__lesf2", "__gesf2", "__eqsf2", "__nesf2", "__unordsf2",
                "__truncdfsf2", "__extendsfdf2", "__muldf3", "__adddf3", "__fixunsdfsi",
                "__floatundidf", "__udivdi3", "__divdi3", "__modsi3", "__umodsi3", "__memset",
                "__memcpy")


def game_symbols():
    """Every name the base game exports, from the reference symbol files."""
    names = set()
    for filename in ("mm.us.rev1.syms.toml", "mm.us.rev1.datasyms.toml"):
        path = REPO / "Zelda64RecompSyms" / filename
        if not path.is_file():
            print(f"note: {path} not found, so symbol checks are skipped for it")
            continue
        # Entries look like: { name = "Actor_Spawn", vram = 0x800BF7CC, size = 0x1D0 }
        names |= set(re.findall(r'\{\s*name\s*=\s*"([^"]+)"', path.read_text(errors="replace")))
    return names


def host_accuracy_test(cc):
    if not cc:
        print("SKIP accuracy test (no host C compiler found; pass CC=...)")
        return None
    with tempfile.TemporaryDirectory() as tmp:
        exe = pathlib.Path(tmp) / "glacio_float_test"
        cmd = cc + ["-std=gnu11", "-O1", "-Wall", "-Wextra", "-Wno-unused-parameter",
                    "-I", str(REPO / "include"), str(REPO / "tests" / "glacio_float_test.c"),
                    "-lm", "-o", str(exe)]
        build = subprocess.run(cmd, capture_output=True, text=True)
        if build.returncode != 0:
            print("FAIL accuracy test did not compile:\n" + build.stdout + build.stderr)
            return False
        run = subprocess.run([str(exe)], capture_output=True, text=True)
        print(run.stdout.rstrip())
        if run.returncode != 0:
            print(run.stderr.rstrip())
            return False
        return True


def object_libcall_check(obj, allow_extra=()):
    """Assert the linked object only references symbols the runtime can actually resolve."""
    if not obj.is_file():
        print(f"FAIL {obj} missing")
        return False
    elf = ElfFile.load(str(obj))
    allowed = BASE_API | set(allow_extra) | set(game_symbols())
    undefined = sorted({sym.name for sym in elf.symbols if sym.shndx == 0 and sym.name})
    libcalls = [name for name in undefined if name.startswith("__")]
    unknown = [name for name in undefined if name not in allowed]

    if libcalls:
        print(f"FAIL soft-float/libgcc references found in {obj.name}: {', '.join(libcalls)}")
        print("      Mod code must not use float arithmetic directly; use include/glacio_float.h.")
        print("      (Typical causes: " + ", ".join(LIBGCC_HINTS[:6]) + ", ...)")
        return False
    if unknown:
        print(f"FAIL symbols the base game does not export: {', '.join(unknown)}")
        print("      RecompModTool resolves undefined symbols by name against the reference symbol")
        print("      file, so any name that is not in there makes the mod fail to load.")
        return False
    print(f"PASS {obj.name}: {len(undefined)} external symbol(s), all resolvable: {', '.join(undefined)}")
    return True


def find_cc():
    """First C compiler that runs, preferring an explicit CC (which may hold flags)."""
    candidates = []
    if os.environ.get("CC"):
        candidates.append(shlex.split(os.environ["CC"]))
    home = pathlib.Path.home()
    candidates += [
        [str(home / "tmpnet/zig-extract/ziglang/zig"), "cc"],
        ["zig", "cc"],
        ["cc"],
        ["clang"],
        ["gcc"],
    ]
    for candidate in candidates:
        if subprocess.run(candidate + ["--version"], capture_output=True).returncode == 0:
            return candidate
    return None


def main():
    obj = None
    for index, arg in enumerate(sys.argv[1:]):
        if arg == "--object":
            obj = pathlib.Path(sys.argv[index + 2])
    if obj is None:
        # Build through the Makefile so the flags exercised here are the shipping ones.
        make = ["make", "-s", "build/src/glacio_village.o"]
        zig = shutil.which("zig")
        if not shutil.which("clang") and not shutil.which("llvm-clang"):
            candidate = zig or str(pathlib.Path.home() / "tmpnet/zig-extract/ziglang/zig")
            if pathlib.Path(candidate).is_file() or zig:
                make += [f"TOOLCHAIN=zig", f"ZIG={zig or candidate}"]
        build = subprocess.run(make, cwd=REPO, capture_output=True, text=True)
        if build.returncode != 0:
            print("FAIL MIPS build failed:\n" + build.stdout + build.stderr)
            return 1
        obj = REPO / "build/src/glacio_village.o"

    ok = True
    if host_accuracy_test(find_cc()) is False:
        ok = False
    if not object_libcall_check(pathlib.Path(obj)):
        ok = False
    print("\nfloat helper + loadability suite: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
