#!/usr/bin/env bash
# Assemble the narratty toolkit: statically linked demo tools for any Linux image.
# Prebuilt musl binaries are downloaded; tmux, file, eza and delta (no static arm64
# release) are cross-compiled with zig, so no emulation is needed. Every download is
# pinned by sha256. Output: /toolkit, laid out to be copied to /usr/local (zsh, tmux and
# file expect that prefix).
#
#   build.sh <amd64|arm64> [share-dir]
set -euo pipefail

arch=${1:?usage: build.sh <amd64|arm64>}
case "$arch" in
  amd64) triple=x86_64 ;;
  arm64) triple=aarch64 ;;
  *) echo "unsupported architecture: $arch" >&2; exit 1 ;;
esac
case "$(uname -m)" in
  x86_64) host=x86_64 ;;
  aarch64) host=aarch64 ;;
esac

GH=https://github.com
share=$(realpath "${2:-$(dirname "$0")/share}")
out=/toolkit
src=/tmp/toolkit-src
licenses=$out/share/narratty/licenses
mkdir -p "$out/bin" "$licenses" "$src"
cd "$src"

# fetch URL SHA256 [NAME]
fetch() {
  local name=${3:-$(basename "$1")}
  curl -fsSL --retry 3 -o "$name" "$1"
  echo "$2  $name" | sha256sum -c --quiet -
}

pick() { if [ "$arch" = amd64 ]; then echo "$1"; else echo "$2"; fi; }

# ── prebuilt static binaries ──────────────────────────────────────────────────
BAT=0.26.1 FD=10.5.0 RG=15.2.0 YAZI=26.9.1 JQ=1.8.2 ZSH_BIN=6.1.1 NERD_FONTS=3.5.1 MICRO=2.0.15

fetch "$GH/sharkdp/bat/releases/download/v$BAT/bat-v$BAT-$triple-unknown-linux-musl.tar.gz" \
  "$(pick 0dcd8ac79732c0d5b136f11f4ee00e581440e16a44eab5b3105b611bbf2cf191 6369242c584065f195fb20cb36fbd7cb63ae690605bbe89868a7596b596c2c23)" bat.tar.gz
fetch "$GH/sharkdp/fd/releases/download/v$FD/fd-v$FD-$triple-unknown-linux-musl.tar.gz" \
  "$(pick 761c72dc8e120d85b22292063be8a796e2eeb20eb3e4f38b8fa2343ccf3514a7 d76c4317f7d5dba69f8a2a15856c90c777e7f0dd4e85f0de8c76de6992c374d4)" fd.tar.gz
fetch "$GH/BurntSushi/ripgrep/releases/download/$RG/ripgrep-$RG-$triple-unknown-linux-musl.tar.gz" \
  "$(pick 33e15bcf1624b25cdd2a55813a47a2f95dbe126268203e76aa6a585d1e7b149c 800b1e7206afe799dfb5a6901f23147cfaabe0e52210538100f61e86e1740915)" rg.tar.gz
fetch "$GH/sxyazi/yazi/releases/download/v$YAZI/yazi-$triple-unknown-linux-musl.zip" \
  "$(pick 9b9c39decccf8cb0ff53a7d637d38f8a79d93bbd0099f4ea9c619ef6bb392f5d dd569daecaae914185f295634109295ccd25c1b42b02eb89a74f651970024f2e)" yazi.zip
fetch "$GH/jqlang/jq/releases/download/jq-$JQ/jq-linux-$arch" \
  "$(pick b1c22172dd303f3be49e935aa56aa48a8b7a46e0bc838b4997d3bb451495870f 8b85c817833814ddca00a144c33705546355afccf0cf39b188f3cdb48b852309)" jq
fetch "$GH/romkatv/zsh-bin/releases/download/v$ZSH_BIN/zsh-5.8-linux-$triple.tar.gz" \
  "$(pick 6df668fb6e9a12874e0d80518d582f2e99e512d4a4532fa73d938360aaddc838 5caca77bcdaa218ec12e79f2e65c53c39058e0ed4f4f299991d18a800ca7c06d)" zsh.tar.gz
fetch "$GH/zyedidia/micro/releases/download/v$MICRO/micro-$MICRO-$(pick linux64-static linux-arm64).tar.gz" \
  "$(pick 267d238eac1e26ed053d13d4d48bd421b87f9eb538b604f0b2f74a85598b6cc2 5ca127857bf5500be3879f1a70b27556e737a49da04a1be5334de9e8e8781ad9)" micro.tar.gz
fetch "$GH/ryanoasis/nerd-fonts/releases/download/v$NERD_FONTS/NerdFontsSymbolsOnly.tar.xz" \
  01172f37db8543edb102e5cb5c64101c9f4686630804d49b419aa07b23a69996 nerd-fonts.tar.xz

