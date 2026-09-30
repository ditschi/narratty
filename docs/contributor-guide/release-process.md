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

## One-time setup

- PyPI and TestPyPI: add a *trusted publisher* for `ditschi/narratty`, workflow
  `release.yml`, environments `pypi` and `testpypi`.
- GitHub: create the `pypi` and `testpypi` environments, and enable GitHub Pages from the
  `gh-pages` branch for the docs.
- GHCR: after the first push, open the `narratty` and `narratty-toolkit` package
  settings on GitHub and set their visibility to public so `docker pull` works
  without logging in.
