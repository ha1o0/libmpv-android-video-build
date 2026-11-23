#!/bin/bash -e
. ../../include/depinfo.sh
. ../../include/path.sh
build=_build$ndk_suffix
case "$1" in build) ;; clean) rm -rf "$build"; exit 0 ;; *) exit 255 ;; esac
# Describe Android's existing zlib for curl's static pkg-config dependency.
cat > "$prefix_dir/lib/pkgconfig/zlib.pc" <<EOF
Name: zlib
Description: Android system zlib
Version: 1.2.8
Libs: -lz
EOF
cmake -S . -B "$build" -G Ninja -DCMAKE_SYSTEM_NAME=Android \
  -DCMAKE_SYSTEM_VERSION=21 -DCMAKE_ANDROID_ARCH_ABI="$(basename "$prefix_dir")" \
  -DCMAKE_ANDROID_NDK="$DIR/sdk/android-sdk-linux/ndk/$v_ndk" \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$prefix_dir" \
  -DCMAKE_INSTALL_LIBDIR=lib -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
  -DBUILD_SHARED_LIBS=OFF -DBUILD_STATIC_LIBS=ON -DBUILD_CURL_EXE=OFF \
  -DBUILD_TESTING=OFF -DBUILD_EXAMPLES=OFF -DBUILD_LIBCURL_DOCS=OFF \
  -DBUILD_MISC_DOCS=OFF -DENABLE_CURL_MANUAL=OFF \
  -DCURL_USE_PKGCONFIG=OFF -DCURL_USE_CMAKECONFIG=OFF \
  -DCURL_USE_OPENSSL=OFF -DCURL_USE_MBEDTLS=ON \
  -DMBEDTLS_INCLUDE_DIR="$prefix_dir/include" \
  -DMBEDTLS_LIBRARY="$prefix_dir/lib/libmbedtls.a" \
  -DMBEDX509_LIBRARY="$prefix_dir/lib/libmbedx509.a" \
  -DMBEDCRYPTO_LIBRARY="$prefix_dir/lib/libmbedcrypto.a" \
  -DCURL_CA_BUNDLE=none -DCURL_CA_PATH=/system/etc/security/cacerts \
  -DUSE_NGHTTP2=ON -DNGHTTP2_USE_STATIC_LIBS=ON \
  -DCMAKE_REQUIRE_FIND_PACKAGE_NGHTTP2=ON \
  -DNGHTTP2_INCLUDE_DIR="$prefix_dir/include" \
  -DNGHTTP2_LIBRARY="$prefix_dir/lib/libnghttp2.a" \
  -DENABLE_ARES=OFF -DENABLE_THREADED_RESOLVER=ON \
  -DUSE_NGTCP2=OFF -DUSE_QUICHE=OFF -DUSE_ECH=OFF \
  -DCURL_USE_LIBPSL=OFF -DCURL_USE_LIBSSH=OFF -DCURL_USE_LIBSSH2=OFF \
  -DCURL_USE_GSSAPI=OFF -DCURL_DISABLE_LDAP=ON -DUSE_LIBIDN2=OFF \
  -DCURL_BROTLI=OFF -DCURL_ZSTD=OFF -DCURL_ZLIB=ON \
  -DZLIB_INCLUDE_DIR="$toolchain/sysroot/usr/include" \
  -DZLIB_LIBRARY="$toolchain/sysroot/usr/lib/$ndk_triple/21/libz.so"
cmake --build "$build" --parallel "$cores"
cmake --install "$build"
sh "$prefix_dir/bin/curl-config" --features | grep -Fxq HTTP2
sh "$prefix_dir/bin/curl-config" --features | grep -Fxq SSL
pkg-config --static --exists libcurl
