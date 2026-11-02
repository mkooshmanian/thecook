"""Application identity and optional Linux desktop launcher installation."""
from importlib.resources import files
from pathlib import Path
import os
import sys

APP_NAME = "The Cook"
# Tk normalizes the resource class to a capitalized name on X11.
WM_CLASS = "Thecook"


def _desktop_string(value):
    return (value.replace("\\", "\\\\").replace("\n", "\\n")
            .replace("\r", "\\r").replace("\t", "\\t"))


def _exec_argument(value):
    # Exec quoting is applied after the desktop file's string escaping.
    quoted = "".join("\\" + char if char in '\\"`$' else char for char in value)
    return _desktop_string('"' + quoted.replace("%", "%%") + '"')


def install_desktop_entry():
    """Install a launcher for the current Python/pipx environment, without sudo."""
    if not sys.platform.startswith("linux"):
        raise RuntimeError("Desktop launcher installation is supported on Linux only.")
    data_home = Path(os.environ.get("XDG_DATA_HOME", "~/.local/share")).expanduser()
    if not data_home.is_absolute():
        data_home = Path.home() / ".local/share"
    icon = data_home / "icons/thecook.png"
    launcher = data_home / "applications/thecook.desktop"
    icon.parent.mkdir(parents=True, exist_ok=True)
    launcher.parent.mkdir(parents=True, exist_ok=True)
    icon.write_bytes(files("thecook").joinpath("assets/thecook.png").read_bytes())
    # Preserve the virtualenv path: resolving its Python symlink would select
    # the system interpreter, which may not have The Cook installed.
    executable = _exec_argument(str(Path(sys.executable).absolute()))
    launcher.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        "Comment=PUS telecommand and telemetry workbench\n"
        f"Exec={executable} -m thecook\n"
        f"Icon={_desktop_string(str(icon))}\n"
        "Terminal=false\n"
        "Categories=Development;\n"
        f"StartupWMClass={WM_CLASS}\n",
        encoding="utf-8",
    )
    return launcher