for tool in bat fd rg; do
  mkdir "$tool" && tar -xzf "$tool.tar.gz" -C "$tool" --strip-components=1
  install -m 0755 "$tool/$tool" "$out/bin/$tool"
  mkdir "$licenses/$tool" && cp "$tool"/LICENSE* "$tool"/UNLICENSE "$licenses/$tool/" 2>/dev/null || true
done
unzip -q yazi.zip && install -m 0755 yazi-*/yazi yazi-*/ya "$out/bin/"
mkdir "$licenses/yazi" && cp yazi-*/LICENSE "$licenses/yazi/"
install -m 0755 jq "$out/bin/jq"
mkdir micro && tar -xzf micro.tar.gz -C micro --strip-components=1
install -m 0755 micro/micro "$out/bin/micro"
mkdir "$licenses/micro" && cp micro/LICENSE micro/LICENSE-THIRD-PARTY "$licenses/micro/"
# Icons for yazi and eza: Chromium falls back to this font for Nerd Font glyphs.
mkdir -p "$out/share/fonts/nerd-fonts" "$licenses/nerd-fonts"
tar -xJf nerd-fonts.tar.xz -C "$out/share/fonts/nerd-fonts" SymbolsNerdFontMono-Regular.ttf
tar -xJf nerd-fonts.tar.xz -C "$licenses/nerd-fonts" LICENSE
# zsh-bin hard-codes its install prefix; point it at /usr/local.
mkdir zsh && tar -xzf zsh.tar.gz -C zsh
zsh/share/zsh/5.8/scripts/relocate -s "$src/zsh" -d /usr/local
cp -a zsh/bin/zsh "$out/bin/zsh"
mkdir -p "$out/share" && cp -a zsh/share/zsh zsh/share/terminfo "$out/share/"

