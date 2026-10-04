# Glacio Village — design and compatibility notes

How the mod works, why each game object was chosen, and what makes it survive the mobile port.

## Goals and the honest scope

The request was: an ice crystal that only appears on the final day, a teleport to the village of the
sorceress Diana, and a boss fight in her castle. What it is *not* is a quest with authored art: a
recompiled mod cannot add meshes, models, scenes or textures to the ROM image it is given. So every
element is a reuse of something Majora's Mask already contains:

| Story element | What actually ships |
| --- | --- |
| Ice crystal | `ACTOR_OBJ_ICE_POLY` (the breakable ice in Ikana and the mountain), spawned with an unreachable switch flag so it is effectively indestructible |
| Glacio Village | Mountain Village **in winter** (scene `ENTR_SCENE_MOUNTAIN_VILLAGE_WINTER`, winter entrance ids) |
| Diana's castle | Ikana Castle throne room (`IkanaBody`/`Ikninside` hall, the room Igos du Ikana occupies) |
| Diana | `ACTOR_EN_KNIGHT` (Igos du Ikana) with a health bonus and a larger scale |
| Freeze / sorcery audio | `NA_SE_EN_COMMON_FREEZE`, `NA_SE_EN_WIZ_VOICE` through `Audio_PlaySfx` |

Consequences of that last row: Diana keeps Igos's AI, his phases, his weakness to light-based
attacks, his dialog-triggered intro, and he stays a *boss-category* actor so the fight ends when his
health hits zero. The mod never invents new behaviour for him beyond buffing health and size, because
reimplementing a boss without touching its code is not possible and reimplementing it *with* patches
would break compatibility (below).

## Quest flow

```
Day 3 in South Clock Town
  └─ crystal spawns 160 units east/south of the entrance anchor (configurable)
       └─ A within trigger_radius  ──► warp slot 0: Clock Town → Glacio Village (MTN VILLAGE, winter)
Glacio Village
  ├─ GLACIO_SLOT_DOOR crystal ──► the castle waygate
  └─ GLACIO_SLOT_HOME crystal ──► back to where you entered from
Ikana throne room
  └─ on entry: spawn Diana, buff her, and arm the victory watch
       └─ she dies ──► rupees awarded, and GLACIO_SLOT_FLEE opens the way back to the village
```

Each crystal carries one of four slot ids, which is all the state the flow needs:

| Slot | Name | From | To |
| --- | --- | --- | --- |
| 0 | `GLACIO_SLOT_TOWN` | South Clock Town | Glacio Village (mountain village, winter) |
| 1 | `GLACIO_SLOT_DOOR` | Glacio Village | Ikana Castle throne room |
| 2 | `GLACIO_SLOT_HOME` | Glacio Village | the entrance the player last came from |
| 3 | `GLACIO_SLOT_FLEE` | throne room | Glacio Village |

Crystals are tagged by writing `GLACIO_MARKER + slot` into `actor->textId`, which is unused for
`Obj_Ice_Poly`. There is no free per-actor scratch field (`Actor` has no `userData`), and `textId` is
the smallest, safest thing to squat on: it only matters if the actor is made to talk, and nothing
makes ice talk.

Everything else is per-session state in one `static GlacioState` — no save-data writes at all. That
has a deliberate consequence: reset the game or leave the flow mid-way and the quest simply starts
from the crystal again. It also means the mod cannot corrupt a save file.

Two details worth knowing:

* `CURRENT_DAY` in Majora's Mask is `gSaveContext.save.day % 5`, and the day the timer runs out on
  is day 4, so "final day" for the crystal is `day == 3` by default, configurable from 1 to 4.
* Returning to South Clock Town cannot use the ordinary town entrance: `ENTRANCE(SOUTH_CLOCK_TOWN, 0)`
  is inside the Clock Tower, so the mod keeps the entrance the player came in through
  (`gSaveContext.save.entrance`) and only overrides the spawn for the village and the castle. Both
  overrides are exposed as config options (0 = "use the vanilla entrance") rather than hardcoded,
  because entrance ids are the one thing that plausibly differs between a US rev1 dump and anything else.

## Warping

`Glacio_Warp` does the minimum the game itself does for a scripted transition:

```c
play->nextEntrance = entrance;
play->state.transitionTrigger = TRANS_TRIGGER_START;
play->state.transitionType = TRANS_TYPE_FADE_WHITE;
play->nextCutsceneIndex = 0xFFF0;
```

`0xFFF0` is the value `Play_Init` uses to mean "no cutscene"; without it a room that stores a
cutscene index in the upper bits of the entrance would fire that cutscene on arrival. `TRANS_TYPE_FADE_WHITE`
is used instead of the default fade-to-black because the crystal freeze reads as a flash.

## Compatibility engineering, and how it is checked

