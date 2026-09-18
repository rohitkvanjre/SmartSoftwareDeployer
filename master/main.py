# import tkinter as tk
# from tkinter import ttk
# import sys
# import traceback
# from .auth_manager.login import LoginDialog
# import os

# project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# sys.path.append(project_root)

# from master.app import MasterAppController
# from master.gui_modern import setup_styles
# from master import logger as master_logger

# def main():
#     """Main function to start the master application."""
#     try:
#         master_logger.setup_logging()
#         root = tk.Tk()
#         root.withdraw()

#         # Apply the global theme
#         setup_styles()

#         # Create and show the login dialog
#         dlg = LoginDialog(root)
#         root.update()
        
#         current_user = dlg.show()

#         if not current_user:
#             print("Login cancelled. Exiting.")
#             sys.exit(0)

#         # On successful login, start the main application
#         root.deiconify()
#         root.state('zoomed')
#         app = MasterAppController(root)
#         app.gui.set_user(current_user)
#         root.protocol("WM_DELETE_WINDOW", app.shutdown)
#         root.mainloop()

#     except Exception:
#         traceback.print_exc()
#         input("\nA fatal error occurred. Press Enter to exit.")
#         sys.exit(1)

# if __name__ == "__main__":
#     main()

import tkinter as tk
from tkinter import simpledialog, messagebox
import sys
import os

# Add the project's root directory to the Python path.
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

# Import all necessary components
from master.app import MasterAppController
from master.gui_modern import setup_styles
from master import logger as master_logger
from master.auth_manager.login import LoginDialog
from master.auth_manager import manage_users
from master.auth_manager.auth import generate_salt, hash_password
from master import config
from master import generate_certs

def bootstrap_first_user(parent):
    """Create the first administrator account through an interactive setup."""
    # Use the USERS_FILE constant from the manage_users module
    users_file_path = manage_users.USERS_FILE
    if not os.path.exists(users_file_path) or len(manage_users.load_users()) == 0:
        print("--- First Time Setup: Create Administrator User ---")
        default_username = "admin"
        while True:
            default_password = simpledialog.askstring(
                "First-time setup",
                "Create a password for the administrator account:",
                show="*",
                parent=parent,
            )
            if default_password is None:
                return False
            if len(default_password) == 0:
                messagebox.showerror("First-time setup", "The password cannot be empty.", parent=parent)
                continue
            password_confirmation = simpledialog.askstring(
                "First-time setup",
                "Confirm the administrator password:",
                show="*",
                parent=parent,
            )
            if default_password != password_confirmation:
                messagebox.showerror("First-time setup", "The passwords do not match.", parent=parent)
                continue
            break
        
        salt = generate_salt()
        password_hash = hash_password(default_password, salt)
        
        initial_user = {
            "username": default_username,
            "password_hash": password_hash,
            "salt": salt,
            "role": "admin"
        }
        manage_users.save_users([initial_user])
        print(f"Default admin user created.")
        print(f"   Username: {default_username}")
        print(f"-------------------")
        print("You can add more users by running 'py -m master.manage_users'")
    return True

def main():
    """Main entry point for the master application with login."""
    master_logger.setup_logging()

    # Silently (re)generate the TLS certificate for this machine's actual
    # network address if one doesn't already exist yet -- makes a freshly
    # installed master work with zero manual setup.
    if config.TLS.get("enabled"):
        try:
            result = generate_certs.ensure_certs_exist()
            if result.get("generated"):
                print(f"Generated a new TLS certificate for this machine: {result}")
        except Exception as e:
            print(f"WARNING: Could not auto-generate TLS certificate: {e}")

    # Create a hidden root window to be the parent of the dialog
    root = tk.Tk()
    setup_styles()
    root.withdraw()

    # Ensure a default user exists for the first run
    if not bootstrap_first_user(root):
        root.destroy()
        return

    # Show the login dialog and wait for the result
    login_dialog = LoginDialog(root)
    user = login_dialog.show()

    # If login is cancelled or fails, exit the application
    if not user:
        print("Login cancelled. Exiting.")
        root.destroy()
        return

    # If login is successful, create and run the main application
    root.destroy() # Close the temporary hidden window
    
    main_root = tk.Tk()
    setup_styles()
    app = MasterAppController(main_root, authenticated_user=user)
    
    main_root.protocol("WM_DELETE_WINDOW", app.shutdown)
    main_root.mainloop()

if __name__ == "__main__":
    main()