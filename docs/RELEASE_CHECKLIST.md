# Release checklist

Use this checklist before creating the next `vMAJOR.MINOR.PATCH` tag.

## Automated release-candidate gate

From a clean working tree with the development dependencies installed, run:

```powershell
.\scripts\test_release_candidate.ps1
```

This gate prepares the pinned FFmpeg build, lints Python and QML, runs the unit/integration
suite, runs real-media end-to-end tests, and builds and verifies the Windows package. Use
`-SkipPackage` only for a faster local check; it is not sufficient to approve a release.

The end-to-end suite generates its own short H.264/AAC media and verifies:

- embedded and external subtitle discovery;
- external subtitle preview parsing;
- quick stream-copy interval removal with video, audio, and embedded subtitles preserved;
- smart hybrid cutting through copy and re-encoded boundary chunks;
- embedded and external subtitle rebuilding, removal, clipping, and timestamp shifting;
- final duration and stream validation with real FFmpeg and ffprobe.

## Manual product review

Install the candidate ZIP with `scripts\install.ps1` on a normal Windows user account, then
check the user-facing paths that cannot be fully covered headlessly:

- launch from the Start Menu and Desktop shortcut;
- import one MP4 and one MKV;
- preview/select one embedded and one external subtitle track;
- create, edit, import, and export cut markers;
- export once with Quick Cutting and once with Smart Cutting;
- play each output through the cut boundary and confirm picture, audio, and subtitles;
- check light/dark themes and each supported UI language;
- check for updates from Settings and confirm the installed version;
- uninstall through Windows Installed apps, preserving user data first;
- reinstall, then uninstall again and choose user-data removal;
- confirm user videos and exported media are never removed.

Record any accepted limitations in the release notes. Do not create the tag while an
automated check fails or a release-blocking manual check is unresolved.

## Publish

1. Make sure CI and Build Windows are green on the release commit.
2. Choose the next semantic version from the change impact.
3. Push the tag, for example: `git tag v1.4.0` then `git push origin v1.4.0`.
4. Wait for the Release workflow to stamp the version, repeat the automated checks on a
   clean Windows runner, verify the package, smoke-launch it, and publish the ZIP/checksum.
5. Install once from the public one-line installer and verify the About version.
