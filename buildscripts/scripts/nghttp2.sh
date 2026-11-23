#!/bin/bash -e
. ../../include/depinfo.sh
. ../../include/path.sh
build=_build$ndk_suffix
case "$1" in build) ;; clean) rm -rf "$build"; exit 0 ;; *) exit 255 ;; esac
cmake -S . -B "$build" -G Ninja -DCMAKE_SYSTEM_NAME=Android \
  -DCMAKE_SYSTEM_VERSION=21 -DCMAKE_ANDROID_ARCH_ABI="$(basename "$prefix_dir")" \
  -DCMAKE_ANDROID_NDK="$DIR/sdk/android-sdk-linux/ndk/$v_ndk" \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$prefix_dir" \
  -DCMAKE_INSTALL_LIBDIR=lib -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
  -DENABLE_LIB_ONLY=ON -DBUILD_STATIC_LIBS=ON -DBUILD_SHARED_LIBS=OFF \
  -DENABLE_DOC=OFF -DENABLE_FAILMALLOC=OFF -DBUILD_TESTING=OFF
cmake --build "$build" --parallel "$cores"
cmake --install "$build"
