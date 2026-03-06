from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple, List


@dataclass
class DroneMetrics:
    """Per-drone tracking metrics"""
    sysid: int
    last_sequence: Dict[str, int] = field(default_factory=dict)  # msg_name -> seq
    last_timestamp_us: int = 0
    last_addr: Optional[Tuple[str, int]] = None
    message_count: int = 0
    bytes_received: int = 0
    loss_count: int = 0
    address_changes: List[Tuple] = field(default_factory=list)
    last_seen_us: int = 0


@dataclass
class MessageTypeMetrics:
    """Per-message-type tracking metrics"""
    msg_name: str
    msg_id: int
    count: int = 0
    bytes: int = 0
    last_seen_us: int = 0
    expected_rate_hz: float = 0.0
    loss_count: int = 0