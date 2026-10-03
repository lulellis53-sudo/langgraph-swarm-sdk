"""Host rule engine and invariant enforcement for low-resource hardware."""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar, TypeVar

from pydantic import BaseModel, Field, model_validator

DEFAULT_MODERN_CLI_TOOLS: dict[str, str] = {
    "grep": "rg",
    "cat": "bat",
    "find": "fd",
    "sed": "sd",
    "awk": "choose",
    "ls": "eza",
}

DEFAULT_SIMD_SUPPORTED: list[str] = ["AVX2", "FMA", "SSE4.2"]
DEFAULT_SIMD_PROHIBITED: list[str] = ["AVX-512"]

WRAPPER_COMMANDS: set[str] = {
    "sudo",
    "xargs",
    "env",
    "nohup",
    "time",
    "nice",
    "exec",
    "doas",
}

T = TypeVar("T")


class _ClassOrInstanceMethod:
    """Descriptor enabling a method to be called on either the class or an instance."""

    def __init__(self, func: Callable[..., Any]) -> None:
        self.func = func

    def __get__(self, instance: Any, owner: type | None = None) -> Callable[..., Any]:
        if instance is None:
            assert owner is not None
            default_instance = owner()

            def class_wrapper(*args: Any, **kwargs: Any) -> Any:
                return self.func(default_instance, *args, **kwargs)

            return class_wrapper

        def instance_wrapper(*args: Any, **kwargs: Any) -> Any:
            return self.func(instance, *args, **kwargs)

        return instance_wrapper


class HostInvariants(BaseModel):
    """Host architectural invariants and resource constraints."""

    cpu_arch: str = "x86_64"
    cpu_model: str = "Intel Core i7-9750H"
    simd_supported: list[str] = Field(default_factory=lambda: list(DEFAULT_SIMD_SUPPORTED))
    simd_prohibited: list[str] = Field(default_factory=lambda: list(DEFAULT_SIMD_PROHIBITED))
    ram_total_gb: float = 16.0
    ram_ceiling_gb: float = 13.6
    max_subagents: int = 3
    modern_cli_tools: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_MODERN_CLI_TOOLS))

    @model_validator(mode="after")
    def validate_simd_constraints(self) -> HostInvariants:
        """Validate that SIMD flags match this host's actual CPU capabilities."""
        supported_upper = [s.upper() for s in self.simd_supported]
        prohibited_upper = [s.upper() for s in self.simd_prohibited]

        if any("AVX-512" in s or "AVX512" in s for s in supported_upper):
            raise ValueError("AVX-512 is strictly prohibited on this host architecture")

        if not any("AVX-512" in s or "AVX512" in s for s in prohibited_upper):
            raise ValueError("AVX-512 must be marked as strictly prohibited in simd_prohibited")

        return self


