# /// script
# requires-python = ">=3.12"
# dependencies = ["matplotlib>=3.9"]
# ///
"""Render the RESULTS.md charts from a k6 summary + Prometheus range data.

Usage:
    uv run scripts/make_charts.py --summary deploy/load/summary.json \
        --start <unix> --end <unix> [--prometheus http://localhost:9090]

Design follows the dataviz method: percentiles as one blue ramp light->dark
(order carried by lightness, CVD-immune), categorical blue/orange for the
two-series timeline, recessive grid, ink-colored text, thin marks, one axis.
Palette validated with the method's validator before use.
"""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Validated palette (dataviz reference instance, light mode)
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
RAMP = {"p50": "#86b6ef", "p95": "#2a78d6", "p99": "#0d366b"}  # ordinal blue
CAT = {"submitted": "#2a78d6", "completed": "#eb6834"}  # categorical 1, 2

RATES = [10, 25, 50, 100, 150, 200]
WINDOW_S = 30


def style_axes(ax: plt.Axes) -> None:
    ax.set_facecolor(SURFACE)
    ax.grid(True, axis="y", color=GRID, linewidth=0.75)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(BASELINE)
    ax.tick_params(colors=MUTED, labelsize=9)
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_color(INK_2)


def new_fig(title: str, subtitle: str) -> tuple[plt.Figure, plt.Axes]:
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    fig.suptitle(title, x=0.06, ha="left", fontsize=13, fontweight="bold", color=INK)
    ax.set_title(subtitle, loc="left", fontsize=9.5, color=INK_2, pad=10)
    style_axes(ax)
    return fig, ax


def chart_latency(summary: dict, out: Path) -> None:
    series: dict[str, list[float]] = {"p50": [], "p95": [], "p99": []}
    for rate in RATES:
        m = summary["metrics"][f"http_req_duration{{scenario:rate{rate}}}"]
        series["p50"].append(m["med"])
        series["p95"].append(m["p(95)"])
        series["p99"].append(m["p(99)"])
    fig, ax = new_fig(
        "Submit latency vs offered load",
        "POST /jobs on the local compose stack; 30s per rate window - lower is better",
    )
    for name in ("p50", "p95", "p99"):
        ax.plot(
            RATES,
            series[name],
            color=RAMP[name],
            linewidth=2,
            marker="o",
            markersize=5,
            label=name,
        )
        ax.annotate(
            name,
            (RATES[-1], series[name][-1]),
            xytext=(8, 0),
            textcoords="offset points",
            va="center",
            fontsize=9,
            color=INK_2,
        )
    ax.set_xlabel("offered load (submissions / second)", fontsize=9.5, color=INK_2)
    ax.set_ylabel("latency (ms)", fontsize=9.5, color=INK_2)
    ax.set_xlim(0, RATES[-1] * 1.12)
    ax.set_ylim(bottom=0)
    ax.legend(loc="upper left", frameon=False, fontsize=9, labelcolor=INK_2)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(out, facecolor=SURFACE, bbox_inches="tight")
    print(f"wrote {out}")


def prom_range(
    base: str, query: str, start: int, end: int, step: int = 5
) -> list[tuple[float, float]]:
    url = f"{base}/api/v1/query_range?" + urllib.parse.urlencode(
        {"query": query, "start": start, "end": end, "step": step}
    )
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = json.load(resp)
    result = data["data"]["result"]
    if not result:
        return []
    return [(float(t), float(v)) for t, v in result[0]["values"]]


def chart_timeline(base: str, start: int, end: int, out: Path) -> None:
    fig, ax = new_fig(
        "Throughput during the load test",
        "submissions accepted vs jobs completed; the gap is the queue absorbing overload",
    )
    for name, query in (
        ("submitted", "sum(rate(orbiter_jobs_submitted_total[15s]))"),
        ("completed", "sum(rate(orbiter_jobs_completed_total[15s]))"),
    ):
        points = prom_range(base, query, start, end)
        if not points:
            print(f"warning: no data for {name}")
            continue
        xs = [(t - start) / 60 for t, _ in points]
        ys = [v for _, v in points]
        ax.plot(xs, ys, color=CAT[name], linewidth=2, label=name)
        ax.annotate(
            name,
            (xs[-1], ys[-1]),
            xytext=(8, 0),
            textcoords="offset points",
            va="center",
            fontsize=9,
            color=INK_2,
        )
    ax.set_xlabel("minutes since test start", fontsize=9.5, color=INK_2)
    ax.set_ylabel("jobs / second", fontsize=9.5, color=INK_2)
    ax.set_ylim(bottom=0)
    ax.legend(loc="upper left", frameon=False, fontsize=9, labelcolor=INK_2)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(out, facecolor=SURFACE, bbox_inches="tight")
    print(f"wrote {out}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--prometheus", default="http://localhost:9090")
    parser.add_argument("--out-dir", type=Path, default=Path("results"))
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    summary = json.loads(args.summary.read_text())
    chart_latency(summary, args.out_dir / "latency-vs-load.png")
    chart_timeline(args.prometheus, args.start, args.end, args.out_dir / "throughput-timeline.png")


if __name__ == "__main__":
    main()
