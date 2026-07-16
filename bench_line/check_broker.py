"""Quick MQTT broker reachability check, used by run_full_grid.bat.

Tries a TCP connect to the broker host/port with a short timeout. Exits
0 if the connect succeeds, 1 with a friendly message on stderr if it
doesn't. Standalone — no dependencies on `mabdt` or the bench packages.

Usage:
    python bench_line/check_broker.py
    python bench_line/check_broker.py --host your-broker-host --port 1883
"""

from __future__ import annotations

import argparse
import socket
import sys


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8883)
    p.add_argument(
        "--timeout",
        type=float,
        default=3.0,
        help="TCP connect timeout in seconds (default: 3.0).",
    )
    args = p.parse_args()

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(args.timeout)
    try:
        s.connect((args.host, args.port))
        s.close()
        return 0
    except Exception as e:
        print(
            f"Cannot reach MQTT broker at {args.host}:{args.port}: {e}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
