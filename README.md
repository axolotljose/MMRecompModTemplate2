# Glacio Village — a Majora's Mask: Recompiled mod

An ice crystal appears in South Clock Town on the **final day** (Day 3). Touching it with **A**
freezes the world over and carries Link to **Glacio Village** — the Mountain Village buried in snow,
now the domain of the sorceress **Diana**. A second crystal opens the way into her castle, and
stepping into its throne room starts a boss fight against her.

This repository started life as `MMRecompModTemplate2`, and it is still that template underneath —
but everything in `src/`, `mod.toml`, `Makefile` and `tools/` here is the mod itself.

## What you get

| Piece | Where |
| --- | --- |
| Mod code (one hook, no patches) | `src/glacio_village.c` |
| Integer-only float helpers | `include/glacio_float.h` |
| Manifest + 13 config options | `mod.toml` |
| Build (clang, zig or a custom toolchain), package, audit | `Makefile` |
| MIPS linker for the zig path | `tools/mm_mips_link.py` + `tools/mm_elf32.py` |
| Compatibility auditor for shipping mods | `tools/check_mod.py` |
| Host test for the float helpers | `tests/glacio_float_test.c`, `tools/test_float_helpers.py` |
| Mod menu thumbnail | `tools/make_thumb.py` → `assets/thumb.png` |
| The template's example, kept for reference | `examples/` |

## The quest

1. **Day 3, in South Clock Town.** A crystal forms a short distance from where Link entered the
   area. It is the same actor the game uses for breakable ice (`Obj_Ice_Poly`), spawned with a
   switch flag that no room ever sets, so it can never be destroyed and never collides with a
   vanilla flag.
2. **A on the crystal** → fade to white, arrive in the Mountain Village (winter) — Glacio Village.
   Snow, freezing air and all. A smaller crystal waits behind you as the way back.
3. **In the village**, a second crystal leads to the castle: Ikana Castle's throne room, reused as
   Diana's hall. A third crystal in the village returns you to Clock Town.
4. **Entering the castle** spawns Diana — Igos du Ikana, larger and tougher than the original, with
   the same AI and the same weakness to light. Defeat her and you are paid in rupees and the castle
   door closes behind you, so the fight cannot be re-run in the same cycle.

Everything is deliberately reversible and stateless: no save data is touched, the crystals are
spawned per session, and disabling the quest in the config leaves the game completely untouched.

## Compatibility with the Android port

