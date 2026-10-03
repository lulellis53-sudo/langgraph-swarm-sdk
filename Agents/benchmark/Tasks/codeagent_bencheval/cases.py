"""Twenty deterministic code-agent benchmark cases.

Each case provides a specification, a reference implementation, and an
acceptance test.  The benchmark harness scores a simulated (or real) Coder
agent by running the generated code against the acceptance test.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CodeBenchCase:
    id: str
    title: str
    prompt: str
    difficulty: str
    think_level: str
    effort: str
    estimated_tokens: int
    reference: str
    test_code: str


def _case(
    id: str,
    title: str,
    prompt: str,
    difficulty: str,
    think_level: str,
    effort: str,
    estimated_tokens: int,
    reference: str,
    test_code: str,
) -> CodeBenchCase:
    return CodeBenchCase(
        id=id,
        title=title,
        prompt=prompt,
        difficulty=difficulty,
        think_level=think_level,
        effort=effort,
        estimated_tokens=estimated_tokens,
        reference=reference,
        test_code=test_code,
    )


BENCH_CASES: list[CodeBenchCase] = [
    _case(
        id="c01_sum_two",
        title="Sum two numbers",
        prompt="Write a function add(a, b) that returns the sum of two numbers.",
        difficulty="easy",
        think_level="low",
        effort="low",
        estimated_tokens=120,
        reference="def add(a, b):\n    return a + b\n",
        test_code="from solution import add\nassert add(2, 3) == 5\nassert add(-1, 1) == 0\n",
    ),
    _case(
        id="c02_reverse",
        title="Reverse a string",
        prompt="Write a function reverse_string(s) that returns s reversed.",
        difficulty="easy",
        think_level="low",
        effort="low",
        estimated_tokens=130,
        reference="def reverse_string(s):\n    return s[::-1]\n",
        test_code=(
            "from solution import reverse_string\n"
            "assert reverse_string('hello') == 'olleh'\n"
            "assert reverse_string('') == ''\n"
        ),
    ),
    _case(
        id="c03_palindrome",
        title="Check palindrome",
        prompt="Write a function is_palindrome(s) that returns True if s is a palindrome.",
        difficulty="easy",
        think_level="low",
        effort="low",
        estimated_tokens=150,
        reference="def is_palindrome(s):\n    return s == s[::-1]\n",
        test_code=(
            "from solution import is_palindrome\n"
            "assert is_palindrome('racecar')\n"
            "assert not is_palindrome('hello')\n"
            "assert is_palindrome('')\n"
        ),
    ),
    _case(
        id="c04_fizzbuzz",
        title="FizzBuzz",
        prompt=(
            "Write a function fizzbuzz(n) returning a list of length n where "
            "multiples of 3 are 'fizz', multiples of 5 are 'buzz', both are "
            "'fizzbuzz', otherwise the number as a string."
        ),
        difficulty="easy",
        think_level="low",
        effort="low",
        estimated_tokens=220,
        reference=(
            "def fizzbuzz(n):\n"
            "    out = []\n"
            "    for i in range(1, n + 1):\n"
            "        if i % 15 == 0:\n"
            "            out.append('fizzbuzz')\n"
            "        elif i % 3 == 0:\n"
            "            out.append('fizz')\n"
            "        elif i % 5 == 0:\n"
            "            out.append('buzz')\n"
            "        else:\n"
            "            out.append(str(i))\n"
            "    return out\n"
        ),
        test_code=(
            "from solution import fizzbuzz\n"
            "assert fizzbuzz(5) == ['1', '2', 'fizz', '4', 'buzz']\n"
            "assert fizzbuzz(15)[14] == 'fizzbuzz'\n"
        ),
    ),
    _case(
        id="c05_factorial",
        title="Factorial",
        prompt="Write a function factorial(n) that returns n! for n >= 0.",
        difficulty="easy",
        think_level="low",
        effort="low",
        estimated_tokens=180,
        reference=(
            "def factorial(n):\n"
            "    if n < 0:\n"
            "        raise ValueError('n must be non-negative')\n"
            "    result = 1\n"
            "    for i in range(2, n + 1):\n"
            "        result *= i\n"
            "    return result\n"
        ),
        test_code=(
            "from solution import factorial\nassert factorial(0) == 1\nassert factorial(5) == 120\n"
        ),
    ),
    _case(
        id="c06_fibonacci",
        title="Fibonacci sequence",
        prompt="Write a function fibonacci(n) returning the first n Fibonacci numbers.",
        difficulty="easy",
        think_level="medium",
        effort="low",
        estimated_tokens=200,
        reference=(
            "def fibonacci(n):\n"
            "    if n <= 0:\n"
            "        return []\n"
            "    seq = [0] * n\n"
            "    if n > 1:\n"
            "        seq[1] = 1\n"
            "    for i in range(2, n):\n"
            "        seq[i] = seq[i - 1] + seq[i - 2]\n"
            "    return seq\n"
        ),
        test_code=(
            "from solution import fibonacci\n"
            "assert fibonacci(1) == [0]\n"
            "assert fibonacci(6) == [0, 1, 1, 2, 3, 5]\n"
        ),
    ),
    _case(
        id="c07_find_max",
        title="Find maximum",
        prompt=(
            "Write a function find_max(values) returning the largest number; "
            "raise ValueError if empty."
        ),
        difficulty="easy",
        think_level="low",
        effort="low",
        estimated_tokens=160,
        reference=(
            "def find_max(values):\n"
            "    if not values:\n"
            "        raise ValueError('empty sequence')\n"
            "    return max(values)\n"
        ),
        test_code=(
            "from solution import find_max\n"
            "assert find_max([3, 1, 4, 1, 5]) == 5\n"
            "import pytest\n"
            "with pytest.raises(ValueError):\n"
            "    find_max([])\n"
        ),
    ),
    _case(
        id="c08_count_vowels",
        title="Count vowels",
        prompt="Write a function count_vowels(s) that counts a, e, i, o, u (case-insensitive).",
        difficulty="easy",
        think_level="low",
        effort="low",
        estimated_tokens=170,
        reference=(
            "def count_vowels(s):\n    return sum(1 for ch in s.lower() if ch in 'aeiou')\n"
        ),
        test_code=(
            "from solution import count_vowels\n"
            "assert count_vowels('Hello World') == 3\n"
            "assert count_vowels('XYZ') == 0\n"
        ),
    ),
    _case(
        id="c09_flatten",
        title="Flatten nested list",
        prompt="Write a function flatten(nested) that flattens one level of nested lists.",
        difficulty="medium",
        think_level="medium",
        effort="low",
        estimated_tokens=190,
        reference=(
            "def flatten(nested):\n"
            "    result = []\n"
            "    for item in nested:\n"
            "        if isinstance(item, list):\n"
            "            result.extend(item)\n"
            "        else:\n"
            "            result.append(item)\n"
            "    return result\n"
        ),
        test_code=(
            "from solution import flatten\n"
            "assert flatten([1, [2, 3], 4]) == [1, 2, 3, 4]\n"
            "assert flatten([[1, 2], [3, 4]]) == [1, 2, 3, 4]\n"
        ),
    ),
    _case(
        id="c10_unique",
        title="Unique elements preserving order",
        prompt="Write a function unique(values) returning unique elements in original order.",
        difficulty="medium",
        think_level="medium",
        effort="low",
        estimated_tokens=200,
        reference=(
            "def unique(values):\n"
            "    seen = set()\n"
            "    out = []\n"
            "    for v in values:\n"
            "        if v not in seen:\n"
            "            seen.add(v)\n"
            "            out.append(v)\n"
            "    return out\n"
        ),
        test_code=(
            "from solution import unique\n"
            "assert unique([1, 2, 2, 3, 1, 4]) == [1, 2, 3, 4]\n"
            "assert unique([]) == []\n"
        ),
    ),
    _case(
        id="c11_parse_csv",
        title="Parse CSV line",
        prompt=(
            "Write a function parse_csv_line(line) splitting on commas and stripping whitespace."
        ),
        difficulty="medium",
        think_level="medium",
        effort="low",
        estimated_tokens=180,
        reference=(
            "def parse_csv_line(line):\n    return [cell.strip() for cell in line.split(',')]\n"
        ),
        test_code=(
            "from solution import parse_csv_line\n"
            "assert parse_csv_line('a, b ,c') == ['a', 'b', 'c']\n"
            "assert parse_csv_line('  x  , y ') == ['x', 'y']\n"
        ),
    ),
    _case(
        id="c12_safe_divide",
        title="Safe division",
        prompt=(
            "Write a function safe_divide(a, b, default=0.0) returning a/b "
            "or default on ZeroDivisionError."
        ),
        difficulty="medium",
        think_level="medium",
        effort="low",
        estimated_tokens=190,
        reference=(
            "def safe_divide(a, b, default=0.0):\n"
            "    try:\n"
            "        return a / b\n"
            "    except ZeroDivisionError:\n"
            "        return default\n"
        ),
        test_code=(
            "from solution import safe_divide\n"
            "assert safe_divide(10, 2) == 5.0\n"
            "assert safe_divide(10, 0) == 0.0\n"
            "assert safe_divide(10, 0, default=None) is None\n"
        ),
    ),
    _case(
        id="c13_timer_decorator",
        title="Timer decorator",
        prompt=(
            "Write a decorator @timer that prints 'elapsed: X.XXXs' after "
            "the wrapped function runs."
        ),
        difficulty="medium",
        think_level="medium",
        effort="medium",
        estimated_tokens=260,
        reference=(
            "import functools\n"
            "import time\n"
            "def timer(func):\n"
            "    @functools.wraps(func)\n"
            "    def wrapper(*args, **kwargs):\n"
            "        start = time.perf_counter()\n"
            "        result = func(*args, **kwargs)\n"
            "        elapsed = time.perf_counter() - start\n"
            "        print(f'elapsed: {elapsed:.3f}s')\n"
            "        return result\n"
            "    return wrapper\n"
        ),
        test_code=(
            "from solution import timer\n"
            "@timer\n"
            "def foo():\n"
            "    return 42\n"
            "import io, sys\n"
            "buf = io.StringIO()\n"
            "old, sys.stdout = sys.stdout, buf\n"
            "assert foo() == 42\n"
            "sys.stdout = old\n"
            "assert 'elapsed:' in buf.getvalue()\n"
        ),
    ),
    _case(
        id="c14_read_lines",
        title="Read matching lines",
        prompt=(
            "Write a function read_lines(path, prefix) that returns all lines from "
            "path starting with prefix, excluding the trailing newline."
        ),
        difficulty="medium",
        think_level="medium",
        effort="medium",
        estimated_tokens=240,
        reference=(
            "def read_lines(path, prefix):\n"
            "    with open(path, 'r', encoding='utf-8') as f:\n"
            "        return [line.rstrip('\\n') for line in f if line.startswith(prefix)]\n"
        ),
        test_code=(
            "from solution import read_lines\n"
            "from pathlib import Path\n"
            "p = Path('sample.txt')\n"
            "p.write_text('alpha one\\nbravo two\\nalpha three\\n')\n"
            "assert read_lines(str(p), 'alpha') == ['alpha one', 'alpha three']\n"
            "p.unlink()\n"
        ),
    ),
    _case(
        id="c15_dataclass_user",
        title="User dataclass",
        prompt=(
            "Define a @dataclass User with name: str and age: int; add a "
            "method is_adult() -> bool for age >= 18."
        ),
        difficulty="medium",
        think_level="medium",
        effort="low",
        estimated_tokens=220,
        reference=(
            "from dataclasses import dataclass\n"
            "@dataclass\n"
            "class User:\n"
            "    name: str\n"
            "    age: int\n"
            "    def is_adult(self) -> bool:\n"
            "        return self.age >= 18\n"
        ),
        test_code=(
            "from solution import User\n"
            "assert User('Ada', 30).is_adult()\n"
            "assert not User('Bob', 17).is_adult()\n"
        ),
    ),
    _case(
        id="c16_async_greet",
        title="Async greet",
        prompt=(
            "Write an async function async_greet(name) that awaits "
            "asyncio.sleep(0) and returns 'Hello {name}'."
        ),
        difficulty="medium",
        think_level="medium",
        effort="medium",
        estimated_tokens=200,
        reference=(
            "import asyncio\n"
            "async def async_greet(name):\n"
            "    await asyncio.sleep(0)\n"
            "    return f'Hello {name}'\n"
        ),
        test_code=(
            "import asyncio\n"
            "from solution import async_greet\n"
            "assert asyncio.run(async_greet('World')) == 'Hello World'\n"
        ),
    ),
    _case(
        id="c17_regex_emails",
        title="Extract emails",
        prompt=(
            "Write a function extract_emails(text) returning a list of unique emails found in text."
        ),
        difficulty="hard",
        think_level="high",
        effort="medium",
        estimated_tokens=280,
        reference=(
            "import re\n"
            "def extract_emails(text):\n"
            "    pattern = r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}'\n"
            "    return sorted(set(re.findall(pattern, text)))\n"
        ),
        test_code=(
            "from solution import extract_emails\n"
            "text = 'Contact a@example.com or b@example.com, a@example.com'\n"
            "assert extract_emails(text) == ['a@example.com', 'b@example.com']\n"
        ),
    ),
    _case(
        id="c18_merge_sorted",
        title="Merge sorted lists",
        prompt=(
            "Write a function merge_sorted(a, b) that merges two sorted lists into one sorted list."
        ),
        difficulty="hard",
        think_level="high",
        effort="medium",
        estimated_tokens=300,
        reference=(
            "def merge_sorted(a, b):\n"
            "    i = j = 0\n"
            "    out = []\n"
            "    while i < len(a) and j < len(b):\n"
            "        if a[i] <= b[j]:\n"
            "            out.append(a[i])\n"
            "            i += 1\n"
            "        else:\n"
            "            out.append(b[j])\n"
            "            j += 1\n"
            "    out.extend(a[i:])\n"
            "    out.extend(b[j:])\n"
            "    return out\n"
        ),
        test_code=(
            "from solution import merge_sorted\n"
            "assert merge_sorted([1, 3, 5], [2, 4, 6]) == [1, 2, 3, 4, 5, 6]\n"
            "assert merge_sorted([], [1, 2]) == [1, 2]\n"
        ),
    ),
    _case(
        id="c19_tempdir_context",
        title="Temp directory context manager",
        prompt=(
            "Write a context manager tempdir() that creates a temporary directory, "
            "yields its path, and deletes it on exit."
        ),
        difficulty="hard",
        think_level="high",
        effort="high",
        estimated_tokens=320,
        reference=(
            "import shutil\n"
            "import tempfile\n"
            "from contextlib import contextmanager\n"
            "from pathlib import Path\n"
            "@contextmanager\n"
            "def tempdir():\n"
            "    path = tempfile.mkdtemp()\n"
            "    try:\n"
            "        yield Path(path)\n"
            "    finally:\n"
            "        shutil.rmtree(path)\n"
        ),
        test_code=(
            "from solution import tempdir\n"
            "from pathlib import Path\n"
            "with tempdir() as d:\n"
            "    assert d.exists()\n"
            "    p = d / 'file.txt'\n"
            "    p.write_text('x')\n"
            "assert not d.exists()\n"
        ),
    ),
    _case(
        id="c20_cli_parser",
        title="CLI argument parser",
        prompt=(
            "Write a function parse_args(args) for '--name' and '--count N' flags, "
            "returning {'name': str, 'count': int}. Defaults are name='world' and count=1."
        ),
        difficulty="hard",
        think_level="high",
        effort="high",
        estimated_tokens=340,
        reference=(
            "def parse_args(args):\n"
            "    name = 'world'\n"
            "    count = 1\n"
            "    i = 0\n"
            "    while i < len(args):\n"
            "        if args[i] == '--name' and i + 1 < len(args):\n"
            "            name = args[i + 1]\n"
            "            i += 2\n"
            "        elif args[i] == '--count' and i + 1 < len(args):\n"
            "            count = int(args[i + 1])\n"
            "            i += 2\n"
            "        else:\n"
            "            i += 1\n"
            "    return {'name': name, 'count': count}\n"
        ),
        test_code=(
            "from solution import parse_args\n"
            "assert parse_args([]) == {'name': 'world', 'count': 1}\n"
            "assert parse_args(['--name', 'Ada', '--count', '5']) == {'name': 'Ada', 'count': 5}\n"
        ),
    ),
]


def get_case(case_id: str) -> CodeBenchCase:
    for case in BENCH_CASES:
        if case.id == case_id:
            return case
    raise KeyError(case_id)


def case_count() -> int:
    return len(BENCH_CASES)
