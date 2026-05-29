#!/usr/bin/env python3

import time
import cmd
import logging
import threading
from typing import Dict, List, Tuple
from datetime import datetime
from dataclasses import dataclass
from control import DroneNode, FlightMode
import math

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)-8s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


@dataclass
class DroneConfig:
    """Configuration for a drone in the swarm"""
    drone_id: int
    ip_address: str
    port: int = 14553
    
    @property
    def connection_string(self) -> str:
        return f"udp:{self.ip_address}:{self.port}"


class SwarmController:
    """Controls a swarm of drones with synchronized commands"""
    
    def __init__(self, drone_configs: List[DroneConfig]):
        """
        Initialize swarm controller
        
        Args:
            drone_configs: List of DroneConfig objects for each drone
        """
        self.drone_configs = drone_configs
        self.drones: Dict[int, DroneNode] = {}
        self.lock = threading.Lock()
        self.is_swarm_armed = False
        
        logger.info(f"Initializing swarm with {len(drone_configs)} drone(s)")
        
    def connect_all(self) -> bool:
        """Connect to all drones in swarm"""
        logger.info("Connecting to all drones...")
        
        success_count = 0
        for config in self.drone_configs:
            try:
                drone = DroneNode(config.connection_string)
                if drone.connect():
                    self.drones[config.drone_id] = drone
                    drone.start_status_tracking()
                    logger.info(f"[OK] Drone {config.drone_id} ({config.ip_address}) connected")
                    success_count += 1
                else:
                    logger.error(f"[FAIL] Drone {config.drone_id} connection failed")
            except Exception as e:
                logger.error(f"[FAIL] Drone {config.drone_id} error: {str(e)}")
        
        if success_count > 0:
            logger.info(f"Connected to {success_count}/{len(self.drone_configs)} drone(s)")
            return True
        else:
            logger.error("Failed to connect to any drones")
            return False
    
    def disconnect_all(self):
        """Disconnect from all drones"""
        logger.info("Disconnecting from all drones...")
        with self.lock:
            for drone_id, drone in self.drones.items():
                try:
                    drone.cleanup()
                    logger.info(f"[OK] Drone {drone_id} disconnected")
                except Exception as e:
                    logger.error(f"[FAIL] Drone {drone_id} disconnect error: {str(e)}")
            self.drones.clear()
    
    def arm_all(self) -> bool:
        """Arm all drones"""
        logger.info("Arming all drones...")
        
        if not self.drones:
            logger.error("No drones connected")
            return False
        
        with self.lock:
            success_count = 0
            for drone_id, drone in self.drones.items():
                try:
                    if drone.arm():
                        logger.info(f"[OK] Drone {drone_id} armed")
                        success_count += 1
                    else:
                        logger.warning(f"[FAIL] Drone {drone_id} arm failed")
                except Exception as e:
                    logger.error(f"[FAIL] Drone {drone_id} arm error: {str(e)}")
            
            if success_count == len(self.drones):
                self.is_swarm_armed = True
                logger.info("All drones armed successfully")
                return True
            else:
                logger.warning(f"Only {success_count}/{len(self.drones)} drones armed")
                return False
    
    def disarm_all(self) -> bool:
        """Disarm all drones"""
        logger.info("Disarming all drones...")
        
        if not self.drones:
            logger.error("No drones connected")
            return False
        
        with self.lock:
            success_count = 0
            for drone_id, drone in self.drones.items():
                try:
                    if drone.disarm():
                        logger.info(f"[OK] Drone {drone_id} disarmed")
                        success_count += 1
                    else:
                        logger.warning(f"[FAIL] Drone {drone_id} disarm failed")
                except Exception as e:
                    logger.error(f"[FAIL] Drone {drone_id} disarm error: {str(e)}")
            
            if success_count == len(self.drones):
                self.is_swarm_armed = False
                logger.info("All drones disarmed successfully")
                return True
            else:
                logger.warning(f"Only {success_count}/{len(self.drones)} drones disarmed")
                return False
    
    def takeoff_all(self, altitude: float = 2.0) -> bool:
        """
        Takeoff all drones to specified altitude
        
        Args:
            altitude: Target altitude in meters (default: 2.0m)
        
        Returns:
            True if all drones takeoff successfully
        """
        if not self.drones:
            logger.error("No drones connected")
            return False
        
        if not self.is_swarm_armed:
            logger.error("Swarm not armed")
            return False
        
        logger.info(f"Taking off all drones to {altitude}m...")
        
        with self.lock:
            success_count = 0
            for drone_id, drone in self.drones.items():
                try:
                    drone.arm()
                    if drone.takeoff(altitude):
                        logger.info(f"[OK] Drone {drone_id} taking off to {altitude}m")
                        success_count += 1
                    else:
                        logger.warning(f"[FAIL] Drone {drone_id} takeoff failed")
                except Exception as e:
                    logger.error(f"[FAIL] Drone {drone_id} takeoff error: {str(e)}")
            
            return success_count == len(self.drones)
    
    def land_all(self) -> bool:
        """Land all drones"""
        logger.info("Landing all drones...")
        
        if not self.drones:
            logger.error("No drones connected")
            return False
        
        with self.lock:
            success_count = 0
            for drone_id, drone in self.drones.items():
                try:
                    if drone.land():
                        logger.info(f"[OK] Drone {drone_id} landing")
                        success_count += 1
                    else:
                        logger.warning(f"[FAIL] Drone {drone_id} land failed")
                except Exception as e:
                    logger.error(f"[FAIL] Drone {drone_id} land error: {str(e)}")
            
            return success_count == len(self.drones)
    
    def fly_to(self, distance: float, speed: float = 1.0) -> bool:
        """
        Fly all drones forward based on current yaw
        
        Args:
            distance: Distance to fly in meters
            speed: Flight speed in m/s (default: 1.0)
        
        Returns:
            True if command sent successfully
        """
        if not self.drones:
            logger.error("No drones connected")
            return False
        
        
        logger.info(f"Flying forward {distance}m at speed {speed}m/s...")
        
        with self.lock:
            success_count = 0
            for drone_id, drone in self.drones.items():
                try:
                    # Set GUIDED mode first
                    drone.set_flight_mode(FlightMode.GUIDED)
                    time.sleep(0.1)
                    
                    # Get current status
                    
                    status = drone.get_drone_status()
                    heading = status.get('heading', 0)
                    _altitude = status.get('altitude', 2.0)
                    
                    # Calculate velocity components based on heading
                    heading_rad = math.radians(heading)
                    vx = speed * math.cos(heading_rad)
                    vy = speed * math.sin(heading_rad)
                    
                    # Send velocity target
                    # calculate duration = distance / speed
                    duration = distance / speed if speed > 0 else 0
                    
                    # Send velocity command
                    # drone.send_velocity_target(vx, vy, 0, duration)
                    drone.send_velocity_target(vx, vy, 0)
                    logger.info(f"[OK] Drone {drone_id} flying forward (heading: {heading}deg, duration: {duration:.1f}s)")
                    success_count += 1
                except Exception as e:
                    logger.error(f"[FAIL] Drone {drone_id} fly_to error: {str(e)}")
            
            return success_count == len(self.drones)
    
    def fly_back(self, distance: float, speed: float = 1.0) -> bool:
        """
        Fly all drones backward based on current yaw
        
        Args:
            distance: Distance to fly backward in meters
            speed: Flight speed in m/s (default: 1.0)
        
        Returns:
            True if command sent successfully
        """
        if not self.drones:
            logger.error("No drones connected")
            return False
        
        if not self.is_swarm_armed:
            logger.error("Swarm not armed")
            return False
        
        logger.info(f"Flying backward {distance}m at speed {speed}m/s...")
        
        with self.lock:
            success_count = 0
            for drone_id, drone in self.drones.items():
                try:
                    # Set GUIDED mode first
                    drone.set_flight_mode(FlightMode.GUIDED)
                    time.sleep(0.1)
                    
                    # Get current status
                    status = drone.get_drone_status()
                    heading = status.get('heading', 0)
                    
                    # Calculate velocity for backward movement (opposite heading)
                    # Add 180 degrees to heading for reverse direction
                    reverse_heading = (heading + 180) % 360
                    heading_rad = math.radians(reverse_heading)
                    vx = speed * math.cos(heading_rad)
                    vy = speed * math.sin(heading_rad)
                    
                    # Calculate duration
                    duration = distance / speed if speed > 0 else 0
                    
                    # Send velocity command
                    drone.send_velocity_target(vx, vy, 0, duration)
                    logger.info(f"[OK] Drone {drone_id} flying backward (duration: {duration:.1f}s)")
                    success_count += 1
                except Exception as e:
                    logger.error(f"[FAIL] Drone {drone_id} fly_back error: {str(e)}")
            
            return success_count == len(self.drones)
    
    def mode_all(self, flight_mode: FlightMode) -> bool:
        """
        Set flight mode for all drones simultaneously
        
        Args:
            flight_mode: FlightMode enum value (GUIDED, STABILIZE, LOITER, etc.)
        
        Returns:
            True if all drones set mode successfully
        """
        if not self.drones:
            logger.error("No drones connected")
            return False
        
        logger.info(f"Setting flight mode to {flight_mode.name} for all drones...")
        
        with self.lock:
            success_count = 0
            for drone_id, drone in self.drones.items():
                try:
                    if drone.set_flight_mode(flight_mode):
                        logger.info(f"[OK] Drone {drone_id} -> {flight_mode.name}")
                        success_count += 1
                    else:
                        logger.warning(f"[FAIL] Drone {drone_id} mode change failed")
                except Exception as e:
                    logger.error(f"[FAIL] Drone {drone_id} error: {str(e)}")
            
            if success_count == len(self.drones):
                logger.info(f"All drones set to {flight_mode.name} mode")
                return True
            else:
                logger.warning(f"Only {success_count}/{len(self.drones)} drones set mode")
                return success_count > 0
    
    def get_swarm_status(self) -> Dict:
        """Get status of all drones in swarm"""
        with self.lock:
            return {
                'timestamp': datetime.now().isoformat(),
                'swarm_armed': self.is_swarm_armed,
                'connected_drones': len(self.drones),
                'drones': {
                    drone_id: drone.get_drone_status()
                    for drone_id, drone in self.drones.items()
                }
            }
    
    def print_swarm_status(self):
        """Print formatted status of all drones"""
        status = self.get_swarm_status()
        
        print("\n" + "=" * 80)
        print(f"Swarm Status - {status['timestamp']}")
        print("=" * 80)
        print(f"Swarm Armed: {'Yes' if status['swarm_armed'] else 'No'}")
        print(f"Connected Drones: {status['connected_drones']}/{len(self.drone_configs)}")
        print()
        
        for drone_id, drone_status in status['drones'].items():
            print(f"Drone {drone_id}:")
            print(f"  Armed:       {drone_status.get('armed', 'N/A')}")
            print(f"  Mode:        {drone_status.get('mode', 'N/A')}")
            print(f"  Altitude:    {drone_status.get('altitude', 'N/A'):.2f} m")
            print(f"  Heading:     {drone_status.get('heading', 'N/A'):.1f}deg")
            print(f"  Groundspeed: {drone_status.get('groundspeed', 'N/A'):.2f} m/s")
            print(f"  Battery:     {drone_status.get('battery', 'N/A')}")
            print(f"  Position:    {drone_status.get('position', 'N/A')}")
            print()
        
        print("=" * 80 + "\n")


