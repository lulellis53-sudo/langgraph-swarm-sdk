# SQL Pro benchmarkable suite

Run the SQL Pro benchmark suite against the current tree and report results.

## Steps

1. Run the suite from the repository root:

   ```bash
   uv run python -m benchmark.sql_pro.run
   ```

   Options: `--suite <path>` (default `Agents/benchmark/sql_pro/suite.yaml`),
   `--case <id>` (repeatable, run only these cases), `--json` (machine-readable
   output), `--write-results` (write JSON to `Agents/benchmark/results/sql_pro/`,
   gitignored).

2. Read the per-case verdicts. Any failing case: report the failing SQL, the
   expected vs actual result, and the exact harness error — do not silently
   retry. If the failure is in the harness itself (import error, missing
   fixture), report `blocked` with the exact error after one retry.

3. Summarize: cases passed / failed / skipped, wall time, and the suite file
   used. When `--write-results` was passed, report the results path only
   (never paste full result JSON into chat).

## Notes

- The suite is offline: cases run against bundled fixtures in
  `Agents/benchmark/sql_pro/fixtures/`, not a live database.
- Results directory `Agents/benchmark/results/` must never be committed.
