# Mobile zcopy builds

The build infrastructure is forked from media-kit. Native player source is pinned
in `mobile-sources.json` to `ha1o0/mpv`, branch `zcopy`, at commit
`d99d62cc036f269d272d060b32f2b8dd6f631167`. The Android source lock also pins FFmpeg 8.1.3, libplacebo 7.360.1
and their header dependencies.
The PC build repositories are maintained independently.

`mobile-release.yml` supports two entry points:

- Push the recipe to `codex/mobile-native-validation` to compile and verify CI
  artifacts. This does not publish a GitHub release.
- Run **workflow_dispatch** with a fresh `release_tag` to compile, verify and
  publish an immutable prerelease. An optional `request_id` correlates callers.

The release manifest records both the recipe commit and `native_sources`, as
well as asset checksums and the Actions run ID. Update both mobile source locks
together when adopting a newer zcopy commit. A moving branch name alone is never
used as the build input. Source archives are checked against SHA256 before use.

libplacebo is built as a real static library, including its OpenGL/GLES backend,
and linked into libmpv. Vulkan rendering stays disabled on these mobile builds.
The Android recipe patches libplacebo's `MAIN_*` and `HOOKED_*` sampling
aliases so Anime4K and other mpv shaders can compile with affected OpenGL ES
drivers. See [Wplayer #12](https://github.com/rapidrabbit76/Wplayer/pull/12)
for the original report and implementation.
The mpv linker rejects unresolved symbols. This avoids the former header-only
libplacebo workaround, which produced iOS binaries that crashed during loading.

The default Android flavor includes the RM demuxer, RV10/RV20/RV30/RV40 video
decoders, Cook/Sipro audio, and the `bwdif` filter used by mpv's deinterlacer.
The release workflow checks these in the linked library for all four ABIs.
A local SDK/NDK build uses the same recipe: run `./bundle_default.sh` inside
`buildscripts` with the SDK at `buildscripts/sdk/android-sdk-linux` on Linux,
or dispatch the workflow from this recipe to build the verified jars elsewhere.

The app consumer is `scripts/mobile_libmpv.py` in bota. Only integrate a published,
verified release; it updates the media-kit mobile package versions/checksums and
then the app submodule lock. CI artifacts alone are not a production dependency.
