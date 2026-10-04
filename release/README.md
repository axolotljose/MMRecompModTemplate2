# Prebuilt mod package

`mm_recomp_glacio_village.nrm` is a built copy of the mod, committed here only so it has a plain
download link (the sandbox this was built in cannot upload GitHub release assets). It is a build
output: `build/` stays gitignored, and `make TOOLCHAIN=zig mod` regenerates this file exactly.

Install: copy the `.nrm` into the game's `mods` folder (`<internal storage>/Zelda64/mods` on the
Android port, `mods/` next to the executable on PC), enable *Glacio Village* in the Mods menu, relaunch.
