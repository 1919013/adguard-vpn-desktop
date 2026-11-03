"""Application entry point for ADGuard VPN Desktop."""


def main() -> int:
    from ui.window import run
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
