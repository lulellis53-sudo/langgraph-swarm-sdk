from swarm_sdk.usage import UsageLog


def test_usage_summary_groups_tokens() -> None:
    log = UsageLog()
    log.add("coder", 10, False)
    log.add("coder", 5, False)
    log.add("cache", 0, True)
    summary = {row["agent"]: row["tokens"] for row in log.summary()}
    assert summary == {"cache": 0, "coder": 15}
