# Lilith's Lullaby for 2 Ship 2 Harkinian

A port of the *Lilith's Lullaby: White Rose Sanctuary* idea from the Zelda 64: Recompiled mod in this repository to
**2 Ship 2 Harkinian** (the Majora's Mask PC port, C++), delivered in stages that you test one at a time.

> This folder has nothing to do with the Recomp mod in the rest of this repository. It only lives here because this is the
> one repository I can push to (see "Why patches" below).

| Stage | What | Status |
|------|------|--------|
| **1** | Song detection + a toggle in the Enhancements menu (playing the song shows a message) | **delivered, waiting for your test** |
| 2 | Warp to an existing scene as a placeholder, plus return-to-position | not started |
| 3 | The White Rose Sanctuary scene, using your custom map assets | not started |
| 4 | The Thornbound Crypt: dungeon, enemies and bosses | not started |

Base: `axolotljose/2ship2harkinian-mods`, branch `develop`, commit `e8757c14a0fc8701461b0458c9ed72c118bcfc67`
("Update build doc and readme", i.e. plain upstream at that point).

## Why patches

My GitHub access to your fork is read-only (the API reports `push: false`), so I cannot push a branch to it. Each stage is a
set of small commits exported with `git format-patch`; you apply them to your fork with `git am`. If you would rather have
branches pushed straight to the fork, add the Arena GitHub app to `axolotljose/2ship2harkinian-mods` with write access and
tell me, then you can just `git pull`.

## Apply Stage 1

Download `stage1/stage1.mbox` from this folder (GitHub: open the file, then **Download raw file**), then in your clone of the fork:

```powershell
cd path\to\2ship2harkinian-mods
git status                                   # start from a clean tree
git switch -c lilith-lullaby                 # optional, keeps develop untouched
git am --3way --ignore-whitespace "C:\path\to\stage1.mbox"
git log --oneline -4                         # you should see the 3 new commits on top of e8757c14
```

`--ignore-whitespace` only matters on Windows with `core.autocrlf` (the repo normalises to LF). If `git am` stops, run
`git am --abort`, and apply the individual `0001`, `0002`, `0003` patches with `git apply --3way` instead. To go back:
`git reset --hard e8757c14`.

## Build on Windows

From the repository's `docs/BUILDING.md` and `CMakeLists.txt` (I could not build here: it needs your ROM and a Windows toolchain).

**One time**
* At least 8 GB of RAM.
* **Visual Studio 2022** (Community is fine) with the **Desktop development with C++** workload: the `MSVC v143` toolset and a Windows SDK (for example 10.0.19041.0 or newer).
* **Python 3**, **Git** and **CMake 3.26 or newer** (`CMakeLists.txt` requires 3.26). Installing Python and Git standalone is recommended over the Visual Studio installer's copies.
* Clone **with submodules**: `git clone --recursive https://github.com/axolotljose/2ship2harkinian-mods.git`. If you already cloned without it: `git submodule update --init`.
* A supported ROM. You can check yours at https://2ship.equipment/ or against `docs/supportedHashes.json`.

**Build** (PowerShell, from the repository root)

```powershell
# 1. Generate the Visual Studio solution at build\x64 (add -DCMAKE_BUILD_TYPE:STRING=Release if you want a release build)
& 'C:\Program Files\CMake\bin\cmake' -S . -B "build/x64" -G "Visual Studio 17 2022" -T v143 -A x64

# 2. Build ZAPD and generate 2ship.o2r (the port's own assets, no ROM needed)
& 'C:\Program Files\CMake\bin\cmake.exe' --build .\build\x64 --target Generate2ShipOtr

# 3. Compile the game (add --config Release for a release build)
& 'C:\Program Files\CMake\bin\cmake.exe' --build .\build\x64
```

Then either open `build\x64\2s2h.sln` in Visual Studio and press F5 (the startup project is `2ship`), or run `2ship.exe` from the
build output folder.

**First launch (ROM).** The game needs `mm.o2r`, which it extracts from your ROM itself. If it is missing the game either
offers to process a ROM it finds next to the executable or opens a file dialog (`BenPort.cpp`). Putting your ROM next to the
executable before the first launch is the simplest.

**After applying a new stage, re-run step 1 (the configure command) before building.** New source files under `mm/2s2h/` are
picked up by a `file(GLOB_RECURSE ...)` in `mm/CMakeLists.txt` that is only evaluated when CMake configures, so without that
step the build will not see them.

## Test Stage 1

1. Launch the game and load a save where you have the **Ocarina of Time** (the built-in Save Editor can add items if needed).
2. Open the menu (**F1** toggles the menu bar) and go to **Enhancements, Items/Songs**. In the **Ocarina** column tick
   **Lilith's Lullaby** (it sits right under "Enable Sun's Song").
3. Take out the ocarina and play **C-Up, C-Left, C-Right, C-Left, C-Up, C-Left, C-Down**. With the default keyboard layout the
   C buttons are the arrow keys, so that is Up, Left, Right, Left, Up, Left, Down.
4. Expected: the game's "song accepted" chime plays and a notification **"Lilith's Lullaby played"** appears for 3 seconds in the
   bottom-right corner (Settings, Overlay, Notifications can move or hide notifications). The ocarina stays open, nothing else happens.

Things worth checking so that nothing regressed:
* A wrong note anywhere in the sequence: no message. Playing it again, correctly, works every time.
* Vanilla songs (for example the Song of Time, Song of Healing) still behave exactly as before, with the toggle on and off.
* With the toggle **off**, playing the melody does nothing.
* Playing the melody and then more notes, or the melody twice in a row, shows the message each time the melody is completed.
* Switching the toggle on or off while the game is running takes effect immediately (no restart).

## What changed (Stage 1)

3 commits, 175 lines added, nothing existing removed or modified except one 5 line hunk in `BenMenu.cpp`.

| File | Change |
|------|--------|
| `mm/2s2h/Enhancements/Songs/LilithsLullabyTracker.h` | **new.** The melody matcher. Plain C++ with no game includes, so it is unit testable on the host. |
| `mm/2s2h/Enhancements/Songs/LilithsLullaby.cpp` | **new.** The enhancement: `gEnhancements.Songs.LilithsLullaby`, polls the ocarina while the CVar is on, plays the chime and shows the notification. |
| `mm/2s2h/BenGui/BenMenu.cpp` | **modified, +5 lines.** The menu checkbox, after "Enable Sun's Song". |

Commits, in order: `Lilith's Lullaby: add the song matcher`, `... detect the song and show a message`,
`... add the Enhancements menu toggle`. Each one compiles on its own.

## Patterns it follows

I read how the existing enhancements work before writing anything, and copied their shape (line numbers are at `e8757c14`):

* **One enhancement = one file** in `mm/2s2h/Enhancements/<Category>/`, with a `CVAR_NAME` such as `gEnhancements.Songs.X`, a
  `RegisterX()` function, and `static RegisterShipInitFunc initFunc(RegisterX, { CVAR_NAME });` (`ShipInit.hpp`). The init
  function runs at startup and again whenever that CVar changes. `EnableSunsSong.cpp` and `FasterSongPlayback.cpp` are the
  closest siblings.
* **GameInteractor hooks** are registered with the macros in `GameInteractor.h`: `COND_HOOK` (560), `COND_ID_HOOK` (569) and
  `COND_VB_SHOULD` (578, for the `VB_*` "vanilla behaviour" overrides). The `COND_` variants unregister the old hook and
  register a new one only while the CVar is on, which is what makes the toggle live. The available events are listed in
  `GameInteractor_HookTable.h`; the C side calls them, for example `GameInteractor_ExecuteOnGameStateUpdate()` at `game.c:168`.
* **Per-frame polling** uses `COND_HOOK(OnGameStateUpdate, ...)` guarded by `gPlayState == nullptr`, exactly like `SongItems.cpp` (549).
  `gPlayState` is set in `Play_Init` and cleared in `Play_Destroy`, so the guard is safe outside gameplay.
* **Reading the notes** uses `AudioOcarina_GetPlayingStaff()` in `MSGMODE_OCARINA_PLAYING`, the same way `Message_Update` does
  (`z_message.c:4613`). There is also a documented hook there, `VB_OVERRIDE_OCARINA_STAFF_STATE` (used by `SongItems.cpp` at 508);
  I did not need it for detection, but it is the natural way to force a vanilla song state later.
* **Menu entries** are `AddWidget(path, "Label", WIDGET_CVAR_CHECKBOX).CVar("...").Options(CheckboxOptions().Tooltip("..."))` in
  `BenMenu.cpp`. The Songs entries live in the "Items/Songs" page, Ocarina column.
* **Notifications** use `Notification::Emit({ ... })` (`BenGui/Notification.h`), as `AudioHook.cpp` and `SkipBottleCatch.cpp` do.
* **Formatting.** CI runs `clang-format-14` with the repo's `.clang-format` and fails on any diff. All three files are clean under it.

## Design decisions you may want to change

* **The song is matched on the side, not added to the vanilla song tables.** The vanilla code only recognises its 24 songs and
  only lets you play one once its quest item bit is set, so adding a 25th would also mean touching the save data. The melody
  `C-Up, C-Left, C-Right, C-Left, C-Up, C-Left, C-Down` was checked against all 24 patterns in `gOcarinaSongButtons` (parsed from
  this repo's `code_8019AF00.c`): it is neither contained in nor a container of any of them, so the game's own detection can never
  fire first or by accident.
* **Message.** A toast notification plus the vanilla chime, because that is what the other enhancements do. If you would rather
  have an in-game text box, say so.
* **Stage 1 does not close the ocarina.** The ocarina stays open after the melody so that Stage 1 changes as little as possible;
  closing it and warping is Stage 2.
* **Rando.** I did not special-case Randomizer saves.

## What was and was not verified

**Verified here**
* The matcher passes a host unit test (`tests/lullaby_tracker_test.cpp`, not added to your fork because it has no unit test
  setup): clean play from every staff position, play after noise, a wrong note, a truncated melody, a game-recognised vanilla
  song in the middle, a skipped staff position, the ocarina reopening with a stale last button, invalid buttons, and
  no collision with any of the 24 vanilla patterns. I broke the matcher on purpose in several ways to make sure the test fails
  when it should; one test gap that this exposed is fixed.
* `LilithsLullaby.cpp` and `BenMenu.cpp` compile (g++ 12, C++20, syntax-only) against **the real headers**: the repo's own
  includes, libultraship at the pinned commit, ImGui `v1.91.9b-docking`, and the same force-included header list that
  `mm/CMakeLists.txt` uses. The same setup compiles the untouched sibling files, and deliberately broken copies of my files are rejected.
* `clang-format-14` reports no diff for the three files.
* The patches apply with `git am` to a fresh clone of your fork at `e8757c14` and produce a tree identical to mine.

**Not verified**
* A full build with MSVC, and **running it in the game**. I have no ROM and no Windows toolchain here, so none of it has been
  run. The most likely things to need attention are the in-game behaviour of the staff polling (timing with very fast note
  sequences) and how the notification looks.
