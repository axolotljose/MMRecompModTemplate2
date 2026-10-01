#!/usr/bin/env bash
#
# One command build of the mod on Linux / macOS / WSL. Nothing is installed system wide: everything goes into ./.toolchain
# (git-ignored), and the finished mod is copied to ./dist/lilith_lullaby_white_rose.nrm
#
#   tools/build_linux.sh            build the mod
#   tools/build_linux.sh --clean    wipe the build directory first
#
# Requirements: git, python3 (with venv + pip), make, a C++20 compiler (g++ or clang++), and internet access to github.com
# and pypi.org the first time.
#
# What it does
#   1. Installs Zig (which bundles clang 18, the LLVM the template asks for, with the MIPS backend) plus cmake and ninja into
#      a python virtualenv. Zig's raw `clang` and `ld.lld` drivers are used exactly like stock LLVM.
#   2. Fetches the decomp headers and the symbol files at the commits this repo pins (or uses your initialised submodules).
#   3. Builds RecompModTool from the N64Recomp commit of the official `mod-tool-release`.
#   4. Runs `make` and `RecompModTool mod.toml build`.
#
# Environment overrides: LIL_TOOLCHAIN_DIR (default ./.toolchain), LIL_USE_SYSTEM_CLANG=1 (use clang/ld.lld from PATH),
# LIL_ALLOWED_HOOKS (comma separated game functions the mod may hook, see the end of this script).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TC="${LIL_TOOLCHAIN_DIR:-$REPO/.toolchain}"
ZIG_VERSION="0.13.0"                                              # bundles clang 18.1.6
RECOMP_TOOL_COMMIT="989a86b36912403cd323de884bf834f2605ea770"     # N64Recomp commit behind the official mod-tool-release
FALLBACK_DECOMP_SHA="385c45ad483502a03c6f93b81e5b1ed5e08281d0"
FALLBACK_SYMS_SHA="e55f1f49a594ff07b5a4115c73fbdad19abb0353"

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
die() { echo "error: $*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "'$1' is required but was not found in PATH"; }

need git; need python3; need make
CXX_BIN="$(command -v g++ || command -v clang++ || true)"
[ -n "$CXX_BIN" ] || die "a C++20 compiler (g++ or clang++) is required to build RecompModTool"
JOBS="$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)"

if [ "${1:-}" = "--clean" ]; then
    rm -rf "$TC/stage/build"
fi
mkdir -p "$TC"

# ---------------------------------------------------------------------------------------------------------------------
# 1. python venv with zig, cmake, ninja
# ---------------------------------------------------------------------------------------------------------------------
if [ "${LIL_USE_SYSTEM_CLANG:-0}" != "1" ] || ! command -v cmake >/dev/null 2>&1; then
    if [ ! -x "$TC/venv/bin/python" ]; then
        say "Creating python virtualenv"
        python3 -m venv "$TC/venv"
    fi
    if ! "$TC/venv/bin/python" -c "import ziglang" >/dev/null 2>&1 || [ ! -x "$TC/venv/bin/cmake" ]; then
        say "Installing zig $ZIG_VERSION, cmake and ninja (pip)"
        "$TC/venv/bin/pip" install --quiet --disable-pip-version-check "ziglang==$ZIG_VERSION" cmake ninja
    fi
fi
VENV_BIN="$TC/venv/bin"

# Wrapper scripts so the Makefile's plain `clang` / `ld.lld` resolve to Zig's embedded (stock) clang and lld.
mkdir -p "$TC/bin"
if [ "${LIL_USE_SYSTEM_CLANG:-0}" != "1" ]; then
    cat > "$TC/bin/clang" <<EOF
#!/bin/bash
exec "$VENV_BIN/python" -m ziglang clang "\$@"
EOF
    cat > "$TC/bin/ld.lld" <<EOF
#!/bin/bash
exec "$VENV_BIN/python" -m ziglang ld.lld "\$@"
EOF
    chmod +x "$TC/bin/clang" "$TC/bin/ld.lld"
fi

# ---------------------------------------------------------------------------------------------------------------------
# 2. decomp headers + symbols
# ---------------------------------------------------------------------------------------------------------------------
pinned_sha() { # <path> <fallback>
    local sha
    sha="$(git -C "$REPO" ls-tree HEAD "$1" 2>/dev/null | awk '{print $3}')"
    echo "${sha:-$2}"
}

fetch_pinned() { # <dir> <url> <sha> [sparse paths...]
    local dir="$1" url="$2" sha="$3"
    shift 3
    if [ -d "$dir/.git" ] && [ "$(git -C "$dir" rev-parse HEAD 2>/dev/null)" = "$sha" ]; then
        return 0
    fi
    rm -rf "$dir"
    git init -q "$dir"
    git -C "$dir" remote add origin "$url"
    if [ "$#" -gt 0 ]; then
        git -C "$dir" config core.sparseCheckout true
        printf '%s\n' "$@" > "$dir/.git/info/sparse-checkout"
        git -C "$dir" fetch -q --depth 1 --filter=blob:none origin "$sha"
    else
        git -C "$dir" fetch -q --depth 1 origin "$sha"
    fi
    git -C "$dir" checkout -q FETCH_HEAD
}

if [ -f "$REPO/mm-decomp/include/global.h" ] && [ -f "$REPO/Zelda64RecompSyms/mm.us.rev1.syms.toml" ]; then
    say "Using the initialised submodules in the repository"
    DECOMP="$REPO/mm-decomp"
    SYMS="$REPO/Zelda64RecompSyms"
else
    DECOMP_SHA="$(pinned_sha mm-decomp "$FALLBACK_DECOMP_SHA")"
    SYMS_SHA="$(pinned_sha Zelda64RecompSyms "$FALLBACK_SYMS_SHA")"
    say "Fetching decomp headers ($DECOMP_SHA) and symbols ($SYMS_SHA)"
    fetch_pinned "$TC/mm-decomp" https://github.com/zeldaret/mm.git "$DECOMP_SHA" 'include/' 'src/' 'assets/'
    fetch_pinned "$TC/Zelda64RecompSyms" https://github.com/Zelda64Recomp/Zelda64RecompSyms.git "$SYMS_SHA"
    DECOMP="$TC/mm-decomp"
    SYMS="$TC/Zelda64RecompSyms"
fi

# ---------------------------------------------------------------------------------------------------------------------
# 3. RecompModTool
# ---------------------------------------------------------------------------------------------------------------------
if [ -n "${RECOMP_MOD_TOOL:-}" ] && [ -x "$RECOMP_MOD_TOOL" ]; then
    MOD_TOOL="$RECOMP_MOD_TOOL"
elif command -v RecompModTool >/dev/null 2>&1; then
    MOD_TOOL="$(command -v RecompModTool)"
else
    MOD_TOOL="$TC/N64Recomp/build/RecompModTool"
    if [ ! -x "$MOD_TOOL" ]; then
        say "Building RecompModTool from N64Recomp $RECOMP_TOOL_COMMIT"
        rm -rf "$TC/N64Recomp"
        git init -q "$TC/N64Recomp"
        git -C "$TC/N64Recomp" remote add origin https://github.com/N64Recomp/N64Recomp.git
        git -C "$TC/N64Recomp" fetch -q --depth 1 origin "$RECOMP_TOOL_COMMIT"
        git -C "$TC/N64Recomp" checkout -q FETCH_HEAD
        git -C "$TC/N64Recomp" submodule update --init --depth 1 --recursive -q
        PATH="$VENV_BIN:$PATH" cmake -S "$TC/N64Recomp" -B "$TC/N64Recomp/build" -G Ninja -DCMAKE_BUILD_TYPE=Release >/dev/null
        PATH="$VENV_BIN:$PATH" cmake --build "$TC/N64Recomp/build" --target RecompModTool -j "$JOBS" >/dev/null
    fi
fi

# ---------------------------------------------------------------------------------------------------------------------
# 4. build
# ---------------------------------------------------------------------------------------------------------------------
# The Makefile expects ./mm-decomp and ./Zelda64RecompSyms next to it. A staging directory of symlinks provides them
# without touching the repository (whose submodule directories stay empty and untouched).
STAGE="$TC/stage"
mkdir -p "$STAGE"
for f in Makefile mod.ld mod.toml thumb.png src include; do
    ln -sfn "$REPO/$f" "$STAGE/$f"
done
ln -sfn "$DECOMP" "$STAGE/mm-decomp"
ln -sfn "$SYMS" "$STAGE/Zelda64RecompSyms"

say "Compiling"
if [ "${LIL_USE_SYSTEM_CLANG:-0}" = "1" ]; then
    ( cd "$STAGE" && make -j "$JOBS" )
else
    ( cd "$STAGE" && PATH="$TC/bin:$PATH" make -j "$JOBS" )
fi

say "Packaging the mod"
( cd "$STAGE" && "$MOD_TOOL" mod.toml build )

mkdir -p "$REPO/dist"
cp "$STAGE"/build/*.nrm "$REPO/dist/"

# What will the game have to do to load this mod? Every hooked game function is regenerated from the ROM at load time and a hook
# that cannot be regenerated stops the whole mod from loading, so the set of hooks is checked against an allowlist (the two
# functions the Scene API mod hooks too). Override with LIL_ALLOWED_HOOKS="A,B" after testing a new hook in the game.
ALLOWED_HOOKS="${LIL_ALLOWED_HOOKS:-Play_InitScene,Room_RequestNewRoom}"
say "Checking what the game has to regenerate to load the mod"
python3 "$REPO/tools/inspect_nrm.py" "$(ls "$REPO"/dist/*.nrm | head -n 1)" "$SYMS/mm.us.rev1.syms.toml" --allow-hooks "$ALLOWED_HOOKS"

say "Done: $(ls "$REPO"/dist/*.nrm)"
