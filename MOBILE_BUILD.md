# Mobile zcopy builds

The build infrastructure is forked from media-kit. Native player source is pinned
in `mobile-sources.json` to `ha1o0/mpv`, branch `zcopy`, at commit
`d99d62cc036f269d272d060b32f2b8dd6f631167`. Android and iOS use identical source
locks: FFmpeg 7.1.5, libplacebo 7.360.1 and its pinned header dependencies.
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
The mpv linker rejects unresolved symbols. This avoids the former header-only
libplacebo workaround, which produced iOS binaries that crashed during loading.

The app consumer is `scripts/mobile_libmpv.py` in bota. Only integrate a published,
verified release; it updates the media-kit mobile package versions/checksums and
then the app submodule lock. CI artifacts alone are not a production dependency.
