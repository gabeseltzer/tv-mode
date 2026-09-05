"""tvmode: switch a Windows PC between display/audio setups with one command."""

__version__ = "0.1.0"


def main() -> int:
    from .cli import main as _main

    return _main()
