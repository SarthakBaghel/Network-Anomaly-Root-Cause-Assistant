from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.db.session import session_scope  # noqa: E402
from app.orchestration import reset_service  # noqa: E402
from app.simulator.engine import SimulatorEngine  # noqa: E402


def main() -> None:
    simulator = SimulatorEngine(background=False)
    reset_service.register_simulator(simulator)
    with session_scope() as session:
        result = reset_service.execute(session)
    print(f"release database reset complete ({result['status']})")


if __name__ == "__main__":
    main()
