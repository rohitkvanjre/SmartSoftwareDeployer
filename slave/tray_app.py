# Create this as a new file, e.g., "tray_app.py"
# You will compile this separately from your service.

import pystray
from PIL import Image, ImageDraw, ImageGrab
import time
import threading
import socket
import logging
import os
import json
import io

# --- Global variable to hold the status ---
# This will be updated by a background thread
global_status = "Starting..."

def create_icon(color):
    """Creates a simple 64x64 icon with a colored circle for the tray."""
    width = 64
    height = 64
    # Create a transparent image
    image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    dc = ImageDraw.Draw(image)
    # Draw a colored circle
    dc.ellipse(
        (width // 4, height // 4, width * 3 // 4, height * 3 // 4),
        fill=color
    )
    return image

# --- Define Icons ---
ICON_GREEN = create_icon('green')
ICON_YELLOW = create_icon('orange')
ICON_RED = create_icon('red')
ICON_BLUE = create_icon('blue')
IPC_DIR = os.path.join(os.environ.get("ProgramData"), "SoftwareDeployerAgent", "ipc")
STATUS_FILE = os.path.join(IPC_DIR, "status.json")
COMMAND_FILE = os.path.join(IPC_DIR, "command.txt")

# Screenshot relay: the Windows Service runs as LocalSystem in Session 0,
# which has no desktop at all -- ImageGrab.grab() there fails outright
# (Session 0 Isolation). This tray app, in contrast, runs in the actual
# logged-on user's own session (see service.py's install_tray_autostart),
# so it's the one place in this whole agent that CAN capture a real
# screenshot. The service drops a request file here; this app watches for
# it, captures the screen, and writes the result back for the service to
# pick up and forward to the master (see tasks.take_screenshot_via_tray_relay).
SCREENSHOT_REQUEST_FILE = os.path.join(IPC_DIR, "screenshot_request.flag")
SCREENSHOT_RESULT_FILE = os.path.join(IPC_DIR, "screenshot_result.jpg")

# Same %ProgramData%\SoftwareDeployerAgent\logs folder the service (service.py)
# and tasks.py already log to. A bare 'tray_app.log' filename resolves against
# the process's current working directory, which for a Scheduled Task with no
# explicit "Start in" folder defaults to C:\Windows\System32 -- unwritable by
# a standard user, so logging.basicConfig(filename='tray_app.log') crashed
# with PermissionError on every logon after this shipped as a scheduled task.
LOG_DIR = os.path.join(os.environ.get("ProgramData"), "SoftwareDeployerAgent", "logs")
LOG_FILE = os.path.join(LOG_DIR, "tray_app.log")


def query_service_status():
    """Reads the status from the service's JSON file."""
    try:
        # If the file is more than 30 seconds old, the service might be crashed
        if os.path.exists(STATUS_FILE) and (time.time() - os.path.getmtime(STATUS_FILE)) < 30:
            with open(STATUS_FILE, "r") as f:
                data = json.load(f)
            return data.get("status", "Unknown")
        else:
            return "Service Stopped"
    except (IOError, json.JSONDecodeError):
        return "IPC Error"
    except Exception as e:
        logging.error(f"Failed to query service status file: {e}")
        return "IPC Error"

def send_service_command(command):
    """Sends a command to the service by writing it to a file."""
    try:
        os.makedirs(IPC_DIR, exist_ok=True)
        with open(COMMAND_FILE, "w") as f:
            f.write(command)
        logging.info(f"Command '{command}' sent to service.")
    except Exception as e:
        logging.error(f"Failed to send command to service: {e}")

def status_poller_thread(icon):
    """A background thread that queries the service every 5 seconds."""
    global global_status
    while True:
        status = query_service_status()
        global_status = status

        # Update the icon text (tooltip)
        icon.title = f"Smart Software Deployer: {status}"

        # Update the icon color based on status
        if "Connected" in status:
            icon.icon = ICON_GREEN
        elif "Installing" in status or "Downloading" in status or "Running" in status:
            icon.icon = ICON_BLUE
        elif "Error" in status or "Stopped" in status:
            icon.icon = ICON_RED
        else:
            icon.icon = ICON_YELLOW # Default for states like "Connecting..."

        time.sleep(5) # Poll every 5 seconds

def screenshot_request_poller_thread():
    """Watches for a screenshot request from the service and, when one
    appears, captures the real screen (this process has desktop access,
    unlike the service) and writes the JPEG result back for it to pick up."""
    while True:
        try:
            if os.path.isfile(SCREENSHOT_REQUEST_FILE):
                os.remove(SCREENSHOT_REQUEST_FILE)  # consume it so it fires only once
                try:
                    screenshot = ImageGrab.grab()
                    buffer = io.BytesIO()
                    screenshot.save(buffer, format="JPEG", quality=75)
                    with open(SCREENSHOT_RESULT_FILE, "wb") as f:
                        f.write(buffer.getvalue())
                    logging.info("Captured screenshot for master request.")
                except Exception as e:
                    logging.error(f"Failed to capture/save screenshot: {e}")
        except Exception as e:
            logging.error(f"Screenshot request poller error: {e}")
        time.sleep(1)

# --- Menu Click Handlers ---
def on_trigger_inventory(icon, item):
    """Called when the user clicks 'Send Inventory'."""
    logging.info("User triggered inventory send.")
    send_service_command("TRIGGER_INVENTORY")

def on_quit(icon, item):
    """Called when the user clicks 'Quit'."""
    icon.stop()

# --- Main Program ---
def start_tray_app():
    os.makedirs(LOG_DIR, exist_ok=True)
    logging.basicConfig(level=logging.INFO, filename=LOG_FILE)
    logging.info("Tray App starting...")
    
    # Setup the system tray icon
    icon = pystray.Icon(
        "DeployerAgent",
        icon=ICON_YELLOW, # Start with yellow
        title="Deployer Agent: Starting...",
        menu=pystray.Menu(
            # The lambda: global_status makes the menu item update its text dynamically
            pystray.MenuItem(lambda item: global_status, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('Send Inventory Now', on_trigger_inventory),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('Quit', on_quit)
        )
    )

    # Start the background polling threads
    poller = threading.Thread(target=status_poller_thread, args=(icon,), daemon=True)
    poller.start()

    screenshot_poller = threading.Thread(target=screenshot_request_poller_thread, daemon=True)
    screenshot_poller.start()

    # Run the icon (this blocks the main thread)
    icon.run()

if __name__ == "__main__":
    start_tray_app()
