import subprocess
import sys
from pathlib import Path

HEARTH = str(Path(__file__).parent.parent / "hearth.py")


def test_hearth_exits_cleanly_on_eof():
    """When stdin is closed (no TTY), hearth exits 0 with 'No input' — not EOFError."""
    result = subprocess.run(
        [sys.executable, HEARTH],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=5,
    )

    combined = result.stdout + result.stderr
    assert result.returncode == 0, f"Expected exit 0, got {result.returncode}\n{combined}"
    assert "No input" in combined, f"Expected 'No input' message, got:\n{combined}"
    assert "EOFError" not in combined, "Unhandled EOFError reached stderr"
    assert "Traceback" not in combined, "Unhandled exception reached stderr"


def test_hearth_imports_without_side_effects():
    """Importing hearth should not launch the app or produce output."""
    result = subprocess.run(
        [sys.executable, "-c", "import hearth"],
        capture_output=True,
        text=True,
        timeout=2,
    )

    assert result.returncode == 0, f"Import failed: {result.stderr}"
