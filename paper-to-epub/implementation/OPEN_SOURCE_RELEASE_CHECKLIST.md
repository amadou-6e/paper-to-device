# Open-Source Release Checklist

## 1. Repository Packaging

- [ ] Add clear root README section for modified `k2pdfopt` support.
- [ ] Add LICENSE coverage for your code and upstream notices.
- [ ] Add `CONTRIBUTING.md` with build/test commands.
- [ ] Add `CHANGELOG.md` for stretch feature and integration updates.

## 2. Build + Binary Distribution

- [ ] Document Windows build path for `external/k2pdfopt`.
- [ ] Publish prebuilt binary in GitHub Releases.
- [ ] Add checksum and version tag for binary artifacts.
- [ ] Keep source changes split into: upstreamable vs local-only patches.

## 3. Minimum Quality Gate

- [ ] Run unit tests for `src/` and `tests/`.
- [ ] Smoke test: convert one known paper end-to-end.
- [ ] Smoke test: baseline vs stretch output generation.
- [ ] Verify CLI help lists stretch options correctly.

## 4. Documentation

- [ ] Add quickstart for first conversion command.
- [ ] Add section: when to use high-fidelity vs OCR-like workflows.
- [ ] Add section: limitations and expected output tradeoffs.
- [ ] Add examples with screenshots or output previews.

## 5. Launch Readiness

- [ ] Create v0.1 release tag.
- [ ] Publish release post summary.
- [ ] Add issue templates for bugs and feature requests.
- [ ] Add discussion prompt for user feedback.
