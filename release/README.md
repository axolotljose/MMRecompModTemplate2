# Prebuilt mod package

`mm_recomp_glacio_village.nrm` is a built copy of the mod, committed here only so it has a plain
download link (the sandbox this was built in cannot upload GitHub release assets). It is a build
output: `build/` stays gitignored, and `make TOOLCHAIN=zig mod` regenerates this file exactly.

`glacio_probe.nrm` is the diagnostic build (`make TOOLCHAIN=zig probe`). It installs the same
`Player_Update` hook, logs one line and runs no quest code, so it separates "the package does not load"
from "the quest code does something bad". If the main mod crashes the app, install only the probe and
check whether the game starts; both mods can be enabled at once, and the probe is inert besides its log
line. Each `.sha256` file is the checksum of the artifact next to it.

Install: copy the `.nrm` into the game's `mods` folder (`<internal storage>/Zelda64/mods` on the
Android port, `mods/` next to the executable on PC), enable *Glacio Village* in the Mods menu, relaunch.
