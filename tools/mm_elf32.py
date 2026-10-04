"""Minimal ELF32 (big-endian MIPS) reader/writer used by the mod build scripts.

This exists so the mod toolchain does not depend on pyelftools or on a MIPS
capable ``ld``/``readelf`` being installed. It only implements the subset of
ELF32 that relocatable objects and small executables produced for
Zelda 64: Recompiled mods need.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

EI_NIDENT = 16
ELFCLASS32 = 1
ELFDATA2MSB = 2
EV_CURRENT = 1
ET_REL = 1
ET_EXEC = 2
EM_MIPS = 8

SHN_UNDEF = 0
SHN_ABS = 0xFFF1
SHN_COMMON = 0xFFF2

SHT_NULL = 0
SHT_PROGBITS = 1
SHT_SYMTAB = 2
SHT_STRTAB = 3
SHT_RELA = 4
SHT_NOBITS = 8
SHT_REL = 9

SHF_WRITE = 0x1
SHF_ALLOC = 0x2
SHF_EXECINSTR = 0x4
SHF_INFO_LINK = 0x40

STT_NOTYPE = 0
STT_OBJECT = 1
STT_FUNC = 2
STT_SECTION = 3
STT_FILE = 4
STB_LOCAL = 0
STB_GLOBAL = 1
STB_WEAK = 2

PT_NULL = 0
PT_LOAD = 1
PF_X = 1
PF_W = 2
PF_R = 4

# MIPS o32 relocation types (see the MIPS psABI / N64Recomp's RelocType enum).
R_MIPS_NONE = 0
R_MIPS_16 = 1
R_MIPS_32 = 2
R_MIPS_REL32 = 3
R_MIPS_26 = 4
R_MIPS_HI16 = 5
R_MIPS_LO16 = 6
R_MIPS_GPREL16 = 7
R_MIPS_LITERAL = 8
R_MIPS_GOT16 = 9
R_MIPS_PC16 = 10
R_MIPS_CALL16 = 11
R_MIPS_SHIFT5 = 16
R_MIPS_INSERT = 24

RELOC_NAMES = {
    0: "R_MIPS_NONE", 1: "R_MIPS_16", 2: "R_MIPS_32", 3: "R_MIPS_REL32", 4: "R_MIPS_26",
    5: "R_MIPS_HI16", 6: "R_MIPS_LO16", 7: "R_MIPS_GPREL16", 8: "R_MIPS_LITERAL",
    9: "R_MIPS_GOT16", 10: "R_MIPS_PC16", 11: "R_MIPS_CALL16", 21: "R_MIPS_GOT_PAGE",
}


@dataclass
class Section:
    name: str = ""
    sh_type: int = SHT_NULL
    flags: int = 0
    addr: int = 0
    offset: int = 0
    size: int = 0
    link: int = 0
    info: int = 0
    addralign: int = 0
    entsize: int = 0
    data: bytes = b""
    index: int = 0


@dataclass
class Symbol:
    name: str = ""
    value: int = 0
    size: int = 0
    info: int = 0
    other: int = 0
    shndx: int = SHN_UNDEF
    index: int = 0

    @property
    def bind(self) -> int:
        return self.info >> 4

    @property
    def type(self) -> int:
        return self.info & 0xF


@dataclass
class Reloc:
    offset: int = 0
    symbol: int = 0
    type: int = 0
    addend: int = 0


@dataclass
class Segment:
    p_type: int = PT_LOAD
    offset: int = 0
    vaddr: int = 0
    paddr: int = 0
    filesz: int = 0
    memsz: int = 0
    flags: int = PF_R | PF_W | PF_X
    align: int = 0x10


@dataclass
class ElfFile:
    data: bytes = b""
    e_type: int = ET_REL
    e_machine: int = EM_MIPS
    e_version: int = EV_CURRENT
    e_entry: int = 0
    e_flags: int = 0
    sections: list = field(default_factory=list)
    symbols: list = field(default_factory=list)
    segments: list = field(default_factory=list)
    relocs: dict = field(default_factory=dict)  # section index -> [Reloc]

    # -- reading ----------------------------------------------------------
    @classmethod
    def load(cls, path) -> "ElfFile":
        raw = open(path, "rb").read() if not isinstance(path, (bytes, bytearray)) else bytes(path)
        if len(raw) < 52 or raw[:4] != b"\x7fELF":
            raise ValueError(f"not an ELF file: {path}")
        if raw[4] != ELFCLASS32:
            raise ValueError(f"not a 32-bit ELF file: {path}")
        if raw[5] != ELFDATA2MSB:
            raise ValueError(f"not a big-endian ELF file: {path}")
        (e_type, e_machine, e_version, e_entry, e_phoff, e_shoff, e_flags, e_ehsize,
         e_phentsize, e_phnum, e_shentsize, e_shnum, e_shstrndx) = struct.unpack_from(
            ">HHIIIIIHHHHHH", raw, 16)
        self = cls(data=raw, e_type=e_type, e_machine=e_machine, e_version=e_version,
                   e_entry=e_entry, e_flags=e_flags)
        # section headers
        strtab_name = b""
        if e_shnum and e_shstrndx < 65535:
            sh_off = e_shoff + e_shstrndx * e_shentsize
            _, _, _, _, shoff, shsize, _, _, _, _ = struct.unpack_from(">IIIIIIIIII", raw, sh_off)
            strtab_name = raw[shoff:shoff + shsize]
        for i in range(e_shnum):
            off = e_shoff + i * e_shentsize
            (sh_name, sh_type, sh_flags, sh_addr, sh_offset, sh_size, sh_link, sh_info,
             sh_addralign, sh_entsize) = struct.unpack_from(">IIIIIIIIII", raw, off)
            sec = Section(
                name=cstr(strtab_name, sh_name), sh_type=sh_type, flags=sh_flags, addr=sh_addr,
                offset=sh_offset, size=sh_size, link=sh_link, info=sh_info,
                addralign=sh_addralign, entsize=sh_entsize,
                data=raw[sh_offset:sh_offset + sh_size] if sh_type != SHT_NOBITS else b"")
            sec.index = i
            self.sections.append(sec)
        # symbols + string table
        symtab = next((s for s in self.sections if s.sh_type == SHT_SYMTAB), None)
        if symtab is not None:
            strtab = self.sections[symtab.link]
            count = symtab.size // 16
            for i in range(count):
                off = symtab.offset + i * 16
                st_name, st_value, st_size, st_info, st_other, st_shndx = struct.unpack_from(">IIIBBH", raw, off)
                self.symbols.append(Symbol(name=cstr(strtab.data, st_name), value=st_value, size=st_size,
                                           info=st_info, other=st_other, shndx=st_shndx, index=i))
        # program headers
        for i in range(e_phnum):
            off = e_phoff + i * e_phentsize
            p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_flags, p_align = \
                struct.unpack_from(">IIIIIIII", raw, off)
            self.segments.append(Segment(p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz,
                                        p_flags, p_align))
        # relocations
        for sec in self.sections:
            if sec.sh_type not in (SHT_REL, SHT_RELA):
                continue
            entsize = sec.entsize or (12 if sec.sh_type == SHT_RELA else 8)
            out = []
            for i in range(sec.size // entsize):
                off = sec.offset + i * entsize
                if sec.sh_type == SHT_RELA:
                    r_offset, r_info, r_addend = struct.unpack_from(">IIi", raw, off)
                else:
                    r_offset, r_info = struct.unpack_from(">II", raw, off)
                    r_addend = 0
                out.append(Reloc(offset=r_offset, symbol=r_info >> 8, type=r_info & 0xFF, addend=r_addend))
            self.relocs.setdefault(sec.info, []).extend(out)
        return self

    def section(self, name):
        for sec in self.sections:
            if sec.name == name:
                return sec
        return None

    def word(self, section_index, offset):
        sec = self.sections[section_index]
        return struct.unpack_from(">I", sec.data, offset)[0]

    # -- writing ----------------------------------------------------------
    @staticmethod
    def write(e_type, e_machine, e_entry, e_flags, sections, symbols, segments) -> bytes:
        """Serialize an ELF32 big-endian file.

        ``sections`` is a list of dicts with keys: name, sh_type, flags, addr, size,
        data (bytes or None), offset (None -> assigned by the writer), link, info,
        addralign, entsize. Symbol/reloc/string-table sections are filled in from
        ``symbols`` and the per-section ``relocs`` key.
        """
        shstr = StringTable()
        strtab = StringTable()

        # Assign names and build the symbol string table.
        for sec in sections:
            sec.setdefault("offset", None)
            sec.setdefault("link", 0)
            sec.setdefault("info", 0)
            sec.setdefault("entsize", 0)
            sec.setdefault("addralign", 1)
            sec.setdefault("flags", 0)
            sec.setdefault("addr", 0)
            sec.setdefault("size", 0)
        for sym in symbols:
            if sym["name"] not in strtab.map:
                strtab.add(sym["name"])

        # Build the section name string table before materialising payloads.
        for sec in sections:
            shstr.add(sec["name"])

        # Materialise generated section payloads.
        symtab_payload = b""
        for i, sym in enumerate(symbols):
            sym["offset"] = len(symtab_payload)
            symtab_payload += struct.pack(">IIIBBH", strtab.map[sym["name"]], sym["value"] & 0xFFFFFFFF,
                                          sym["size"], sym["info"], sym.get("other", 0), sym["shndx"])
        for si, sec in enumerate(sections):
            if sec.get("relocs") is not None:
                payload = b""
                for r in sec["relocs"]:
                    payload += struct.pack(">II", r["offset"], (r["symbol"] << 8) | r["type"])
                    if sec["sh_type"] == SHT_RELA:
                        payload += struct.pack(">i", r.get("addend", 0))
                sec["data"] = payload
                sec["size"] = len(payload)
                sec["entsize"] = 12 if sec["sh_type"] == SHT_RELA else 8
                sec["info"] = sec.get("reloc_target", 0)
            elif sec["name"] == ".symtab":
                sec["data"] = symtab_payload
                sec["size"] = len(symtab_payload)
                sec["entsize"] = 16
            elif sec["name"] == ".strtab":
                sec["data"] = strtab.blob
                sec["size"] = len(strtab.blob)
            elif sec["name"] == ".shstrtab":
                sec["data"] = shstr.blob
                sec["size"] = len(shstr.blob)

        for sec in sections:
            sec["name_off_shstr"] = shstr.map[sec["name"]]

        ehdr_size = 52
        phnum = len(segments)
        shentsize = 40
        cursor = ehdr_size + phnum * 32
        cursor = (cursor + 15) & ~15
        # Auto-placed sections must not overlap explicitly placed ones (the image).
        for sec in sections:
            if sec.get("offset") is not None and sec["sh_type"] != SHT_NULL:
                cursor = max(cursor, sec["offset"] + sec["size"])
        for sec in sections:
            if sec["sh_type"] == SHT_NULL:
                sec["offset"] = 0
                continue
            if sec.get("offset") is None:
                align = max(1, sec["addralign"])
                cursor = (cursor + align - 1) & ~(align - 1)
                sec["offset"] = cursor
                if sec["sh_type"] not in (SHT_NOBITS,):
                    cursor += sec["size"]
        out = bytearray()
        buf_ph = out  # program headers are patched after offsets are known
        ident = bytes([0x7F]) + b"ELF" + bytes([ELFCLASS32, ELFDATA2MSB, EV_CURRENT, 0]) + b"\0" * 8
        out += ident
        shstrtab_index = next(i for i, s in enumerate(sections) if s["name"] == ".shstrtab")
        out += struct.pack(">HHIIIIIHHHHHH", e_type, e_machine, EV_CURRENT, e_entry,
                           ehdr_size if phnum else 0, 0, e_flags, ehdr_size,
                           32 if phnum else 0, phnum, shentsize, len(sections), shstrtab_index)
        ph_off = len(out)
        out += b"\0" * (32 * len(segments))
        for sec in sections:
            if sec["sh_type"] == SHT_NULL:
                continue
            pad = sec["offset"] - len(out)
            if pad > 0:
                out += b"\0" * pad
            elif pad < 0:
                raise ValueError(f"section {sec['name']} offset {sec['offset']:#x} overlaps previous data at {len(out):#x}")
            if sec["sh_type"] != SHT_NOBITS:
                payload = sec.get("data") or b""
                if len(payload) != sec["size"]:
                    raise ValueError(f"section {sec['name']}: size {sec['size']} != payload {len(payload)}")
                out += payload
        # Patch program header file sizes so they never claim bytes that do not exist.
        for si, seg in enumerate(segments):
            if seg.get("p_type", PT_LOAD) != PT_LOAD:
                continue
            end = seg["offset"]
            for sec in sections:
                if sec["sh_type"] in (SHT_NULL, SHT_NOBITS) or not (sec["flags"] & SHF_ALLOC):
                    continue
                if sec["offset"] >= seg["offset"]:
                    end = max(end, sec["offset"] + sec["size"])
            seg["filesz"] = end - seg["offset"]
        for i, seg in enumerate(segments):
            struct.pack_into(">IIIIIIII", buf_ph, ph_off + i * 32, seg["p_type"], seg["offset"], seg["vaddr"],
                             seg.get("paddr", seg["vaddr"]), seg["filesz"], seg["memsz"], seg["flags"],
                             seg.get("align", 0x10))
        e_shoff = (len(out) + 15) & ~15
        out += b"\0" * (e_shoff - len(out))
        for sec in sections:
            out += struct.pack(">IIIIIIIIII", shstr.map[sec["name"]], sec["sh_type"], sec["flags"], sec["addr"],
                               sec["offset"], sec["size"], sec["link"], sec["info"], sec["addralign"],
                               sec["entsize"])
        buf = bytearray(out)
        struct.pack_into(">I", buf, 32, e_shoff)
        return bytes(buf)


class StringTable:
    def __init__(self):
        self.buf = bytearray(b"\0")
        self.map = {"": 0}

    def add(self, s: str) -> int:
        if s in self.map:
            return self.map[s]
        off = len(self.buf)
        self.buf += s.encode("utf-8") + b"\0"
        self.map[s] = off
        return off

    @property
    def blob(self) -> bytes:
        return bytes(self.buf)


def cstr(blob: bytes, offset: int) -> str:
    if offset >= len(blob):
        return ""
    end = blob.find(b"\0", offset)
    if end < 0:
        end = len(blob)
    return blob[offset:end].decode("utf-8", "replace")


def elf_symbol_info(bind: int, type_: int) -> int:
    return (bind << 4) | type_