# ── cross-compiled with zig ───────────────────────────────────────────────────
UV=0.9.5 ZIG=0.15.2 CARGO_ZIGBUILD=0.23.4
TMUX=3.7c LIBEVENT=2.1.12 EZA=0.23.5 DELTA=0.19.2
NCURSES=${NCURSES:-6.5}
NCURSES_URL=${NCURSES_URL:-https://ftp.gnu.org/gnu/ncurses/ncurses-$NCURSES.tar.gz}
NCURSES_SHA256=${NCURSES_SHA256:-136d91bc269a9a5785e5f9e980bc76ab57428f604ce3e5a5a90cebc767971cc6}
FILE=${FILE:-5.48}
FILE_URL=${FILE_URL:-https://astron.com/pub/file/file-$FILE.tar.gz}
FILE_SHA256=${FILE_SHA256:-ed14656883b23a364b4057c05595d93252da9bc473d30106519519d0da141283}

if [ "$host" = x86_64 ]; then uv_sha=3665ffb6c429c31ad6c778ac0489b7746e691acf025cf530b3510b2f9b1660ff
else uv_sha=42b9b83933a289fe9c0e48f4973dee49ce0dfb95e19ea0b525ca0dbca3bce71f; fi
fetch "$GH/astral-sh/uv/releases/download/$UV/uv-$host-unknown-linux-musl.tar.gz" "$uv_sha" uv.tar.gz
tar -xzf uv.tar.gz --strip-components=1 -C /usr/local/bin
uv venv -q /opt/zig
uv pip install -q --python /opt/zig "ziglang==$ZIG" "cargo-zigbuild==$CARGO_ZIGBUILD"
export PATH="/opt/zig/bin:$PATH"

zig_target=$triple-linux-musl
for tool in cc ar ranlib; do
  printf '#!/bin/sh\nexec python -m ziglang %s %s "$@"\n' "$tool" \
    "$([ $tool = cc ] && echo "-target $zig_target")" >"/usr/local/bin/zig-$tool"
  chmod 0755 "/usr/local/bin/zig-$tool"
done
printf '#!/bin/sh\nexec python -m ziglang cc "$@"\n' >/usr/local/bin/zig-host-cc
chmod 0755 /usr/local/bin/zig-host-cc
cross=(--host="$zig_target" CC=zig-cc AR=zig-ar RANLIB=zig-ranlib)
deps=$src/deps

fetch "$GH/libevent/libevent/releases/download/release-$LIBEVENT-stable/libevent-$LIBEVENT-stable.tar.gz" \
  92e6de1be9ec176428fd2367677e61ceffc2ee1cb119035037a27d346b0403bb libevent.tar.gz
fetch "$NCURSES_URL" "$NCURSES_SHA256" ncurses.tar.gz
fetch "$GH/tmux/tmux/releases/download/$TMUX/tmux-$TMUX.tar.gz" \
  7c60cae9a0e25288e2e24750aafc9e8800fc7fd4555e447e1b29ee4201cfb3bf tmux.tar.gz

mkdir libevent ncurses tmux
tar -xzf libevent.tar.gz -C libevent --strip-components=1
tar -xzf ncurses.tar.gz -C ncurses --strip-components=1
tar -xzf tmux.tar.gz -C tmux --strip-components=1

(cd libevent && ./configure -q "${cross[@]}" --prefix="$deps" --disable-shared --enable-static \
  --disable-openssl --disable-samples --disable-libevent-regress && make -s -j"$(nproc)" install)
# Common terminals are compiled in, so tmux works in images without a terminfo database.
(cd ncurses && ./configure -q "${cross[@]}" BUILD_CC=zig-host-cc --prefix="$deps" --without-shared \
  --without-debug --without-ada --without-cxx --without-cxx-binding --without-manpages \
  --without-progs --without-tests --enable-widec --disable-db-install \
  --with-terminfo-dirs=/etc/terminfo:/lib/terminfo:/usr/share/terminfo \
  --with-fallbacks=xterm-256color,screen-256color,tmux-256color,xterm,screen,vt100 \
  && make -s -j"$(nproc)" install)
(cd tmux && PKG_CONFIG=false ./configure -q "${cross[@]}" --prefix=/usr/local \
  --sysconfdir=/usr/local/etc --enable-static LDFLAGS=-s \
  LIBEVENT_CORE_CFLAGS="-I$deps/include" LIBEVENT_CORE_LIBS="-L$deps/lib -levent_core" \
  LIBEVENT_CFLAGS="-I$deps/include" LIBEVENT_LIBS="-L$deps/lib -levent_core" \
  LIBTINFO_CFLAGS="-I$deps/include -I$deps/include/ncursesw" LIBTINFO_LIBS="-L$deps/lib -lncursesw" \
  && make -s -j"$(nproc)")
install -m 0755 tmux/tmux "$out/bin/tmux"
mkdir "$licenses/tmux" && cp tmux/COPYING "$licenses/tmux/"

# file: yazi detects MIME types with it; without it, yazi shows no previews.
fetch "$FILE_URL" "$FILE_SHA256" file.tar.gz
mkdir file && tar -xzf file.tar.gz -C file --strip-components=1 && cp -a file file-host
no_libs=(--disable-shared --enable-static --disable-zlib --disable-bzlib --disable-xzlib
  --disable-zstdlib --disable-lzlib --disable-lrziplib --disable-libseccomp)
# The magic database is compiled by a file of the same version that runs on the build host.
(cd file-host && ./configure -q CC=zig-host-cc "${no_libs[@]}" && make -s -j"$(nproc)" -C src)
(cd file && ./configure -q "${cross[@]}" "${no_libs[@]}" --prefix=/usr/local --datadir=/usr/local/share \
  LDFLAGS=-s && make -s -j"$(nproc)" FILE_COMPILE="$src/file-host/src/file")
install -m 0755 file/src/file "$out/bin/file"
install -D -m 0644 file/magic/magic.mgc "$out/share/misc/magic.mgc"
mkdir "$licenses/file" && cp file/COPYING "$licenses/file/"

rust_target=$triple-unknown-linux-musl
rustup target add "$rust_target" >/dev/null
fetch "https://static.crates.io/crates/eza/eza-$EZA.crate" \
  334199a8059861f81a2d3d888a45f44fa55f82dade2412e752144a404d7ae9af eza.tar.gz
mkdir eza && tar -xzf eza.tar.gz -C eza --strip-components=1
(cd eza && cargo zigbuild -q --release --locked --target "$rust_target" --features vendored-libgit2)
install -m 0755 "eza/target/$rust_target/release/eza" "$out/bin/eza"
mkdir "$licenses/eza" && cp -r eza/LICENSE* "$licenses/eza/"

# delta has no static arm64 release; build both the same way.
fetch "https://static.crates.io/crates/git-delta/git-delta-$DELTA.crate" \
  7ff64457ae0530c322df9b6fc1d7fbc017870006cf4bbba334cd93c2f145ad3c delta.tar.gz
mkdir delta && tar -xzf delta.tar.gz -C delta --strip-components=1
(cd delta && cargo zigbuild -q --release --locked --target "$rust_target")
install -m 0755 "delta/target/$rust_target/release/delta" "$out/bin/delta"
mkdir "$licenses/delta" && cp delta/LICENSE "$licenses/delta/"

# ── recording defaults ────────────────────────────────────────────────────────
# tmux reads /usr/local/etc/tmux.conf before ~/.tmux.conf; yazi, bat and micro are pointed
# at their config by env.sh (or ENV lines in the image).
mkdir -p "$out/etc"
cp "$share/tmux.conf" "$out/etc/tmux.conf"
cp -r "$share/env.sh" "$share/yazi" "$share/bat" "$share/micro" "$out/share/narratty/"
cp "$share/THIRD-PARTY.md" "$licenses/"
