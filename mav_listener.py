#!/usr/bin/env python3
"""
Simple MAVLink Listener for Windows PC
Receives MAVLink packets from SITL on WSL
"""

import socket
import sys
from datetime import datetime

def simple_listener_windows(host='0.0.0.0', port=5566):
    """Listen for UDP packets on Windows"""
    
    print(f"\n{'='*70}")
    print(f"MAVLink Listener - Windows PC")
    print(f"Binding to {host}:{port}")
    print(f"{'='*70}\n")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(1)
    
    try:
        sock.bind((host, port))
        print(f"✓ Listening on {host}:{port}")
        print(f"Waiting for SITL packets from WSL...")
        print(f"Expected source IP: 172.21.141.99 (WSL)")
        print(f"Press Ctrl+C to stop...\n")
        
        packet_num = 0
        drones = {}  # Track drones by source address
        
        while True:
            try:
                data, addr = sock.recvfrom(1024)
                packet_num += 1
                
                # Track drone sources
                if addr not in drones:
                    drones[addr] = {'count': 0, 'first_byte': None}
                
                drones[addr]['count'] += 1
                
                timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
                
                # Only print every Nth packet to reduce spam
                if packet_num % 100 == 1:  # Print first and every 100th
                    print(f"\n[Packet #{packet_num}] {timestamp}")
                    print(f"  From: {addr[0]}:{addr[1]}")
                    print(f"  Size: {len(data)} bytes")
                    print(f"  First 16 bytes (hex): {' '.join(f'{b:02X}' for b in data[:16])}")
                    
                    if len(data) > 0:
                        first_byte = data[0]
                        print(f"  First byte: 0x{first_byte:02X}", end="")
                        
                        if first_byte == 0xFD:
                            print(" ← MAVLink 2.0 ✓")
                            if len(data) > 1:
                                payload_len = data[1]
                                print(f"  Payload length: {payload_len} bytes")
                                if len(data) > 8:
                                    sysid = data[5]
                                    compid = data[6]
                                    print(f"  System ID: {sysid}, Component ID: {compid}")
                        elif first_byte == 0xFE:
                            print(" ← MAVLink 1.0")
                        else:
                            print()
                    
                    # Show active drones
                    if drones:
                        print(f"\n  Active drone sources:")
                        for src, info in drones.items():
                            print(f"    {src[0]}:{src[1]} - {info['count']} packets")
                
            except socket.timeout:
                continue
            except KeyboardInterrupt:
                print("\n\n✓ Shutdown requested")
                break
            except Exception as e:
                print(f"Error: {e}")
                
    except OSError as e:
        print(f"✗ Error binding to {host}:{port}")
        print(f"  {e}")
        print(f"\n  Possible solutions:")
        print(f"  1. Port {port} is already in use")
        print(f"     Try: netstat -ano | findstr :5566")
        print(f"  2. Windows Firewall is blocking the port")
        print(f"     Try (PowerShell as Admin):")
        print(f"     netsh advfirewall firewall add rule name='MAVLink' dir=in action=allow protocol=udp localport=5566")
        print(f"  3. Try a different port:")
        print(f"     python {sys.argv[0]} --port 5567")
        sys.exit(1)
        
    finally:
        sock.close()
        print("Listener closed.")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(
        description='MAVLink Listener for Windows PC receiving from WSL SITL',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Listen on all interfaces (recommended)
  python %(prog)s --host 0.0.0.0 --port 5566
  
  # Listen on specific WSL bridge interface
  python %(prog)s --host 172.21.128.1 --port 5566
  
  # Use different port
  python %(prog)s --host 0.0.0.0 --port 5567

Setup for WSL SITL:
  1. Start this server on Windows PC
  2. In WSL, run: sim_vehicle.py -v ArduCopter -I 0 --out=172.21.128.1:5566
  3. Check this window for incoming packets
        """
    )
    parser.add_argument('--host', default='0.0.0.0', 
                       help='Host/IP to bind to (default: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=5566, 
                       help='UDP port to listen on (default: 5566)')
    
    args = parser.parse_args()
    
    try:
        simple_listener_windows(args.host, args.port)
    except KeyboardInterrupt:
        print("\n\nShutdown.")