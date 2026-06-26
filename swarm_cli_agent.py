#!/usr/bin/env python3

import cmd
import logging
import math
import threading
import time
from dataclasses import dataclass
from typing import Dict, List

from control import DroneNode, FlightMode

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
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

        logger.debug(f"Initializing swarm with {len(drone_configs)} drone(s)")

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
                    logger.info(
                        f"[OK] Drone {config.drone_id} ({config.ip_address}) connected"
                    )
                    success_count += 1
                else:
                    logger.error(f"[FAIL] Drone {config.drone_id} connection failed")
            except Exception as e:
                logger.error(f"[FAIL] Drone {config.drone_id} error: {str(e)}")

        if success_count > 0:
            logger.info(
                f"Connected to {success_count}/{len(self.drone_configs)} drone(s)"
            )
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
                logger.warning(
                    f"Only {success_count}/{len(self.drones)} drones disarmed"
                )
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

        logger.info(f"Taking off all drones to {altitude}m...")

        with self.lock:
            for drone_id, drone in self.drones.items():
                if drone.takeoff(altitude):
                    logger.info(f"[OK] Drone {drone_id} taking off to {altitude}m")
                else:
                    logger.warning(f"[FAIL] Drone {drone_id} takeoff failed")

            return True

    def land_all(self) -> bool:
        """Land all drones"""
        logger.info("Landing all drones...")

        if not self.drones:
            logger.error("No drones connected")
            return False

        with self.lock:
            success_count = 0
            for drone_id, drone in self.drones.items():
                if drone.land():
                    logger.info(f"[OK] Drone {drone_id} landing")
                    success_count += 1
            logger.info(f"land_count: {success_count}")
            return success_count == len(self.drones)

    def move(self, distance: float, altitude: float = None) -> bool:
        """
        Fly all drones forward or backward relative to current heading using fly_to_target

        Args:
            distance: Distance to fly in meters.
                     Positive = move forward, Negative = move backward
                     Example: 30 = move forward 30m, -30 = move backward 30m
            altitude: Target altitude in meters (maintains current if None)

        Returns:
            True if command sent successfully
        """
        if not self.drones:
            logger.error("No drones connected")
            return False

        direction = "forward" if distance >= 0 else "backward"
        abs_distance = abs(distance)
        logger.info(
            f"Flying all drones {direction} {abs_distance}m using fly_to_target..."
        )

        with self.lock:
            success_count = 0
            for drone_id, drone in self.drones.items():
                try:
                    # Get current drone status
                    status = drone.get_drone_status()

                    # Get current position
                    current_position = status.get("position")
                    current_heading = status.get("heading")
                    current_altitude = status.get("altitude", 0)

                    if current_position is None or current_heading is None:
                        logger.warning(
                            f"[SKIP] Drone {drone_id}: Cannot get current position or heading"
                        )
                        continue

                    # Use provided altitude or maintain current altitude
                    target_altitude = (
                        altitude if altitude is not None else current_altitude
                    )

                    # Extract current lat/lon
                    current_lat, current_lon = current_position

                    # Calculate target position offset based on distance and heading
                    # Convert heading to radians
                    heading_rad = math.radians(current_heading)

                    # For negative distance (backward), adjust heading by 180 degrees
                    if distance < 0:
                        heading_rad = heading_rad + math.pi

                    # Calculate lat/lon offset
                    # Approximate: 1 degree latitude ≈ 111 km = 111000 meters
                    # 1 degree longitude ≈ 111 km * cos(latitude) at the equator
                    lat_offset = (abs_distance / 111000.0) * math.cos(heading_rad)
                    lon_offset = (
                        abs_distance / (111000.0 * math.cos(math.radians(current_lat)))
                    ) * math.sin(heading_rad)

                    # Calculate target position
                    target_lat = current_lat + lat_offset
                    target_lon = current_lon + lon_offset

                    # Send fly_to_target command
                    if drone.fly_to_target(target_lat, target_lon, target_altitude):
                        logger.info(
                            f"[OK] Drone {drone_id}: Flying {direction} {abs_distance}m to ({target_lat:.7f}, {target_lon:.7f}) at {target_altitude}m"
                        )
                        success_count += 1
                    else:
                        logger.warning(
                            f"[FAIL] Drone {drone_id}: fly_to_target command failed"
                        )

                except Exception as e:
                    logger.error(f"[ERROR] Drone {drone_id}: {str(e)}")

            if success_count > 0:
                logger.info(
                    f"Move command sent to {success_count}/{len(self.drones)} drone(s)"
                )
                return True
            else:
                return False

    def mode_all(self, flight_mode: FlightMode) -> bool:
        """
        Set flight mode for all drones

        Args:
            flight_mode: FlightMode enum

        Returns:
            True if all drones successfully set to the mode
        """
        if not self.drones:
            logger.error("No drones connected")
            return False

        logger.info(f"Setting all drones to {flight_mode.name} mode...")

        with self.lock:
            success_count = 0
            for drone_id, drone in self.drones.items():
                try:
                    if drone.set_flight_mode(flight_mode):
                        logger.info(
                            f"[OK] Drone {drone_id} set to {flight_mode.name} mode"
                        )
                        success_count += 1
                    else:
                        logger.warning(f"[FAIL] Drone {drone_id} mode change failed")
                except Exception as e:
                    logger.error(f"[FAIL] Drone {drone_id} mode error: {str(e)}")

        return success_count == len(self.drones)

    def stop_all(self) -> bool:
        """
        Emergency stop - set to BRAKE mode

        Returns:
            True if all drones successfully stopped
        """
        logger.warning("EMERGENCY STOP - Setting all drones to BRAKE mode")
        return self.mode_all(FlightMode.BRAKE)


