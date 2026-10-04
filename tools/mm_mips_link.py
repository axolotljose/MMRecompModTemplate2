#!/usr/bin/env python3
"""mm_mips_link.py - minimal MIPS32 (big-endian, o32) static linker for Zelda64 recomp mods.

The mod template's Makefile normally links mod code with
``ld.lld -T mod.ld --emit-relocs --unresolved-symbols=ignore-all``. Environments
without a MIPS capable linker (minimal containers, CI sandboxes) can use this
script instead; it produces an ELF that ``RecompModTool`` accepts.

What it does:
  * merges input sections into ``.text`` / ``.rodata`` / ``.data`` / ``.bss``, and
    keeps one output section per ``.recomp_*`` section (patch, export, import,
    hook, hook_return, event, callback) because the mod tool keys off those names;
  * lays the image out so ``sh_addr - sh_offset`` is a single constant for every
    allocated section, which is what makes the mod tool merge the whole image into
    one relocatable mod section (equivalent to ``-T mod.ld`` with ``--no-nmagic``);
  * resolves symbols across objects and applies MIPS relocations;
  * keeps relocations for internal and undefined (base game) symbols like
    ``--emit-relocs`` does, emitting SHT_REL ``.rel<name>`` sections where each
    R_MIPS_HI16 group is immediately followed by its matching R_MIPS_LO16 (the
    mod tool pairs them before sorting);
  * resolves PC relative relocations and drops them;
  * discards ``.got``, ``.MIPS.abiflags``, ``.reginfo``, ``.pdr``, ``.comment``,
    ``.eh_frame`` and debug sections, and fails loudly on PIC/small-data code,
    which mods cannot use.

Usage:
    python3 mm_mips_link.py --base 0x81000000 -o build/mod.elf a.o b.o ...
    python3 mm_mips_link.py --dump build/mod.elf
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mm_elf32 as E
from mm_elf32 import (RELOC_NAMES, SHN_ABS, SHN_COMMON, SHN_UNDEF, SHF_ALLOC, SHF_EXECINSTR,
                      SHF_INFO_LINK, SHF_WRITE, SHT_NOBITS, SHT_PROGBITS, SHT_REL, SHT_STRTAB,
                      SHT_SYMTAB, STT_FILE, STT_FUNC, STT_NOTYPE, STT_OBJECT, STT_SECTION, ElfFile)

R_MIPS_NONE, R_MIPS_16, R_MIPS_32, R_MIPS_REL32 = 0, 1, 2, 3
R_MIPS_26, R_MIPS_HI16, R_MIPS_LO16, R_MIPS_GPREL16 = 4, 5, 6, 7
R_MIPS_LITERAL, R_MIPS_GOT16, R_MIPS_PC16, R_MIPS_CALL16 = 8, 9, 10, 11

# Input sections that never belong in a mod image.
DISCARD_PREFIXES = (".debug", ".note", ".comment", ".eh_frame", ".llvm_addrsig", ".pdr",
                    ".reginfo", ".MIPS.", ".mdebug", ".gnu.attributes", ".strtab", ".symtab",
                    ".shstrtab", ".rel")
# Sections whose presence means the code was not compiled the way mods require.
FORBIDDEN_SECTIONS = (".got", ".got2", ".lit8", ".lit4", ".sdata", ".sbss")
# Relocation types this linker refuses to silently mishandle.
UNSUPPORTED_RELOCS = (R_MIPS_GPREL16, R_MIPS_LITERAL, R_MIPS_GOT16, R_MIPS_CALL16, 13, 14, 15, 21, 22, 23)

SECTION_PRIORITY = {".text": 0, ".rodata": 1, ".data": 2}


def out_name_for(name: str) -> str:
    """Map an input section name onto the output section it belongs to."""
    if name.startswith(".recomp"):
        return name  # special mod sections keep their exact names
    if name == ".text" or name.startswith(".text."):
        return ".text"
    if name in (".rodata", ".rodata1") or name.startswith(".rodata."):
        return ".rodata"
    if name in (".data", ".data1", ".data.rel.ro") or name.startswith(".data."):
        return ".data"
    if name.startswith(".sdata"):
        return ".data"
    if name.startswith(".bss") or name.startswith(".sbss"):
        return ".bss"
    return name


def sign_extend(value, bits):
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


class InputObj:
    __slots__ = ("path", "elf", "sections", "symbols", "relocs")

    def __init__(self, path):
        self.path = Path(path)
        self.elf = ElfFile.load(self.path)
        self.sections = self.elf.sections
        self.symbols = self.elf.symbols
        self.relocs = self.elf.relocs

    def section_data(self, index):
        sec = self.sections[index]
        if sec.sh_type == SHT_NOBITS:
            return bytearray(sec.size)
        return bytearray(sec.data)

class MipsOpcodes:
    """MIPS opcode tables, used only to sanity check that the linked image is real code.

    Anything the R4300 (MIPS III) cannot encode is left out, so a mis-linked word -- a data blob
    filed into .text, or an immediate that swallowed an opcode -- trips the verifier instead of
    crashing the emulator in the middle of gameplay.
    """

    # Reserved, COP-unreachable or MIPS32r6-only primary opcodes.
    INVALID_PRIMARY = {9, 10, 11, 12, 13, 14, 15, 29, 30, 31}
    PRIMARY_OPS = set(range(64)) - INVALID_PRIMARY
    # SPECIAL (opcode 0) function codes, and REGIMM (opcode 1) branch conditions.
    SPECIAL_FUNCS = {0x00, 0x02, 0x03, 0x04, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0F,
                     0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x1B,
                     0x1C, 0x1D, 0x1E, 0x1F, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27,
                     0x28, 0x29, 0x2A, 0x2B, 0x2C, 0x2D, 0x2E, 0x2F,
                     0x30, 0x31, 0x32, 0x33, 0x34, 0x36}
    REGIMM_FUNCS = {0x00, 0x01, 0x10, 0x11, 0x12, 0x13}
    # I-type branches whose target is a sign extended 16 bit offset, in words.
    BRANCH_OPS = {4, 5, 6, 7, 20, 21}


# Reloc types the mod runtime can apply (librecomp's RelocEntryType stops at R_MIPS_GPREL16 and the
# live recompiler only consumes these four).
LOADER_APPLIES = {R_MIPS_16, R_MIPS_32, R_MIPS_26, R_MIPS_HI16, R_MIPS_LO16}


class Chunk:
    """One input section placed inside an output section."""
    __slots__ = ("obj", "sec_index", "offset", "size")

    def __init__(self, obj, sec_index, offset, size):
        self.obj = obj
        self.sec_index = sec_index
        self.offset = offset
        self.size = size


class OutSec:
    def __init__(self, name):
        self.name = name
        self.kind = SHT_PROGBITS
        self.flags = SHF_ALLOC
        self.align = 4
        self.chunks = []
        self.data = bytearray()
        self.addr = 0
        self.size = 0
        self.bss_size = 0
        self.relocs = []

    @property
    def end(self):
        return self.addr + (self.bss_size if self.kind == SHT_NOBITS else self.size)


def parse_reference_syms(path):
    """Read a Zelda64RecompSyms *.syms.toml / *.datasyms.toml into {name: (section_rom, section_vram, vram)}.

    Those files are the only description of where the base game's functions and variables live, which
    is what a mod's reference relocations have to be resolved against (the same lookup RecompModTool
    does through its recompiler context). Sections are matched by the function's own vram because the
    files list each symbol's vram but only each section's rom/vram.
    """
    text = Path(path).read_text(errors="replace")
    result = {}
    sections = []
    # Note the two files are not shaped the same way: *.syms.toml sections carry a rom address,
    # *.datasyms.toml sections only a vram (and their symbols no size), so a missing rom becomes 0.
    # That is safe because reference *variables* are patched by absolute address and never get a
    # relocation record, while reference *functions* always come from *.syms.toml (see mm_nrm_pack).
    cur = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line == "[[section]]":
            cur = {"rom": None, "vram": None}
            sections.append(cur)
            continue
        if cur is None:
            continue
        if line.startswith("rom"):
            cur["rom"] = int(line.split("=", 1)[1].split("#")[0].strip(), 0)
        elif line.startswith("vram"):
            cur["vram"] = int(line.split("=", 1)[1].split("#")[0].strip(), 0)
        elif line.startswith("{"):
            m = re.search(r'name\s*=\s*"([^"]+)"', line)
            v = re.search(r'vram\s*=\s*(0x[0-9A-Fa-f]+)', line)
            if m and v:
                sections[-1].setdefault("syms", []).append((m.group(1), int(v.group(1), 0)))
    for sec in sections:
        if sec["vram"] is None:
            continue
        for name, vram in sec.get("syms", []):
            result.setdefault(name, (sec["rom"] or 0, sec["vram"], vram))
    return result


class Linker:
    def __init__(self, object_paths, base=0, image_offset=0x1000, min_align=16, verify_code=True,
                 reference_funcs=None, reference_data=None):
        # name -> (section_rom, section_vram, vram) for base game functions and variables. A
        # reference *function* keeps a relocation (the loader patches the call to the native
        # implementation); a reference *variable* is patched here and gets no relocation, which is
        # exactly what RecompModTool does for non-relocatable reference sections.
        self.reference_funcs = reference_funcs or {}
        self.reference_data = reference_data or {}
        self.base = base
        self.image_offset = image_offset
        self.verify_code = verify_code
        self.min_align = min_align
        self.inputs = [InputObj(p) for p in object_paths]
        if not self.inputs:
            raise SystemExit("error: no input objects given")
        self.sections = []
        self.sec_of = {}          # (obj id, input section idx) -> (OutSec, offset in out section)
        self.symbols = []         # output symtab entries
        self.symbol_of = {}       # (obj id, input symbol idx) -> resolved symbol dict
        self.globals = {}         # name -> winning resolved symbol
        self.undef_symbols = {}   # name -> output symbol index
        self.section_symbols = {}  # id(OutSec) -> output symbol index
        self.elf_section_index = {}  # id(OutSec) -> index in the output section header table

    # -- section merging ----------------------------------------------------
    def collect_sections(self):
        by_name = {}
        for obj in self.inputs:
            for idx, sec in enumerate(obj.sections):
                if sec.sh_type not in (SHT_PROGBITS, SHT_NOBITS) or not (sec.flags & SHF_ALLOC):
                    continue
                for forbidden in FORBIDDEN_SECTIONS:
                    if (sec.name == forbidden or sec.name.startswith(forbidden + ".")) and sec.size:
                        raise SystemExit(
                            f"error: {obj.path}: section {sec.name} cannot be used in a mod; compile with "
                            f"-mno-abicalls -fno-pic -G0 so no GOT or small data sections are generated")
                if sec.size == 0:
                    continue
                if any(sec.name.startswith(p) for p in DISCARD_PREFIXES) and not sec.name.startswith(".recomp"):
                    continue
                name = out_name_for(sec.name)
                out = by_name.get(name)
                if out is None:
                    out = OutSec(name)
                    by_name[name] = out
                    self.sections.append(out)
                out.kind = sec.sh_type
                out.flags |= sec.flags
                out.align = max(out.align, sec.addralign or 4, 4)
                out.chunks.append(Chunk(obj, idx, 0, sec.size))
        progbits = sorted([s for s in self.sections if s.kind != SHT_NOBITS],
                          key=lambda s: (SECTION_PRIORITY.get(s.name, 3), s.name))
        nobits = sorted([s for s in self.sections if s.kind == SHT_NOBITS], key=lambda s: s.name)
        if not progbits:
            raise SystemExit("error: no allocated content sections found in the input objects")
        self.sections = progbits + nobits
        for i, out in enumerate(self.sections):
            out.flags |= SHF_ALLOC
            if out.name == ".text" or out.name.startswith(".recomp"):
                out.flags |= SHF_EXECINSTR
            self.elf_section_index[id(out)] = i + 1  # +1 because index 0 is the null section

    # -- layout -------------------------------------------------------------
    def layout(self):
        cursor = self.image_offset
        for out in self.sections:
            align = max(out.align, self.min_align)
            cursor = (cursor + align - 1) & ~(align - 1)
            out.addr = self.base + cursor
            inner = 0
            for chunk in out.chunks:
                sec = chunk.obj.sections[chunk.sec_index]
                chunk_align = max(sec.addralign or 4, 4)
                inner = (inner + chunk_align - 1) & ~(chunk_align - 1)
                data = chunk.obj.section_data(chunk.sec_index)
                if inner > len(out.data):
                    out.data += b"\0" * (inner - len(out.data))
                out.data += data
                chunk.offset = inner
                chunk.size = len(data)
                inner += len(data)
                self.sec_of[(id(chunk.obj), chunk.sec_index)] = (out, chunk.offset)
            if out.kind == SHT_NOBITS:
                out.bss_size = (inner + self.min_align - 1) & ~(self.min_align - 1)
                out.data = bytearray()
                out.size = 0
                cursor += out.bss_size
            else:
                out.data += b"\0" * ((4 - (inner % 4)) % 4)
                out.size = len(out.data)
                cursor += out.size

    # -- symbol resolution ----------------------------------------------------
    def resolve_symbols(self):
        candidates = {}
        for obj in self.inputs:
            for idx, sym in enumerate(obj.symbols):
                if not sym.name or sym.type == STT_FILE:
                    continue
                if sym.shndx == SHN_COMMON:
                    raise SystemExit(f"error: {obj.path}: common symbol {sym.name}: compile with -fno-common")
                addr = None
                if sym.shndx == SHN_ABS:
                    addr = sym.value
                elif sym.shndx == SHN_UNDEF:
                    addr = None
                elif sym.shndx < len(obj.sections):
                    mapped = self.sec_of.get((id(obj), sym.shndx))
                    if mapped is None:
                        continue  # defined in a section that was discarded
                    out, off = mapped
                    addr = out.addr + off + sym.value
                else:
                    continue
                res = {"name": sym.name, "addr": addr if addr is not None else 0,
                       "defined": addr is not None, "size": sym.size, "type": sym.type,
                       "bind": sym.bind, "obj": obj, "alias": None}
                self.symbol_of[(id(obj), idx)] = res
                if sym.bind in (E.STB_GLOBAL, E.STB_WEAK):
                    candidates.setdefault(sym.name, []).append(res)
        for name, entries in candidates.items():
            if len(entries) > 1:
                defs = [e for e in entries if e["defined"] and e["bind"] == E.STB_GLOBAL]
                if len(defs) > 1:
                    where = ", ".join(str(d["obj"].path.name) for d in defs)
                    raise SystemExit(f"error: duplicate definition of global symbol {name} in: {where}")
            entries.sort(key=lambda e: (0 if e["defined"] else 1, 0 if e["bind"] == E.STB_GLOBAL else 1))
            winner = entries[0]
            self.globals[name] = winner
            for entry in entries:
                entry["alias"] = winner
        for res in self.symbol_of.values():
            if res["alias"] is None and res["bind"] in (E.STB_GLOBAL, E.STB_WEAK):
                res["alias"] = self.globals.get(res["name"])

    def lookup(self, obj, sym_index):
        """Resolve an input symbol reference: (addr_or_None, name, defined, sym_type)."""
        if sym_index >= len(obj.symbols):
            return None, "", False, STT_NOTYPE
        sym = obj.symbols[sym_index]
        if sym.type == STT_SECTION:
            mapped = self.sec_of.get((id(obj), sym.shndx))
            if mapped is None:
                return None, "", False, sym.type
            out, off = mapped
            return out.addr + off + sym.value, "", True, sym.type
        res = self.symbol_of.get((id(obj), sym_index))
        if res is None:
            return None, sym.name, False, sym.type
        res = res["alias"] or res
        return (res["addr"] if res["defined"] else None), res["name"], res["defined"], res["type"]

    # -- output symbol table ----------------------------------------------------
    def build_symbol_table(self):
        self.symbols = [{"name": "", "value": 0, "size": 0, "info": 0, "other": 0, "shndx": SHN_UNDEF}]
        for out in self.sections:
            self.section_symbols[id(out)] = len(self.symbols)
            self.symbols.append({"name": "", "value": 0, "size": 0,
                                 "info": (E.STB_LOCAL << 4) | STT_SECTION, "other": 0,
                                 "shndx": self.elf_section_index[id(out)]})
        # Carry over every defined function symbol, not just the ones that happen to be referenced.
        #
        # This is the single most important thing this linker does. RecompModTool records one entry in
        # the mod symbol file's function table per STT_FUNC symbol with a size, and the runtime live
        # recompiles *exactly those* functions -- nothing else. A helper that is missing from the table
        # is therefore never turned into code: the call site stays a jal to a mod address that has no
        # compiled body, and the first frame that reaches it faults. That is a hard crash at game start
        # (no mod error dialog, because the package itself parsed fine), and it is invisible on a PC
        # build that never runs the mod. Locals must precede globals, hence this runs first.
        self._emitted_func_addrs = set()
        seen_funcs = self._emitted_func_addrs
        for out in self.sections:
            if out.kind == SHT_NOBITS:
                continue
            for chunk in out.chunks:
                for sym in chunk.obj.symbols:
                    if sym.shndx != chunk.sec_index or sym.type != STT_FUNC or sym.size == 0:
                        continue
                    addr = out.addr + chunk.offset + sym.value
                    if addr in seen_funcs:
                        continue
                    seen_funcs.add(addr)
                    local = sym.bind == E.STB_LOCAL
                    self.symbols.append({"name": sym.name, "value": addr, "size": sym.size,
                                         "info": ((E.STB_LOCAL if local else E.STB_GLOBAL) << 4) | STT_FUNC,
                                         "other": 0, "shndx": self.elf_section_index[id(out)],
                                         "local": local})

        self.first_global = len(self.symbols)
        for name, res in sorted(self.globals.items()):
            if not res["defined"]:
                continue
            if res["type"] not in (STT_FUNC, STT_OBJECT, STT_NOTYPE):
                continue
            addr = res["addr"]
            if res["type"] == STT_FUNC and addr in getattr(self, "_emitted_func_addrs", ()):
                continue  # already carried over from the input object's symbol table
            self.symbols.append({"name": name, "value": addr, "size": res["size"],
                                 "info": (E.STB_GLOBAL << 4) | res["type"], "other": 0,
                                 "shndx": self.section_index_of_address(addr)})

    def section_index_of_address(self, addr):
        for out in self.sections:
            if out.addr <= addr < out.end:
                return self.elf_section_index[id(out)]
        return 0

    def undefined_symbol(self, name, type_):
        idx = self.undef_symbols.get(name)
        if idx is not None:
            return idx
        info = (E.STB_GLOBAL << 4) | (type_ if type_ in (STT_FUNC, STT_OBJECT) else STT_NOTYPE)
        idx = len(self.symbols)
        self.symbols.append({"name": name, "value": 0, "size": 0, "info": info, "other": 0,
                             "shndx": SHN_UNDEF})
        self.undef_symbols[name] = idx
        return idx

    def reloc_symbol_for(self, addr, defined, name, type_):
        """Which symtab index a relocation record should name.

        Relocs against the mod's own image name the section they landed in, exactly like `ld -r`
        output, while relocs that point into the base game stay *undefined* by name: that is what
        RecompModTool keys its reference resolution off, and an absolute address would be wrong as
        soon as the loader moves the mod image.
        """
        if not defined:
            return self.undefined_symbol(name, type_)
        for out in self.sections:
            if out.addr <= addr < out.end:
                return self.section_symbols[id(out)]
        if name in self.reference_funcs or name in self.reference_data:
            return self.undefined_symbol(name, type_)
        raise SystemExit(f"error: relocation at {addr:#x} against {name} lies outside the mod image "
                         f"(a symbol the linker resolved but that is in no output section)")

    # -- relocation application --------------------------------------------------
    def relocate(self):
        self.build_symbol_table()
        for out in self.sections:
            out.relocs = []
            if out.kind == SHT_NOBITS:
                continue
            entries = []
            for chunk in out.chunks:
                for r in chunk.obj.relocs.get(chunk.sec_index, []):
                    if r.type == R_MIPS_NONE:
                        continue
                    entries.append({"addr": chunk.offset + r.offset, "chunk": chunk, "r": r})
            if not entries:
                continue
            entries.sort(key=lambda e: (e["addr"], e["r"].type))
            self.relocate_section(out, entries)

    def relocate_section(self, out, entries):
        from collections import defaultdict, deque

        def fail(entry, msg):
            obj = entry["chunk"].obj
            raise SystemExit(f"error: {obj.path}: {msg} at {out.addr + entry['addr']:#x} in {out.name}")

        for entry in entries:
            if entry["r"].type in UNSUPPORTED_RELOCS:
                fail(entry, f"unsupported relocation {RELOC_NAMES.get(entry['r'].type, entry['r'].type)}; "
                            f"mods must be compiled with -G0 -mno-abicalls -fno-pic")

        # Pair HI16 groups with the following LO16 for the same symbol, matching what
        # ld.lld does so the mod tool's pairing pass sees them adjacent in the output.
        pending = defaultdict(deque)
        pairs = []          # (sort_key, [hi entries], lo entry or None)
        others = []
        for entry in entries:
            r = entry["r"]
            if r.type == R_MIPS_HI16:
                pending[r.symbol].append(entry)
                continue
            if r.type == R_MIPS_LO16:
                his = list(pending[r.symbol])
                pending[r.symbol].clear()
                if his:
                    pairs.append((entry["addr"], his, entry))
                else:
                    pairs.append((entry["addr"], [], entry))
                continue
            others.append(entry)
        # Unpaired HI16/LO16 relocs are legitimate (MIPS System V ABI: an LO16 without an
        # immediately preceding HI16 reuses the high half materialised earlier, and a HI16 whose
        # matching LO16 was folded into another instruction stays standalone). ld.lld emits them
        # as-is and the mod tool documents them, so route them through the single reloc path.
        for sym, queue in pending.items():
            while queue:
                others.append(queue.popleft())

        resolved = {}

        def resolve(entry):
            key = id(entry)
            if key not in resolved:
                chunk, r = entry["chunk"], entry["r"]
                resolved[key] = self.lookup(chunk.obj, r.symbol)
            return resolved[key]

        def bake(entry, hi_value=None, lo_value=None):
            """Return (defined, addr, name, type) for the entry's symbol."""
            return resolve(entry)

        def reference(name):
            """(kind, section_rom, section_vram, vram) if the name is a base game symbol."""
            if name in self.reference_funcs:
                rom, svram, vram = self.reference_funcs[name]
                return "function", rom, svram, vram
            if name in self.reference_data:
                rom, svram, vram = self.reference_data[name]
                return "data", rom, svram, vram
            return None

        emitted = []  # (sort_key, order, reloc dict)
        for lo_addr, his, lo in pairs:
            target, name, defined, stype = resolve(lo)
            addend = lo["r"].addend
            ref = None if defined else reference(name)
            if ref is not None:
                kind, ref_rom, ref_svram, ref_vram = ref
                target, defined = ref_vram, True
                if kind == "data":
                    # Patched in place, no record: the base game's data keeps its original address.
                    ref = ("data-patched", ref_rom, ref_svram, ref_vram)
                else:
                    ref = ("function", ref_rom, ref_svram, ref_vram)
            elif not defined:
                raise SystemExit(f"error: {name or 'unnamed'} is referenced by the mod but exists in "
                                 f"neither the function nor the data reference symbols; a mod can only "
                                 f"call base game symbols or RECOMP_IMPORTs")
            lo_word = struct.unpack_from(">I", out.data, lo_addr)[0]
            if his:
                hi_addr = his[0]["addr"]
                hi_word = struct.unpack_from(">I", out.data, hi_addr)[0]
                addend += his[0]["r"].addend
            else:
                hi_word = 0
            full = (((hi_word & 0xFFFF) << 16) + sign_extend(lo_word & 0xFFFF, 16))
            full = (full + (target if defined else 0) + addend) & 0xFFFFFFFF
            hi_value = ((full + 0x8000) >> 16) & 0xFFFF
            lo_value = full & 0xFFFF
            record = None
            if ref is not None and ref[0] == "function":
                record = {"kind": "reference", "ref_rom": ref[1], "ref_svram": ref[2]}
            for entry in his:
                word = struct.unpack_from(">I", out.data, entry["addr"])[0]
                struct.pack_into(">I", out.data, entry["addr"], (word & 0xFFFF0000) | hi_value)
                # Reference data pairs are patched above and intentionally left unrecorded, so a
                # function reference is the only case that still needs a record here.
                if record is not None or ref is None:
                    rel = {"offset": out.addr + entry["addr"],
                           "symbol": self.reloc_symbol_for(full, defined, name, stype),
                           "type": R_MIPS_HI16, "value": full, "name": name}
                    rel.update(record or {})
                    emitted.append((lo_addr, 0, rel))
            word = struct.unpack_from(">I", out.data, lo_addr)[0]
            struct.pack_into(">I", out.data, lo_addr, (word & 0xFFFF0000) | lo_value)
            if his and (record is not None or ref is None):
                rel = {"offset": out.addr + lo_addr,
                       "symbol": self.reloc_symbol_for(full, defined, name, stype),
                       "type": R_MIPS_LO16, "value": full, "name": name}
                rel.update(record or {})
                emitted.append((lo_addr, 1, rel))
            else:
                # Orphaned LO16: still record it so the loader can shift the value.
                others.append(lo)

        for entry in others:
            r = entry["r"]
            addr = entry["addr"]
            target, name, defined, stype = resolve(entry)
            word = struct.unpack_from(">I", out.data, addr)[0] if addr + 4 <= len(out.data) else 0
            ref = None if defined else reference(name)
            if ref is not None:
                kind, ref_rom, ref_svram, ref_vram = ref
                target, defined = ref_vram, True
                value = target + r.addend
            else:
                ref_rom = ref_svram = 0
                value = (target if defined else 0) + r.addend
            if ref is not None and ref[0] == "data":
                # Reference data: bake the address, emit no record (matches RecompModTool).
                if r.type == R_MIPS_32:
                    struct.pack_into(">I", out.data, addr, (word + value) & 0xFFFFFFFF)
                elif r.type == R_MIPS_LO16:
                    struct.pack_into(">I", out.data, addr, (word & 0xFFFF0000) | (value & 0xFFFF))
                elif r.type == R_MIPS_HI16:
                    struct.pack_into(">I", out.data, addr,
                                     (word & 0xFFFF0000) | (((value + 0x8000) >> 16) & 0xFFFF))
                else:
                    fail(entry, f"cannot patch reference variable {name} with {RELOC_NAMES.get(r.type)}")
                continue

            if r.type == R_MIPS_26:
                struct.pack_into(">I", out.data, addr,
                                 (word & 0xFC000000) | (((value & 0x0FFFFFFF) >> 2) & 0x03FFFFFF))
                rel = {"offset": out.addr + addr, "symbol": self.reloc_symbol_for(value, defined, name, stype),
                       "type": R_MIPS_26, "value": value, "name": name}
                if ref is not None:
                    rel["kind"] = "reference"
                    rel["ref_rom"] = ref_rom
                    rel["ref_svram"] = ref_svram
                out.relocs.append(rel)
                continue
            if r.type == R_MIPS_32:
                struct.pack_into(">I", out.data, addr, (word + value) & 0xFFFFFFFF)
                rel = {"offset": out.addr + addr, "symbol": self.reloc_symbol_for(value, defined, name, stype),
                       "type": R_MIPS_32, "value": value, "name": name}
                if ref is not None:
                    rel["kind"] = "reference"
                    rel["ref_rom"] = ref_rom
                    rel["ref_svram"] = ref_svram
                out.relocs.append(rel)
                continue
            if r.type == R_MIPS_16:
                struct.pack_into(">H", out.data, addr, (word + value) & 0xFFFF)
                continue
            if r.type == R_MIPS_LO16:
                # Orphaned LO16: only the low half is stored in this instruction, the high half
                # comes from an earlier LUI. Keep the reloc so the loader can still shift it.
                struct.pack_into(">I", out.data, addr, (word & 0xFFFF0000) | (value & 0xFFFF))
                out.relocs.append({"offset": out.addr + addr,
                                   "symbol": self.reloc_symbol_for(value, defined, name, stype),
                                   "type": R_MIPS_LO16, "value": value, "name": name})
                continue
            if r.type == R_MIPS_HI16:
                # Orphaned HI16: round the address up so the matching (unrelocated) low half
                # stays in [0, 0xFFFF] after the sign extension the instruction implies.
                hi_value = ((value + 0x8000) >> 16) & 0xFFFF
                struct.pack_into(">I", out.data, addr, (word & 0xFFFF0000) | hi_value)
                out.relocs.append({"offset": out.addr + addr,
                                   "symbol": self.reloc_symbol_for(value, defined, name, stype),
                                   "type": R_MIPS_HI1, "value": value, "name": name})
                continue
            if r.type in (R_MIPS_PC16, R_MIPS_REL32):
                if not defined:
                    fail(entry, f"PC relative relocation targets undefined symbol {name}")
                delta = (target + r.addend) - (out.addr + addr)
                struct.pack_into(">I", out.data, addr, (word & 0xFFFF0000) | ((delta >> 2) & 0xFFFF))
                continue
            fail(entry, f"unhandled relocation type {r.type} ({RELOC_NAMES.get(r.type, '?')})")

        # Final order: address order, with each HI16 group immediately before its LO16.
        out.relocs.extend(rel for (_key, _order, rel) in sorted(emitted, key=lambda t: (t[0], t[1])))
        out.relocs.sort(key=lambda rel: rel["offset"]) if False else None

    # -- ELF emission ------------------------------------------------------------
    def emit(self):
        specs = [{"name": "", "sh_type": 0, "flags": 0, "addr": 0, "size": 0, "offset": 0,
                  "addralign": 0, "entsize": 0}]
        for out in self.sections:
            specs.append({"name": out.name, "sh_type": out.kind, "flags": out.flags, "addr": out.addr,
                          "offset": out.addr - self.base,
                          "size": out.bss_size if out.kind == SHT_NOBITS else out.size,
                          "data": None if out.kind == SHT_NOBITS else bytes(out.data),
                          "addralign": max(out.align, 16), "entsize": 0, "link": 0, "info": 0})
        rel_specs = []
        symtab_index = len(specs) + sum(1 for o in self.sections if o.relocs)
        for out in self.sections:
            if not out.relocs:
                continue
            rel_specs.append({"name": ".rel" + out.name, "sh_type": SHT_REL, "flags": SHF_INFO_LINK,
                              "addr": 0, "offset": None, "size": 0, "addralign": 4, "entsize": 8,
                              "link": symtab_index, "info": self.elf_section_index[id(out)],
                              "relocs": out.relocs, "reloc_target": self.elf_section_index[id(out)]})
        specs.extend(rel_specs)
        assert len(specs) == symtab_index
        specs.append({"name": ".symtab", "sh_type": SHT_SYMTAB, "flags": 0, "addr": 0, "offset": None,
                      "size": 0, "addralign": 4, "entsize": 16, "link": len(specs) + 1,
                      "info": self.first_global})
        specs.append({"name": ".strtab", "sh_type": SHT_STRTAB, "flags": 0, "addr": 0, "offset": None,
                      "size": 0, "addralign": 1, "entsize": 0, "link": 0, "info": 0})
        specs.append({"name": ".shstrtab", "sh_type": SHT_STRTAB, "flags": 0, "addr": 0, "offset": None,
                      "size": 0, "addralign": 1, "entsize": 0, "link": 0, "info": 0})
        image_end = self.image_offset
        for out in self.sections:
            span = out.bss_size if out.kind == SHT_NOBITS else out.size
            image_end = max(image_end, (out.addr - self.base) + span)
        segments = [{"p_type": E.PT_LOAD, "offset": 0, "vaddr": self.base, "paddr": self.base,
                     "filesz": image_end, "memsz": image_end, "flags": SHF_WRITE | SHF_ALLOC | SHF_EXECINSTR,
                     "align": 0x10}]
        return ElfFile.write(E.ET_EXEC, E.EM_MIPS, 0, 0, specs, self.symbols, segments)

    # -- mod symbol file records -------------------------------------------------------
    def build_nrm_records(self):
        """Produce everything the mod symbol file needs, in the shape tools/mm_nrm_pack.py writes.

        The rules are a faithful port of RecompModTool's collection pass: input sections that share a
        rom-to-ram delta merge into one output section; import sections contribute no functions or
        relocations (their thunks are dummy code and imports are discovered from the call sites that
        target them); each function in a .recomp_hook[.return].<name> section becomes a hook record
        carrying the hooked base function's section rom and vram; relocations to the mod's own image
        are recorded as (offset, type, offset-in-image) against the self section, while reference
        functions are recorded against their game section so the loader can patch the call.
        """
        IMPORT_PREFIX = ".recomp_import."
        HOOK_PREFIX = ".recomp_hook."
        HOOK_RETURN_PREFIX = ".recomp_hook_return."
        alloc = [out for out in self.sections if out.kind != SHT_NOBITS]
        if not alloc:
            raise SystemExit("error: linked image has no allocated sections")
        image_base = min(out.addr for out in alloc)
        image_end = max(out.addr + out.size for out in alloc)
        rom_size = image_end - image_base
        bss_end = image_end
        for out in self.sections:
            if out.kind == SHT_NOBITS and out.addr <= bss_end + 16:
                bss_end = max(bss_end, out.addr + out.bss_size)
        bss_size = bss_end - image_end

        def is_import(out):
            return out.name.startswith(IMPORT_PREFIX)

        # Functions, in ascending image offset (the order the reference tool's output ends up in).
        funcs = []
        func_index_at = {}
        for out in alloc:
            if is_import(out):
                continue
            for chunk in out.chunks:
                for sym in chunk.obj.symbols:
                    if sym.shndx != chunk.sec_index or sym.type != STT_FUNC or sym.size == 0:
                        continue
                    addr = out.addr + chunk.offset + sym.value
                    funcs.append((addr - image_base, sym.size, sym.name, out.name))
        funcs.sort(key=lambda f: f[0])
        for i, f in enumerate(funcs):
            func_index_at[f[0]] = i
        dupes = len(funcs) - len(func_index_at)
        if dupes:
            raise SystemExit(f"error: {dupes} duplicate function address(es) in the linked image")

        # Import thunks: name -> the .recomp_import.<dep> section they live in.
        import_addrs = {}
        for out in alloc:
            if not is_import(out):
                continue
            dep = out.name[len(IMPORT_PREFIX):]
            for chunk in out.chunks:
                for sym in chunk.obj.symbols:
                    if sym.shndx != chunk.sec_index or sym.size == 0:
                        continue
                    import_addrs[out.addr + chunk.offset + sym.value] = (sym.name, dep)
        # An import record is created per import *call site*, not per declared thunk. The mod API
        # headers declare far more functions than any one mod uses, and every record the tool did not
        # emit would oblige the loader to resolve an API symbol this mod never calls - which fails the
        # whole mod on a runtime that does not export it. Collecting them from the call sites is what
        # RecompModTool does, so a package built here and one built by the tool agree on this table.
        imports = []  # (name, dep) in first-use order, matching the reloc indices below
        import_index = {}
        deps = []

        relocs = []
        for out in alloc:
            if is_import(out):
                continue
            for rel in out.relocs:
                if rel["type"] == R_MIPS_NONE:
                    continue
                offset = rel["offset"] - image_base
                if "value" not in rel:
                    raise SystemExit(f"error: internal: relocation record at {rel['offset']:#x} "
                                     f"(type {rel['type']}) carries no resolved value")
                target_addr = rel["value"]
                if rel.get("kind") == "reference":
                    relocs.append([offset, rel["type"], target_addr - rel["ref_svram"], rel["ref_rom"]])
                    continue
                thunk = import_addrs.get(target_addr)
                if thunk is not None:
                    name, dep = thunk
                    idx = import_index.get(name)
                    if idx is None:
                        idx = len(imports)
                        import_index[name] = idx
                        imports.append((name, dep))
                        if dep not in deps:
                            deps.append(dep)
                    relocs.append([offset, rel["type"], idx, 0xFFFFFFFE])
                    continue
                if not (image_base <= target_addr < image_end + bss_size):
                    raise SystemExit(f"error: relocation at {rel['offset']:#x} targets {target_addr:#x}, "
                                     f"outside the mod image; only the image, its bss, imports and "
                                     f"reference symbols may be relocated")
                relocs.append([offset, rel["type"], target_addr - image_base, 0x80000000])
        relocs.sort(key=lambda r: (r[0], r[1]))
        if not deps:
            deps = ["*"]  # the base game is always a dependency of a code mod

        hooks = []
        for out in alloc:
            if out.name.startswith(HOOK_RETURN_PREFIX):
                hooked, flags = out.name[len(HOOK_RETURN_PREFIX):], 1
            elif out.name.startswith(HOOK_PREFIX):
                hooked, flags = out.name[len(HOOK_PREFIX):], 0
            else:
                continue
            if hooked not in self.reference_funcs:
                raise SystemExit(f"error: hook target {hooked} is not a function in the reference symbols")
            rom, svram, vram = self.reference_funcs[hooked]
            for chunk in out.chunks:
                for sym in chunk.obj.symbols:
                    if sym.shndx != chunk.sec_index or sym.type != STT_FUNC or sym.size == 0:
                        continue
                    foff = out.addr + chunk.offset + sym.value - image_base
                    if foff not in func_index_at:
                        raise SystemExit(f"error: hook function for {hooked} was not registered as a function")
                    hooks.append([func_index_at[foff], rom, vram, flags])

        return {
            "image_base": image_base,
            "image_file_offset": image_base - self.base,
            "rom_size": rom_size,
            "bss_size": bss_size,
            "funcs": [[off, size] for off, size, _name, _sec in funcs],
            "func_names": [name for _off, _size, name, _sec in funcs],
            "func_sections": [sec for _off, _size, _name, sec in funcs],
            "relocs": relocs,
            "imports": [[name, dep] for name, dep in imports],
            "deps": deps,
            "hooks": hooks,
        }

    def run(self):
        self.collect_sections()
        self.layout()
        self.resolve_symbols()
        self.relocate()
        if self.verify_code:
            errors = self.verify()
            if errors:
                raise SystemExit("error: linked image failed verification:\n  " + "\n  ".join(errors[:20]))
        return self.emit()


    # -- post link verification -----------------------------------------------------
    def verify(self):
        """Check the linked image is loadable code, not just well-formed bytes.

        A mod is live recompiled instruction by instruction, so a mis-linked word does not fail to
        load: it crashes the emulator mid-gameplay. Two mistakes matter, and both are linker bugs
        rather than compiler ones, so they are worth catching here:

          * a jump whose target escaped the image (a section laid out at the wrong address, or a
            relocation that was resolved against a symbol the tool never exports), and
          * a HI16 followed in the relocation list by an LO16 for a different symbol, which the
            mod tool rejects outright, plus relocation types the runtime cannot apply at all.
        """
        errors = []
        spans = [(out.addr, out.addr + (out.bss_size if out.kind == SHT_NOBITS else out.size))
                 for out in self.sections]

        def inside(addr):
            return any(start <= addr < end for start, end in spans)

        for out in self.sections:
            if not (out.flags & 0x4) or out.kind == SHT_NOBITS:
                continue
            data = bytes(out.data)
            # Calls to the base game and to the base API are intentionally emitted as jal 0: the
            # R_MIPS_26 relocation attached to them is what resolves the target (the mod tool keeps
            # the reloc, and the runtime patches the jump once it knows the recompiled address). So
            # an out of image jump is only a bug when nothing will ever fix it up.
            call_relocs = {rel["offset"] for rel in out.relocs if rel["type"] == R_MIPS_26}
            for offset in range(0, len(data) - 3, 4):
                addr = out.addr + offset
                word = struct.unpack_from(">I", data, offset)[0]
                op = word >> 26
                if op in (2, 3):  # j / jal: 26 bit target inside the current 256MB region
                    target = (addr & 0xF0000000) | ((word & 0x03FFFFFF) << 2)
                    if not inside(target) and addr not in call_relocs:
                        errors.append(f"{addr:#x}: {'jal' if op == 3 else 'j'} targets {target:#x}, "
                                      f"outside the image and with no R_MIPS_26 relocation to fix it")
                elif op in (4, 5, 6, 7, 20, 21):  # beq/bne/blez/bgtz/beql/bnel
                    raw = word & 0xFFFF
                    delta = (raw - (1 << 16)) << 2 if raw & 0x8000 else raw << 2
                    target = addr + 4 + delta
                    if target < out.addr or target > out.addr + len(data):
                        errors.append(f"{addr:#x}: branch word {word:08x} leaves {out.name}")

            # The mod tool refuses a HI16 whose next list entry is an LO16 for another symbol.
            for i in range(len(out.relocs) - 1):
                cur, nxt = out.relocs[i], out.relocs[i + 1]
                if cur["type"] == R_MIPS_HI16 and nxt["type"] == R_MIPS_LO16 \
                        and cur["symbol"] != nxt["symbol"]:
                    errors.append(f"{out.name}: HI16 at {addr if False else out.addr + cur['offset']:#x} is "
                                  f"followed by an LO16 for a different symbol "
                                  f"({cur['symbol']} vs {nxt['symbol']})")
            for rel in out.relocs:
                if rel["type"] not in LOADER_APPLIES:
                    errors.append(f"{out.name}: reloc type {rel['type']} at {out.addr + rel['offset']:#x} "
                                  f"cannot be applied by the mod runtime")
        return errors

