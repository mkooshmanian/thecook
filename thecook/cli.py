"""Installed entry point; help and version do not require a graphical display."""
import argparse
from importlib.metadata import PackageNotFoundError, version


def main():
    try:
        release = version("thecook")
    except PackageNotFoundError:
        release = "uninstalled source checkout"
    parser = argparse.ArgumentParser(
        prog="thecook",
        description="The Cook — a desktop PUS telecommand and telemetry workbench.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {release}")
    parser.add_argument("--install-desktop-entry", action="store_true",
                        help="install the Linux application-menu launcher and icon for this environment")
    args = parser.parse_args()

    if args.install_desktop_entry:
        from .desktop import install_desktop_entry
        try:
            launcher = install_desktop_entry()
        except (OSError, RuntimeError) as exc:
            parser.exit(1, f"Unable to install desktop launcher: {exc}\n")
        print(f"Desktop launcher installed: {launcher}")
        return

    try:
        from .app import main as run_app
    except ModuleNotFoundError as exc:
        if exc.name not in ("tkinter", "_tkinter"):
            raise
        parser.exit(
            1,
            "The Cook requires Tkinter in the Python used by pipx.\n"
            "On Debian/Ubuntu: sudo apt install python3-tk\n"
            "For other systems, install Python with Tcl/Tk support.\n",
        )
    run_app()


if __name__ == "__main__":
    main()
