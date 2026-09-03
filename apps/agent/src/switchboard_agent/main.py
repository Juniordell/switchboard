"""Agent entrypoint.

The cascade pipeline lands at T5.1 and the Triage / Service / Dispatch split at
T5.2, which is also when livekit-agents gets pinned. This module exists so the
image builds and the workspace wiring is proven: apps/agent imports
packages/core, which is the reason its Dockerfile takes the repository root as
its build context.
"""

import switchboard_core


def main() -> None:
    print(f"switchboard-agent placeholder, core {switchboard_core.__version__}")


if __name__ == "__main__":
    main()
