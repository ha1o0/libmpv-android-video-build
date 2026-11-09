#!/bin/bash -e
. ../../include/depinfo.sh
. ../../include/path.sh

build=_build$ndk_suffix
case "$1" in
  build) ;;
  clean) rm -rf "$build"; exit 0 ;;
  *) exit 255 ;;
esac

unset CC CXX
meson setup "$build" --cross-file "$prefix_dir/crossfile.txt" \
  --libdir=lib --default-library=static -Db_staticpic=true \
  -Dauto_features=disabled -Dopengl=enabled -Dgl-proc-addr=enabled \
  -Ddovi=enabled -Ddemos=false -Dtests=false -Dbench=false -Dfuzz=false
ninja -C "$build" -j"$cores"
DESTDIR="$prefix_dir" ninja -C "$build" install
# Keep the mobile bundle self-contained; do not introduce libc++_shared.so.
sed -i '/^Libs:/s/$/ -lc++_static -lc++abi/' "$prefix_dir/lib/pkgconfig/libplacebo.pc"
