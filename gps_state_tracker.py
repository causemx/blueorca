import time
import threading
import csv

from typing import Dict, TYPE_CHECKING
from loguru import logger
from datetime import datetime

if TYPE_CHECKING:
    from control import DroneNode

# TODO Maybe dataclass it better
class GPSStateRecord:
    """Single GPS state data point with timestamp"""
    
    def __init__(self, timestamp, latitude, longitude, altitude, eph, epv, satellites_visible):
        self.timestamp = timestamp
        self.latitude = latitude
        self.longitude = longitude
        self.altitude = altitude
        self.eph = eph
        self.epv = epv
        self.satellites_visible = satellites_visible
    
    def validate(self):
        """
        Validate GPS state record
        
        Returns:
            bool: True if valid, False otherwise
        """
        checks = [
            (-90 <= self.latitude <= 90, "Latitude out of range"),
            (-180 <= self.longitude <= 180, "Longitude out of range"),
            (self.altitude >= 0, "Altitude must be non-negative"),
            (self.eph >= 0, "EPH must be non-negative"),
            (self.epv >= 0, "EPV must be non-negative"),
            (self.satellites_visible >= 0, "Satellites must be non-negative"),
            (self.timestamp is not None, "Timestamp missing")
        ]
        
        for check, msg in checks:
            if not check:
                logger.warning(f"GPS validation failed: {msg}")
                return False
        return True
    

    def to_csv_row(self):
        """Convert record to CSV row format"""
        return [
            self.timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] if self.timestamp else "",
            f"{self.latitude:.6f}",
            f"{self.longitude:.6f}",
            f"{self.altitude:.2f}",
            f"{self.eph:.2f}",
            f"{self.epv:.2f}",
            self.satellites_visible
        ]

    def to_dict(self):
        """Serialization

        Returns:
            _type_: _description_
        """
        return {
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'altitude': self.altitude,
            'eph': self.eph,
            'epv': self.epv,
            'satellites_visible': self.satellites_visible
        }
    
    @classmethod
    def from_dict(cls, data):
        """Deserialization

        Args:
            data (_type_): _description_

        Returns:
            _type_: _description_
        """
        timestamp_str = data.get('timestamp')
        timestamp = datetime.fromisoformat(timestamp_str) if timestamp_str else None
        
        return cls(
            timestamp=timestamp,
            latitude=float(data.get('latitude', 0)),
            longitude=float(data.get('longitude', 0)),
            altitude=float(data.get('altitude', 0)),
            eph=float(data.get('eph', 0)),
            epv=float(data.get('epv', 0)),
            satellites_visible=int(data.get('satellites_visible', 0))
        )
    
    def __repr__(self):
        return (f"GPSStateRecord(time={self.timestamp}, "
                f"lat={self.latitude:.6f}, lon={self.longitude:.6f}, "
                f"alt={self.altitude:.1f}m, eph={self.eph:.2f}m, "
                f"epv={self.epv:.2f}m, sats={self.satellites_visible})")