class HostRuleEngine:
    """Host hardware rule engine and safety enforcement."""

    DEFAULT_MACHINE_RULES: ClassVar[Path] = Path("/Users/usuario/AGENTS.md")
    DEFAULT_REPO_RULES: ClassVar[Path] = Path("/Users/usuario/Swarm/AGENTS.md")

    def __init__(
        self,
        root_dir: str | Path | None = None,
        rules_path: str | Path | None = None,
        invariants: HostInvariants | None = None,
    ) -> None:
        """Initialize the rule engine with the host invariants."""
        self.root_dir: Path | None = Path(root_dir) if root_dir is not None else None
        if rules_path is not None:
            self.rules_path: Path | None = Path(rules_path)
        else:
            self.rules_path = self.discover_rules(self.root_dir)

        if invariants is not None:
            self.invariants = invariants
        else:
            self.invariants = self.parse_invariants(self.rules_path)

    @classmethod
    def discover_rules(
        cls, root_dir: str | Path | None = None, fallback_to_system: bool = False
    ) -> Path | None:
        """Looks for AGENTS.md in root_dir or standard repository/machine paths."""
        if root_dir is not None:
            p = Path(root_dir)
            if p.is_file():
                return p
            candidate = p / "AGENTS.md"
            if candidate.is_file():
                return candidate
            if not fallback_to_system:
                return None

        # Standard hierarchy
        for candidate in (cls.DEFAULT_REPO_RULES, cls.DEFAULT_MACHINE_RULES):
            if candidate.is_file():
                return candidate

        return None

    def _parse_invariants_content(self, content: str) -> HostInvariants:
        # Check if content attempts to enable or support AVX-512
        avx512_prohibited_violation = re.search(
            r"(?i)(?:\bsimd_supported\s*:[^\n]*\bavx-?512\b|\b(?:enable[ds]?|support(?:ed|s)?|allow(?:ed|s)?)\b[^\n]*\bavx-?512\b|\bavx-?512\b[^\n]*\b(?:enable[ds]?|support(?:ed|s)?|allow(?:ed|s)?)\b)",
            content,
        )
        if avx512_prohibited_violation:
            raise ValueError("AVX-512 is strictly prohibited on this host architecture")

        # Parse subagent concurrency cap
        max_subagents = 3
        subagents_match = re.search(
            r"(?i)(?:concurrency cap:\s*(?:never\s+spawn\s+more\s+than\s+)?"
            r"|never\s+spawn\s+more\s+than\s+(?:\d+\s+to\s+)?|max_subagents:\s*)(\d+)",
            content,
        )
        if subagents_match:
            max_subagents = int(subagents_match.group(1))

        # Parse RAM capacity
        ram_total_gb = 16.0
        ram_match = re.search(r"(\d+(?:\.\d+)?)\s*GB\s+RAM", content)
        if ram_match:
            ram_total_gb = float(ram_match.group(1))

        return HostInvariants(
            max_subagents=max_subagents,
            ram_total_gb=ram_total_gb,
        )

    @_ClassOrInstanceMethod
    def parse_invariants(self, rules_path: str | Path | None = None) -> HostInvariants:
        """Reads discovered rules or loads default host profile, enforcing AVX-512 prohibition."""
        target_path: Path | None = None
        if rules_path is not None:
            target_path = Path(rules_path)
        elif self.rules_path is not None:
            target_path = self.rules_path

        if target_path is None or not target_path.is_file():
            return HostInvariants()

        try:
            content = target_path.read_text(encoding="utf-8")
        except OSError, UnicodeDecodeError:
            return HostInvariants()

        return self._parse_invariants_content(content)

    @_ClassOrInstanceMethod
    def inject_system_prompt(self, base_prompt: str = "") -> str:
        """Formats system instructions injecting host constraints and modern CLI tool rules."""
        invariants = self.invariants
        simd_sup = ", ".join(invariants.simd_supported)
        simd_prohib = ", ".join(invariants.simd_prohibited)
        tools_mapping = "\n".join(
            f"  - `{legacy}` -> `{modern}`"
            for legacy, modern in invariants.modern_cli_tools.items()
        )

        rules_block = (
            "## Host Architectural Invariants & Execution Constraints\n"
            f"- Target Architecture: `{invariants.cpu_arch}`\n"
            f"- CPU Model: `{invariants.cpu_model}`\n"
            f"- Supported SIMD: {simd_sup}\n"
            f"- Strictly Prohibited SIMD: {simd_prohib} "
            "(STRICTLY PROHIBITED: Host hardware lacks AVX-512 support)\n"
            f"- RAM Budget: {invariants.ram_total_gb} GB total, "
            f"{invariants.ram_ceiling_gb} GB hard ceiling\n"
            f"- Concurrency Cap: Maximum {invariants.max_subagents} concurrent active subagents\n\n"
            "## Mandated Modern CLI Tooling (Legacy Unix Commands Prohibited)\n"
            "Always use the modern replacements; do NOT fall back to legacy commands:\n"
            f"{tools_mapping}"
        )

        if not base_prompt or not base_prompt.strip():
            return rules_block

        return f"{base_prompt.strip()}\n\n{rules_block}"

    def _check_prohibited_simd(self, command_line: str) -> str | None:
        """Checks if a command enables or targets prohibited SIMD instructions."""
        for simd in self.invariants.simd_prohibited:
            if simd.upper() == "AVX-512":
                # Look for flags like -mavx512, +avx512, --enable-avx512, -DENABLE_AVX512
                flag_match = re.search(
                    r"(?i)(?:-m|\+|--enable-|-enable-|-D[A-Za-z0-9_]*?)avx-?512\w*", command_line
                )
                if flag_match:
                    prefix = command_line[max(0, flag_match.start() - 5) : flag_match.start()]
                    if not prefix.endswith("-mno-") and not prefix.endswith("-no-"):
                        return f"Command attempts to use prohibited SIMD instruction set: {simd}"

                # Look for word matches like avx512 / AVX-512 unless preceded by negation
                for m in re.finditer(
                    r"(?i)(?:^|[^a-zA-Z0-9_-])(?:[A-Za-z0-9_]+_)?avx-?512\w*", command_line
                ):
                    start = m.start()
                    prefix = command_line[max(0, start - 10) : start]
                    if re.search(r"(?i)(?:-mno-?|no[-_\s]+)$", prefix):
                        continue
                    return f"Command attempts to use prohibited SIMD instruction set: {simd}"
        return None

    def _split_pipeline_commands(self, command_line: str) -> list[list[str]]:
        """Tokenizes shell commands into separate pipeline and chained executions."""
        try:
            lexer = shlex.shlex(command_line, posix=True, punctuation_chars="|;&")
            lexer.whitespace_split = True
            tokens = list(lexer)
        except ValueError:
            # Fallback regex split on control operators if unclosed quotes
            raw_segments = re.split(r"(?:\|\||&&|[|;&\n])", command_line)
            commands: list[list[str]] = []
            for seg in raw_segments:
                seg_tokens = seg.strip().split()
                if seg_tokens:
                    commands.append(seg_tokens)
            return commands

        commands = []
        current_cmd: list[str] = []
        for token in tokens:
            if token in {"|", "||", "&&", ";", "&"}:
                if current_cmd:
                    commands.append(current_cmd)
                    current_cmd = []
            else:
                current_cmd.append(token)
        if current_cmd:
            commands.append(current_cmd)
        return commands

    @_ClassOrInstanceMethod
    def validate_command_safety(self, command_line: str) -> tuple[bool, str | None]:
        """Validates that a command does not invoke prohibited SIMD or legacy CLI tools."""
        # 1. Check prohibited SIMD instructions
        simd_error = self._check_prohibited_simd(command_line)
        if simd_error is not None:
            return False, simd_error

        # 2. Check nested subshell executions e.g. $(cat file) or `cat file`
        subshells = re.findall(r"\$\((.*?)\)|`([^`]+)`", command_line)
        for s1, s2 in subshells:
            sub_cmd = s1 or s2
            if sub_cmd.strip():
                safe, reason = self.validate_command_safety(sub_cmd)
                if not safe:
                    return safe, reason

        # 3. Check individual pipeline commands
        commands = self._split_pipeline_commands(command_line)
        modern_tools = self.invariants.modern_cli_tools

        for cmd_tokens in commands:
            tokens = list(cmd_tokens)
            # Strip environment variable assignments (e.g. VAR=val cmd)
            while tokens and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=.*$", tokens[0]):
                tokens.pop(0)

            # Strip command wrappers like sudo, xargs, etc.
            while tokens and os.path.basename(tokens[0]) in WRAPPER_COMMANDS:
                tokens.pop(0)
                while tokens and tokens[0].startswith("-"):
                    flag = tokens.pop(0)
                    if (
                        flag in {"-u", "-n", "-I", "-s", "-P", "-C"}
                        and tokens
                        and not tokens[0].startswith("-")
                    ):
                        tokens.pop(0)

            if not tokens:
                continue

            executable = tokens[0]
            cmd_name = os.path.basename(executable)

            if cmd_name in modern_tools:
                replacement = modern_tools[cmd_name]
                return False, f"Legacy tool '{cmd_name}' is prohibited; use '{replacement}' instead"

            # Check nested sh -c "cat ..." or bash -c "..."
            if cmd_name in {"sh", "bash", "zsh"} and "-c" in tokens:
                c_idx = tokens.index("-c")
                if c_idx + 1 < len(tokens):
                    sub_str = tokens[c_idx + 1]
                    safe, reason = self.validate_command_safety(sub_str)
                    if not safe:
                        return safe, reason

        return True, None
