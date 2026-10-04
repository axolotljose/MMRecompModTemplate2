#!/usr/bin/env python3
"""Verify a packaged .nrm is compilable by the live recompiler on the target.

The Android port (and any relocatable-mod host) does not run mod code through a fallback interpreter:
`N64Recomp::recompile_function` walks every instruction of every function in the mod's symbol table and
generates sljit code for it. If a single word is one it cannot handle, it prints "Unhandled instruction:
<name>" and returns false, which the mod loader surfaces to the player as

    <mod name>: Failed to load mod code (Failed to recompile mod)

The whole mod fails; there is no partial load. Three families of rule decide whether that happens, and
this script mirrors each of them against the artifact that actually ships:

  instruction legality  the op table implements the R4300i (MIPS III) instruction set plus a few
                        extras. MIPS32 Release 2 encodings (`mul`, `ext`, `ins`, `seb`, `seh`, `clz`,
                        `mfhc1`, `mthc1`), MIPS IV `movn`/`movz`, `ll`/`sc`, `sync` and `pref` are
                        absent, and those are the ones a compiler will happily emit for a "mips"
                        target, so they are the deny list below. The full supported set is snapshotted
                        in tools/live_recomp_supported.txt, generated from the commit the target pins.
                        Coprocessor sub-ops are only checked when they can be named with confidence:
                        mods that are known to load on the target use lwc1/swc1/dmtc1 and branch-on-FP,
                        so unmodellable COP1/COP2 words are reported, never failed.
  relocation shape      src/recompilation.cpp pairs a relocation with the instruction it lands on:
                        HI16 only on `lui` with an immediate, LO16 only on loads, stores and adds,
                        26-bit only on `j`/`jal`. Anything else hits `assert(false); errored = true`
                        in live_generator.cpp (asserts are compiled out in release builds, so the
                        function ends up half-built and reported as a failure instead of crashing).
  jump resolution       `j`/`jal`/branches must resolve. A target inside the current function is fine;
                        a target at the start of a registered function is compiled as a call or tail
                        call; a `jal` to any other in-section address is turned into a static function;
                        a *branch* to any other address fails ("Unhandled branch"). A computed `jr`
                        (jump table) and `jalr` with a return register other than $ra also fail.

Usage:
    check_live_recomp.py <mod.nrm> [--supported FILE] [--allow-float] [--strict] [-q]

Exit status: 0 clean, 1 if any FAIL (or WARN with --strict).
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mm_nrm_inspect import (  # noqa: E402
    SECTION_EVENT_VROM,
    SECTION_IMPORT_VROM,
    SECTION_SELF_FLAG,
    load_nrm,
)

FAIL, WARN, PASS, INFO = "fail", "warn", "pass", "info"


# --- MIPS decode ------------------------------------------------------------
# Names are the lowercase mnemonics rabbitizer uses, because that is the vocabulary of
# tools/live_recomp_supported.txt. Only what a compiler realistically emits for this target is
# modelled; anything unrecognised is reported as undecodable, which is the correct answer anyway
# (rabbitizer will not decode it either).
MAIN_OP = {
    0x01: "regimm", 0x02: "j", 0x03: "jal", 0x04: "beq", 0x05: "bne", 0x06: "blez", 0x07: "bgtz",
    0x08: "addi", 0x09: "addiu", 0x0A: "slti", 0x0B: "sltiu", 0x0C: "andi", 0x0D: "ori", 0x0E: "xori",
    0x0F: "lui", 0x10: "cop0", 0x11: "cop1", 0x12: "cop2", 0x13: "cop3",
    0x14: "beql", 0x15: "bnel", 0x16: "blezl", 0x17: "bgtzl",
    0x18: "daddi", 0x19: "daddiu", 0x1A: "ldl", 0x1B: "ldr", 0x1C: "special2", 0x1F: "special3",
    0x20: "lb", 0x21: "lh", 0x22: "lwl", 0x23: "lw", 0x24: "lbu", 0x25: "lhu", 0x26: "lwr",
    0x28: "sb", 0x29: "sh", 0x2A: "swl", 0x2B: "sw", 0x2C: "swr", 0x2D: "cache",
    0x30: "ll", 0x31: "lwc1", 0x32: "lwc2", 0x33: "pref", 0x34: "ldc1", 0x35: "ldc2",
    0x38: "sc", 0x39: "swc1", 0x3A: "swc2", 0x3C: "sdc1", 0x3D: "sdc2",
}

# SPECIAL (opcode 0) sub-function codes, named exactly as the target's op table names them.
SPECIAL = {
    0x00: "sll", 0x02: "srl", 0x03: "sra", 0x04: "srlv", 0x05: "srav", 0x06: "sllv",
    0x08: "jr", 0x09: "jalr", 0x0A: "movz", 0x0B: "movn", 0x0C: "syscall", 0x0D: "break",
    0x10: "mfhi", 0x11: "mthi", 0x12: "mflo", 0x13: "mtlo",
    0x18: "mult", 0x19: "multu", 0x1A: "div", 0x1B: "divu",
    0x1C: "ddiv", 0x1D: "ddivu", 0x1E: "dmult", 0x1F: "dmultu",
    0x20: "add", 0x21: "addu", 0x22: "sub", 0x23: "subu", 0x24: "and", 0x25: "or", 0x26: "xor",
    0x27: "nor", 0x2A: "slt", 0x2B: "sltu", 0x2C: "dadd", 0x2D: "daddu", 0x2E: "dsub", 0x2F: "dsubu",
    0x30: "and", 0x31: "or", 0x32: "xor", 0x33: "nor", 0x38: "dadd", 0x39: "daddu",
}
REGIMM = {0x00: "bltz", 0x01: "bgez", 0x02: "bltzl", 0x03: "bgezl", 0x08: "tgei", 0x09: "tgeiu",
          0x0A: "tlti", 0x0B: "tltiu", 0x10: "bltzal", 0x11: "bgezal", 0x14: "beql", 0x15: "bnel",
          0x16: "blezl", 0x17: "bgtzl"}
# These exist on MIPS32 Release 2 / MIPS64 but not on the R4300i, so they are listed only so the
# failure message can name them. Anything here is a build error on the target.
SPECIAL2 = {0x00: "madd", 0x01: "maddu", 0x02: "mul", 0x03: "mulu", 0x04: "msub", 0x05: "msubu",
            0x08: "clz", 0x09: "clo", 0x0A: "snop", 0x20: "bposge32"}
SPECIAL3 = {0x00: "ext", 0x01: "dext", 0x04: "ins", 0x05: "dins", 0x0C: "bset", 0x0D: "bclr",
            0x0E: "bcloc", 0x10: "mthid", 0x12: "mfhc0", 0x13: "mthc0", 0x18: "dextm", 0x19: "dextu",
            0x1A: "dinsm", 0x1B: "dinsu", 0x1C: "seb", 0x1D: "seh", 0x20: "mthc1"}

LOADS = {"lb", "lbu", "lh", "lhu", "lw", "lwu", "lwl", "lwr", "ld", "ldl", "ldr", "lwc1", "ldc1"}
STORES = {"sb", "sh", "sw", "swl", "swr", "sd", "sdl", "sdr", "swc1", "sdc1"}
ADDISH = {"addu", "add", "addi", "addiu", "daddi", "daddiu", "addiu32"}
BRANCHES = {"beq", "bne", "blez", "bgtz", "bltz", "bgez", "bltzal", "bgezal", "beql", "bnel",
            "blezl", "bgtzl", "bltzl", "bgezl"}
JUMPS = {"j", "jal"}


def decode(word: int):
    """Return (name, rd, rs, rt) for a MIPS word; name=None when the word is not an instruction the
    R4300 decoder knows how to name (which is itself the failure the target would report)."""
    op = (word >> 26) & 0x3F
    rs = (word >> 21) & 0x1F
    rt = (word >> 16) & 0x1F
    rd = (word >> 11) & 0x1F
    code = word & 0x3F
    name = MAIN_OP.get(op)
    if op == 0x00:
        if word == 0:
            return "nop", rd, rs, rt
        name = SPECIAL.get(code)
        if name is None:
            name = f"special:0x{code:02x}"
    elif op == 0x01:
        name = REGIMM.get(rt, f"regimm:0x{rt:02x}")
    elif op == 0x1C:
        name = SPECIAL2.get(code) or SPECIAL2.get(rs) or f"special2:0x{code:02x}"
    elif op == 0x1F:
        sa = (word >> 6) & 0x1F
        if code == 0x20 and sa in (0x18, 0x19):
            name = {0x18: "mfhc1", 0x19: "mthc1"}[sa]
        else:
            name = SPECIAL3.get(rs) or SPECIAL3.get(code) or f"special3:0x{rs:02x}"
    elif op in (0x10, 0x11, 0x12, 0x13):
        # Coprocessor moves key off rs; FP arithmetic (COP1, rs=0x10/0x11) off the function field.
        sub = {0x10: {0: "mfc0", 2: "cfc0", 3: "mtc0", 5: "ctc0"},
               0x11: {0: "mfc1", 1: "dmfc1", 2: "cfc1", 3: "mtc1", 4: "dmtc1", 5: "ctc1",
                      0x10: "cop1.branch", 0x11: "cop1.arith"}}.get(op, {})
        if op == 0x11 and rs in (0x10, 0x11):
            name = sub[rs]
        else:
            name = sub.get(rs, f"cop{op - 0x10}:0x{rs:02x}")
    elif op in (0x14, 0x15, 0x16, 0x17):
        name = {0x14: "beql", 0x15: "bnel", 0x16: "blezl", 0x17: "bgtzl"}[op]
    return name, rd, rs, rt


# Encodings a MIPS32 Release 2+ compiler emits that the R4300i does not have. Every one of these has
# been seen in a mod built by zig/clang for a bare `-mips2` target, and each makes the target fail the
# whole mod. Deliberately a deny list rather than "anything not in the supported set": the supported
# names come from rabbitizer and an approximate decoder cannot reproduce all of them, and a checker
# that cries wolf on known-good mods (which do use lwc1, bc1t and jump tables) is a checker nobody
# runs. Anything genuinely undecodable still fails, via live/decodable.
UNSUPPORTED_ENCODINGS = {
    # MIPS32 Release 2 (SPECIAL2 / SPECIAL3)
    "mul", "mulu", "madd", "maddu", "msub", "msubu", "clz", "clo",
    "ext", "dext", "dextm", "dextu", "ins", "dins", "dinsm", "dinsu",
    "bset", "bclr", "bcloc", "bitrev", "seb", "seh", "mthid", "mfthl", "mtthl",
    "mfhc0", "mthc0", "mfhc1", "mthc1", "mfmc0", "mtmc0", "dmfc0", "dmtc0",
    # MIPS IV
    "movn", "movz", "rdhwr", "wrpgpr", "dadd", "dsub",
    # MIPS32 Release 1/2 memory-model and misc
    "ll", "sc", "llw", "scw", "lld", "scd", "sync", "pref",
    # Release 6 compact branches and PAA, which a generic CPU may select
    "blezc", "bgtzc", "bltzc", "bgezc", "b", "beqzc", "bnezc", "lwx", "lhx", "lwcx", "swx", "shx",
    "madd", "maddu", "mul", "rdpgpr",
}


def is_float(name):
    if not name:
        return False
    return (("." in name and not name.startswith("?")) or name in {"mfc1", "mtc1", "dmfc1", "dmtc1",
            "cfc1", "ctc1", "lwc1", "swc1", "ldc1", "sdc1", "mov.f", "mthc1", "mfhc1", "mftc1",
            "mfmc1", "cvt.w.s", "cvt.s.w"})


def load_supported(path: Path):
    names = set()
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        names.add(line)
    if not names:
        raise SystemExit(f"{path}: no instruction names found")
    return names


def main() -> int:
    ap = argparse.ArgumentParser(description="check a .nrm against the live recompiler's rules")
    ap.add_argument("nrm")
    ap.add_argument("--supported", default=str(Path(__file__).resolve().parent / "live_recomp_supported.txt"),
                    help="snapshot of the instructions the target's live recompiler implements")
    ap.add_argument("--allow-float", action="store_true",
                    help="tolerate coprocessor-1 instructions (the op table implements only part of them)")
    ap.add_argument("--strict", action="store_true", help="treat warnings as failures")
    ap.add_argument("-q", "--quiet", action="store_true", help="only print failures and warnings")
    args = ap.parse_args()

    supported = load_supported(Path(args.supported))
    manifest, syms, binary, _ = load_nrm(args.nrm)
    mod_name = manifest.get("name") or Path(args.nrm).stem

    results = []

    def add(level, check, msg):
        results.append((level, check, msg))

    # Section addresses/bytes and the registered function set, which is exactly the pair the
    # recompiler walks (functions in the symbol table; bytes from the binary blob).
    sections = []
    func_starts = set()
    for idx, sec in enumerate(syms["sections"]):
        lo = sec["file_offset"]
        blob = binary[lo:lo + sec["rom_size"]]
        sections.append({"index": idx, "vram": sec["vram"], "blob": blob, "funcs": sec["funcs"],
                         "relocs": sec["relocs"]})
        for foff, fsize in sec["funcs"]:
            func_starts.add(sec["vram"] + foff)

    if not func_starts:
        add(FAIL, "live/functions", "no functions registered, nothing would be compiled")
        return report(results, args.strict, args.quiet, mod_name)

    reloc_by_addr = {}
    for sec in sections:
        for off, rtype, target, vrom in sec["relocs"]:
            reloc_by_addr[(sec["index"], sec["vram"] + off)] = (rtype, target, vrom, sec)

    def resolve_jump(addr, word, sec, name):
        """Effective branch target, mirroring getBranchVramGeneric then the relocation override."""
        upper = addr & 0xF0000000
        if name in JUMPS:
            target = ((word & 0x03FFFFFF) << 2) | upper
        else:
            imm = word & 0xFFFF
            if imm & 0x8000:
                imm -= 0x10000
            target = addr + 4 + (imm << 2)
        rl = reloc_by_addr.get((sec["index"], addr))
        if rl:
            rtype, rtarget, rsection, rsec = rl
            if rsection & SECTION_SELF_FLAG:
                idx = rsection & ~SECTION_SELF_FLAG
                if idx < len(sections):
                    target = sections[idx]["vram"] + rtarget
            elif rsection in (SECTION_IMPORT_VROM, SECTION_EVENT_VROM):
                return None, rsection  # resolved against the base game or another mod
        return target, None

    checked = 0
    undecodable = []
    unsupported = []
    floats = []
    bad_reloc = []
    bad_jump = []
    computed_jumps = 0
    jal_static = 0
    cop1_unnamed = []

    code_shapes_ok = {  # relocation type -> predicate on the instruction name
        5: lambda n: n == "lui",
        6: lambda n: n in LOADS or n in STORES or n in ADDISH,
        4: lambda n: n in JUMPS,
    }

    for sec in sections:
        blob = sec["blob"]
        for foff, fsize in sec["funcs"]:
            start = sec["vram"] + foff
            end = start + (fsize if fsize else 4)
            for addr in range(start, min(end, start + len(blob)), 4):
                rel = addr - sec["vram"]
                if rel + 4 > len(blob):
                    break
                word, = struct.unpack_from(">I", blob, rel)
                checked += 1
                name, rd, rs, rt = decode(word)
                if name is None or name.startswith("??"):
                    undecodable.append((addr, f"{word:#010x}", name))
                    continue
                if name in UNSUPPORTED_ENCODINGS:
                    unsupported.append((addr, name, f"{word:#010x}"))
                elif name and name.startswith("cop1:"):
                    cop1_unnamed.append((addr, name))
                if is_float(name):
                    floats.append((addr, name))
                rl = reloc_by_addr.get((sec["index"], addr))
                if rl:
                    rtype = rl[0]
                    if rtype in code_shapes_ok and not code_shapes_ok[rtype](name):
                        bad_reloc.append((addr, rtype, name))
                    elif rtype in (1, 2, 3, 7):
                        bad_reloc.append((addr, rtype, name))
                if name == "jalr" and rd != 31:
                    bad_jump.append((addr, f"jalr with return register ${rd} (only $ra is supported)"))
                if name == "jr" and rs != 31:
                    computed_jumps += 1
                if name in JUMPS or name in BRANCHES:
                    target, special = resolve_jump(addr, word, sec, name)
                    if special is None and target is not None:
                        inside = start <= target < end
                        known = target in func_starts
                        if not inside and not known:
                            if name == "jal":
                                jal_static += 1  # compiled as a synthetic static function
                            else:
                                bad_jump.append((addr, f"{name} to {target:#010x} which is neither "
                                                       f"inside its function nor a registered function start"))

    if undecodable:
        add(FAIL, "live/decodable", f"{len(undecodable)} word(s) inside functions that the target's "
            f"decoder cannot name, e.g. " + "; ".join(f"{a:#010x} {w}" for a, w, _ in undecodable[:3]))
    else:
        add(PASS, "live/decodable", f"all {checked} words inside the {len(func_starts)} registered "
            "function(s) decode as MIPS instructions")

    if unsupported:
        detail = "; ".join(f"{n} @ {a:#010x}" for a, n, _ in unsupported[:6])
        more = f" (+{len(unsupported) - 6} more)" if len(unsupported) > 6 else ""
        add(FAIL, "live/implemented", f"{len(unsupported)} MIPS32-R2+/MIPS-IV encoding(s) the R4300i "
            f"does not have, which makes the loader print \"Unhandled instruction: ...\" and fail the "
            f"whole mod: {detail}{more}. Build with -mcpu=mips2.")
    else:
        add(PASS, "live/implemented", "no instruction outside the R4300i set; the target's op table has "
            f"{len(supported)} entries and nothing here needs one it lacks")

    if floats:
        add(INFO, "live/float", f"{len(floats)} coprocessor-1 instruction(s) present; the op table "
            "implements lwc1/swc1/dmtc1/branch-on-fp but only part of the comparisons, so integer-only "
            "code is the safe path on this target"
            + (" (this build is not integer-only)" if not args.allow_float else ""))
    else:
        add(PASS, "live/float", "no floating-point instructions in the image")
    if cop1_unnamed:
        add(INFO, "live/cop1_names", f"{len(cop1_unnamed)} coprocessor-1 sub-op(s) this decoder does not "
            "name (they are inside functions, so the target will decode them with rabbitizer; only the "
            "known-missing encodings are failed outright)")

    if bad_reloc:
        names = {1: "R_MIPS_16", 2: "R_MIPS_32", 3: "R_MIPS_REL32", 4: "R_MIPS_26",
                 5: "R_MIPS_HI16", 6: "R_MIPS_LO16", 7: "R_MIPS_GPREL16"}
        add(FAIL, "live/reloc_shape", "; ".join(
            f"{names.get(t, t)} on {n} @ {a:#010x}" for a, t, n in bad_reloc[:6]) +
            " -- the recompiler pairs HI16 only with lui and LO16 only with loads/stores/adds")
    else:
        add(PASS, "live/reloc_shape", "every relocation lands on the instruction shape the recompiler accepts")

    if computed_jumps:
        add(INFO, "live/jump_tables", f"{computed_jumps} computed jump(s) (jr on a register other than "
            "$ra); the recompiler resolves switches through its jump-table machinery, which needs every "
            "case label to exist, so prefer -fno-jump-tables when a switch starts faulting")
    else:
        add(PASS, "live/jump_tables", "no computed jumps / jump tables")

    if bad_jump:
        add(FAIL, "live/jump_resolve", "; ".join(f"{a:#010x} {m}" for a, m in bad_jump[:5]) +
            " -- the recompiler resolves jumps via the registered function table only")
    else:
        add(PASS, "live/jump_resolve", "every jump and branch target resolves as the recompiler expects")

    if jal_static:
        add(INFO, "live/static_funcs", f"{jal_static} jal target(s) are not registered functions (import "
            "thunks and similar); the recompiler synthesizes a static function per target, which is what "
            "mods known to load on this target also do (dpad_builtin 35, save_editor 330, corelib 64)")

    return report(results, args.strict, args.quiet, mod_name)


def report(results, strict, quiet, mod_name):
    counts = {FAIL: 0, WARN: 0, PASS: 0, INFO: 0}
    for level, check, msg in results:
        counts[level] += 1
        if quiet and level not in (FAIL, WARN):
            continue
        print(f"{level:4s} {check:20s} {msg}")
    fails = counts[FAIL] + (counts[WARN] if strict else 0)
    print(f"\n{counts[FAIL]} fail, {counts[WARN]} warn, {counts[PASS]} pass, {counts[INFO]} info")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
