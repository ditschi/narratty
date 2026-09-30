"""Greet someone from the command line."""

import sys


def greeting(name: str) -> str:
    return f"Hello, {name}!"


def main() -> None:
    names = sys.argv[1:] or ["world"]
    for name in names:
        print(greeting(name))


if __name__ == "__main__":
    main()
