# ---------------------------------------------------------------------------
# Toolchain selection
#
#   make                  uses clang + ld.lld, which is what the N64Recomp tooling expects and the
#                         fastest option when a MIPS-capable clang/lld is installed.
#   make TOOLCHAIN=zig    uses `zig cc` for compiling and tools/mm_mips_link.py (a small Python
#                         MIPS linker written for this template) for linking. Zig ships a MIPS
#                         backend but no MIPS linker, so this is the "nothing else is installed"
#                         path: it works on any machine with Python 3 and a copy of zig.
#                         Point ZIG at the binary if zig is not on PATH:  make TOOLCHAIN=zig ZIG=./zig
#   make TOOLCHAIN=custom uses your own $(CC)/$(LD), e.g. a mips-elf GCC/binutils:
#                         make TOOLCHAIN=custom CC="mips-elf-gcc" LD="mips-elf-ld"
# ---------------------------------------------------------------------------

TOOLCHAIN ?= clang
ZIG       ?= zig

ifeq ($(TOOLCHAIN),zig)
    CC      := $(ZIG) cc
    LD      :=
    # zig's freestanding MIPS target defaults to soft-float and to int-sized ptrdiff_t/wchar_t,
    # which disagree with the game headers. The first two flags also matter for correctness: the
    # sources avoid float arithmetic anyway (see src/glacio_village.c), and a mod that pulled in
    # __mulsf3 or friends would not load at all, because the base game does not export them.
    TARGETFLAGS := -target mips-freestanding -D'__PTRDIFF_TYPE__=long' -D'__WCHAR_TYPE__=long'
else ifeq ($(TOOLCHAIN),custom)
    CC      ?= clang
    LD      ?= ld.lld
    TARGETFLAGS :=
else ifeq ($(OS),Windows_NT)
    CC      := clang
    LD      := ld.lld
    TARGETFLAGS :=
else ifneq ($(shell uname),Darwin)
    CC      := clang
    LD      := ld.lld
    TARGETFLAGS :=
else
    CC      ?= clang
    LD      ?= ld.lld
    TARGETFLAGS :=
endif

# DEMO=1 builds the template's example mod in its own directory, so a demo build can never be
# mistaken for the real one (see the DEMO block below).
BUILD_DIR ?= $(if $(filter 1,$(DEMO)),build-demo,$(if $(filter 1,$(PROBE)),build-probe,build))

TARGET  := $(BUILD_DIR)/mod.elf
LINKER  := tools/mm_mips_link.py

LDSCRIPT := mod.ld
# -mcpu=mips2 is load-bearing, not decoration. The N64's R4300i is a MIPS III core and the live
# recompiler implements exactly that instruction set: one unsupported encoding makes
# src/recompilation.cpp print "Unhandled instruction: <name>" and fail the entire mod ("Failed to
# recompile mod" in the in-game error dialog). Under zig the ISA option -mips2 does NOT constrain
# instruction selection -- zig's driver also injects -mfp64, so clang freely emits Release 2 encodings
# (mul, ext, ins) and 64-bit-FPR integer moves (mfhc1/mthc1), plus movn/movz from MIPS IV, none of
# which the recompiler knows. -mcpu=mips2 sets the subtarget itself, which does disable them.
# `make live` re-checks the packaged image against the target's op table so this can never regress.
ARCHFLAGS := $(TARGETFLAGS) -mcpu=mips2 -mabi=32 -O2 -G0 -fno-pic -mno-abicalls -mno-odd-spreg -mno-check-zero-division \
             -fomit-frame-pointer -ffast-math -fno-unsafe-math-optimizations -fno-builtin-memset
WARNFLAGS := -Wall -Wextra -Wno-incompatible-library-redeclaration -Wno-unused-parameter -Wno-unknown-pragmas -Wno-unused-variable \
              -Wno-missing-braces -Wno-unsupported-floating-point-opt -Wno-macro-redefined -Werror=section
CFLAGS   := $(ARCHFLAGS) $(WARNFLAGS) -D_LANGUAGE_C -nostdinc -ffunction-sections
CPPFLAGS := $(if $(filter 1,$(PROBE)),-DGLACIO_PROBE )-DMIPS -DF3DEX_GBI_2 -DF3DEX_GBI_PL -DGBI_DOWHILE -I include -I include/dummy_headers \
            -I mm-decomp/include -I mm-decomp/src -I mm-decomp/extracted/n64-us -idirafter include/libc -idirafter mm-decomp/include/libc
LDFLAGS  := -nostdlib -T $(LDSCRIPT) -Map $(BUILD_DIR)/mod.map --unresolved-symbols=ignore-all --emit-relocs -e 0 --no-nmagic -gc-sections

