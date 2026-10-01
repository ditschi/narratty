# Release process

Versions come from git tags (hatch-vcs); commitizen writes the changelog.

```bash
uv run cz bump        # bumps the version, updates CHANGELOG.md, commits "bump: version …"
git push              # push main (not the tag); or open a PR with the bump commit
                      # (merge it with a merge commit, so the bump commit reaches main)
```

When the bump commit reaches `main`, `.github/workflows/release.yml` tags it `vX.Y.Z`
and releases it: build, publish to TestPyPI, verify the install, publish to PyPI,
container images, GitHub release and versioned docs. Pushing a `v*` tag by hand
triggers the same release. If a release fails after tagging, the next push to `main` retries it
until the GitHub release exists.

The release calls `.github/workflows/docker.yml`, which pushes the container images to
GHCR for linux/amd64 and linux/arm64:

| Event | Tags |
|---|---|
| Pull request | built and tested, not pushed |
| Push to `main` | `edge` |
| Release `v1.2.3` | `1.2.3`, `1.2`, `latest` |

`narratty-toolkit` gets the same tags.

## Spec changes

The spec's `version` and `schema/vN.json` mark breaking changes only.

| Change | What to do |
|---|---|
| New key, action, value or short form | Keep `version: 1`; add "(since X.Y)" to the key in `docs/user-guide/spec.md` and the release to its [Spec versions](../user-guide/spec.md#spec-versions) table |
| Default changed, e.g. a timing (like `timing.pause_ms` in 0.3) | Keep `version: 1`; say in the changelog how to get the old behaviour |
| Key removed or renamed, or its meaning changed so that existing specs fail or do something else | New `version: 2` with `schema/v2.json`; keep reading `version: 1` for at least one minor release and say how to migrate in the changelog |
| Something deprecated (like the bare `- enter`) | Keep accepting it; mark it `deprecated` in the schema and add a `validate` hint |

`schema/v1.json` is regenerated with `narratty schema > schema/v1.json` (a unit test
checks it), and each release tag serves its own copy.

## One-time setup

- PyPI and TestPyPI: add a *trusted publisher* for `ditschi/narratty`, workflow
  `release.yml`, environments `pypi` and `testpypi`.
- GitHub: create the `pypi` and `testpypi` environments, and enable GitHub Pages from the
  `gh-pages` branch for the docs.
- GHCR: after the first push, open the `narratty` and `narratty-toolkit` package
  settings on GitHub and set their visibility to public so `docker pull` works
  without logging in.
