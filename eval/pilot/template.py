"""Write the empty question sheet the customer's lawyers fill in.

uv run --directory backend python ../eval/pilot/template.py questions.xlsx [--rows 70]
"""

import argparse
from pathlib import Path

from sheets import write_question_template


def main() -> None:
    options = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    options.add_argument("path", type=Path)
    options.add_argument("--rows", type=int, default=70)
    args = options.parse_args()
    write_question_template(args.path, args.rows)
    print(f"written: {args.path}")


if __name__ == "__main__":
    main()
