"""Tabular tooling with polars and pyarrow.

Frames are loaded with polars (pyarrow-backed I/O) and rendered to plain text
so swarm agents can consume schema, statistics, and quality checks without
holding DataFrame objects in LLM context.
"""


def load_table(path: str):
    """Load a CSV or Parquet file into a polars DataFrame."""
    import polars as pl

    if path.endswith((".parquet", ".pq")):
        return pl.read_parquet(path)
    return pl.read_csv(path)


def to_arrow(frame):
    """Convert a polars frame to a pyarrow Table for Arrow-based exchange."""
    return frame.to_arrow()


def summarize_frame(frame) -> str:
    """Render shape, schema and null counts as agent-friendly text."""
    schema = "\n".join(f"  {name}: {dtype}" for name, dtype in frame.schema.items())
    nulls = "\n".join(f"  {name}: {frame[name].null_count()}" for name in frame.columns)
    return (
        f"rows={frame.height}, columns={frame.width}\n"
        f"schema:\n{schema}\n"
        f"null counts:\n{nulls}"
    )


def table_tool(path: str, *, name: str = "inspect_table"):
    """Return a tool function that lets an agent inspect one dataset."""

    def inspect(question: str) -> str:
        """Inspect the dataset's structure to answer a question about it."""
        return f"{summarize_frame(load_table(path))}\nquestion: {question}"

    inspect.__name__ = name
    return inspect


def validate_dataset_tool(path: str, *, name: str = "validate_dataset"):
    """Return a tool function that checks one dataset for quality issues."""

    def validate() -> str:
        """Check the dataset for nulls, duplicate rows and empty strings."""
        import polars as pl

        frame = load_table(path)
        nulls = sum(int(frame[col].null_count()) for col in frame.columns)
        duplicates = frame.height - frame.unique().height
        empty_strings = sum(
            int((frame[col] == "").sum())
            for col, dtype in frame.schema.items()
            if dtype == pl.String
        )
        problems = []
        if nulls:
            problems.append(f"{nulls} null values")
        if duplicates:
            problems.append(f"{duplicates} duplicate rows")
        if empty_strings:
            problems.append(f"{empty_strings} empty strings")
        if not problems:
            return "Dataset is clean."
        return "Dataset issues: " + ", ".join(problems) + "."

    validate.__name__ = name
    return validate
