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


def save_group_returns_plot(group_returns: pd.DataFrame, path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(10, 5))
    group_returns.mean().plot(kind="bar", ax=ax, color="#0f766e")
    ax.set_title("Average Return by Factor Group")
    ax.set_xlabel("Factor group")
    ax.set_ylabel("Average forward return")
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def save_ic_plot(ic_series: pd.Series, path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(10, 4))
    ic_series.plot(ax=ax, color="#7c2d12", linewidth=1.2)
    ax.axhline(0, color="#111827", linewidth=0.8, alpha=0.5)
    ax.set_title("Rank IC Over Time")
    ax.set_xlabel("Time")
    ax.set_ylabel("Rank IC")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def save_risk_attribution_plot(comparison: dict, path: Path) -> Path:
    labels = ["raw_sharpe", "neutralized_sharpe", "exposure_decay"]
    raw = float(comparison.get("raw_sharpe") or 0.0)
    neutralized = float(comparison.get("neutralized_sharpe") or 0.0)
    values = [raw, neutralized, raw - neutralized]
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(labels, values, color=["#2563eb", "#0f766e", "#dc2626"])
    ax.axhline(0, color="#111827", linewidth=0.8, alpha=0.5)
    ax.set_title("Risk Attribution Proxy")
    ax.set_ylabel("Sharpe contribution proxy")
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path
