import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
from datetime import datetime, time
from zoneinfo import ZoneInfo
from typing import List, Optional

from matplotlib.patches import Patch


from .event_block import EventBlock


# Color style (you can adjust)
COLOR_MAP = {
    EventBlock.TYPE_SHUTDOWN: ("blue", 0.5, 0),   # (color, alpha, y-offset)
    EventBlock.TYPE_IDLE:     ("gray", 0.4, 0.1),
    EventBlock.TYPE_GLANCE:   ("orange", 0.45, 0.2),
    EventBlock.TYPE_GAP:      ("red",  0.4, 0.3),
}


def hour_of_day(ts: pd.Timestamp) -> float:
    """Convert timestamp into float hour-of-day."""
    return ts.hour + ts.minute/60 + ts.second/3600 + ts.microsecond/3_600_000_000


def plot_daily_blocks(
    shutdown_blocks: List[EventBlock],
    idle_blocks: List[EventBlock],
    glance_blocks: List[EventBlock],
    gap_blocks: List[EventBlock],
    out_png: str,
    tz_name: str = "UTC",
    title: str = "Device Activity (Shutdown / Idle / Glance / Gap)",
    dpi: int = 220,
    height_per_day: float = 0.6,
    min_vis_minutes: float = 0.0,
    only_days_with_data: bool = False,
    min_duration_seconds = 10
):
    """
    Plot shutdown, idle, glance, and gap blocks in a single daily-separated PNG file.

    Each day is a separate horizontal row.
    Each block_type has its own color + transparency.
    """

    # Flatten all blocks into one list
    blocks = shutdown_blocks + idle_blocks + glance_blocks
    if not blocks:
        print("No blocks found; nothing to plot.")
        return
    
    for b in gap_blocks:
        if b.block_type == EventBlock.TYPE_GAP:
            blocks.append(b)

    # All timestamps must be in the same timezone for plotting
    tz = ZoneInfo(tz_name)

    # Convert to local tz and collect (start, end, type)
    intervals = []
    for b in blocks:
        if b.duration_seconds is None or b.duration_seconds < min_duration_seconds:
            continue  # skip orphan blocks for plotting
        start_local = b.start_ts.tz_convert(tz)
        end_local   = b.end_ts.tz_convert(tz)
        if end_local <= start_local:
            continue
        intervals.append((start_local, end_local, b.block_type))

    if not intervals:
        print("No paired intervals to plot.")
        return

    # Determine the date range
    dates = []
    for start_local, end_local, _ in intervals:
        d0 = start_local.date()
        d1 = end_local.date()
        # Expand multi-day blocks (rare but possible)
        cur = pd.Timestamp(d0)
        while cur.date() <= d1:
            dates.append(cur.date())
            cur += pd.Timedelta(days=1)

    if not dates:
        print("No dates extracted.")
        return

    start_date = min(dates)
    end_date   = max(dates)
    all_days = pd.date_range(start_date, end_date, freq="D")

    # Optionally filter days without any blocks
    if only_days_with_data:
        days_with_blocks = set()
        for start_local, end_local, _ in intervals:
            d0 = start_local.date()
            d1 = end_local.date()
            cur = pd.Timestamp(d0)
            while cur.date() <= d1:
                days_with_blocks.add(cur.date())
                cur += pd.Timedelta(days=1)
        all_days = pd.to_datetime(sorted(days_with_blocks))

    # Figure size
    fig_h = max(4.0, len(all_days) * height_per_day)
    fig, ax = plt.subplots(figsize=(14, fig_h))

    ylabels = []

    # Draw all blocks day-by-day
    for idx, day in enumerate(all_days):
        y = idx
        day_date = day.date()
        ylabels.append(day_date.isoformat())

        day_start = pd.Timestamp(datetime.combine(day_date, time.min), tz=tz)
        day_end   = pd.Timestamp(datetime.combine(day_date, time.max), tz=tz)

        for start_local, end_local, btype in intervals:

            # Does this block overlap this day?
            if end_local < day_start or start_local > day_end:
                continue

            ps = max(start_local, day_start)
            pe = min(end_local, day_end)

            width_sec = (pe - ps).total_seconds()
            if min_vis_minutes > 0:
                min_width = min_vis_minutes * 60
                if width_sec < min_width:
                    pe = ps + pd.Timedelta(seconds=min_width)

            left = hour_of_day(ps)
            right = hour_of_day(pe)
            width = right - left

            color, alpha, yoffset = COLOR_MAP.get(btype, ("blue", 0.5, 0))

            ax.barh(
                y=y+yoffset,
                width=width,
                left=left,
                height=0.38,
                color=color,
                alpha=alpha,
                edgecolor="none",
                align="center",
            )

    # Formatting
    ax.set_title(title)
    ax.set_xlabel(f"Time of Day ({tz_name})")
    ax.set_yticks(range(len(ylabels)))
    ax.set_yticklabels(ylabels)
    ax.invert_yaxis()
    ax.set_xlim(0, 24)
    ax.set_xticks(range(0, 25, 2))
    ax.xaxis.set_major_formatter(
        FuncFormatter(lambda x, pos: f"{int(x):02d}:{int((x-int(x))*60):02d}")
    )
    ax.grid(True, axis="x", linestyle="--", alpha=0.3)

    # Build legend from COLOR_MAP
    legend_handles = []
    for btype, (color, alpha, yoffset) in COLOR_MAP.items():
        legend_handles.append(
            Patch(
                facecolor=color,
                alpha=alpha,
                edgecolor="none",
                label=btype.capitalize()
            )
        )

    ax.legend(
        handles=legend_handles,
        loc="upper right",
        frameon=True,
    )

    plt.tight_layout()
    plt.savefig(out_png, dpi=dpi)
    plt.close(fig)

    print("Plot saved to:", out_png)
