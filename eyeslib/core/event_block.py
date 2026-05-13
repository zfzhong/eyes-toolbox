# shutdown_block.py
from dataclasses import dataclass
from typing import Optional
import pandas as pd


@dataclass
class EventBlock:
    TYPE_SHUTDOWN='SHUTDOWN'
    TYPE_IDLE='IDLE'
    TYPE_GAP='GAP'
    TYPE_GLANCE='GLANCE'
    TYPE_MIXED='MIXED'
    TYPE_ACTIVE='ACTIVE'
    
    """
    Generic block structure reused for:
      - shutdown blocks   (block_type="shutdown")
      - idle blocks       (block_type="idle")
      - gap blocks        (block_type="gap"), later if needed

    start_ts / end_ts:
      - for shutdown: [shutdown_time, boot_time]
      - for idle:     [idle_start, idle_end]
      - for gap:      [gap_start, gap_end]
    """
    block_type: str                       # "shutdown", "idle", "gap", ...
    start_ts: Optional[pd.Timestamp]
    end_ts: Optional[pd.Timestamp]
    next: Optional["EventBlock"] = None

    @property
    def kind(self) -> str:
        """
        Logical “completeness”:
          - paired      : both start_ts and end_ts
          - start_only  : only start_ts
          - end_only    : only end_ts
          - empty       : neither (shouldn't really happen)
        """
        if self.start_ts is not None and self.end_ts is not None:
            return "paired"
        if self.start_ts is not None:
            return "start_only"
        if self.end_ts is not None:
            return "end_only"
        return "empty"

    def is_paired(self) -> bool:
        return self.start_ts is not None and self.end_ts is not None
    
    @property
    def duration_seconds(self) -> Optional[int]:
        if self.start_ts is not None and self.end_ts is not None:
            return int((self.end_ts - self.start_ts).total_seconds())
        return None
