"""No invalid escape sequences in string literals.

The BI server runs Python 3.13, where an unrecognised escape is a
SyntaxWarning printed on every run. verify_date_bounds.py shipped with Windows
paths in an ordinary docstring and greeted its first real run with

    SyntaxWarning: invalid escape sequence '\\D'

before any output. Harmless, but it lands in the diagnostic log that gets read
back, and it is the sort of thing that makes a correct run look broken.

Development happens on 3.10, where these are silent, so compiling the module
locally proves nothing. This tokenises instead and is therefore
version-independent — which is the point.
"""

import io
import re
import tokenize
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# Everything Python accepts after a backslash. A newline is line continuation.
VALID = set("\n\\'\"abfnrtv01234567xNuU")

SOURCES = sorted(
    p
    for p in REPO.rglob("*.py")
    if ".venv" not in p.parts and "__pycache__" not in p.parts
)


def invalid_escapes(path: Path):
    out = []
    for tok in tokenize.generate_tokens(
        io.StringIO(path.read_text(encoding="utf-8")).readline
    ):
        if tok.type != tokenize.STRING:
            continue
        prefix = re.match(r"[A-Za-z]*", tok.string).group().lower()
        if "r" in prefix or "b" in prefix:  # raw and bytes are exempt
            continue
        for m in re.finditer(r"\\(.)", tok.string, re.DOTALL):
            if m.group(1) not in VALID:
                out.append((tok.start[0], "\\" + m.group(1)))
    return out


def test_the_repo_has_python_files_to_check():
    """Guards against the sweep silently matching nothing."""
    assert len(SOURCES) > 10


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(REPO)))
def test_no_invalid_escape_sequences(path):
    found = invalid_escapes(path)
    assert not found, (
        f"{path.relative_to(REPO)} has invalid escape sequences at "
        + ", ".join(f"line {ln} ({esc!r})" for ln, esc in found)
        + ". Windows paths belong in a raw string — prefix the literal with r."
    )


class TestTheCheckItself:
    def test_flags_a_windows_path_in_an_ordinary_string(self, tmp_path):
        r"""Only \D is flagged: \2 is a valid octal escape, so Python accepts
        it silently and quietly gives you the wrong character. That is exactly
        what the server reported — one warning, not two, for a path containing
        both "\Dashboards" and "\2. Revenue Data"."""
        f = tmp_path / "bad.py"
        f.write_text('"""C:\\Dashboards and Data Analysis\\2. Revenue Data"""\n')
        assert [e for _, e in invalid_escapes(f)] == ["\\D"]

    def test_accepts_the_same_path_raw(self, tmp_path):
        f = tmp_path / "good.py"
        f.write_text('r"""C:\\Dashboards and Data Analysis\\2. Revenue Data"""\n')
        assert invalid_escapes(f) == []

    def test_leaves_real_escapes_alone(self, tmp_path):
        f = tmp_path / "ok.py"
        f.write_text('x = "a\\nb\\tc\\\\d\\x41"\n')
        assert invalid_escapes(f) == []
