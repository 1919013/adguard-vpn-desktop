"""Tiny child-side gate: wait for the coordinator before exec'ing the app."""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command or not all(isinstance(part, str) and part for part in command):
        return 125
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(20)
        client.connect(args.socket)
        client.sendall((json.dumps({"pid": os.getpid()}) + "\\n").encode("utf-8"))
        response = b""
        while not response.endswith(b"\\n") and len(response) < 32:
            chunk = client.recv(32 - len(response))
            if not chunk:
                break
            response += chunk
        client.close()
        if response != b"GO\\n":
            return 125
        os.execvpe(command[0], command, os.environ.copy())
    except (OSError, ValueError):
        return 125
    return 125


if __name__ == "__main__":
    raise SystemExit(main())