def dump_elf(path):
    elf = ElfFile.load(path)
    print(f"{path}: type={elf.e_type} machine={elf.e_machine} entry={elf.e_entry:#x} "
          f"sections={len(elf.sections)} symbols={len(elf.symbols)}")
    for seg in elf.segments:
        print(f"  segment: type={seg.p_type} off={seg.offset:#x} vaddr={seg.vaddr:#x} "
              f"paddr={seg.paddr:#x} filesz={seg.filesz:#x} memsz={seg.memsz:#x} flags={seg.flags:x}")
    for sec in elf.sections:
        if sec.sh_type == 0:
            continue
        print(f"  section {sec.name:<26} type={sec.sh_type} flags={sec.flags:#x} addr={sec.addr:#010x} "
              f"off={sec.offset:#06x} size={sec.size:#06x} align={sec.addralign} info={sec.info} link={sec.link}")
    print("  symbols:")
    for sym in elf.symbols:
        if not sym.name:
            continue
        print(f"    {sym.name:<34} val={sym.value:#010x} size={sym.size:<5} info={sym.info:#04x} shndx={sym.shndx}")
    for idx, relocs in sorted(elf.relocs.items()):
        target = elf.sections[idx].name if idx < len(elf.sections) else "?"
        print(f"  relocations for {target} ({len(relocs)}):")
        for r in relocs[:40]:
            name = elf.symbols[r.symbol].name if r.symbol < len(elf.symbols) else "?"
            print(f"    {elf.sections[idx].addr + r.offset:#010x} {RELOC_NAMES.get(r.type, r.type):<14} {name}")
        if len(relocs) > 40:
            print(f"    ... {len(relocs) - 40} more")


