import time
from typing import Optional, Tuple, Callable, Dict, Any
from loguru import logger

from .mq import MessageCaptureQueue
from .message import CapturedMessage, MAVLinkExtractor

class MessageCapturer:
    
    def __init__(
        self,
        queue_maxsize: int = 10000,
        drop_policy: str = MessageCaptureQueue.DROP_OLDEST,
        extract_all_fields: bool = False,
        enabled: bool = True,
    ):

        self.enabled = enabled
        self.queue = MessageCaptureQueue(maxsize=queue_maxsize, drop_policy=drop_policy)
        self.extractor = MAVLinkExtractor(extract_all_fields=extract_all_fields)
        
        self._processors: Dict[str, Callable] = {}
    
    def capture_message(
        self,
        parsed_msg: Any,
        raw_bytes: bytes,
        src_addr: Tuple[str, int],
    ) -> Optional[CapturedMessage]:

        if not self.enabled:
            return None
        
        try:
            # Get high-resolution timestamps
            capture_time_ns = time.time_ns()
            capture_time_us = capture_time_ns // 1000
            
            # Extract metadata(Optional)
            captured = self.extractor.extract(
                parsed_msg,
                raw_bytes,
                src_addr,
                capture_time_ns,
                capture_time_us,
            )
            
            # Enqueue for processing (non-blocking)
            if self.queue.enqueue(captured):
                # Run registered processors (should be very fast)
                self._run_processors(captured)
                return captured
            else:
                logger.debug("Message dropped due to queue overflow")
                return None
        
        except Exception as e:
            logger.error(f"Capture error: {e}")
            stats = self.queue.get_stats()
            if stats:
                stats.errors_other += 1
            return None
    
    def _run_processors(self, msg: CapturedMessage):
        """Run registered fast processors on captured message"""
        for name, processor in self._processors.items():
            try:
                processor(msg)
            except Exception as e:
                logger.error(f"Processor '{name}' error: {e}")
    
    def register_processor(self, name: str, processor: Callable[[CapturedMessage], None]):
        self._processors[name] = processor
        logger.info(f"Registered processor: {name}")
    
    def get_stats(self):
        return self.queue.get_stats()
    
    def disable(self):
        self.enabled = False
    
    def enable(self):
        self.enabled = True