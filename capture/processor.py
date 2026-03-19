# file: capture/processor.py

import threading
import time
from typing import List, Callable
from loguru import logger
from .message import CapturedMessage
from .mq import MessageCaptureQueue

class MessageProcessor(threading.Thread):
    """Work thread that process captured messages

    Args:
        threading (_type_):
    """
    
    def __init__(self, queue: MessageCaptureQueue, batch_size: int = 100, 
                 batch_timeout: float = 0.5):
        super().__init__(daemon=True)
        self.queue = queue
        self.batch_size = batch_size
        self.batch_timeout = batch_timeout
        self.running = False
        self._handlers: List[Callable] = []
    
    def register_handler(self, handler: Callable[[List[CapturedMessage]], None]):
        """Register batch message handler

        Args:
            handler (Callable[[List[CapturedMessage]], None]): message handler callable
        """
        self._handlers.append(handler)
    
    def run(self):
        self.running = True
        logger.debug("Message processor started")
        
        try:
            while self.running:
                batch = self.queue.dequeue_batch(
                    batch_size=self.batch_size,
                    timeout=self.batch_timeout
                )
                
                if batch:
                    for handler in self._handlers:
                        try:
                            handler(batch)
                        except Exception as e:
                            logger.error(f"Handler error: {e}")
                else:
                    time.sleep(0.01)
        finally:
            logger.debug("Message processor stopped")
    
    def stop(self):
        self.running = False
    
    def join_wait(self, timeout: float = 5.0):
        self.stop()
        self.join(timeout=timeout)