import pandas as pd
from typing import List
from .event_block import EventBlock


def build_blocks_from_csv(csv_path: str) -> List[EventBlock]:
    """
    Read a CSV of dumped blocks (shutdown / idle / gap) and reconstruct
    a list of EventBlock objects.

    Rules:
      - Only blocks with BOTH start_ts and end_ts are kept.
      - Blocks do NOT overlap.
      - Sorted strictly by start_ts.
      - No linked-list pointers are used.

    Required CSV columns:
      - block_type
      - start_ts
      - end_ts
    """

    df = pd.read_csv(csv_path)

    required = {"block_type", "start_ts", "end_ts"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns in blocks CSV: {missing}")

    # Parse timestamps
    df["start_ts"] = pd.to_datetime(df["start_ts"], format="mixed", errors="coerce")
    df["end_ts"]   = pd.to_datetime(df["end_ts"],   format="mixed", errors="coerce")

    # Keep only paired, valid intervals
    df = df.dropna(subset=["start_ts", "end_ts"])
    df = df[df["start_ts"] < df["end_ts"]]
    if df.empty:
        return []

    # Sort by start_ts only
    df = df.sort_values("start_ts").reset_index(drop=True)

    blocks: List[EventBlock] = []
    for _, row in df.iterrows():
        blocks.append(
            EventBlock(
                block_type=row["block_type"],
                start_ts=row["start_ts"],
                end_ts=row["end_ts"],
                next=None,   # unused, can be removed from dataclass later
            )
        )

    return blocks
