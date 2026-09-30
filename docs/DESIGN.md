# Design notes

How "Lilith's Lullaby: White Rose Sanctuary" works, which engine facts it relies on, and what has (and has not) been verified.
Decomp references are to the `mm-decomp` commit this repo pins (`385c45ad`), the same one the Scene API mod uses.

## Overview

```
player plays C-Up C-Left C-Right C-Left C-Up C-Left C-Down
        |
        v   hook: Message_Update (src/lullaby.c, matcher in src/lil_song_tracker.h)
  close the ocarina like a B press
        |
        +-- a listener wants the song (statue, boss) ........ consumed, ocarina ends
        +-- awake custom monsters within ~9.5 m (in the mod's scenes) ... lulled to sleep, consumed
        +-- outside our scenes ...... OCARINA_MODE_WARP_TO_* -> vanilla Song of Soaring warp, destination swapped for the Sanctuary
        +-- inside our scenes ....... OCARINA_MODE_WARP_TO_ENTRANCE with the saved origin -> back to the exact spot
```

| File | Role |
|------|------|
| `src/lullaby.c` | song detection, both warp directions, listener registry, sleep pulse, autosave protection |
| `src/lil_song_tracker.h` | the melody matcher, plain C, unit tested on the host |
| `src/scene_loader.c` | registers scene / entrance / persistent-flag table entries, swaps in the mod's scene and room data |
| `src/actors/*.c` | custom actors (see below) |
| `src/gen/*.c`, `include/lil_gen.h` | generated scenes, collision, textures, models |
| `tools/gen_world.py` | the generator and its validation |

## The song

**Detection.** The vanilla ocarina only recognises its 24 songs, and only lets you play one if the matching quest item bit is
set, so the mod does not hijack a slot. `AudioOcarina_GetPlayingStaff()` exposes the live staff: `pos` (notes played in the
current 8 note window, wraps 8 -> 1, 0 right after the ocarina opens), `buttonIndex` (last button) and `state` (`0xFE` while no
vanilla song was recognised). Each frame (`Message_Update`, only while `msgMode == MSGMODE_OCARINA_PLAYING` with
`OCARINA_ACTION_FREE_PLAY`) a change of `pos` means a new note; the last 7 notes are compared with the melody. A vanilla song
being recognised, a skipped staff position (a note went by unseen) or `pos == 0` reset the history.

**Why these notes.** `ULRLULD` (Up Left Right Left Up Left Down) is not equal to, contained in, or a container of any of the
24 vanilla patterns, so the game's own detection can never fire first or by accident. `tools/tests/test_song.c` checks this
against every vanilla pattern, and also plays the melody from every staff start position, after unrelated notes, with a wrong
note, truncated, and so on.

**Closing the ocarina.** The same three calls the game makes when you press B: `AudioOcarina_SetInstrument(OFF)`,
`msgCtx.ocarinaMode = <mode>`, `Message_CloseTextbox()`.

**Warp to the Sanctuary.** Setting `ocarinaMode` to a `OCARINA_MODE_WARP_TO_*` value is all it takes: `Player_Action_63` then
spawns `EnTest7` (the feather / wind capsule cutscene actor) by itself. `EnTest7_WarpCsWarp` picks the destination entrance
from a table and starts the transition; a return hook on it overwrites `play->nextEntrance` with the Sanctuary. The Sanctuary's
arrival spawn uses `PLAYER_START_MODE_OWL`, so `EnTest7` also plays the vanilla arrival cutscene. Before leaving, the player's
exact position is captured with the game's own `Play_SetRespawnData` (the `respawn[TOP]` slot is restored immediately, so the
game's data is untouched).

**Warp back.** `OCARINA_MODE_WARP_TO_ENTRANCE` is what the game uses for "play Soaring inside a dungeon": `EnTest7` reloads the
scene in `gSaveContext.respawn[RESPAWN_MODE_TOP]` (position, yaw, room) with `respawnFlag = -6`. The mod loads the saved origin
into that slot first. The rose circles do the same without an ocarina session (`Lil_FadeHome`). If the origin is unknown, the
vanilla Clock Town owl statue destination is used.

**Listeners and sleep.** Actors register a handler (`Lil_RegisterLullabyListener`); any handler returning true consumes the
song. The statue uses it to set the gate's switch flag; the bosses use it to get exhausted / put to sleep. In the mod's scenes,
any awake custom monster within 950 units is put to sleep for 10 s first (`Lil_SleepPulse`) and that also consumes the song.

