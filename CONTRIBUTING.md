# Contributing to FM2note

Thanks for your interest in contributing! Here's how to get started.

## Development Setup

```bash
git clone https://github.com/Austin5925/FM2note.git
cd FM2note
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Workflow

```bash
make lint      # ruff check
make format    # ruff format
make test      # pytest (all tests must pass before committing)
make test-cov  # pytest with coverage report
make build     # python -m build (generate sdist + wheel)
```

## Code Style

- **Linter**: ruff (line-length 100, Python 3.11+)
- **Type hints**: Required on all public APIs
- **Architecture**: Protocol-based abstractions (Transcriber, Summarizer)
- **Naming**: modules `snake_case`, classes `PascalCase`
- **Async**: All I/O operations use `async/await`
- **Logging**: loguru with structured context

## Adding a New ASR Engine

1. Create `src/transcriber/your_engine.py`
2. Implement the `Transcriber` protocol from `src/transcriber/base.py`
3. Register in `src/transcriber/factory.py`
4. Add tests in `tests/test_your_engine.py`
5. Update `config/config.example.yaml` and README

## Adding a New Summarizer

1. Create `src/summarizer/your_summarizer.py`
2. Implement the `Summarizer` protocol from `src/summarizer/base.py`
3. Register in `src/summarizer/factory.py`
4. Add tests
5. Update config, `.env.example`, and README

## Pull Request Process

1. Fork and create a branch
2. Make your changes
3. Run `make lint && make test`
4. Open a PR with a clear description
5. Ensure CI passes

## Commit Messages

Format: `vX.Y.Z: description` (for releases) or `description` (for regular commits).

## Reporting Issues

Use [GitHub Issues](https://github.com/Austin5925/FM2note/issues) with the provided templates.
