# Prebuilt mod

`lilith_lullaby_white_rose.nrm` is the packaged mod, **version 0.1.1**. Copy it into the `mods` folder of Zelda 64: Recompiled (Settings -> Mods -> *Open Mods Folder*), replacing any older copy (the file name is the same), and enable it in the mod menu. The mod menu shows the version.

It is a build artifact of the sources in this repository (`tools/build_linux.sh`); rebuild it after changing anything.

* This exact file: 217577 bytes, SHA-256 `d9456a4d303c99c01b8a76eacb39f2c7f4e901d10a233e72d525af466982e714`.
  A rebuild gives a different whole-file hash because the zip stores file timestamps, so compare the contents instead.
* Contents (identical in every rebuild, SHA-256):
  * `mod_binary.bin` `67ec74e6758a499015bc8eaa8318d425dc9bff0f785d06c40df1068ada937189`
  * `mod_syms.bin` `deb05e9101972fdf7b2488f57085961a164699085ff233bd02a50a63c0ad068e`
  * `mod.json` `879e26e176fffd19014dc605fbc18e8a525a6b7d9383d919204c3de0ae5fc1e0`
* Compiler: clang 18.1.6 (bundled in Zig 0.13.0) with the template's flags
* Packager: RecompModTool built from N64Recomp commit `989a86b36912403cd323de884bf834f2605ea770` (the official `mod-tool-release`)
* Game: Majora's Mask (US 1.0), Zelda 64: Recompiled 1.2.2 or newer
* Hooked game functions (the game regenerates these from the ROM when it loads the mod): only `Play_InitScene` and `Room_RequestNewRoom`.
  `python3 tools/inspect_nrm.py dist/lilith_lullaby_white_rose.nrm` lists them, and the events the mod uses.

**This build has not been run in the game yet.** Version 0.1.0, which hooked five game functions, failed to load in Zelda 64: Recompiled with
"code mod loading internal error"; this version removes the most likely cause. See the status note in the top level README and
docs/DESIGN.md for what went wrong and what is and is not verified.