**Autosave.** Zelda 64: Recompiled autosaves. Saving `save.entrance` while inside a custom scene would write an entrance that
only exists while this mod is loaded, so `recomp_on_autosave` temporarily substitutes the place the player came from (and
flushes the scene flags with `Play_SaveCycleSceneFlags`); `recomp_after_autosave` restores it.

## Custom scenes

The approach matches the Scene API mod (CC0), with one scene per slot instead of multiplexing:

* The vanilla tables have unused entries. We use scene ids `SCENE_UNSET_3A` / `SCENE_UNSET_31` and entrance scene ids
  `ENTR_SCENE_UNSET_37` / `ENTR_SCENE_UNSET_2E`. Because every scene has its own slot, the game can always tell which scene
  is loading from the id alone (game over, void out, continue, autosave...).
* `Lil_RegisterTables` fills `gSceneTable`, `sSceneEntranceTable` (16 layers per spawn, because `Entrance_GetTableEntry` also
  indexes by the current scene layer) and `sPersistentCycleSceneFlags` (progress survives the three day reset). It runs on
  every `Play_Init`, so it does not depend on when the game's own static data is initialised.
* The scene table entry points at the real scene file `Z2_INSIDETOWER` so the game's DMA request stays valid; the hook on
  `Play_InitScene` then replaces `play->sceneSegment` with the mod's scene header, and `Room_RequestNewRoom` answers with the
  mod's room data (the vanilla function does nothing once the request status is set).
* The game's default collision memory is enough, so nothing is hooked there: the Crypt's 1752 collision polygons need at most
  ~7000 lookup nodes (an over-count by polygon bounding box, reported by `tools/gen_world.py --check`) against ~30000 available, and the
  handful of dynamic collision actors fit easily in the default dynamic limits. (Only `SCENE_F01` uses the small-memory path.)
* **The scene's cutscene list is not optional.** The Player finds its ocarina / item get / song warp camera ids by walking a
  chain of `CutsceneEntry` records starting at the cutscene id in the player's spawn entry
  (`Play_AssignPlayerCsIdsFromScene`). Without `CS_CAM_ID_GLOBAL_SONG_WARP` in that chain `EnTest7_Init` kills itself and the
  player is stuck mid-warp. Each generated scene contains the standard 10 entry chain.
* Both scenes: one room; time frozen (`SCENE_CMD_TIME_SETTINGS(255, 255, 0)`); no skybox; fixed light settings; audio spec 0
  (specs 0-9 are identical in the game); music reused from the game.

## Custom actors

* **Registration, no patching.** `Actor_LoadOverlay` already uses `overlayEntry->profile` directly when `vramStart == NULL`,
  and `Actor_FreeOverlay` / `Actor_Delete` ignore such entries, so an unused `gActorOverlayTable` entry plus an `ActorProfile`
  is a complete actor. Entries are taken from the end of the table at runtime (`Lil_RegisterActors`). The ProxyMM CustomActor
  library instead patches `Actor_SpawnAsChildAndCutscene`; only one mod can do that, so it was not used.
* The generated actor lists use placeholder ids (`LIL_ACTOR_ID(slot)`) which are replaced by the real ids at registration.
* All custom models are lit by vertex normals and drawn relative to the matrix `Actor_Draw` sets up (actor scale 1.0).
* `Flags_GetClear` is only set by a few vanilla actors, so the "enemies do not spawn in a cleared room" rule never applies.

| Actor | What it does |
|-------|--------------|
| Lilith statue | lullaby listener; sets the Sanctuary gate's switch flag |
| Rose circle | 3 variants: to the Crypt, back to the Sanctuary, home (exact origin) |
| Barrier | thorn wall / white rose gate with dynamic collision that sinks when its switch flag is set |
| Plate | pressure plate, sets a switch flag |
| Path | the Petal Path memory puzzle (demonstrates N W E W N, then checks the pads you step on) |
| Bramble | dynamic collision wall destroyed by `DMG_EXPLOSIVES`, `DMG_FIRE_ARROW`, `DMG_DEKU_STICK` |
| Arena | spawns enemy waves as children, sets a switch flag when the last wave is dead |
| Hazard | petal shot / thorn spike (telegraph, erupt, retract) |
| Thornling, Petal Wisp, Rose Knight | the three enemies |
| Thorn Warden, Queen of Thorns | the bosses |

Damage tables in this game hold multiplier indices (`{0, 1x, 2x, 0.5x, 0.25x, 3x, 4x}`), not damage amounts; see
`lil_actor.h`.

## The generator

