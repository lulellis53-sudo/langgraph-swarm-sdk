from pathlib import Path

import pytest
from WebSearch.frontend.providers import PrefilterPolicy, load_providers


def _load(tmp_path: Path, text: str):
    path = tmp_path / "providers.yaml"
    path.write_text(text, encoding="utf-8")
    return load_providers(path)


def test_prefilter_defaults_without_block(tmp_path: Path) -> None:
    assert _load(tmp_path, "version: 1\n").prefilter == PrefilterPolicy()


def test_prefilter_block_is_parsed_and_normalized(tmp_path: Path) -> None:
    cfg = _load(
        tmp_path,
        "prefilter:\n"
        "  schemes: [HTTPS]\n"
        "  blocked_domains: ['.Spam.Example', '']\n"
        "  min_snippet_chars: '12'\n"
        "  require_title: false\n",
    )
    assert cfg.prefilter == PrefilterPolicy(
        schemes=("https",),
        blocked_domains=("spam.example",),
        min_snippet_chars=12,
        require_title=False,
    )


def test_prefilter_empty_schemes_fall_back_to_default(tmp_path: Path) -> None:
    assert _load(tmp_path, "prefilter:\n  schemes: []\n").prefilter.schemes == (
        "http",
        "https",
    )


def test_prefilter_bad_number_names_the_field(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"prefilter\.min_snippet_chars"):
        _load(tmp_path, "prefilter:\n  min_snippet_chars: abc\n")


def test_prefilter_non_bool_require_title_names_the_field(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"prefilter\.require_title"):
        _load(tmp_path, "prefilter:\n  require_title: 'false'\n")


def test_packaged_providers_yaml_has_permissive_prefilter() -> None:
    assert load_providers().prefilter == PrefilterPolicy()
