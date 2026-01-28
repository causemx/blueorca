#!/usr/bin/env python3
"""
Simple MAVLink Server using PyMAVLink library
Runs on Windows PC, receives from SITL on WSL
Shows drone connections and disconnections
"""

import socket
import time
import datetime
from pymavlink.dialects.v20 import ardupilotmega as mavlink

class SimpleMAVLinkServer:
    """Simple MAVLink server with connection detection"""
    
    def __init__(self, host='0.0.0.0', port=5566, timeout=10):
        """
        Initialize server
        
        Args:
            host: IP to bind to
            port: UDP port
            timeout: Seconds without data before drone disconnect
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        self.socket = None
        self.drones = {}  # {(ip, port): {'sysid': id, 'time': last_time, 'count': msg_count}}
        self.parsers = {}  # {(ip, port): parser}
        
    def start(self):
        """Start the server"""
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
        self.socket.settimeout(1)
        
        try:
            self.socket.bind((self.host, self.port))
        except OSError as e:
            print(f"✗ Error: Cannot bind to {self.host}:{self.port}")
            print(f"  {e}")
            return
        
        print(f"\n{'='*70}")
        print(f"Simple MAVLink Server (PyMAVLink)")
        print(f"Listening on {self.host}:{self.port}")
        print(f"{'='*70}\n")
        
        print(f"Setup for WSL SITL:")
        print(f"  sim_vehicle.py -v ArduCopter -I 0 --out=172.21.128.1:5566\n")
        print(f"Waiting for drone connections...\n")
        
        try:
            while True:
                self._check_disconnections()
                
                try:
                    data, addr = self.socket.recvfrom(1024)
                    if data:
                        self._handle_packet(data, addr)
                except socket.timeout:
                    continue
                    
        except KeyboardInterrupt:
            print("\n\nShutting down...")
            self.stop()
    
    def _handle_packet(self, data, addr):
        """Handle incoming MAVLink packet"""
        try:
            # Initialize parser for this drone if needed
            if addr not in self.parsers:
                self.parsers[addr] = mavlink.MAVLink(None, False)
            
            parser = self.parsers[addr]
            
            # Parse the packet byte by byte
            for byte in data:
                msg = parser.parse_char(bytes([byte]))
                
                if msg:
                    # Got a complete message
                    sysid = msg.get_srcSystem()
                    compid = msg.get_srcComponent()
                    msg_type = msg.get_type()
                    
                    # Check if this is a new drone
                    if addr not in self.drones:
                        self._drone_connected(addr, sysid, compid, msg_type)
                    else:
                        # Update heartbeat for existing drone
                        self.drones[addr]['time'] = time.time()
                        self.drones[addr]['count'] += 1
                        
                        # Print every 100 messages (reduce spam)
                        if self.drones[addr]['count'] % 100 == 0:
                            print(f"[{addr[0]}:{addr[1]}] SysID:{sysid} | Messages:{self.drones[addr]['count']} | Type:{msg_type}")
                    
        except Exception as e:
            # Silently ignore parsing errors
            pass
    
    def _drone_connected(self, addr, sysid, compid, first_msg_type):
        """Handle new drone connection"""
        self.drones[addr] = {
            'sysid': sysid,
            'compid': compid,
            'time': time.time(),
            'count': 1
        }
        
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print("✓ DRONE CONNECTED")
        print(f"  Address:       {addr[0]}:{addr[1]}")
        print(f"  System ID:     {sysid}")
        print(f"  Component ID:  {compid}")
        print(f"  First Message: {first_msg_type}")
        print(f"  Timestamp:     {timestamp}\n")
    
    def _check_disconnections(self):
        """Check for drones that stopped sending data"""
        current_time = time.time()
        disconnected = []
        
        for addr, info in self.drones.items():
            if current_time - info['time'] > self.timeout:
                disconnected.append(addr)
        
        for addr in disconnected:
            info = self.drones.pop(addr)
            
            # Clean up parser
            if addr in self.parsers:
                del self.parsers[addr]
            
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print("✗ DRONE DISCONNECTED")
            print(f"  Address:       {addr[0]}:{addr[1]}")
            print(f"  System ID:     {info['sysid']}")
            print(f"  Total Messages: {info['count']}")
            print(f"  Timestamp:     {timestamp}\n")
    
    def stop(self):
        """Stop the server"""
        if self.socket:
            self.socket.close()
        print("Server stopped.")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Simple MAVLink Server using PyMAVLink',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Quick Start:
  1. Install pymavlink:
     pip install pymavlink
  
  2. Run this server on Windows PC:
     python mavlink_server_pymavlink_simple.py
  
  3. In WSL, start SITL:
     sim_vehicle.py -v ArduCopter -I 0 --out=172.21.128.1:5566

Multiple SITL Instances:
  # WSL Terminal
  sim_vehicle.py -v ArduCopter -I 0 --out=172.21.128.1:5566 &
  sim_vehicle.py -v ArduCopter -I 1 --out=172.21.128.1:5566 &
  sim_vehicle.py -v ArduCopter -I 2 --out=172.21.128.1:5566 &
  sim_vehicle.py -v ArduCopter -I 3 --out=172.21.128.1:5566 &

Windows Firewall:
  netsh advfirewall firewall add rule name="MAVLink" dir=in action=allow protocol=udp localport=5566
        """
    )
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to (default: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=5566, help='Port to listen on (default: 5566)')
    parser.add_argument('--timeout', type=int, default=10, help='Drone timeout in seconds (default: 10)')
    
    args = parser.parse_args()
    
    server = SimpleMAVLinkServer(host=args.host, port=args.port, timeout=args.timeout)
    server.start()