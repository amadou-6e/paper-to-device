# Paper-to-EPUB

This folder is the implementation hub for the open-source release.

## Goal

Ship a fully open-source toolchain where users can:
- convert paper PDFs for better e-reader reading
- use the modified `k2pdfopt` binary with stretch controls
- reproduce results from CLI and batch workflows

## Current Implementation Map

The codebase currently lives at repository root and is referenced here for release planning:
- `src/` - app code and CLI
- `tests/` - test suite
- `external/k2pdfopt/` - modified upstream source and build
- `requirements.txt` and `pyproject.toml` - Python packaging

## Release Scope (v0.1)

1. Open-source release with clear install/build instructions.
2. Prebuilt Windows `k2pdfopt` binary artifact (and source patch notes).
3. CLI path that supports current crop/reflow workflow.
4. Basic examples using papers in `example-papers/`.

## Next Implementation Tasks

1. Consolidate implementation docs under `paper-to-epub/implementation/`.
2. Add a reproducible build script for modified `k2pdfopt`.
3. Add an integration test that checks stretch flags are accepted.
4. Publish release notes for new stretch flags:
   - `-stretch`
   - `-stretch-`
   - `-stretchr <ratio>`
   - `-stretchmax <ratio>`

## Suggested GitHub Repo Positioning

- Name: `paper-to-epub`
- One-line pitch: Open-source PDF paper to e-reader conversion with high-fidelity layout preservation and optional reflow stretch controls.
