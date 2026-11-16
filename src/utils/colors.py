"""Terminal color and style utilities for colored output."""


class c:
    """ANSI color codes for terminal output."""
    RST = '\033[0m'  # Reset - clear all formatting back to default
    B = '\033[1m'   # Bold
    DIM = '\033[2m'  # Dim
    U = '\033[4m'   # Underline
    R = '\033[91m'   # red
    G = '\033[92m'   # green
    Y = '\033[93m'   # yellow
    BL = '\033[94m'   # blue
    M = '\033[95m'   # magenta
    C = '\033[38;2;0;255;255m'   # cyan
    W = '\033[97m'   # white


def colorize(text: str, *codes: str) -> str:
    """Apply ANSI codes to text. e.g. colorize('hello', c.G, c.B) for green bold."""
    prefix = ''.join(codes)
    return f'{prefix}{text}{c.RST}'


# Optional convenience wrappers — use if you want, or just use colorize directly
def ok(text: str) -> str:
    """Success / checkmark."""
    return colorize(f'✓ {text}', c.G, c.B)


def warn(text: str) -> str:
    """Warning / attention."""
    return colorize(f'⚠ {text}', c.Y, c.B)


def info(text: str) -> str:
    """Informational."""
    return colorize(text, c.C)


def error(text: str) -> str:
    """Error / failure."""
    return colorize(f'✗ {text}', c.R, c.B)


def header(text: str) -> str:
    """Section header."""
    return colorize(f'\n{text}', c.M, c.B)
