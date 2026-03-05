from typing import Optional, List
from queue import Queue, Full
from threading import Lock
from loguru import logger

from .message import CapturedMessage

class MessageCaptureQueue:
    
    # Drop policies
    DROP_OLDEST = "drop_oldest"      # Remove oldest message when full
    DROP_NEWEST = "drop_newest"      # Reject new message when full
    DROP_OVERFLOW = "drop_overflow"  # Same as DROP_NEWEST
    
    def __init__(
        self,
        maxsize: int = 10000,
        drop_policy: str = DROP_OLDEST,
    ):
        self.maxsize = maxsize
        self.drop_policy = drop_policy
        
        self._queue: Queue[CapturedMessage] = Queue(maxsize=maxsize)
        self._lock = Lock()
        self._shutdown = False
    
    def enqueue(self, msg: CapturedMessage) -> bool:
        if self._shutdown:
            return False
        
        try:
            # Try non-blocking put
            self._queue.put(msg, block=False)
            return True
            
        except Full:
            # Handle overflow based on policy
            return self._handle_queue_full(msg)
    
    def _handle_queue_full(self, new_msg: CapturedMessage) -> bool:
        if self.drop_policy == self.DROP_OLDEST:
            try:
                # Remove oldest (blocking=False fails, so remove from internal queue)
                old_msg = self._queue.get_nowait()
                
                # Now add new message
                self._queue.put(new_msg, block=False)
                
                logger.warning(f"Queue overflow: dropped message {old_msg.msg_name}")
                return True
                
            except Exception as e:
                logger.error(f"Queue handling failed: {e}")
                return False
        
        else:  # DROP_NEWEST
            return False
    
    def dequeue(self, timeout: Optional[float] = None) -> Optional[CapturedMessage]:
        try:
            msg = self._queue.get(timeout=timeout)
            return msg
        except Exception:
            return None
    
    def dequeue_batch(self, batch_size: int = 100, timeout: float = 0.1) -> List[CapturedMessage]:
        batch = []
        
        # Get first message with timeout
        msg = self.dequeue(timeout=timeout)
        if msg:
            batch.append(msg)
        
        # Get remaining messages without blocking
        while len(batch) < batch_size:
            msg = self.dequeue(timeout=0)
            if msg:
                batch.append(msg)
            else:
                break
        
        return batch
    
    def qsize(self) -> int:
        return self._queue.qsize()
    
    
    def clear(self):
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except Exception:
                break
    
    def shutdown(self):
        self._shutdown = True