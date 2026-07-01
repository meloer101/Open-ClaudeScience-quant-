from pathlib import Path
import os
import tempfile

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "quantbench_matplotlib"))
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


def save_equity_curve_plot(equity_curve: pd.Series, path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(10, 5))
    equity_curve.plot(ax=ax, color="#2563eb", linewidth=1.6)
    ax.set_title("Equity Curve")
    ax.set_xlabel("Time")
    ax.set_ylabel("Equity")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def save_drawdown_plot(drawdown: pd.Series, path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(10, 4))
    drawdown.plot(ax=ax, color="#dc2626", linewidth=1.4)
    ax.fill_between(drawdown.index, drawdown.values, 0, color="#dc2626", alpha=0.18)
    ax.set_title("Drawdown")
    ax.set_xlabel("Time")
    ax.set_ylabel("Drawdown")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path
