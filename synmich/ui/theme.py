"""Theme and banner for synmich."""

from rich.console import Console
from rich.text import Text
from rich.panel import Panel
from rich.align import Align

from synmich import __version__

# Shared global console
console = Console()


# Palette colors
COLOR_PRIMARY = "bright_cyan"
COLOR_SECONDARY = "blue"
COLOR_ACCENT = "yellow"
COLOR_SUCCESS = "green"
COLOR_WARNING = "yellow"
COLOR_ERROR = "red"
COLOR_MUTED = "grey50"
COLOR_INFO = "cyan"


BANNER_ASCII = r"""
   ███████╗██╗   ██╗███╗   ██╗███╗   ███╗██╗ ██████╗██╗  ██╗
   ██╔════╝╚██╗ ██╔╝████╗  ██║████╗ ████║██║██╔════╝██║  ██║
   ███████╗ ╚████╔╝ ██╔██╗ ██║██╔████╔██║██║██║     ███████║
   ╚════██║  ╚██╔╝  ██║╚██╗██║██║╚██╔╝██║██║██║     ██╔══██║
   ███████║   ██║   ██║ ╚████║██║ ╚═╝ ██║██║╚██████╗██║  ██║
   ╚══════╝   ╚═╝   ╚═╝  ╚═══╝╚═╝     ╚═╝╚═╝ ╚═════╝╚═╝  ╚═╝
"""


def _gradient_banner() -> Text:
    """Colored ASCII banner with a blue→cyan gradient."""
    text = Text()
    lines = BANNER_ASCII.strip("\n").split("\n")
    # Simulated gradient: alternating blue and bright_cyan
    colors = [
        "blue",
        "bright_blue",
        "cyan",
        "bright_cyan",
        "bright_cyan",
        "bright_cyan",
    ]
    for i, line in enumerate(lines):
        color = colors[min(i, len(colors) - 1)]
        text.append(line + "\n", style=f"bold {color}")
    return text


def print_banner(subtitle_extra: str = "") -> None:
    """Print the full banner."""
    console.print()
    console.print(_gradient_banner(), end="")

    # Subtitle
    subtitle = Text()
    subtitle.append("         ", style="")
    subtitle.append("Synology Photos", style="bold white")
    subtitle.append("  ", style="")
    subtitle.append("→", style=f"bold {COLOR_ACCENT}")
    subtitle.append("  ", style="")
    subtitle.append("Immich Migration", style="bold white")
    subtitle.append("  ·  ", style=COLOR_MUTED)
    subtitle.append(f"v{__version__}", style=COLOR_MUTED)

    console.print(subtitle)

    # Footer
    footer = Text()
    footer.append(
        "                github.com/t3ksin/synmich · MIT",
        style=COLOR_MUTED,
    )
    console.print(footer)

    if subtitle_extra:
        console.print()
        console.print(
            Align.center(Text(subtitle_extra, style=COLOR_INFO))
        )
    console.print()


def print_section(title: str) -> None:
    """Print a section separator."""
    console.print()
    console.rule(f"[bold {COLOR_PRIMARY}]{title}[/]", style=COLOR_SECONDARY)
    console.print()


def success(msg: str) -> None:
    console.print(f"  [{COLOR_SUCCESS}]✓[/] {msg}")


def info(msg: str) -> None:
    console.print(f"  [{COLOR_INFO}]ℹ[/] {msg}")


def warn(msg: str) -> None:
    console.print(f"  [{COLOR_WARNING}]⚠[/] {msg}")


def error(msg: str) -> None:
    console.print(f"  [{COLOR_ERROR}]✗[/] {msg}")


def muted(msg: str) -> None:
    console.print(f"  [{COLOR_MUTED}]{msg}[/]")
