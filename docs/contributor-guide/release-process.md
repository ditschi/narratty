# Release process

Versions come from git tags (hatch-vcs); commitizen writes the changelog.

```bash
uv run cz bump        # bumps the version, updates CHANGELOG.md, creates the vX.Y.Z tag
git push --follow-tags
```

Pushing a `v*` tag runs `.github/workflows/release.yml`: build, publish to TestPyPI, verify
the install, publish to PyPI, create the GitHub release and deploy versioned docs.

The same tag runs `.github/workflows/docker.yml`, which pushes the container images to
GHCR for linux/amd64 and linux/arm64:

| Event | Tags |
|---|---|
| Pull request | built and tested, not pushed |
| Push to `main` | `edge`, `edge-kokoro` |
| Tag `v1.2.3` | `1.2.3`, `1.2`, `latest` and the same with `-kokoro` |

## One-time setup

- PyPI and TestPyPI: add a *trusted publisher* for `ditschi/narratty`, workflow
  `release.yml`, environments `pypi` and `testpypi`.
- GitHub: create the `pypi` and `testpypi` environments, and enable GitHub Pages from the
  `gh-pages` branch for the docs.
- GHCR: after the first push, open the `narratty` package settings on GitHub and set
  its visibility to public so `docker pull` works without logging in.