`tools/gen_world.py` builds everything from Python: rooms from convex footprints with door gaps, tunnels, pillars and boxes,
procedural 32x32 IA8 textures (brick, flagstone, cobble, grass, hedge, marble, rune, water), baked lighting in vertex colours
(a directional term, a vertical gradient and glow points), static collision with per-area light settings, dynamic collision
boxes, and low poly actor models. The output is deterministic. The display lists follow the render state the game sets up for
rooms (`Gfx_SetupDL25_Opa`): lighting off and vertex colours for the rooms, `PRIMITIVE * SHADE` with normals for actors.

`python3 tools/gen_world.py --check` validates the layout: collision normals are unit length, every spawn and actor is over a
floor, and every route (Sanctuary: arrival -> statue -> gate -> tunnel, and back; Crypt: entrance -> every door -> boss) can be
walked: continuous floor, steps under 22 units, and no wall or ceiling polygon crosses the path at body height. (This found a
real bug during development: a pillar standing in the boss arena's doorway.)

## Verification and known limitations

**Verified, by running it:**

* Everything compiles and links with clang 18.1.6 and the template's exact flags, with no warnings, against the real decomp headers.
* `RecompModTool` accepts the mod. It resolves every game function and data symbol the mod references against
  `Zelda64RecompSyms` (an undefined symbol is a hard error; I confirmed the tool rejects one) and every hook target exists in the ROM.
* `tools/tests/test_song.c` (song tracker) and `tools/gen_world.py --check` (layout) pass.
* Software renders of the levels and models (`docs/previews/`) look as intended.
* `tools/build_linux.sh` produces the `.nrm` from nothing: a fresh clone of this branch, an empty toolchain directory, and the
  GitHub / PyPI fetches (under a minute, no warnings). GitHub Actions does the same on a clean runner. A second, independent
  rebuild reproduced `mod_binary.bin`, `mod_syms.bin`, `mod.json` and `thumb.png` byte for byte (only the zip timestamps differ).

**Verified against the runtime's source (read, not run).** Everything the game has to resolve when it loads the mod was
checked against Zelda 64: Recompiled (`v1.2.2`, the latest release, and `dev`) and N64ModernRuntime instead of being assumed:

* The two event callbacks, `recomp_on_autosave` and `recomp_after_autosave`, are declared by the game's `patches/autosaving.c`
  with the same `(PlayState*)` signature, in `v1.2.2` as well as `dev`.
* The one import, `recomp_printf`, is exported by the game's `patches/print.c`.
* All five hook targets (`Message_Update`, `EnTest7_WarpCsWarp`, `Play_Init`, `Play_InitScene`, `Room_RequestNewRoom`) are
  ordinary recompiled functions with a non-zero size. None is stubbed, ignored or natively reimplemented (the loader rejects
  those as `CannotBeHooked`). The game itself replaces `Play_Init`, and the loader has a dedicated path that applies mod hooks to
  base-patched functions.
* `EnTest7_WarpCsWarp` is also what the game's "skip the Song of Soaring cutscene" patch (`patches/skip_sos.c`) calls when A or B
  is pressed, so the destination override covers a skipped warp too.
* The manifest `id` passes N64Recomp's own `validate_mod_id` (I ran the real function; it rejects malformed ids), and
  `minimum_recomp_version` (1.2.2) is the latest release.

**Not verified: anything that needs the game running.** The mod was written against the decomp source, not observed. The
engine behaviours it relies on were checked by reading the decomp (the most important ones are listed above), but real
execution can still differ. In rough order of how likely they are to need attention:

1. **Song recognition in practice**: the staff semantics (`pos` / `buttonIndex` / `state`), timing with quick note sequences.
2. **The warp**: the `EnTest7` destination override, the arrival at the Sanctuary, the exact-return data.
3. **Scene loading**: table registration timing, the dummy DMA range, collision memory, the room object list.
4. **Rendering**: textures, vertex-colour lighting and fog against the game's render state; any z-fighting; actor model orientation.
5. **Actors**: collider sizes, enemy and boss behaviour and balance, hit detection of bramble / shield / spikes.
6. Things deliberately left out: custom music, dialogue text, a title card, a minimap, a pause-menu entry for the song.

If something misbehaves, the useful places to look are `Lil_OnMessageUpdate` (song), `Lil_AfterWarpCsWarp` (warp),
`Lil_RegisterTables` / `scene_loader.c` (loading), and the `sCylinderInit` / state machine of the actor in question. Most
tunables (health, speeds, timers, ranges) are constants at the top of each actor.
