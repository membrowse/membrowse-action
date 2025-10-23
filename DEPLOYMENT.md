# Deployment Guide

This document describes how to publish the `membrowse` package to PyPI.

## Overview

The project uses GitHub Actions to automatically build and publish the package to PyPI. The workflow supports multiple deployment scenarios:

1. **Automatic deployment on release** (recommended)
2. **Manual deployment via workflow dispatch**
3. **Test deployment to TestPyPI**

## Prerequisites

### PyPI Trusted Publishing (Recommended)

The workflow uses PyPI's [Trusted Publishing](https://docs.pypi.org/trusted-publishers/) feature, which uses OpenID Connect (OIDC) tokens instead of API tokens. This is more secure and doesn't require managing secrets.

**Setup steps:**

1. Go to your PyPI project page: https://pypi.org/manage/project/membrowse/
2. Navigate to "Publishing" section
3. Add a new "trusted publisher" with these settings:
   - **PyPI Project Name**: `membrowse`
   - **Owner**: `membrowse` (or your GitHub org/username)
   - **Repository name**: `membrowse-action`
   - **Workflow name**: `publish-to-pypi.yml`
   - **Environment name**: `pypi`

4. For TestPyPI (optional, for testing):
   - Go to: https://test.pypi.org/manage/project/membrowse/
   - Add the same trusted publisher with environment name: `testpypi`

### GitHub Repository Settings

Configure protected environments in your GitHub repository:

1. Go to repository Settings → Environments
2. Create a new environment named `pypi`:
   - Add protection rules (e.g., require reviewers)
   - This prevents accidental deployments
3. Optionally create a `testpypi` environment for testing

## Deployment Methods

### Method 1: Automatic Deployment (Recommended)

The workflow automatically triggers when you create a GitHub release:

1. **Update version number** in both:
   - `setup.py` (line 10)
   - `pyproject.toml` (line 7)

2. **Commit and push changes:**
   ```bash
   git add setup.py pyproject.toml
   git commit -m "Bump version to X.Y.Z"
   git push origin main
   ```

3. **Create a Git tag:**
   ```bash
   git tag -a vX.Y.Z -m "Release version X.Y.Z"
   git push origin vX.Y.Z
   ```

4. **Create a GitHub Release:**
   - Go to: https://github.com/membrowse/membrowse-action/releases/new
   - Select the tag you just created
   - Fill in release title and description
   - Click "Publish release"

5. **Monitor the deployment:**
   - Go to the Actions tab
   - Watch the "Publish to PyPI" workflow
   - The workflow will:
     - Run all tests
     - Build the package
     - Publish to PyPI automatically

### Method 2: Manual Deployment

Trigger deployment manually via the GitHub Actions UI:

1. Go to: Actions → "Publish to PyPI" workflow
2. Click "Run workflow"
3. Choose options:
   - **Branch**: Select the branch to deploy from (usually `main`)
   - **Dry run**:
     - `true`: Publishes to TestPyPI for testing
     - `false`: Publishes to production PyPI

4. Click "Run workflow"

### Method 3: Test Deployment to TestPyPI

Test the deployment process without affecting production:

1. Follow "Method 2" above
2. Set **Dry run** to `true`
3. The package will be published to: https://test.pypi.org/project/membrowse/

To test installation from TestPyPI:
```bash
pip install -i https://test.pypi.org/simple/ membrowse
```

## Workflow Details

### Workflow Steps

1. **Test Job**: Runs the full test suite to ensure code quality
2. **Build Job**: Creates source distribution (`.tar.gz`) and wheel (`.whl`)
3. **Publish Job**: Uploads to PyPI using trusted publishing

### Files Built

- **Source distribution**: `membrowse-X.Y.Z.tar.gz`
- **Wheel**: `membrowse-X.Y.Z-py3-none-any.whl`

Both files are uploaded as GitHub artifacts and retained for 7 days.

## Version Management

The package version is defined in two places (must be kept in sync):

- `setup.py`: Line 10 → `version="X.Y.Z"`
- `pyproject.toml`: Line 7 → `version = "X.Y.Z"`

### Versioning Scheme

Follow [Semantic Versioning](https://semver.org/):
- **MAJOR**: Incompatible API changes
- **MINOR**: New functionality (backward compatible)
- **PATCH**: Bug fixes (backward compatible)

Examples:
- `0.0.1` → `0.0.2`: Bug fix
- `0.0.2` → `0.1.0`: New feature
- `0.1.0` → `1.0.0`: First stable release

## Troubleshooting

### "403 Forbidden" error during publish

**Cause**: Trusted publishing not configured properly

**Solution**:
1. Verify trusted publisher settings on PyPI
2. Ensure environment name matches exactly: `pypi`
3. Check that workflow name is: `publish-to-pypi.yml`

### "Package version already exists" error

**Cause**: Version number not updated

**Solution**:
1. Update version in `setup.py` and `pyproject.toml`
2. Create a new tag and release

### Tests fail during deployment

**Cause**: Code issues introduced since last test run

**Solution**:
1. Run tests locally: `python -m pytest tests/ -v`
2. Fix any failing tests
3. Push fixes and retry deployment

### Distribution check fails

**Cause**: Invalid package metadata or missing README

**Solution**:
1. Check `setup.py` and `pyproject.toml` for errors
2. Ensure `README.md` exists and is valid
3. Test locally: `python -m build && twine check dist/*`

## Manual Publishing (Fallback)

If the GitHub workflow fails, you can publish manually:

1. **Install build tools:**
   ```bash
   pip install build twine
   ```

2. **Build the package:**
   ```bash
   python -m build
   ```

3. **Check the distribution:**
   ```bash
   twine check dist/*
   ```

4. **Upload to TestPyPI (test first):**
   ```bash
   twine upload --repository testpypi dist/*
   ```

5. **Upload to PyPI (production):**
   ```bash
   twine upload dist/*
   ```

   You'll need a PyPI API token. Create one at: https://pypi.org/manage/account/token/

## Post-Deployment Verification

After publishing, verify the deployment:

1. **Check PyPI page:**
   - https://pypi.org/project/membrowse/

2. **Test installation:**
   ```bash
   pip install membrowse
   membrowse --help
   ```

3. **Verify version:**
   ```bash
   pip show membrowse
   ```

## Security Best Practices

- ✅ Use trusted publishing (OIDC) instead of API tokens
- ✅ Require environment approval for production deployments
- ✅ Always run tests before publishing
- ✅ Never commit API tokens to the repository
- ✅ Review changes carefully before creating releases

## Additional Resources

- [PyPI Trusted Publishers Guide](https://docs.pypi.org/trusted-publishers/)
- [Python Packaging Guide](https://packaging.python.org/)
- [GitHub Actions for Python](https://docs.github.com/en/actions/automating-builds-and-tests/building-and-testing-python)
- [PyPA Publish Action](https://github.com/pypa/gh-action-pypi-publish)
