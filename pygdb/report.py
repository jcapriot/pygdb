"""
Command-line form of `pygdb.unseen_feature_report`::

    python -m pygdb.report survey.gdb

Prints the report a `GDBUnseenFeatureWarning` asks you to post. Kept out
of `pygdb/unseen.py` (which the package imports) so that running it with
`-m` doesn't re-execute an already imported module.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from .unseen import unseen_feature_report


def main(argv: Optional[Sequence[str]] = None) -> int:
    """
    Print the unseen-feature report for each file named on the command line.

    Parameters
    ----------
    argv : sequence of str, optional
        The arguments, default `sys.argv[1:]`: one or more `.gdb` paths.

    Returns
    -------
    int
        The exit status, 0.
    """
    parser = argparse.ArgumentParser(
        prog="python -m pygdb.report",
        description="Describe the format features in a .gdb file that pygdb has never "
                    "seen, for posting in an issue. Nothing about the file's data is included.",
    )
    parser.add_argument("paths", nargs="+", metavar="FILE", help="a .gdb file")
    args = parser.parse_args(argv)
    for i, path in enumerate(args.paths):
        if i:
            print()
        sys.stdout.write(unseen_feature_report(path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
