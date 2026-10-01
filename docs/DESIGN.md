# Design notes

How "Lilith's Lullaby: White Rose Sanctuary" works, which engine facts it relies on, and what has (and has not) been verified.
Decomp references are to the `mm-decomp` commit this repo pins (`385c45ad`), the same one the Scene API mod uses.

## Overview

```
player plays C-Up C-Left C-Right C-Left C-Up C-Left C-Down
        |
        v   event: recomp_after_play_update (src/lullaby.c, matcher in src/lil_song_tracker.h)
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
vanilla song was recognised). Each frame (`recomp_after_play_update`, only while `msgMode == MSGMODE_OCARINA_PLAYING` with
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
from a table and starts the transition during the actor update, and `Play_UpdateMain` only reads `play->nextEntrance` at the start
of the next frame. So `recomp_after_play_update` overwrites it with the Sanctuary (`Lil_RedirectOwlWarp`), but only when it is
exactly the destination the vanilla code chose for the mode we asked for (`ENTRANCE(SOUTH_CLOCK_TOWN, 9)`, or
`ENTRANCE(IKANA_CANYON, 6)` inside the Secret Shrine, a vanilla special case), so no other transition can be redirected by
mistake. (Version 0.1.0 hooked `EnTest7_WarpCsWarp` instead, see "What went wrong in the first version" below.) The Sanctuary's
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
  every `Play_Init` (through the `recomp_on_play_init` event), so it does not depend on when the game's own static data is initialised.
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

**Verified against the runtime's source (read, not run).** What the game has to resolve when it loads the mod was checked against
the Zelda 64: Recompiled `v1.2.2` tag and the N64ModernRuntime commit it pins (`df7e820`), instead of being assumed:

* The four events the mod listens to (`recomp_on_play_init`, `recomp_after_play_update`, `recomp_on_autosave`,
  `recomp_after_autosave`) are declared by the game's patches at the `v1.2.2` tag with a `(PlayState*)` parameter.
  `recomp_on_play_init` is the first statement of the game's `Play_Init`, and `recomp_after_play_update` runs right after
  `Play_Update` in `Play_Main`.
* The one import, `recomp_printf`, is exported by the game's `patches/print.c`.
* The two hooked functions (`Play_InitScene`, `Room_RequestNewRoom`) exist with a non-zero size and are not stubbed, ignored or
  natively reimplemented. The Scene API mod (needs recomp 1.2.2) hooks the same two on the same runtime, and so does an older
  scene proof of concept (needs 1.2.0).
* `EnTest7_WarpCsWarp` (no longer hooked) is what the game's "skip the Song of Soaring cutscene" patch (`patches/skip_sos.c`)
  calls when A or B is pressed, so the destination override in `Lil_RedirectOwlWarp` covers a skipped warp too: it looks at the
  result, not at the call.
* The manifest `id` passes N64Recomp's own `validate_mod_id` (I ran the real function; it rejects malformed ids), and
  `minimum_recomp_version` (1.2.2) is the latest release.

This kind of checking is necessary but **not sufficient**, as the next section shows. A symbol that exists in the symbol file is
not the same as a function the runtime can regenerate, and my first round of reading looked at the newest runtime source instead
of the version the game actually pins.

**What went wrong in the first version (0.1.0).** Its first real run failed to load: *error loading mods: failed to load mod code
(code mod loading internal error)*, with no mod id in the message. The runtime in Zelda 64: Recompiled 1.2.2 (the release I read the source of; I do not know which
version the failing run used) loads a code mod in three steps. In the first two (compile the mod's own code with the live recompiler; resolve its imports, events and hooks) an
error names the mod. The third step **regenerates every hooked game function from the ROM**, again with the live recompiler, and
an error there carries no mod id: one function that cannot be regenerated rejects the whole mod. 0.1.0 hooked five game functions
(`Message_Update`, `Play_Init`, `Play_InitScene`, `Room_RequestNewRoom` and, at both entry and return, `EnTest7_WarpCsWarp`).
The build tool cannot see this, it only checks that the symbols exist, and I cannot run the game's ROM here, so **I could not
determine which function failed**. The prime suspect is `EnTest7_WarpCsWarp`: an actor overlay function hooked at entry and at
return, in an overlay that the game itself patches (`EnTest7_Update`), and the only one of the five that no mod I could find
hooks (shipping mods hook the other four). So 0.1.1 **hooks only `Play_InitScene` and `Room_RequestNewRoom`** and does everything
else from events the game raises itself: `recomp_on_play_init`, `recomp_after_play_update` and the autosave events. Events are
called from the game's own, already compiled code and cost nothing at load time.

`tools/inspect_nrm.py` prints, by name, which game functions a built mod asks the runtime to regenerate and which events it uses.
`tools/build_linux.sh` runs it and fails the build if the mod hooks anything outside an allowlist (`LIL_ALLOWED_HOOKS`), and CI
does the same, so adding a hook is a conscious, game-tested decision.

**Not verified: anything that needs the game running.** The mod was written against the decomp source, not observed. The
engine behaviours it relies on were checked by reading the decomp (the most important ones are listed above), but real
execution can still differ. In rough order of how likely they are to need attention:

1. **That the game now loads the mod at all.** 0.1.1 removes the most likely cause of the 0.1.0 load failure (see above) but has
   not been run in the game either.
2. **Song recognition in practice**: the staff semantics (`pos` / `buttonIndex` / `state`), timing with quick note sequences. The
   song is now polled after `Play_Update` instead of just before `Message_Update`, which only moves the check by a fraction of a frame.
3. **The warp**: the destination override in `Lil_RedirectOwlWarp` (it relies on the next-frame read of `nextEntrance` described
   above), the arrival at the Sanctuary, the exact-return data.
4. **Scene loading**: table registration timing, the dummy DMA range, collision memory, the room object list.
5. **Rendering**: textures, vertex-colour lighting and fog against the game's render state; any z-fighting; actor model orientation.
6. **Actors**: collider sizes, enemy and boss behaviour and balance, hit detection of bramble / shield / spikes.
7. Things deliberately left out: custom music, dialogue text, a title card, a minimap, a pause-menu entry for the song.

If something misbehaves, the useful places to look are `Lil_PollOcarina` (song), `Lil_RedirectOwlWarp` (warp),
`Lil_RegisterTables` / `scene_loader.c` (loading), and the `sCylinderInit` / state machine of the actor in question. Most
tunables (health, speeds, timers, ranges) are constants at the top of each actor.
