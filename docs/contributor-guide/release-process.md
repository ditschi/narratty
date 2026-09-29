# Release process

Versions come from git tags (hatch-vcs); commitizen writes the changelog.

```bash
uv run cz bump        # bumps the version, updates CHANGELOG.md, creates the vX.Y.Z tag
git push --follow-tags
```

Pushing a `v*` tag runs `.github/workflows/release.yml`: build, publish to TestPyPI, verify
the install, publish to PyPI, create the GitHub release and deploy versioned docs.

## One-time setup

- PyPI and TestPyPI: add a *trusted publisher* for `ditschi/narratty`, workflow
  `release.yml`, environments `pypi` and `testpypi`.
- GitHub: create the `pypi` and `testpypi` environments, and enable GitHub Pages from the
  `gh-pages` branch for the docs.
