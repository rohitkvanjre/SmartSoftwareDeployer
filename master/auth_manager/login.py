import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
import time
from .auth import verify_password, hash_password
from . import manage_users
from ..theme import BG_COLOR, FONT_LARGE_BOLD, FONT_NORMAL

# --- Brute-force / enumeration mitigations ---
# Fixed dummy salt+hash used to perform a "wasted" PBKDF2 computation when the
# supplied username does not exist, so that login timing does not reveal
# whether a username is valid.
_DUMMY_SALT = "0" * 64
_DUMMY_HASH = hash_password("dummy-password-for-timing-safety", _DUMMY_SALT)

# After this many consecutive failed attempts (in this dialog session), start
# throttling further attempts with an increasing lockout delay.
FAILED_ATTEMPTS_THRESHOLD = 3
BASE_LOCKOUT_SECONDS = 5
MAX_LOCKOUT_SECONDS = 300

class LoginDialog(tk.Toplevel):
    """A themed, modal login dialog."""
    def __init__(self, parent, users_json=None):
        super().__init__(parent)

        self.users_path = users_json or manage_users.USERS_FILE
        self.result = None
        self._failed_attempts = 0
        self._lockout_until = 0.0

        self.title("Smart Software Deployer - Login")
        self.geometry("350x250")
        self.resizable(False, False)
        self.configure(bg=BG_COLOR)
        self.grab_set()

        main_frame = ttk.Frame(self, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(1, weight=1)

        ttk.Label(main_frame, text="User Login", font=FONT_LARGE_BOLD).grid(
            row=0, column=0, columnspan=2, pady=(0, 20))

        ttk.Label(main_frame, text="Username:", font=FONT_NORMAL).grid(
            row=1, column=0, sticky="w", padx=5, pady=5)
        self.user_e = ttk.Entry(main_frame)
        self.user_e.grid(row=1, column=1, sticky="ew", padx=5, pady=5)
        self.user_e.focus_set()

        ttk.Label(main_frame, text="Password:", font=FONT_NORMAL).grid(
            row=2, column=0, sticky="w", padx=5, pady=5)
        self.pass_e = ttk.Entry(main_frame, show="*")
        self.pass_e.grid(row=2, column=1, sticky="ew", padx=5, pady=5)

        btns = ttk.Frame(main_frame)
        btns.grid(row=3, column=1, sticky="e", pady=(20, 0))
        ttk.Button(btns, text="Login", command=self._on_login).pack(side="left", padx=5)
        ttk.Button(btns, text="Cancel", command=self._on_cancel).pack(side="left")

        self.bind("<Return>", lambda e: self._on_login())
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

    def _load_users(self):
        if not os.path.exists(self.users_path): return []
        try:
            with open(self.users_path, "r", encoding="utf-8") as f: return json.load(f)
        except Exception: return []

    def _on_login(self):
        now = time.time()
        if now < self._lockout_until:
            remaining = int(self._lockout_until - now) + 1
            messagebox.showerror(
                "Login",
                f"Too many failed attempts. Please wait {remaining} second(s) and try again.",
                parent=self,
            )
            return

        username = self.user_e.get().strip()
        password = self.pass_e.get()
        if not username or not password:
            messagebox.showerror("Login", "Username and password are required.", parent=self)
            return

        users = self._load_users()
        matched_user = None
        for u in users:
            if u.get("username") == username:
                matched_user = u
                break

        if matched_user is not None:
            if verify_password(password, matched_user.get("salt"), matched_user.get("password_hash")):
                self._failed_attempts = 0
                self.result = {"username": username, "role": matched_user.get("role", "user")}
                self.destroy()
                return
        else:
            # Perform a dummy hash computation so the response time is the same
            # whether or not the username exists, mitigating enumeration.
            verify_password(password, _DUMMY_SALT, _DUMMY_HASH)

        self._register_failed_attempt()
        messagebox.showerror("Login failed", "Invalid username or password.", parent=self)

    def _register_failed_attempt(self):
        """Tracks consecutive failed attempts and applies an increasing lockout delay."""
        self._failed_attempts += 1
        if self._failed_attempts >= FAILED_ATTEMPTS_THRESHOLD:
            lockout_seconds = min(
                BASE_LOCKOUT_SECONDS * (2 ** (self._failed_attempts - FAILED_ATTEMPTS_THRESHOLD)),
                MAX_LOCKOUT_SECONDS,
            )
            self._lockout_until = time.time() + lockout_seconds

    def _on_cancel(self):
        self.result = None
        self.destroy()

    def show(self):
        self.master.wait_window(self)
        return self.result