class SwarmCLI(cmd.Cmd):
    """Command-line interface for swarm control"""

    intro = """DRONE SWARM AGENT CLI"""

    prompt = "> "

    def __init__(self, swarm: SwarmController):
        super().__init__()
        self.swarm = swarm

    def do_connect(self, arg):
        """Connect to all drones"""
        if self.swarm.connect_all():
            print("[SUCCESS] All drones connected")
        else:
            print("[ERROR] Failed to connect to drones")

    def do_disarm(self, arg):
        """Disarm all drones"""
        if self.swarm.disarm_all():
            print("[SUCCESS] All drones disarmed")
        else:
            print("[ERROR] Disarm command failed")

    def do_arm(self, arg):
        """Arm all drones"""
        if self.swarm.arm_all():
            print("[SUCCESS] All drones armed")
        else:
            print("[ERROR] Arm command failed")

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

    def do_move(self, arg):
        """
        Fly all drones forward or backward based on current heading using fly_to_target

        Usage:
            move <distance> [altitude]

        Args:
            distance: Distance to fly in meters.
                     Positive = move forward, Negative = move backward
                     (required)
            altitude: Target altitude in meters - maintains current if omitted
                     (optional)

        Examples:
            move 30          - Move forward 30 meters at current altitude
            move -30         - Move backward 30 meters at current altitude
            move 50 10       - Move forward 50 meters to 10 meters altitude
            move -20 8       - Move backward 20 meters to 8 meters altitude
        """
        try:
            args = arg.strip().split()
            if not args:
                print("[ERROR] Usage: move <distance> [altitude]")
                print("  distance: positive=forward, negative=backward (meters)")
                print("  altitude: optional target altitude (meters)")
                return

            distance = float(args[0])
            altitude = float(args[1]) if len(args) > 1 else None

            # Validate distance
            if abs(distance) < 1:
                print("[ERROR] Distance must be at least 1 meter")
                return
            if abs(distance) > 500:
                print("[ERROR] Distance cannot exceed 500 meters")
                return

            # Validate altitude if provided
            if altitude is not None:
                if altitude < 0.5 or altitude > 100:
                    print("[ERROR] Altitude must be between 0.5 and 100 meters")
                    return

            direction = "forward" if distance >= 0 else "backward"
            abs_dist = abs(distance)
            alt_msg = (
                f" to {altitude}m altitude" if altitude else " at current altitude"
            )

            if self.swarm.move(distance, altitude):
                print(f"[SUCCESS] All drones moving {direction} {abs_dist}m{alt_msg}")
            else:
                print("[ERROR] Move command failed")
        except ValueError:
            print(f"[ERROR] Invalid arguments: {arg}")
            print("Usage: move <distance> [altitude]")

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
        if not args or args[0] == "HELP":
            print(self.do_mode.__doc__)
            return

        # List available modes
        if args[0] == "?":
            print("\n" + "-" * 50)
            print("Available Flight Modes")
            print("-" * 50)
            for mode in FlightMode:
                print(f"  - {mode.name:20}")
            print("-" * 50 + "\n")
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

    def do_stop(self, arg):
        """Emergency stop - set all drones to BRAKE mode"""
        print("\nEMERGENCY STOP - Setting all drones to BRAKE mode")
        if self.swarm.stop_all():
            print("[SUCCESS] All drones emergency stopped")
        else:
            print("[ERROR] Emergency stop command failed")

    def do_check(self, arg):
        """
        Display status of all connected drones

        Usage:
            status          - Show status of all drones
            status <id>     - Show status of specific drone (e.g., status 1)

        Displays:
            - Drone ID
            - Armed status
            - Flight mode
            - Heading (degrees)
            - Altitude (meters)
            - Battery (voltage)
            - GPS status (satellites and fix type)
            - Groundspeed (m/s)

        Examples:
            status          - Show all drones
            status 1        - Show only drone 1
        """
        try:
            # Parse optional drone ID argument
            drone_id_filter = None
            if arg.strip():
                try:
                    drone_id_filter = int(arg.strip())
                except ValueError:
                    print(f"[ERROR] Invalid drone ID: {arg}")
                    return

            if not self.swarm.drones:
                print("[ERROR] No drones connected")
                return

            # Prepare drones to display
            drones_to_show = {}
            if drone_id_filter:
                if drone_id_filter in self.swarm.drones:
                    drones_to_show[drone_id_filter] = self.swarm.drones[drone_id_filter]
                else:
                    print(f"[ERROR] Drone {drone_id_filter} not found")
                    return
            else:
                drones_to_show = self.swarm.drones

            # Display header
            print(
                f"{'ID':>4} {'Armed':>7} {'Mode':>12} {'Heading':>10} {'Alt(m)':>8} {'Battery(V)':>12} {'GPS Sats':>10} {'Fix Type':>12} {'Speed(cm/s)':>12} {'Ready?':>12}"
            )
            print("-" * 110)

            # Display status for each drone
            for drone_id in sorted(drones_to_show.keys()):
                drone = drones_to_show[drone_id]
                status = drone.get_drone_status()

                # Extract status information with defaults
                armed = "Yes" if status.get("armed", False) else "No"
                mode = status.get("mode", "Unknown")
                heading = status.get("heading", "N/A")
                altitude = status.get("altitude", "N/A")
                _groundspeed = status.get("groundspeed", "N/A")

                # Format heading
                if isinstance(heading, (int, float)):
                    heading_str = f"{heading:.1f}°"
                else:
                    heading_str = str(heading)

                # Format altitude
                if isinstance(altitude, (int, float)):
                    altitude_str = f"{altitude:.2f}"
                else:
                    altitude_str = str(altitude)

                # Format WPNAV_SPEED
                try:
                    wpnav_speed = drone.get_drone_param("WPNAV_SPEED")
                    if wpnav_speed is not None:
                        wpnav_speed_str = f"{float(wpnav_speed):.2f}"
                    else:
                        wpnav_speed_str = "N/A"
                except Exception:
                    wpnav_speed_str = "N/A"

                # Extract battery information
                battery_info = status.get("battery")
                if battery_info:
                    if isinstance(battery_info, dict):
                        battery_voltage = battery_info.get("voltage", "N/A")
                        battery_str = f"{int(battery_voltage) / 1000:.2f}"
                else:
                    battery_str = "N/A"

                # Extract GPS information
                gps_info = status.get("gps", {})
                if gps_info:
                    satellites = gps_info.get("satellites_visible", "N/A")
                    fix_type = gps_info.get("fix_type", "N/A")

                    # Map fix type numbers to names
                    fix_type_names = {
                        0: "No Fix",
                        1: "Dead Reck",
                        2: "2D Fix",
                        3: "3D Fix",
                        4: "DGPS Fix",
                        5: "RTK Float",
                        6: "RTK Fixed",
                    }
                    if isinstance(fix_type, int):
                        fix_type_str = fix_type_names.get(
                            fix_type, f"Unknown({fix_type})"
                        )
                    else:
                        fix_type_str = str(fix_type)

                    if isinstance(satellites, int):
                        satellites_str = str(satellites)
                    else:
                        satellites_str = str(satellites)
                else:
                    satellites_str = "N/A"
                    fix_type_str = "N/A"

                # Print drone status row
                print(
                    f"{drone_id:>4} {armed:>7} {mode:>12} {heading_str:>10} {altitude_str:>8} {battery_str:>12} {satellites_str:>10} {fix_type_str:>12} {wpnav_speed_str:>12} {'':>7}🥴"
                )

            # print("\nFix Types: No Fix=0, Dead Reck=1, 2D=2, 3D=3, DGPS=4, RTK Float=5, RTK Fixed=6\n")

        except Exception as e:
            logger.error(f"Error getting drone status: {str(e)}")
            print(f"[ERROR] Failed to get drone status: {str(e)}")

    def do_help(self, arg):
        """Show available commands and their usage"""
        if arg:
            # Show help for specific command
            arg_lower = arg.lower()
            if hasattr(self, f"do_{arg_lower}"):
                method = getattr(self, f"do_{arg_lower}")
                print(method.__doc__)
            else:
                print(f"[ERROR] Unknown command: {arg}")
        else:
            # Show all available commands
            commands = [
                ("connect", "Connect to all drones"),
                ("arm", "Arm all drones"),
                ("disarm", "Disarm all drones"),
                ("takeoff <alt>", "Takeoff to altitude in meters"),
                (
                    "move <dist> [alt]",
                    "Move forward/back by distance (use fly_to_target)",
                ),
                (
                    "mode <mode_name>",
                    "Set flight mode (GUIDED, STABILIZE, LOITER, etc.)",
                ),
                ("stop", "Emergency stop (BRAKE mode)"),
                ("land", "Land all drones"),
                ("check", "Check drones status before start"),
                ("help [cmd]", "Show help for command"),
                ("exit", "Disconnect and exit swarm agent"),
            ]

            print("\n" + "-" * 80)
            print("Drone Swarm CLI - Available Commands")
            print("-" * 80)
            for cmd, desc in commands:
                print(f"  {cmd:40} - {desc}")
            print("-" * 80)

    def do_exit(self, arg):
        """Disconnect and exit"""
        print("\nDisarming and disconnecting all drones...")
        try:
            self.swarm.disarm_all()
            time.sleep(1)
            self.swarm.disconnect_all()
        except Exception:
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

    # Configure drone list
    # UPDATE THESE IPs TO MATCH YOUR DRONES
    drone_configs = [
        DroneConfig(drone_id=1, ip_address="192.168.3.157", port=14553),
        # DroneConfig(drone_id=2, ip_address='192.168.3.200', port=14653),
        # DroneConfig(drone_id=1, ip_address="172.21.128.1", port=14553),
        # DroneConfig(drone_id=2, ip_address="172.21.128.1", port=14563),
        # DroneConfig(drone_id=3, ip_address="172.21.128.1", port=14573),
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
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        try:
            swarm.disarm_all()
            swarm.disconnect_all()
        except Exception:
            pass

    print("Exiting swarm agent...")


if __name__ == "__main__":
    main()