Each rule below exists because breaking it produces a mod that loads on a PC build and does nothing
(or fails to load) on
[Zelda64Recomp-Android](https://github.com/linkzenic/Zelda64Recomp-Android). `tools/check_mod.py`
enforces all of them against the packaged `.nrm`.

**1. Pure `.nrm`, no native libraries.** The manifest declares no `native_libraries`, so the package
is `mod.json` + `mod_syms.bin` + `mod_binary.bin` (+ `thumb.png`). Android cannot load a desktop
`.so`, and an offline-recompiled mod is per-platform by construction. Live recompilation is the
portable path, and it is what `RecompModTool` produces when there is no patch table.

**2. Hooks only, never `RECOMP_PATCH`.** The port ships 188 base-patched functions (`patches/*.c`,
detected by the `RECOMP_PATCH` marker). Patching a function the base recomp already patches makes the
mod fail to load, so a single `RECOMP_PATCH` is enough to make a mod unshippable for mobile users. The
mod hooks `Player_Update` once and drives everything from that hook. Hooking a base-patched function
is explicitly allowed and multiple mods may hook the same function, so this also stacks.

**3. No float arithmetic anywhere.** `-target mips-freestanding` selects soft float, so any `+`,
`/`, `(int)` or `(float)` on a float becomes a call to `__addsf3`, `__fixsfsi`, `__floatsisf`,
`__ltsf2`... and Majora's Mask exports none of them: the mod does not load, and on Android the
failure looks like "the mod does nothing". `include/glacio_float.h` implements the three operations
the mod needs — float→int truncation, scaled int→float with round-to-nearest, and multiplication —
using only integer shifts and a bit-punning union, so the compiler can emit no conversion at all.

This is not academic: the first version of `Glacio_SpawnCrystal` wrote

```c
Glacio_F32ToS32(playerActor->home.pos.x) + dx   /* fine */
playerActor->home.pos.x + (f32)dx               /* NOT fine: home.pos is a Vec3f */
```

`Actor.home` is a `PosRot` whose `pos` is a `Vec3f`, so touching it *is* float math. The IR showed
`load float` → `sitofp` → `fadd` → `fptosi`, and the object gained four libcalls. The fix is to
convert to integers first, do the arithmetic in `s32`, and convert back through the helper.

`make test` guards this on two levels: it compiles the header for the host and checks the helpers
against real float arithmetic over ~850k inputs (including every power of two and the ranges the mod
can actually produce), and it then compiles the mod for MIPS and fails if *any* undefined symbol is
outside the base API plus the names the game exports. That is the check that would have caught the
`home.pos` bug.

**4. Every function must be registered, or it is never compiled.** This is what actually broke the
first Android build. RecompModTool records one entry in the symbol file's function table per `STT_FUNC`
ELF symbol that has a size, and the runtime live recompiles *exactly those* functions — nothing else.
The Zig path's linker was only carrying over the symbols it happened to need for relocations, so the
package declared a single function (the hook) while the image held eleven: every internal helper was
present in `mod_binary.bin` but had no compiled body. The first frame that reached a call into one of
them faulted, which on Android is a force close with no mod error dialog, because the package itself
parsed fine. A PC build that never got run would have hidden this forever. The linker now carries over
all defined function symbols, and `check_mod.py` fails a package whose hook or replacement records an
out-of-range function index and warns when one function covers most of the image (the shape that means
"the compiler inlined everything and nothing else was registered").

**5. Sections live in the mod region.** `mod.ld` puts the image at `RAMBASE = 0x81000000`, and every
`.nrm` that is known to load — including the ones bundled with the Android port — has its first section
at exactly `0x81000000`. The Zig path links with `--base 0x80FFF000 --image-offset 0x1000` to land on
the same address, and `check_mod.py` fails any package whose sections fall outside
`[0x81000000, 0x82000000)`. An earlier revision of this build linked at `0x1000` instead, having
mis-read a field in the port's built-in `.nrm`; that deviation is what the auditor rule exists to
prevent.

**5. Symbols that resolve everywhere.** Game functions and data are referenced *by name* — never by a
stored address, since the loader resolves undefined symbols against `mm.us.rev1.syms.toml` /
`mm.us.rev1.datasyms.toml` at build time and against the base symbol table at load time. Imports are
limited to the documented base API (`recomp_alloc`, `recomp_printf`, `recomp_get_config_*`, ...) and
`check_mod.py` warns on anything else, because an import that does not exist on the platform is a
silent no-op.

**6. Version floor.** `minimum_recomp_version` must not exceed what the port builds against (its
librecomp is at 1.2.2), otherwise the mod is refused with no visible error. `check_mod.py` fails on
this rather than letting it be discovered by a user.

### Config schema rules that bite

`tools/check_mod.py` validates the manifest the same way the runtime's parser does
(`librecomp/src/mod_manifest.cpp`): the only types are `Enum`, `Number` and `String`; `Enum` `default`
must be one of its `options` or the manifest load fails outright; `Number` fields are all optional.
Two practical notes from wiring the 13 options up:

* The mod reads every option with `recomp_get_config_u32` and clamps in `Glacio_ConfigInt`, out of
  range falling back to the documented default. `recomp_get_config_double` is avoided on purpose: its
  implementation's `(f32)` conversion pulls in `__truncdfsf2` ✗.
* There is no `Bool` type, so the on/off switch is an `Enum` of `Yes`/`No` with `Yes` default — which
  the code treats as non-zero ✓.

## What has been verified, and what has not

Verified in this repository, reproducibly:

```
$ make TOOLCHAIN=zig test
all float helper checks passed            # ~850k comparisons against host float arithmetic
PASS glacio_village.o: 4 external symbol(s), all resolvable:
     Actor_SetScale, Actor_Spawn, Audio_PlaySfx, gSaveContext

$ make TOOLCHAIN=zig mod MOD_TOOL=.../RecompModTool
0 fail, 0 warn, 18 pass, 3 info
```

`make mod` is strict: it fails the build on any warning. The audit covers `compat/patches` (0
replacements, 1 hook, cross-checked against the port's 188 base patches), `syms/relocs` (131
relocations, all of them applicable types), `binary/baked_addresses` (none), `api/imports` (base API
only), `manifest/recomp_version` (the 1.2.2 floor), `manifest/stale_package` (packaged manifest agrees
with mod.toml), `package/elf_match` (the packaged image really came from the linked elf), the config
schema and the package layout. The linked image also passes the linker's own decode-and-check pass.

Not verified: **running it**. There is no Majora's Mask ROM, PC build or Android device in this
environment, so "loads and plays correctly" is not something I can claim — the work here proves the
properties that make mods fail on the port are absent, and that the code is well-formed, not that the
quest is fun or bug-free on hardware. Expect to iterate on the *gameplay* numbers (crystal offsets,
trigger radius, which entrance you arrive at) rather than on loading: they are all config options for
that reason.

## Field report: the boot crash, and how to bisect it if it comes back

The first Android build force-closed the port on starting the game, with no mod error dialog. Two
things were wrong, and neither is visible from a PC-only workflow or from `RecompModTool`'s exit code:

1. **Unregistered functions** (the actual crash): the mod's internal helpers were compiled into the
   image but absent from the symbol file's function table, so they were never live recompiled. The
   package loaded; the first frame that called a helper faulted. Fixed by emitting a `STT_FUNC` symbol
   for every defined function in `tools/mm_mips_link.py`.
2. **A wrong link base** introduced in the same revision (sections at `0x1000` instead of
   `0x81000000`), found by parsing the `.nrm` files that ship with the port and comparing field for
   field. Fixed and now enforced by the auditor.

The lesson generalises: "the mod tool printed nothing" is not evidence. Diff against a package that is
known to load on the target, field by field — `python3 tools/mm_nrm_inspect.py <mine.nrm>` next to
`<working.nrm>` is what found both of these, and `make mod` now asserts the invariants it exposed.

If a build still crashes on a device, bisect with the two artefacts this repo produces:

* `build-probe/glacio_probe.nrm` — installs the same `Player_Update` hook, logs one line, runs no quest
  code. Probe crashes too  → packaging/loader problem, not the quest. Probe loads, mod crashes → the
  quest code; then narrow it with the config options (`enabled = No` should make the mod inert while
  still loading, which separates "loaded and hooked" from "the quest logic did something bad").
* `adb logcat -s Zelda64Recomp:* NativeUI:* libc:* DEBUG:*` while launching — the mod loader prints the
  reason for every *reported* load failure, and a native `SIGSEGV` backtrace shows which function the
  fault was in. That output distinguishes the cases far faster than reasoning about them, so it is worth
  grabbing before re-testing.

## Reproducing the checks

```sh
make TOOLCHAIN=zig test                 # helpers + libgcc/libcall scan
make TOOLCHAIN=zig probe                # build-probe/glacio_probe.nrm: hook only, one log line
make TOOLCHAIN=zig mod MOD_TOOL=$HOME/tools/RecompModTool
python3 tools/check_mod.py mod.toml build/mm_recomp_glacio_village.nrm \
    --patches ../Zelda64Recomp-Android/patches \
    --reference-syms Zelda64RecompSyms/mm.us.rev1.syms.toml --strict
python3 tools/mm_nrm_inspect.py build/mm_recomp_glacio_village.nrm   # raw symbol file view
```

`--patches` is what makes the compat claim checkable: without it the auditor cannot know whether a
hook target or (had there been one) a replacement collides with the port's own patches.

## Troubleshooting

| Symptom | Cause to check first |
| --- | --- |
| Mod listed but does nothing | `enabled` is `No`, or `crystal_day` is not the day you are playing |
| Mod not listed at all | `.nrm` is not in the app's `mods` folder, or `minimum_recomp_version` is above the runtime |
| Loads on PC, not on Android | `native_libraries` present, or a `RECOMP_PATCH` colliding with a base patch — both are audit failures |
| `Failed to create mod file` / `zip` error | `RecompModTool` shells out to `zip`; and check `additional_files` paths exist (`assets/thumb.png`) |
| `Undefined symbol: ...` from the mod tool | a game name that is not in `mm.us.rev1.syms.toml`, or a compiler-runtime symbol (float math crept back in) |
| Arrives in the Clock Tower interior | an `*_entrance_override` set to spawn 0 of that scene; set it to 0 to inherit the vanilla entrance |
| Diana does not appear | she is only spawned inside the reused throne room; elsewhere `Actor_Spawn` of that actor fails by design |