rwildcard = $(foreach d,$(wildcard $(1:=/*)),$(call rwildcard,$d,$2) $(filter $(subst *,%,$2),$d))
getdirs = $(sort $(dir $(1)))

# PROBE=1 builds the diagnostic variant (hook + one log line, no quest code) for bisecting a
# load failure on a device. It gets its own directory and its own mod_filename.
ifeq ($(PROBE),1)
BUILD_DIR := build-probe
MOD_TOML := probe.toml
endif

# DEMO=1 builds the template's example mod (examples/always_spin_attack.c) instead of Glacio Village.
ifeq ($(DEMO),1)
C_SRCS := $(wildcard examples/*.c)
else
C_SRCS := $(call rwildcard,src,*.c)
endif
C_OBJS := $(addprefix $(BUILD_DIR)/, $(C_SRCS:.c=.o))
C_DEPS := $(addprefix $(BUILD_DIR)/, $(C_SRCS:.c=.d))

ALL_OBJS := $(C_OBJS)
ALL_DEPS := $(C_DEPS)
BUILD_DIRS := $(call getdirs,$(ALL_OBJS))

# Mod sections live in the region the loader reserves for mods. Every .nrm in the ecosystem -- the
# ones bundled with the Android port included -- links its first section at exactly 0x81000000, which
# is mod.ld's RAMBASE, so this path matches it rather than inventing a convention: the loader keeps a
# function lookup table keyed by guest address, and a mod outside that region is at best a different
# code path. With --image-offset 0x1000 (room for the ELF headers in this linker's output) the base
# is 0x81000000 - 0x1000.
LINK_BASE ?= 0x80FFF000
LINK_IMAGE_OFFSET ?= 0x1000

# RecompModTool packages the linked elf into a .nrm. It ships in the N64Recomp repository (tag
# mod-tool-release): cmake -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build --target
# RecompModTool. Point MOD_TOOL at the binary if it is not on PATH.
MOD_TOOL ?= RecompModTool
MOD_TOML ?= mod.toml

# The .nrm is named after mod_filename in the toml, so derive it instead of hardcoding one name.
MOD_FILENAME := $(shell sed -n 's/^[[:space:]]*mod_filename[[:space:]]*=[[:space:]]*"[^"]*".*/&/p' $(MOD_TOML) | head -n1 | sed 's/.*"\([^"]*\)".*/\1/')
NRM := $(BUILD_DIR)/$(if $(MOD_FILENAME),$(MOD_FILENAME),mod).nrm

# Which sources the auditor should cross-check the declared config options against.
SRC_DIR := $(if $(filter 1,$(DEMO)),examples,src)

# The mobile port's base patch sources, when the port is checked out next to this repo. The auditor
# needs them to prove no hook or replacement collides with a function the port already patches, so
# they are picked up automatically and can be overridden with PORT_PATCHES=...
PORT_PATCHES ?= $(firstword $(wildcard ../Zelda64Recomp-Android/patches ../android-repo/patches))
REFERENCE_SYMS ?= Zelda64RecompSyms/mm.us.rev1.syms.toml
AUDIT_ARGS := $(if $(PORT_PATCHES),--patches $(PORT_PATCHES) --reference-syms $(REFERENCE_SYMS))

# Fail with instructions instead of "No such file or directory", which tells you nothing.
check-tool = @command -v $(1) >/dev/null 2>&1 || test -x $(1) || { \
    echo "error: $(1) not found."; \
    echo "       Build it from N64Recomp (git checkout mod-tool-release) and re-run with"; \
    echo "       MOD_TOOL=/path/to/RecompModTool, or drop it on your PATH."; exit 2; }

all: $(TARGET)

$(TARGET): $(ALL_OBJS) $(LDSCRIPT) | $(BUILD_DIR)
ifeq ($(TOOLCHAIN),zig)
	python3 $(LINKER) $(ALL_OBJS) -o $@ --base $(LINK_BASE) --image-offset $(LINK_IMAGE_OFFSET)
else
	$(LD) $(ALL_OBJS) $(LDFLAGS) -o $@
endif

# Package the linked elf into a .nrm (the format the loaders on PC and Android understand).
nrm: $(TARGET)
	$(call check-tool,$(MOD_TOOL))
	$(MOD_TOOL) $(MOD_TOML) $(BUILD_DIR)
	python3 tools/check_mod.py $(MOD_TOML) $(NRM) --src $(SRC_DIR) $(AUDIT_ARGS)

# Build, package and audit. This is the target to run before shipping a mod.
mod: $(TARGET)
	$(call check-tool,$(MOD_TOOL))
	$(MOD_TOOL) $(MOD_TOML) $(BUILD_DIR)
	python3 tools/check_mod.py $(MOD_TOML) $(NRM) --src $(SRC_DIR) $(AUDIT_ARGS) $(CHECK_EXTRA) --strict
	$(MAKE) --no-print-directory live

# Does the packaged image compile on the target? Mirrors the live recompiler's own rules (op-table
# membership, relocation/instruction pairing, jump resolution) against mod_binary.bin, i.e. the exact
# bytes the device feeds to sljit. Run this before blaming a device.
live:
	python3 tools/check_live_recomp.py $(NRM) $(if $(STRICT),--strict,)

# Host-side checks that do not need a packaged mod: float helper accuracy and the rule that the
# object must not reference any symbol the base game cannot resolve.
test:
	python3 tools/test_float_helpers.py

# Build the diagnostic variant: build-probe/glacio_probe.nrm.
probe:
	$(MAKE) PROBE=1 TOOLCHAIN=$(TOOLCHAIN) ZIG=$(ZIG) MOD_TOOL=$(MOD_TOOL) CHECK_EXTRA=--skip-config-source mod

check:
	python3 tools/check_mod.py $(MOD_TOML) $(NRM) --src $(SRC_DIR) $(AUDIT_ARGS)
	$(MAKE) --no-print-directory live

$(BUILD_DIR) $(BUILD_DIRS):
ifeq ($(OS),Windows_NT)
	if not exist "$(subst /,\,$@)" mkdir "$(subst /,\,$@)"
else
	mkdir -p $@
endif

$(C_OBJS): $(BUILD_DIR)/%.o : %.c | $(BUILD_DIRS)
	$(CC) $(CFLAGS) $(CPPFLAGS) $< -MMD -MF $(@:.o=.d) -c -o $@

clean:
ifeq ($(OS),Windows_NT)
	if exist $(BUILD_DIR) rmdir /S /Q $(BUILD_DIR)
else
	rm -rf $(BUILD_DIR)
endif

-include $(ALL_DEPS)

.PHONY: clean all nrm mod live check test probe

# Print target for debugging
print-% : ; $(info $* is a $(flavor $*) variable set to [$($*)]) @true