def main():
    ap = argparse.ArgumentParser(description="minimal MIPS32 BE linker for Zelda64 recomp mods")
    ap.add_argument("objects", nargs="*", help="input .o files (or ELF files with --dump)")
    ap.add_argument("-o", "--output", help="output ELF path")
    ap.add_argument("--base", default="0x80FFF000",
                    help="bias added to section addresses. Mod sections must land in the region the "
                         "loader reserves for mods, which every working .nrm starts at 0x81000000; "
                         "combined with the default --image-offset 0x1000 (space for the ELF headers) "
                         "the first section ends up at exactly 0x81000000. Use 0 only for a "
                         "self-describing dump, and 0x81000000 for a fixed-address offline build.")
    ap.add_argument("--reference-syms", default="",
                    help="base game function symbols (Zelda64RecompSyms mm.us.rev1.syms.toml); enables "
                         "resolving calls to game functions, which the mod loader patches to natives")
    ap.add_argument("--reference-datasyms", default="",
                    help="base game data symbols (mm.us.rev1.datasyms.toml); references to these are "
                         "patched to their fixed address and get no relocation record")
    ap.add_argument("--pack-json", default="",
                    help="write the mod symbol file records for tools/mm_nrm_pack.py to this path")
    ap.add_argument("--image-offset", default="0x1000", help="file offset of the image start")
    ap.add_argument("--dump", action="store_true", help="dump ELF(s) instead of linking")
    ap.add_argument("--no-verify", action="store_true", help="skip decoding the linked image to check it")
    args = ap.parse_args()
    if args.dump:
        for path in args.objects:
            dump_elf(path)
        return
    if not args.output:
        raise SystemExit("error: -o/--output is required")
    ref_funcs = parse_reference_syms(args.reference_syms) if args.reference_syms else {}
    ref_data = parse_reference_syms(args.reference_datasyms) if args.reference_datasyms else {}
    if args.reference_syms and not ref_funcs:
        raise SystemExit(f"error: no function symbols parsed from {args.reference_syms}")
    linker = Linker(args.objects, base=int(args.base, 0), image_offset=int(args.image_offset, 0),
                    verify_code=not args.no_verify, reference_funcs=ref_funcs, reference_data=ref_data)
    blob = linker.run()
    if args.pack_json:
        Path(args.pack_json).write_text(json.dumps(linker.build_nrm_records(), indent=1) + "\n")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(blob)
    total = sum((s.size if s.kind != SHT_NOBITS else s.bss_size) for s in linker.sections)
    relocs = sum(len(s.relocs) for s in linker.sections)
    undefined = len(linker.undef_symbols)
    print(f"mm_mips_link: {out_path} - {len(blob)} bytes, image+bss {total} bytes, "
          f"{len(linker.sections)} sections, {relocs} relocations, "
          f"{len(linker.symbols)} symbols ({undefined} undefined/reference)")


if __name__ == "__main__":
    main()