class GPSStateTracker:
    def __init__(self, drone_node: 'DroneNode', interval: int=1):
        self.drone_node = drone_node
        self.interval = interval
        self.records = []
        self.tracking = False
        self.tracker_thread = None
        self.lock = threading.Lock()
        self.start_time = None
        self.end_time = None

    def start_tracking(self) -> bool:
        if self.tracking:
            logger.warning("GPS state tracking already started")
            return False
        self.tracking = True
        self.start_time = datetime.now()
        self.tracker_thread = threading.Thread(target=self._track_loop, daemon=True)
        self.tracker_thread.start()

        logger.info(f"GPS state tracking started (interval: {self.interval}s)")
        return True

    def stop_tracking(self) -> bool:
        if not self.tracking:
            logger.warning("GPS state tracker not actived")
            return False
        
        self.tracking = False
        self.end_time = datetime.now()

        if self.tracker_thread:
            self.tracker_thread.join(timeout=5.0)
        
        logger.success(f"GPS state tracking stopped. Recorded {len(self.records)} samples")
        return True

    def get_records_count(self) -> int:
        with self.lock:
            return len(self.records)
    
    def clear_records(self) -> None:
         with self.lock:
            self.records = []
            logger.info("GPS state records cleared")

    def get_statistics(self) -> Dict:
        with self.lock:
            if not self.records:
                return {
                    'total_samples': 0,
                    'duration_seconds': 0
                }
            
            lats = [r.latitude for r in self.records]
            lons = [r.longitude for r in self.records]
            alts = [r.altitude for r in self.records]
            ephs = [r.eph for r in self.records]
            epvs = [r.epv for r in self.records]
            sats = [r.satellites_visible for r in self.records]
            
            duration = (self.records[-1].timestamp - self.records[0].timestamp).total_seconds()
            
            return {
                'total_samples': len(self.records),
                'duration_seconds': duration,
                'latitude': {'min': min(lats), 'max': max(lats), 'avg': sum(lats) / len(lats)},
                'longitude': {'min': min(lons), 'max': max(lons), 'avg': sum(lons) / len(lons)},
                'altitude': {'min': min(alts), 'max': max(alts), 'avg': sum(alts) / len(alts)},
                'eph': {'min': min(ephs), 'max': max(ephs), 'avg': sum(ephs) / len(ephs)},
                'epv': {'min': min(epvs), 'max': max(epvs), 'avg': sum(epvs) / len(epvs)},
                'satellites': {'min': min(sats), 'max': max(sats), 'avg': sum(sats) / len(sats)}
            }

    def export_to_csv(self, filepath: str) -> bool:
        if not self.records:
            return False

        try: 
            with open(filepath, mode='w', newline='') as file:
                writer = csv.writer(file)
                # Write header
                header = ['timestamp', 'latitude', 'longitude', 'altitude', 
                        'eph', 'epv', 'satellites_visible']
                writer.writerow(header)

                with self.lock:
                    for record in self.records:
                        writer.writerow(record.to_csv_row())
            logger.info("Write to csv success")
            return True
        except Exception as e:
            logger.error(f"Write to csv failed: {str(e)}")
            return False

    def _track_loop(self):
        last_sample_time = time.time()

        while self.tracking:
            try:
                current_time = time.time()
                if current_time - last_sample_time >= self.interval:
                    record = self._collect_sample()
                    if record:
                        with self.lock:
                            self.records.append(record)
                        # TODO show satellites_visible and eph of record on 1.3 oled real-time
                        logger.info(f"GPS state record has appended: {record}")
                    last_sample_time = current_time
                    time.sleep(0.01)
            except Exception as e:
                logger.error(f"Error in GPS state tracking: {str(e)}")
                time.sleep(1)

    def _collect_sample(self) -> GPSStateRecord:
        """Collect gps state records

        Returns:
            GPSStateRecord: _description_
        """
        try:
            # Get latest GPS state from drone node
            if not hasattr(self.drone_node, 'latest_gps_state'):
                logger.warning("DroneNode does not have latest_gps_state attribute")
                return None
            
            # Use lock if available, otherwise proceed without it
            if hasattr(self.drone_node, 'gps_lock'):
                with self.drone_node.gps_lock:
                    state = self.drone_node.latest_gps_state.copy()
            else:
                state = self.drone_node.latest_gps_state.copy()
            
            # Check if all required fields are present
            required_fields = ['latitude', 'longitude', 'altitude', 
                                'eph', 'epv', 'satellites_visible']
            
            missing_fields = [f for f in required_fields if state.get(f) is None]
            if missing_fields:
                logger.debug(f"Incomplete GPS data, skipping sample. Missing: {missing_fields}")
                return None
            
            # Convert EPH/EPV from centimeters to meters if needed
            eph = state['eph']
            epv = state['epv']
            
            # If value > 100, assume it's in centimeters, convert to meters
            if eph > 100:
                eph = eph / 100.0
            if epv > 100:
                epv = epv / 100.0
            
            # Create record
            record = GPSStateRecord(
                timestamp=state.get('timestamp', datetime.now()),
                latitude=state['latitude'],
                longitude=state['longitude'],
                altitude=state['altitude'],
                eph=eph,
                epv=epv,
                satellites_visible=state['satellites_visible']
            )
            
            # [OPTIONAL] Validate record
            """
            if not record.validate():
                logger.warning("GPS state record validation failed")
                return None
            """
            return record
        
        except Exception as e:
            logger.error(f"Error collecting GPS sample: {str(e)}")
            return None          