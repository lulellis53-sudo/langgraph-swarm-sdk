# Newsletter lane

Offline digest assembly for the `feat/newsletter` worktree (`../Newsletter`).

## Run tests

From the worktree root:

```bash
uv run pytest tests/test_newsletter_engine.py -q
```

## API

```python
from Newsletter import SourceSnippet, build_digest

result = build_digest(
    "Weekly",
    [SourceSnippet("A", "First item.", url="https://example.com/a")],
)
print(result.markdown)
```

Email/SMTP providers are out of scope for MVP.
