# Publishing a release

The root `VERSION` file is the version source for the app, installer and release assets.

1. Set `VERSION` to the next `MAJOR.MINOR.PATCH` version. Update the version in the Appx manifest if preparing an MSIX package.
2. Add the user-facing changes under that version in `CHANGELOG.md`.
3. Commit and push the changes to `main`.

The Windows release workflow checks the version, builds the app and installer, verifies bundled conversions, then creates the matching `v`-prefixed GitHub tag and release with the installer, source archive and SHA-256 checksums attached.

Alternatively, run **Build Windows release** from the Actions tab after updating `VERSION` and selecting its matching value for the manual workflow input.

