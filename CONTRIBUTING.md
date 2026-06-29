# Contributing to searchts

Thank you for your interest in contributing to searchts! This document provides guidelines and instructions for contributing.

## Getting Started

1. Fork the repository on GitHub
2. Clone your fork locally
3. Create a new branch for your contribution
4. Make your changes
5. Run tests and linting
6. Submit a pull request

## Development Setup

```bash
# Clone your fork
git clone https://github.com/capad-xyz/searchts.git
cd searchts

# Install in development mode
pip install -e ".[dev]"

# Install pre-commit hooks (optional but recommended)
pre-commit install
```

## Code Style

We use the following tools to maintain code quality:

- **ruff**: Linting and import sorting
- **mypy**: Type checking
- **pytest**: Testing

Run all checks before submitting a PR:

```bash
# Linting
ruff check searchts tests
ruff format searchts tests

# Type checking
mypy searchts

# Tests
pytest
```

## Adding New Channels

searchts uses a unified channel interface. To add a new platform:

1. Create a new file in `searchts/channels/`
2. Implement the channel contract (see existing channels for examples)
3. Add tests in `tests/test_channels.py`
4. Update `searchts/doctor.py` to include the new channel
5. Update documentation

## Pull Request Guidelines

- **Small, focused changes** are preferred over large refactors
- Include tests for new functionality
- Update documentation if needed
- Follow existing code style
- Reference any related issues

## Reporting Issues

When reporting bugs, please include:

- Python version
- Operating system
- Steps to reproduce
- Expected vs actual behavior
- Any error messages

## Questions?

Open an issue or a discussion on GitHub, or reach out at oss@capad.fyi.
