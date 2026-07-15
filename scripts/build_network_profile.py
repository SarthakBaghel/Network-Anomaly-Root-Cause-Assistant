"""Reproduce the deterministic scenario outputs from the checked-in profile.

This is the stable Person 3 entry point named by the handoff contract. The
implementation lives in ``build_scenario_bundle`` so generation and validation
cannot drift between two scripts.
"""

from __future__ import annotations

import argparse

from build_scenario_bundle import run


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if profile-derived checked-in outputs are not byte-identical",
    )
    args = parser.parse_args()
    run(check=args.check)


if __name__ == "__main__":
    main()
