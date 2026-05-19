"""Full-screen Textual dashboard for synmich migrate."""

from datetime import datetime, timedelta

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import (
    Header,
    Footer,
    Static,
    RichLog,
)
from rich.text import Text
from rich.table import Table

from synmich import __version__
from synmich.core.migrator import (
    MigrationStats,
    MigrationControl,
)


class StatsPanel(Static):
    """Panneau de stats live."""

    DEFAULT_CSS = """
    StatsPanel {
        border: round cyan;
        padding: 0 1;
    }
    """

    def __init__(self, stats: MigrationStats, **kw):
        super().__init__(**kw)
        self.stats = stats
        self.start_time = datetime.now()
        self.border_title = "Stats"

    def on_mount(self) -> None:
        self.set_interval(0.5, self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        self.update(self._make_table())

    def _format_eta(self) -> str:
        if self.stats.items_total == 0 or self.stats.items_done == 0:
            return "--:--"
        elapsed = (datetime.now() - self.start_time).total_seconds()
        if elapsed < 1:
            return "--:--"
        rate = self.stats.items_done / elapsed
        remaining = self.stats.items_total - self.stats.items_done
        if rate <= 0:
            return "--:--"
        return str(timedelta(seconds=int(remaining / rate)))

    def _format_rate(self) -> str:
        elapsed = (datetime.now() - self.start_time).total_seconds()
        if elapsed < 1:
            return "—"
        rate = self.stats.items_done / elapsed
        if rate < 1:
            return f"{rate*60:.0f}/min"
        return f"{rate:.1f}/sec"

    def _make_table(self) -> Table:
        t = Table.grid(padding=(0, 2))
        t.add_column(justify="right", style="bold cyan")
        t.add_column()
        t.add_row(
            "☁  Uploaded:",
            f"[green]{self.stats.uploaded}[/]",
        )
        t.add_row(
            "♻  Duplicate:",
            f"[yellow]{self.stats.duplicate}[/]",
        )
        t.add_row(
            "✖  Failed:",
            f"[red]{self.stats.failed}[/]",
        )
        t.add_row(
            "📂 Albums:",
            f"{self.stats.albums_done}/{self.stats.albums_total}",
        )
        t.add_row(
            "⏱  ETA:",
            f"[yellow]{self._format_eta()}[/]",
        )
        t.add_row(
            "⚡ Rate:",
            f"{self._format_rate()}",
        )
        return t


class CurrentPanel(Static):
    """Album courant + progress bar texte."""

    DEFAULT_CSS = """
    CurrentPanel {
        border: round cyan;
        padding: 0 1;
    }
    """

    def __init__(self, stats: MigrationStats, **kw):
        super().__init__(**kw)
        self.stats = stats
        self.border_title = "Current"

    def on_mount(self) -> None:
        self.set_interval(0.5, self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        self.update(self._make_content())

    def _make_content(self) -> Text:
        text = Text()
        text.append("Step:    ", style="bold")
        text.append(
            self.stats.current_step.upper() + "\n",
            style="bold yellow",
        )
        text.append("Current: ", style="bold")
        text.append(
            (self.stats.current_album or "—") + "\n\n",
            style="bold cyan",
        )

        if self.stats.items_total > 0:
            pct = (
                self.stats.items_done / self.stats.items_total * 100
            )
            bar_len = 40
            filled = int(
                bar_len * self.stats.items_done / self.stats.items_total
            )
            bar = "█" * filled + "░" * (bar_len - filled)
            text.append("Album:   ", style="bold")
            text.append(bar, style="green")
            text.append(
                f"  {self.stats.items_done}/"
                f"{self.stats.items_total}  ({pct:.1f}%)",
                style="bold",
            )
        return text


class LogPanel(RichLog):
    """Panneau de logs scrollable."""

    DEFAULT_CSS = """
    LogPanel {
        border: round cyan;
    }
    """

    def __init__(self, stats: MigrationStats, **kw):
        super().__init__(highlight=True, markup=True, **kw)
        self.stats = stats
        self.last_count = 0
        self.border_title = "Log"

    def on_mount(self) -> None:
        self.set_interval(0.3, self._poll)

    def _poll(self) -> None:
        msgs = self.stats.last_messages
        if len(msgs) > self.last_count:
            for m in msgs[self.last_count:]:
                try:
                    self.write(m)
                except Exception:
                    self.write(str(m))
            self.last_count = len(msgs)


class MigrationApp(App):
    """App Textual principale."""

    CSS = """
    Screen {
        background: $surface;
    }

    #top {
        height: 12;
    }

    StatsPanel {
        width: 40;
        height: 100%;
    }

    CurrentPanel {
        width: 1fr;
        height: 100%;
    }

    LogPanel {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("p", "pause", "Pause/Resume"),
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "force_quit", "Force Quit"),
    ]

    def __init__(
        self,
        stats: MigrationStats,
        control: MigrationControl,
        migrate_callable,
    ):
        super().__init__()
        self.stats = stats
        self.control = control
        self.migrate_callable = migrate_callable

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="top"):
            yield StatsPanel(self.stats, id="stats")
            yield CurrentPanel(self.stats, id="current")
        yield LogPanel(self.stats, id="log")
        yield Footer()

    def on_mount(self) -> None:
        self.title = f"synmich v{__version__}"
        self.sub_title = "Synology → Immich"
        self.run_worker(self._run_migration, thread=True)

    def _run_migration(self) -> None:
        try:
            self.migrate_callable()
        except Exception as e:
            self.stats.log_message(
                f"[red]✖ Migration crashed: {e}[/]"
            )
        finally:
            self.stats.current_step = "done"

    def action_pause(self) -> None:
        if self.control.is_paused():
            self.control.resume()
            self.stats.log_message("[yellow]▶ Resumed[/]")
        else:
            self.control.pause()
            self.stats.log_message("[yellow]⏸ Paused[/]")

    def action_quit(self) -> None:
        self.stats.log_message(
            "[yellow]Stopping... (waiting for current items)[/]"
        )
        self.control.stop()
        self.exit()

    def action_force_quit(self) -> None:
        self.control.stop()
        self.exit()
