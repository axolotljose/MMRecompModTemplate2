# The `.nrm` format, and how this template writes it without `RecompModTool`

A Zelda 64: Recompiled **code mod** is a zip - `.nrm` is just a renamed archive - holding:

| entry | what it is |
| --- | --- |
| `mod.json` | the manifest; `[manifest]` of `mod.toml` copied through, `config_options` becoming `config_schema.options` |
| `mod_syms.bin` | the mod symbol file: sections, functions, relocations, hooks, imports, dependencies |
| `mod_binary.bin` | the MIPS image the runtime live-recompiles, i.e. the linked bytes with no ELF wrapper |
| `thumb.png`, … | optional extras, listed under `additional_files` in the toml |

Everything the loader needs to place the mod in memory and patch it lives in `mod_syms.bin`; the image is
position-independent *only* because that file says so. Getting one field wrong does not produce a warning,
it produces `Failed to load mod code (Code mod loading internal error)`.

## `mod_syms.bin`, version 1

All fields little-endian u32 unless noted. `N64Recomp/src/mod_symbols.cpp` reads this; the counts in the
header are what makes the file self-describing, so unknown record kinds are skipped rather than
misparsed.

```
"N64RSYMS"
version                     = 1
num_sections                (the same value repeats as the first of the ten counts below)
counts[10]                  num_sections, num_dependencies, num_imported_functions,
                            num_dependency_events, num_replacements, num_exported_functions,
                            num_callbacks, num_events, num_hooks, string_table_size
string_table                names concatenated, one trailing NUL; referenced by (start, size),
                            so the NUL is cosmetic. Dependency names come first, then imports.
sections[num_sections]      flags, file_offset, vram, rom_size, bss_size, num_funcs, num_relocs
    funcs[num_funcs]        offset, size                    (offset is inside the section image)
    relocs[num_relocs]      offset, type, target, vrom
dependencies[num]           4 reserved bytes, name_start, name_size
imports[num]                name_start, name_size, dependency_index
dependency_events[num]      dependency_index, begin, end
replacements[num]           input_func, reference_symbol, reference_section, flags
exported_functions[num]     func, name_start, name_size
callbacks[num]              callback_func, first_event? (unused by this mod)
events[num]                 name_start_size?, first_callback (unused by this mod)
hooks[num]                  func_index, original_section_vrom, original_vram, flags  (1 = AtReturn)
relocations                 (listed per section above; also reachable as one flat table)
```

Relocation `vrom` selects the *kind* of reference, and this is the part a hand-written writer gets wrong:

| `vrom` | meaning | what `target` holds |
| --- | --- | --- |
| `0x80000000 \| index` | inside the mod's own image (self) | offset in that section; `.bss` offsets past `rom_size` are valid |
| `0xFFFFFFFE` | an imported function | index into the import table |
| `0xFFFFFFFD` | a dependency's event | index into the event table |
| rom address of a base-ROM section (`..code` = 0x00B3C000, `..boot` = 0x00001060 for mm.us.rev1) | a game function | offset inside that game section; the loader patches the call to the recompiled native function |
| anything else (overlays, and all data sections) | resolved by the tool | no record is emitted at all: the address is baked into the image |

Types are the ELF MIPS numbers: 5 = `R_MIPS_HI16`, 6 = `R_MIPS_LO16` (always emitted as a pair, HI16
first, and the pair is a single logical relocation), 4 = `R_MIPS_32`, 3 = `R_MIPS_26` for `jal`.

A mod section's `vram` is what the loader rebases: every known-good mod links its first section at
`0x81000000`, and `mod_binary.bin` is stored at `vram - image_base` inside the elf this repo links, so
the packager slices the file rather than re-laying it out.

## Which rules are enforced by code, and where

| rule | enforced by |
| --- | --- |
| the byte layout above | `tools/mm_nrm_pack.py --selftest` - parses every real `.nrm` in `release/` and requires the re-serialised bytes to be identical, so the writer is correct by comparison with `RecompModTool`'s own output |
| hook targets must live in `..code`/`..boot` | `tools/check_mod.py` → `compat/hook_section` (a hook on an overlay is legal to *write* and fatal to *load*: the loader recompiles the hooked function from the decompressed base ROM, which has no overlays) |
| every function must be `STT_FUNC` with a size | `tools/mm_mips_link.py`, which registers them in the function table the hook and relocation records index into |
| no instruction outside the R4300i set | `tools/check_live_recomp.py` (`make live`), against `tools/live_recomp_supported.txt` derived from the runtime commit the target pins |
| no unresolved or libgcc-dependent symbol | `tools/check_mod.py` (`make check`), `symbols/*` |

## Regenerating the packaging records

The linker, not the packager, is the only component that knows how each relocation was resolved, so
`tools/mm_mips_link.py --pack-json build/mod.pack.json` writes the record set (functions, relocations,
imports discovered from call sites, hooks discovered from `.recomp_hook.*` sections) as JSON.
`tools/mm_nrm_pack.py` turns that into `mod_syms.bin`, slices `mod_binary.bin` and zips both with the
manifest generated from `mod.toml`. `USE_MOD_TOOL=1` switches back to upstream's binary, which is still
the reference implementation; the two produce the same relocation table for this mod (152 records, same
types and targets), which is the property `make test` protects.
