"""Child entry for a supervised Job. The parent already claimed the row."""

from __future__ import annotations

import importlib
import os
import sys

from backend.jobs.store import CLAIMED_ENV


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    target, job_id = args[0], args[1]
    module_name, func_name = target.split(":")
    os.environ[CLAIMED_ENV] = "1"
    fn = getattr(importlib.import_module(module_name), func_name)
    fn(job_id)


if __name__ == "__main__":
    main()