class SwarmCLI(cmd.Cmd):
    """Interactive CLI for swarm control"""
    
    intro = """
==========================================================================
              Drone Swarm Control Agent v1.0
          Multi-Drone Synchronized Flight Control System
==========================================================================

Laptop IP: 192.168.3.157
Drones: 192.168.3.2, 192.168.3.3 (via MAVProxy UDP:14553)

Type 'help' to see available commands.
Type 'help <command>' for command-specific help.
Type 'exit' to disconnect and exit.

"""
    
    prompt = "SWARM> "
    
    def __init__(self, swarm: SwarmController):
        """Initialize CLI with swarm controller"""
        super().__init__()
        self.swarm = swarm
    
    def do_connect(self, arg):
        """Connect to all drones"""
        if self.swarm.connect_all():
            print("[SUCCESS] Connected to all drones")
        else:
            print("[ERROR] Connection failed")
    
    def do_disconnect(self, arg):
        """Disconnect from all drones"""
        self.swarm.disconnect_all()
        print("[SUCCESS] Disconnected from all drones")
    
    def do_arm(self, arg):
        """Arm all drones for flight"""
        if self.swarm.arm_all():
            print("[SUCCESS] All drones armed successfully")
        else:
            print("[ERROR] Arm command failed")
    
    def do_disarm(self, arg):
        """Disarm all drones"""
        if self.swarm.disarm_all():
            print("[SUCCESS] All drones disarmed successfully")
        else:
            print("[ERROR] Disarm command failed")
    
    def do_takeoff(self, arg):
        """
        Takeoff all drones to specified altitude
        
        Usage:
            takeoff [altitude]
        
        Args:
            altitude: Target altitude in meters (default: 2.0m)
        
        Examples:
            takeoff        - Takeoff to 2.0 meters
            takeoff 5.0    - Takeoff to 5.0 meters
        """
        try:
            if arg.strip():
                altitude = float(arg.strip())
                # Validate altitude
                if altitude < 0.5 or altitude > 100:
                    print("[ERROR] Altitude must be between 0.5 and 100 meters")
                    return
            else:
                altitude = 2.0
            
            self.swarm.arm_all()

            if self.swarm.takeoff_all(altitude):
                print(f"[SUCCESS] All drones taking off to {altitude}m")
            else:
                print("[ERROR] Takeoff failed")
        except ValueError:
            print(f"[ERROR] Invalid altitude: {arg}")
    
    def do_land(self, arg):
        """Land all drones"""
        if self.swarm.land_all():
            print("[SUCCESS] All drones landing")
        else:
            print("[ERROR] Land command failed")
    
    def do_fly_to(self, arg):
        """
        Fly all drones forward based on current heading
        
        Usage:
            fly_to <distance> [speed]
        
        Args:
            distance: Distance to fly in meters (required)
            speed: Flight speed in m/s (default: 1.0)
        
        Examples:
            fly_to 5.0        - Fly 5 meters at 1.0 m/s
            fly_to 10.0 2.0   - Fly 10 meters at 2.0 m/s
        """
        try:
            args = arg.strip().split()
            if not args:
                print("[ERROR] Usage: fly_to <distance> [speed]")
                return
            
            distance = float(args[0])
            speed = float(args[1]) if len(args) > 1 else 1.0
            
            if distance <= 0 or speed <= 0:
                print("[ERROR] Distance and speed must be positive")
                return
            
            if self.swarm.fly_to(distance, speed):
                print(f"[SUCCESS] All drones flying forward {distance}m at {speed}m/s")
            else:
                print("[ERROR] Fly forward command failed")
        except ValueError:
            print(f"[ERROR] Invalid arguments: {arg}")
    
    def do_fly_back(self, arg):
        """
        Fly all drones backward based on current heading
        
        Usage:
            fly_back <distance> [speed]
        
        Args:
            distance: Distance to fly backward in meters (required)
            speed: Flight speed in m/s (default: 1.0)
        
        Examples:
            fly_back 5.0        - Fly backward 5 meters at 1.0 m/s
            fly_back 10.0 2.0   - Fly backward 10 meters at 2.0 m/s
        """
        try:
            args = arg.strip().split()
            if not args:
                print("[ERROR] Usage: fly_back <distance> [speed]")
                return
            
            distance = float(args[0])
            speed = float(args[1]) if len(args) > 1 else 1.0
            
            if distance <= 0 or speed <= 0:
                print("[ERROR] Distance and speed must be positive")
                return
            
            if self.swarm.fly_back(distance, speed):
                print(f"[SUCCESS] All drones flying backward {distance}m at {speed}m/s")
            else:
                print("[ERROR] Fly backward command failed")
        except ValueError:
            print(f"[ERROR] Invalid arguments: {arg}")
    
    def do_mode(self, arg):
        """
        Set flight mode for all drones
        
        Usage:
            mode <mode_name>    - Set flight mode (GUIDED, STABILIZE, LOITER, etc.)
            mode ?              - List available flight modes
            mode help           - Show this help
        
        Available modes:
            STABILIZE, GUIDED, AUTO, LOITER, RTL, LAND, BRAKE, DRIFT,
            SPORT, AUTOTUNE, POSHOLD, GUIDED_NOGPS, CIRCLE
        
        Examples:
            mode GUIDED         - Switch all drones to GUIDED mode
            mode LOITER         - Switch all drones to LOITER (hover)
            mode ?              - List all available modes
        """
        
        # Parse arguments (convert to uppercase for case-insensitive matching)
        args = arg.strip().upper().split()
        
        # Show help if no arguments or 'help' given
        if not args or args[0] == 'HELP':
            print(self.do_mode.__doc__)
            return
        
        # List available modes
        if args[0] == '?':
            print("\n" + "=" * 50)
            print("Available Flight Modes")
            print("=" * 50)
            for mode in FlightMode:
                print(f"  - {mode.name:20}")
            print("=" * 50 + "\n")
            return
        
        # Get mode name and convert to FlightMode enum
        mode_name = args[0]
        
        try:
            # Convert string to FlightMode
            flight_mode = FlightMode.from_string(mode_name)
            
            # Check if mode is valid
            if flight_mode is None:
                print(f"[ERROR] Unknown flight mode: {mode_name}")
                print("Type 'mode ?' to see available modes")
                return
            
            # Send mode command to all drones
            if self.swarm.mode_all(flight_mode):
                print(f"[SUCCESS] All drones set to {flight_mode.name} mode")
            else:
                print(f"[WARNING] Some drones failed to set {flight_mode.name} mode")
        
        except Exception as e:
            print(f"[ERROR] Error setting mode: {str(e)}")
    
    def do_status(self, arg):
        """Show status of all drones"""
        self.swarm.print_swarm_status()
    
    def do_help(self, arg):
        """Show available commands and their usage"""
        if arg:
            # Show help for specific command
            arg_lower = arg.lower()
            if hasattr(self, f'do_{arg_lower}'):
                method = getattr(self, f'do_{arg_lower}')
                print(method.__doc__)
            else:
                print(f"[ERROR] Unknown command: {arg}")
        else:
            # Show all available commands
            commands = [
                ('connect', 'Connect to all drones'),
                ('disconnect', 'Disconnect from all drones'),
                ('arm', 'Arm all drones for flight'),
                ('disarm', 'Disarm all drones (after landing)'),
                ('status', 'Show status of all drones'),
                ('takeoff <alt>', 'Takeoff to altitude in meters'),
                ('land', 'Land all drones'),
                ('fly_to <dist> [speed]', 'Fly forward by distance (meters)'),
                ('fly_back <dist> [speed]', 'Fly backward by distance (meters)'),
                ('mode <mode_name>', 'Set flight mode (GUIDED, STABILIZE, LOITER, etc.)'),
                ('mode ?', 'List available flight modes'),
                ('help [cmd]', 'Show help for command'),
                ('exit', 'Disconnect and exit swarm agent'),
            ]
            
            print("\n" + "=" * 80)
            print("Drone Swarm CLI - Available Commands")
            print("=" * 80)
            for cmd, desc in commands:
                print(f"  {cmd:40} - {desc}")
            print("=" * 80)
            print("\nFor help on a specific command, type: help <command_name>")
            print("Example: help mode\n")
    
    def do_exit(self, arg):
        """Disconnect and exit"""
        print("\nDisarming and disconnecting all drones...")
        try:
            self.swarm.disarm_all()
            time.sleep(1)
            self.swarm.disconnect_all()
        except:
            pass
        
        print("Goodbye!\n")
        return True
    
    def emptyline(self):
        """Handle empty line input"""
        pass
    
    def default(self, line):
        """Handle unknown commands"""
        print(f"[ERROR] Unknown command: '{line}'. Type 'help' for available commands.")


def main():
    """Main entry point"""
    
    print("Drone Swarm Control Agent")
    
    # Configure drone list
    # UPDATE THESE IPs TO MATCH YOUR DRONES
    drone_configs = [
        # DroneConfig(drone_id=1, ip_address='192.168.3.157', port=14553),
        # DroneConfig(drone_id=2, ip_address='192.168.3.157', port=14653),
        DroneConfig(drone_id=1, ip_address='172.21.128.1', port=14553),
        DroneConfig(drone_id=2, ip_address='172.21.128.1', port=14563),
        DroneConfig(drone_id=3, ip_address='172.21.128.1', port=14573),
    ]
    
    # Create swarm controller and CLI
    swarm = SwarmController(drone_configs)
    cli = SwarmCLI(swarm)
    
    try:
        cli.cmdloop()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        try:
            swarm.disarm_all()
            swarm.disconnect_all()
        except:
            pass
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        try:
            swarm.disarm_all()
            swarm.disconnect_all()
        except:
            pass
    
    print("Exiting swarm agent...")


if __name__ == '__main__':
    main()