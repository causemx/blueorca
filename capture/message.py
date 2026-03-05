
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Tuple, Any, Dict
from loguru import logger

@dataclass
class CapturedMessage:
    """Container for a captured MAVLink message with metadata"""
    
    # Timing
    timestamp_ns: int  # nanoseconds since epoch (high precision)
    timestamp_us: int  # microseconds since epoch
    
    # Network info
    src_addr: Tuple[str, int]  # (IP, port)
    src_sysid: int
    src_compid: int
    
    # MAVLink message info
    msg_id: int
    msg_name: str
    msg_seq: int  # sequence number
    payload_len: int
    
    # Raw data
    raw_bytes: bytes  # entire packet
    
    # Processing state
    processed: bool = False
    error: Optional[str] = None
    timestamp_dt: datetime = field(default_factory=datetime.now)
    parsed_fields: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Calculate derived fields"""
        if not self.timestamp_dt:
            self.timestamp_dt = datetime.fromtimestamp(self.timestamp_us / 1e6)
    
    def __str__(self):
        return (f"CapturedMessage(ts={self.timestamp_us}, "
                f"sysid={self.src_sysid}, msgid={self.msg_id}({self.msg_name}), "
                f"seq={self.msg_seq}, addr={self.src_addr[0]}:{self.src_addr[1]})")
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for storage/serialization"""
        return {
            'timestamp_ns': self.timestamp_ns,
            'timestamp_us': self.timestamp_us,
            'timestamp_dt': self.timestamp_dt.isoformat(),
            'src_addr': f"{self.src_addr[0]}:{self.src_addr[1]}",
            'src_sysid': self.src_sysid,
            'src_compid': self.src_compid,
            'msg_id': self.msg_id,
            'msg_name': self.msg_name,
            'msg_seq': self.msg_seq,
            'payload_len': self.payload_len,
            'parsed_fields': self.parsed_fields,
        }

class MAVLinkExtractor:
    """
    Extract metadata and fields from parsed MAVLink messages.
    """
    
    # Common message types we want to parse fields from
    PRIORITY_MESSAGES = {
        'HEARTBEAT': ['system_status', 'autopilot', 'base_mode', 'custom_mode'],
        'ATTITUDE': ['roll', 'pitch', 'yaw', 'rollspeed', 'pitchspeed', 'yawspeed'],
        'GPS_RAW_INT': ['lat', 'lon', 'alt', 'eph', 'epv', 'vel', 'cog', 'satellites_visible'],
        'VFR_HUD': ['airspeed', 'groundspeed', 'heading', 'throttle', 'alt', 'climb'],
        'SYS_STATUS': ['onboard_control_sensors_health', 'battery_voltage', 'battery_current', 'battery_remaining'],
        'RC_CHANNELS': ['chan1_raw', 'chan2_raw', 'chan3_raw', 'chan4_raw', 'chan5_raw', 'chan6_raw'],
    }
    
    def __init__(self, extract_all_fields: bool = False):
        self.extract_all_fields = extract_all_fields
        self._field_cache: Dict[int, list] = {}  # msgid -> field names
    
    def extract(
        self,
        parsed_msg: Any,  # pymavlink message object
        raw_bytes: bytes,
        src_addr: Tuple[str, int],
        capture_time_ns: int,
        capture_time_us: int,
    ) -> CapturedMessage:

        try:
            msg_id = parsed_msg.get_msgId()
            msg_name = parsed_msg.get_type()
            sysid = parsed_msg.get_srcSystem()
            compid = parsed_msg.get_srcComponent()
            
            # Extract sequence number (message dependent)
            msg_seq = self._get_sequence(parsed_msg)
            
            # Extract payload fields
            fields = self._extract_fields(parsed_msg, msg_name)
            
            
            return CapturedMessage(
                timestamp_ns=capture_time_ns,
                timestamp_us=capture_time_us,
                src_addr=src_addr,
                src_sysid=sysid,
                src_compid=compid,
                msg_id=msg_id,
                msg_name=msg_name,
                msg_seq=msg_seq,
                payload_len=len(raw_bytes),
                raw_bytes=raw_bytes,
                parsed_fields=fields,
            )
        
        except Exception as e:
            logger.error(f"Error extracting message: {e}")
            # Return minimal message on error
            return CapturedMessage(
                timestamp_ns=capture_time_ns,
                timestamp_us=capture_time_us,
                src_addr=src_addr,
                src_sysid=0,
                src_compid=0,
                msg_id=0,
                msg_name="UNKNOWN",
                msg_seq=0,
                payload_len=len(raw_bytes),
                raw_bytes=raw_bytes,
                error=str(e),
            )
    
    def _get_sequence(self, msg: Any) -> int:
        """Extract sequence number from message if available"""
        try:
            # Most MAVLink messages have seq field
            if hasattr(msg, 'seq'):
                return msg.seq
            return 0
        except Exception:
            return 0
    
    def _extract_fields(self, msg: Any, msg_name: str) -> Dict[str, Any]:
        """Extract important fields from message payload"""
        fields = {}
        
        try:
            # Determine which fields to extract
            if msg_name in self.PRIORITY_MESSAGES:
                field_names = self.PRIORITY_MESSAGES[msg_name]
            elif self.extract_all_fields:
                field_names = [f for f in dir(msg) if not f.startswith('_')]
            else:
                return fields
            
            # Extract each field
            for field_name in field_names:
                try:
                    if hasattr(msg, field_name):
                        value = getattr(msg, field_name)
                        # Convert non-serializable types
                        if isinstance(value, (int, float, str, bool)):
                            fields[field_name] = value
                        else:
                            fields[field_name] = str(value)
                except Exception:
                    pass
            
        except Exception as e:
            logger.debug(f"Error extracting fields from {msg_name}: {e}")
        
        return fields