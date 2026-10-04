# Prebuilt mod packages

These are built copies of the mod, committed here only so a phone browser has a plain download link
(the environment they were built in cannot upload GitHub release assets). They are build outputs:
`make TOOLCHAIN=zig mod` and `make TOOLCHAIN=zig probe` regenerate them (`build/` and `build-probe/` are
gitignored), byte-for-byte except for the timestamps a zip records.

| file | what it is | sha256 |
| --- | --- | --- |
| `mm_recomp_glacio_village.nrm` | the mod (v1.0.3) | see `.sha256` |
| `glacio_probe.nrm` | diagnostic build: the same `Play_Update` hook, one log line, no quest code | see `.sha256` |

Each `.nrm` is a zip already - do not extract or rename it. Copy it into the game's `mods` folder
(`<internal storage>/Zelda64/mods` on the Android port, `mods/` next to the executable on PC), enable it
in the Mods menu and relaunch. Verify a download with `sha256sum -c <name>.nrm.sha256`.

**v1.0.3 is the Android load fix.** The mod used to hook `Player_Update`, which lives in the
`..ovl_player_actor` overlay; a hook target has to be in the base ROM (`..code`/`..boot`) because the
loader recompiles the *hooked* function from there, and the port reported the failure as a dialog that
did not even name the mod. It now hooks `Play_Update` (`0x80167DE4`, in `..code`) and null-checks
`GET_PLAYER(play)`. `tools/check_mod.py` fails any package whose hook points outside the base ROM.

The probe exists to separate "the package does not load" from "the quest code does something bad": if
the main mod fails on a device, install only the probe and see whether the game starts with the mod
enabled. Both can be enabled at once. The v1.0.2 probe was packaged from the wrong build directory and
was therefore a copy of the main mod, which made it prove nothing; `probe.toml` now points at
`build-probe/mod.elf` and the audit warns whenever two packages share a payload.

Release notes with direct links for this version:
<https://github.com/axolotljose/MMRecompModTemplate2/releases/tag/glacio-village-v1.0.3>