The point of this build is that it also runs on
[Zelda64Recomp-Android](https://github.com/linkzenic/Zelda64Recomp-Android), where a lot of PC mods
fail. That imposes four rules, and `tools/check_mod.py` proves all four hold on the packaged `.nrm`:

* **Pure `.nrm`, no `native_libraries`.** The Android loader cannot load a desktop `.so`/`.dll`, so
  the mod ships as MIPS code the runtime live-recompiles.
* **No `RECOMP_PATCH`.** The port patches 188 base functions itself; a mod that replaces one of
  those functions fails to load. This mod hooks `Player_Update` and nothing else, so it stacks with
  the port's patches and with other mods.
* **No float arithmetic.** The base game does not export libgcc's `__addsf3`/`__fixsfsi`/..., so one
  stray float op means the mod never loads. `include/glacio_float.h` does the IEEE-754 work with
  integers instead, and `make test` checks those helpers against real float arithmetic (~850k cases)
  and re-checks the compiled object for compiler-runtime references.
* **Every function in the image is registered.** The runtime live-recompiles exactly the functions the
  symbol file lists, so an unlisted helper is code that exists but has no compiled body — the first call
  into it is a force close, not a load error. The linker emits one `STT_FUNC` symbol per function and
  the auditor checks the package's function indices stay in range.
* **Only instructions the R4300i actually has.** The live recompiler implements the N64's MIPS III
  instruction set; one MIPS32 Release 2 encoding (`mul`, `ext`, `ins`, `movn`, `movz`, `mfhc1`) fails the
  whole mod with "Failed to recompile mod", so the build uses `-mcpu=mips2` and `make live` decodes the
  packaged image and asserts no such encoding survives into it.
* **Only symbols the loader can resolve.** Imports are limited to the base API, undefined symbols
  must exist in `Zelda64RecompSyms/mm.us.rev1.syms.toml`, no absolute game address may be baked into
  data, and every relocation must be a type the runtime applies. `minimum_recomp_version` is kept at
  or below the port's runtime version, or the mod is refused silently.

`make mod` builds, packages and audits; the last line of the audit is the shipping report. The
symbol-file checks are cross-referenced against the port's own `patches/*.c` when you point
`--patches` at it, which is what turns "it loads on my PC" into something you can actually verify.

## Building

You need a MIPS-capable C compiler and `make`. Two supported toolchains:

```sh
# clang + ld.lld (what the template expects)
make

# zig cc + the Python linker in tools/, no LLVM or binutils install required
make TOOLCHAIN=zig ZIG=zig
```

Then package and audit. `RecompModTool` comes from the [N64Recomp](https://github.com/N64Recomp/N64Recomp)
releases, or build it yourself from the `mod-tool-release` tag:

```sh
make mod MOD_TOOL=/path/to/RecompModTool      # build + package + audit
make nrm MOD_TOOL=/path/to/RecompModTool      # build + package
make check                                    # audit build/mm_recomp_glacio_village.nrm
make test                                     # float helpers + libgcc check
make DEMO=1 all                               # build the template's example mod instead (into build-demo/)
make PROBE=1 probe                            # diagnostic build: hook only, no quest code (build-probe/)
make live                                             # check the packaged image against the live recompiler's rules
```

`make check`, `nrm` and `mod` cross-check against the mobile port automatically when it is checked
out next to this repo (`../Zelda64Recomp-Android/patches` or `../android-repo/patches`); override with
`PORT_PATCHES=/path/to/patches`, and leave it unset to skip just that one check. `DEMO=1` builds into
`build-demo/` so a demo artifact can never be packaged as the real mod — and the auditor now catches
that anyway (`package/elf_match` compares the packaged image against the elf the manifest names).

The artifact is `build/mm_recomp_glacio_village.nrm`.

## Download the built mod

The loadable `.nrm` files are committed in the repository and published on the release page, which carries the
direct links and checksums: <https://github.com/axolotljose/MMRecompModTemplate2/releases/tag/glacio-village-v1.0.2>

* `release/mm_recomp_glacio_village.nrm` — the mod.
* `release/glacio_probe.nrm` — diagnostic build (same hook, no quest code), for telling a packaging problem apart
  from a gameplay one when a device reports an error.

`release/` is a copy of what `make mod` and `make probe` produce, kept in git only so a phone browser can fetch a
`.nrm` without cloning or building; `build/` stays gitignored. GitHub's asset-upload host is not reachable from the
environment these were built in, which is why they live in the tree and are linked from the release notes instead of
being attached as release assets. Each has a `.sha256` next to it.

## Installing

* **PC (Zelda64Recomp / N64Recomp):** drop the `.nrm` into the `mods` folder next to the executable,
  then enable *Glacio Village* in the Mods menu and restart the game if it was running.
* **Android (Zelda64Recomp-Android):** copy the `.nrm` into the mods directory the app reports
  (usually `<internal storage>/Zelda64/mods`), open the in-game Mods menu, enable it, and relaunch
  the game. Configure the quest from the same menu — the day the crystal forms on, how close you
  have to stand, Diana's health bonus and size, and the two override slots for entrances.

`docs/GLACIO_VILLAGE.md` covers the design decisions, the actor and scene choices, and what the
auditor checks.

---

## Template notes

The sections below are the upstream template's, kept because they still apply.

Example code for using the recompui API to build in-game UI can be found in the `ui-example` branch.
See [this document](https://hackmd.io/fMDiGEJ9TBSjomuZZOgzNg) for an explanation of the modding
framework, including how to write function patches and perform interop between different mods.

### Tools

You'll need `clang` and `make` to build this template (or `zig`, as above).

* On Windows, using [chocolatey](https://chocolatey.org/) to install both is recommended. The
  packages are `llvm` and `make` respectively. The LLVM 19.1.0 release binary, which is also what
  chocolatey provides, does not support MIPS correctly; install 18.1.8 instead.
* On Linux, use your distro's packages for `clang` and `lld`.
* On MacOS, use Homebrew. Apple clang won't work, as you need a MIPS target.
* On Linux and MacOS you'll also need `zip` (the mod tool shells out to it).

### Updating the Majora's Mask decompilation submodule

Mods can also be made with newer versions of the decompilation than the commit this repo pins.

* Build [N64Recomp](https://github.com/N64Recomp/N64Recomp) and copy the executable to the repo root.
* Build the decomp you want to target with `KEEP_MDEBUG=1` (from a clean build) and copy its `.elf`
  to the repo root.
* Point the `mm-decomp` submodule at that commit.
* Run `N64Recomp generate_symbols.toml --dump-context`.
* Rename `dump.toml` and `data_dump.toml` to `mm.us.rev1.syms.toml` and `mm.us.rev1.datasyms.toml`
  and place both in `Zelda64RecompSyms`.
* Try building. If a header is missing, add an empty file under `include/dummy_headers` matching the
  path the compiler complains about.
