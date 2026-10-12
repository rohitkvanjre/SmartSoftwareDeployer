import argparse
import time
import logging
from .client import SlaveClient
from . import config, pairing
from . import logger as slave_logger

def main():
    """Main function for the slave client with a robust connect-then-discover fallback."""
    parser = argparse.ArgumentParser(prog="python -m slave")
    parser.add_argument("--pair", metavar="CODE", help="pairing code shown on the master's 'Pair New Slaves' screen")
    args = parser.parse_args()
    if args.pair:
        pairing.store_pairing_code(args.pair)

    slave_logger.setup_logging()
    RECONNECT_DELAY_SECONDS = 15

    while True:
        master_ip = None
        control_port = config.PORTS.get("control", 5050)

        # --- STEP 1: Try Configured IP First ---
        configured_ip = config.MASTER_IP
        if configured_ip and configured_ip.lower().strip() not in ['none', 'null', '']:
            logging.info(f"Attempting connection to configured MASTER_IP: {configured_ip}")
            master_ip = configured_ip

            if pairing.ensure_paired(master_ip, control_port):
                slave = SlaveClient(master_ip, control_port)
                # The start() method blocks if connection is successful and returns on failure.
                if not slave.start():
                    logging.critical("Exiting due to a fatal, unrecoverable error.")
                    break # Exit the main while loop
            
            # If we're here, it means the connection to the configured IP failed with a retryable error.
            logging.warning(f"Connection to configured IP {master_ip} failed or was lost. Falling back to discovery.")
            master_ip = None # Reset master_ip to trigger discovery
        
        # --- STEP 2: Fallback to Discovery ---
        # This block runs if no IP was configured, it was 'none', or the attempt above failed.
        if not master_ip:
            logging.info("MASTER_IP not set or failed to connect. Starting discovery...")
            discovered_ip, discovered_port = SlaveClient.discover_master()
            
            if discovered_ip:
                master_ip = discovered_ip
                if discovered_port:
                    control_port = discovered_port
                
                logging.info(f"Master discovered at {master_ip}:{control_port}. Connecting...")
                if pairing.ensure_paired(master_ip, control_port):
                    slave = SlaveClient(master_ip, control_port)
                    if not slave.start():
                        logging.critical("Exiting due to a fatal, unrecoverable error on discovered IP.")
                        break # Exit main loop
            else:
                logging.warning("Could not find master via discovery.")

        # --- STEP 3: Wait Before Retrying the Entire Process ---
        logging.info(f"Restarting connection process in {RECONNECT_DELAY_SECONDS} seconds.")
        time.sleep(RECONNECT_DELAY_SECONDS)

if __name__ == "__main__":
    main()