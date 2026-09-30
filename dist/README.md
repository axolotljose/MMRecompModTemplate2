# Prebuilt mod

`lilith_lullaby_white_rose.nrm` is the packaged mod. Copy it into the `mods` folder of Zelda 64: Recompiled (Settings -> Mods -> *Open Mods Folder*) and enable it in the mod menu.

It is a build artifact of the sources in this repository (`tools/build_linux.sh`); rebuild it after changing anything.

* This exact file: 217564 bytes, SHA-256 `800bfe796d002a48faa5dbbe812bd91433e765595da38df5ff8dec58c29d0fd8`.
  A rebuild gives a different whole-file hash because the zip stores file timestamps, so compare the contents instead.
* Contents (identical in every rebuild, SHA-256):
  * `mod_binary.bin` `2451c15ba08a913f657e3d60b8695a5c464ba471ee8abc69a62f5d37f71ac9ec`
  * `mod_syms.bin` `106c0c3ad569cafab875f0aa8ed9fb8dcc311b265c900418b5de7e70109c3cad`
  * `mod.json` `8eff85e1fb00ad7296463689178a1ac36013929d95b09dd44066705199cb1ee9`
* Compiler: clang 18.1.6 (bundled in Zig 0.13.0) with the template's flags
* Packager: RecompModTool built from N64Recomp commit `989a86b36912403cd323de884bf834f2605ea770` (the official `mod-tool-release`)
* Game: Majora's Mask (US 1.0), Zelda 64: Recompiled 1.2.2 or newer

**This build has not been run in the game yet** (see the status note in the top level README).
