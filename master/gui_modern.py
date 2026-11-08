"""
Module: modern_gui
A new, feature-rich, and modern GUI for the master application.
Author: Gemini
Version: 2.4
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import time
import os
import datetime
from collections import Counter
import traceback
import logging
from .theme import *
import base64
import io
from PIL import Image, ImageTk # Requires Pillow: pip install Pillow

def setup_styles():
        """Configures the global ttk style for the application's dark theme."""
        style = ttk.Style()
        style.theme_use('clam')
        # General styles
        style.configure(".", background=BG_COLOR, foreground=FG_COLOR, font=FONT_NORMAL, borderwidth=0, lightcolor=BG_COLOR, darkcolor=BG_COLOR)
        style.configure("TFrame", background=BG_COLOR)
        style.configure("TLabel", background=BG_COLOR, foreground=FG_COLOR, font=FONT_NORMAL)
        style.configure("TButton", background=ACCENT_COLOR, foreground=FG_COLOR, font=FONT_BOLD, borderwidth=0, focusthickness=0)
        style.map("TButton", background=[('active', '#005f9e')])
        # Treeview styles
        style.configure("Treeview", background=LIST_BG, foreground=FG_COLOR, fieldbackground=LIST_BG, rowheight=28, font=FONT_NORMAL)
        style.configure("Treeview.Heading", background=HEADER_BG, foreground=FG_COLOR, font=FONT_BOLD, relief="flat")
        style.map("Treeview.Heading", background=[('active', ACCENT_COLOR)])
        # Other widget styles
        style.configure("Vertical.TScrollbar", background=BG_COLOR, troughcolor=LIST_BG)
        style.configure("TEntry", fieldbackground=LIST_BG, foreground=FG_COLOR, insertcolor=FG_COLOR, bordercolor=HEADER_BG, selectbackground=ACCENT_COLOR)
        style.configure("TLabelframe", background=BG_COLOR, bordercolor=HEADER_BG)
        style.configure("TLabelframe.Label", background=BG_COLOR, foreground=FG_COLOR, font=FONT_BOLD)
        style.configure("TNotebook", background=BG_COLOR, borderwidth=0)
        style.configure("TNotebook.Tab", background=HEADER_BG, foreground=FG_COLOR, padding=[10, 5], font=FONT_BOLD)
        style.map("TNotebook.Tab", background=[("selected", ACCENT_COLOR)])   

class CustomCombobox(ttk.Frame):
    """A custom, fully-stylable dropdown widget."""
    def __init__(self, parent, values, textvariable):
        super().__init__(parent)
        self.values = values
        self.textvariable = textvariable
        
        # --- Configure Grid ---
        self.columnconfigure(0, weight=1)

        # --- Widgets ---
        self.entry = ttk.Entry(self, textvariable=self.textvariable, state="readonly", style="TEntry")
        self.entry.grid(row=0, column=0, sticky="ew")

        arrow_button = ttk.Button(self, text="▼", width=2, command=self._show_dropdown)
        arrow_button.grid(row=0, column=1)

        self._dropdown = None

    def _show_dropdown(self):
        """Creates and displays the dropdown listbox."""
        if self._dropdown and self._dropdown.winfo_exists():
            self._dropdown.destroy()
            return

        # --- Get position of the entry widget ---
        x = self.entry.winfo_rootx()
        y = self.entry.winfo_rooty() + self.entry.winfo_height()
        width = self.entry.winfo_width()

        # --- Create Dropdown Window ---
        self._dropdown = tk.Toplevel(self.master)
        self._dropdown.overrideredirect(True) # Borderless window
        self._dropdown.geometry(f"{width}x150+{x}+{y}")
        self._dropdown.bind("<FocusOut>", lambda e: self._dropdown.destroy())

        # --- Create Listbox ---
        listbox = tk.Listbox(
            self._dropdown,
            background=LIST_BG,
            foreground=FG_COLOR,
            selectbackground=ACCENT_COLOR,
            selectforeground=FG_COLOR,
            highlightthickness=1,
            highlightcolor=ACCENT_COLOR,
            borderwidth=0,
            font=FONT_NORMAL,
            activestyle="none"
        )
        listbox.pack(expand=True, fill="both")
        
        for value in self.values:
            listbox.insert(tk.END, value)

        # --- Set current selection ---
        current_value = self.textvariable.get()
        if current_value in self.values:
            idx = self.values.index(current_value)
            listbox.see(idx)
            listbox.activate(idx)
            listbox.selection_set(idx)
        
        listbox.bind("<<ListboxSelect>>", self._on_select)
        self._dropdown.focus_set()

    def _on_select(self, event):
        """Handles item selection from the listbox."""
        widget = event.widget
        selection_indices = widget.curselection()
        if selection_indices:
            value = widget.get(selection_indices[0])
            self.textvariable.set(value)
        if self._dropdown:
            self._dropdown.destroy()

class InventoryPopup(tk.Toplevel):
    """A styled popup window to display detailed node inventory."""
    def __init__(self, parent, hostname, all_nodes_cache, callbacks: dict):
        super().__init__(parent)
        self.title(f"Inventory — {hostname}")
        self.hostname = hostname
        self.all_nodes_cache = all_nodes_cache # Store the main cache
        self.callbacks = callbacks or {}
        self.geometry("800x500")
        self.configure(bg=BG_COLOR)

        # --- Main Frame ---
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Header ---
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(header_frame, text=f"Host: {hostname}", font=("Segoe UI", 12, "bold")).pack(side=tk.LEFT)
        
        btn_frame = ttk.Frame(header_frame)
        btn_frame.pack(side=tk.RIGHT)
        ttk.Button(btn_frame, text="Refresh", command=self._fetch).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Close", command=self.destroy).pack(side=tk.LEFT)

        # --- Paned Window for System Info and Apps ---
        pane = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True)

        # --- System Info Panel ---
        sys_frame = ttk.LabelFrame(pane, text="System Information", style="TLabelframe")
        self.sys_text = tk.Text(sys_frame, wrap="word", relief="flat", bg=LIST_BG, fg=FG_COLOR, font=FONT_NORMAL)
        self.sys_text.tag_configure("header", font=FONT_BOLD)
        self.sys_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        pane.add(sys_frame, weight=1)

        # --- Applications Panel ---
        apps_frame = ttk.LabelFrame(pane, text="Installed Applications", style="TLabelframe")
        
        # --- THIS IS THE CORRECTED LAYOUT ---
        # 1. Pack the static button from the BOTTOM first to reserve its space.
        uninstall_btn = ttk.Button(apps_frame, text="Uninstall Selected", command=self._uninstall_selected)
        uninstall_btn.pack(side=tk.BOTTOM, pady=5)
        
        # 2. Pack the expanding Treeview from the TOP to fill the remaining space.
        self.tree = ttk.Treeview(apps_frame, columns=("name", "version", "publisher"), show="headings")
        self.tree.heading("name", text="Name"); self.tree.column("name", width=300, anchor="center")
        self.tree.heading("version", text="Version"); self.tree.column("version", width=100, anchor="center")
        self.tree.heading("publisher", text="Publisher"); self.tree.column("publisher", width=200, anchor="center")
        self.tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=5)
        # --- END OF CORRECTION ---
        
        pane.add(apps_frame, weight=2)

        self._last_info = None
        self.load_from_cache()

    def load_from_cache(self):
        # (This function is unchanged)
        getter = self.callbacks.get("get_last_inventory")
        info = getter(self.hostname) if getter else {}
        self._last_info = info or {}
        self.sys_text.config(state=tk.NORMAL)
        self.sys_text.delete("1.0", tk.END)
        info_categories = [("os_info", "OS"), ("cpu_info", "CPU"), ("ram_info", "RAM"), 
                           ("disk_info", "Disk"), ("network_info", "Network"), ("boot_info", "Boot")]
        if isinstance(self._last_info, dict):
            for key, title in info_categories:
                data = self._last_info.get(key)
                if not data or not isinstance(data, dict): continue
                self.sys_text.insert(tk.END, f"--- {title} ---\n", "header")
                if key == 'disk_info':
                    for drive, details in data.items():
                        self.sys_text.insert(tk.END, f"  {drive}\n")
                        if isinstance(details, dict):
                            for k, v in details.items(): self.sys_text.insert(tk.END, f"    {k.replace('_', ' ').capitalize()}: {v}\n")
                else:
                    for k, v in data.items(): self.sys_text.insert(tk.END, f"  {k.replace('_', ' ').capitalize()}: {v}\n")
                self.sys_text.insert(tk.END, "\n")
        self.sys_text.config(state=tk.DISABLED)
        for row in self.tree.get_children(): self.tree.delete(row)
        installed = self._last_info.get("installed_software", [])
        if isinstance(installed, list):
            for app in installed:
                if isinstance(app, dict):
                    self.tree.insert("", tk.END, values=(app.get("name", "N/A"), app.get("version", "N/A"), app.get("publisher", "N/A")))

    def _fetch(self):
        # --- MODIFIED: This function is now smarter ---
        node_status = self.all_nodes_cache.get(self.hostname, {}).get('status', 'offline')
        if node_status != 'online':
            messagebox.showwarning("Slave Offline", "Cannot refresh inventory because the slave is offline.", parent=self)
            return

        if self.callbacks.get("on_request_inventory"):
            self.callbacks["on_request_inventory"](self.hostname)
            messagebox.showinfo("Requested", f"Inventory request sent to {self.hostname}.", parent=self)

    def _uninstall_selected(self):
        # (This function is unchanged)
        sel = self.tree.selection()
        if not sel: return
        name = self.tree.item(sel[0])["values"][0]
        if name and messagebox.askyesno("Confirm", f"Uninstall '{name}' from {self.hostname}?", parent=self):
            if self.callbacks.get("on_uninstall"):
                self.callbacks["on_uninstall"](self.hostname, name)

class MainGUI:
    def __init__(self, root, callbacks: dict):
        self.root = root
        self.callbacks = callbacks or {}
        self.root.title("Smart Software Deployer - Master Control")
        self.root.state('zoomed')
        self.root.minsize(1000, 600)
        self.root.configure(bg=BG_COLOR)

        self.search_var = tk.StringVar()
        self.audit_search_var = tk.StringVar()
        self.user = None
        self.active_toasts = []

        self.green_dot_img = tk.PhotoImage(file=os.path.join(os.path.dirname(__file__), "assets", "green_dot.png"))
        self.red_dot_img = tk.PhotoImage(file=os.path.join(os.path.dirname(__file__), "assets", "red_dot.png"))
        self.yellow_dot_img = tk.PhotoImage(file=os.path.join(os.path.dirname(__file__), "assets", "yellow_dot.png"))

        # --- Style Configuration ---
        style = ttk.Style()
        style.theme_use('clam')
        style.configure(".", background=BG_COLOR, foreground=FG_COLOR, font=FONT_NORMAL)
        style.configure("Card.TFrame", background=HEADER_BG, relief="flat")
        style.configure("TFrame", background=BG_COLOR)
        style.configure("TLabel", background=BG_COLOR, foreground=FG_COLOR, font=FONT_NORMAL)
        style.configure("TButton", background=ACCENT_COLOR, foreground=FG_COLOR, font=FONT_BOLD, borderwidth=0)
        style.map("TButton", background=[('active', '#005f9e')])
        style.configure("Treeview", background=LIST_BG, foreground=FG_COLOR, fieldbackground=LIST_BG, rowheight=40, font=FONT_NORMAL)
        style.configure("Treeview.Heading", background=HEADER_BG, foreground=FG_COLOR, font=FONT_BOLD, relief="flat")
        style.map("Treeview.Heading", background=[('active', ACCENT_COLOR)])
        style.configure("Vertical.TScrollbar", background=BG_COLOR, troughcolor=LIST_BG)
        style.configure("TEntry", fieldbackground=LIST_BG, foreground=FG_COLOR, insertcolor=FG_COLOR, bordercolor=HEADER_BG)
        style.configure("TLabelframe", background=BG_COLOR, bordercolor=HEADER_BG)
        style.configure("TLabelframe.Label", background=BG_COLOR, foreground=FG_COLOR, font=FONT_BOLD)
        style.configure("TNotebook", background=BG_COLOR, borderwidth=0)
        # style.configure("TNotebook.Tab", background=HEADER_BG, foreground=FG_COLOR, padding=[10, 5], font=FONT_BOLD)
        # style.map("TNotebook.Tab", background=[("selected", ACCENT_COLOR)])


        # Style for the Combobox itself (the entry field and arrow)
        # style.configure('Dark.TCombobox',
        #                 selectbackground=ACCENT_COLOR,
        #                 fieldbackground=LIST_BG,
        #                 background=HEADER_BG,
        #                 foreground=FG_COLOR,
        #                 arrowcolor=FG_COLOR,
        #                 bordercolor=HEADER_BG)
        
        # # Ensures the colors don't change when the widget is 'readonly'
        # style.map('Dark.TCombobox',
        #           fieldbackground=[('readonly', LIST_BG)],
        #           selectbackground=[('readonly', ACCENT_COLOR)],
        #           foreground=[('readonly', FG_COLOR)])

        # # Style for the dropdown list that appears
        # self.root.option_add('*TCombobox*Listbox.background', LIST_BG)
        # self.root.option_add('*TCombobox*Listbox.foreground', FG_COLOR)
        # self.root.option_add('*TCombobox*Listbox.selectBackground', ACCENT_COLOR)
        # self.root.option_add('*TCombobox*Listbox.selectForeground', FG_COLOR)
        # self.root.option_add('*TCombobox*Listbox.font', FONT_NORMAL)

        # --- Top Bar for Title and User Info ---
        top_bar = ttk.Frame(root, style="TFrame")
        top_bar.pack(fill=tk.X, padx=10, pady=(10, 0))
        title_label = ttk.Label(top_bar, text="Smart Software Deployer", font=("Segoe UI", 16, "bold"))
        title_label.pack(side=tk.LEFT)
        # self.user_label = ttk.Label(top_bar, text="Not logged in", font=("Segoe UI", 12))
        # self.user_label.pack(side=tk.RIGHT)

        self.settings_icon = tk.PhotoImage(file=os.path.join(os.path.dirname(__file__), "assets", "settings_icon.png"))
        settings_btn = ttk.Button(top_bar, image=self.settings_icon, command=self._on_show_settings)
        settings_btn.pack(side=tk.RIGHT, padx=(0, 10))

        self.export_compliance_btn = ttk.Button(top_bar, text="Export Compliance Report", command=self._on_export_compliance_report)
        self.export_compliance_btn.pack(side=tk.RIGHT, padx=(0, 10))

        broadcast_btn = ttk.Button(top_bar, text="Broadcast Message...", command=self._on_broadcast_message)
        broadcast_btn.pack(side=tk.RIGHT, padx=(0, 10))
        
        self.user_label = ttk.Label(top_bar, text="Not logged in", font=("Segoe UI", 12))
        self.user_label.pack(side=tk.RIGHT, padx=(0, 5))

        # --- Main Layout ---
        # Create a Notebook (tabbed interface)
        notebook = ttk.Notebook(root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # --- Dashboard Tab ---
        dashboard_tab = ttk.Frame(notebook)
        notebook.add(dashboard_tab, text="Dashboard")
        self._create_dashboard_tab_widgets(dashboard_tab)

        # --- Node Management Tab ---
        management_tab = ttk.Frame(notebook)
        notebook.add(management_tab, text="Node Management")

        catalog_tab = ttk.Frame(notebook)
        notebook.add(catalog_tab, text="Software Catalog")
        self._create_catalog_widgets(catalog_tab)

        audit_log_tab = ttk.Frame(notebook)
        notebook.add(audit_log_tab, text="Audit Log")
        self._create_audit_log_widgets(audit_log_tab)

        scripts_tab = ttk.Frame(notebook)
        notebook.add(scripts_tab, text="Scripts")
        self._create_scripts_tab_widgets(scripts_tab)

        policy_tab = ttk.Frame(notebook)
        notebook.add(policy_tab, text="Policy Management")
        self._create_policy_tab_widgets(policy_tab)

        self.notebook = notebook
        notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # ------------------------

        # Your entire old layout now goes inside the "management_tab"
        main_pane = ttk.PanedWindow(management_tab, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True)
        
        left_frame = ttk.Frame(main_pane, width=250)
        self._create_group_widgets(left_frame)
        main_pane.add(left_frame, weight=1)
        
        right_pane = ttk.PanedWindow(main_pane, orient=tk.VERTICAL)
        nodes_frame = ttk.Frame(right_pane)
        self._create_nodes_widgets(nodes_frame)
        right_pane.add(nodes_frame, weight=3)
        
        bottom_notebook = ttk.Notebook(right_pane, height=200)
        logs_frame = ttk.Frame(bottom_notebook)
        self._create_log_widgets(logs_frame)
        history_frame = ttk.Frame(bottom_notebook)
        self._create_history_widgets(history_frame)
        bottom_notebook.add(logs_frame, text="Live Logs")
        bottom_notebook.add(history_frame, text="Deployment History")
        right_pane.add(bottom_notebook, weight=1)

        main_pane.add(right_pane, weight=4)

        # --- Data Storage ---
        self._all_nodes = {}
        self._all_groups = {}
        self._last_inventories = {}
        self._inventory_popups = {}
        self._active_progress_bars = {}
        self._context_menu = None
        self._group_context_menu = None
        self._power_menu = None
        self._group_power_menu = None
        self._screenshot_group_popups = {}  # group_name -> ScreenshotGroupPopup
        self._command_results_popups = []   # list of open CommandResultsPopup
        self._install_batch_popups = {}     # batch_id -> InstallBatchSummaryPopup
        self._pairing_dialog = None

        self.update_group_list()
        self.root.after(200, self._refresh_dashboard_tab)

    def _on_update_agent(self):
        """Handler for the 'Update Slave Agent' context menu item."""
        targets = self._get_selected_nodes()
        if not targets:
            messagebox.showwarning("No Selection", "Please select one or more nodes to update.", parent=self.root)
            return
        
        if messagebox.askyesno("Confirm Agent Update", f"This will update the agent service on {len(targets)} selected node(s), causing them to restart.\n\nAre you sure you want to proceed?", parent=self.root):
            if self.callbacks.get("on_update_agents"):
                self.callbacks["on_update_agents"](targets)

    def _on_show_settings(self):
        """Callback to open the raw config file editor."""
        if self.callbacks.get("on_get_config_file"):
            config_content = self.callbacks["on_get_config_file"]()
            # --- CORRECTION: Provide all required arguments ---
            title = "Master Configuration (config.json)"
            # For the master config, hostname is None
            ConfigEditorDialog(self.root, title, config_content, None, self.callbacks)

    def _on_reconnect(self):
        """Handler for the 'Restart Connection' context menu item."""
        nodes_to_reconnect = self._get_selected_nodes()
        if not nodes_to_reconnect:
            messagebox.showwarning("No Selection", "Please select one or more nodes to reconnect.", parent=self.root)
            return

        if self.callbacks.get("on_reconnect"):
            for hostname in nodes_to_reconnect:
                self.callbacks["on_reconnect"](hostname)

    def show_toast(self, title, message, notification_type="info"):
        """Creates and displays a new toast notification, stacking if necessary."""
        toast = ToastNotification(self.root, title, message, notification_type)
        self.active_toasts.append(toast)

        # Position the toast at the bottom right
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        width, height = 300, 100
        padding = 10
        
        x = screen_width - width - padding
        
        # Stack notifications vertically
        y = screen_height - height - padding - (len(self.active_toasts) - 1) * (height + 5)
        
        toast.set_position(x, y)

        # When the toast is destroyed, remove it from the active list.
        # Toasts are borderless (overrideredirect) and normally self-destroy
        # via their fade-out animation, which never triggers WM_DELETE_WINDOW.
        # Binding to the <Destroy> virtual event instead ensures cleanup runs
        # regardless of how/why the toast window is destroyed.
        def _on_toast_destroyed(event, toast=toast):
            if event.widget is toast and toast in self.active_toasts:
                self.active_toasts.remove(toast)

        toast.bind("<Destroy>", _on_toast_destroyed)
        toast.protocol("WM_DELETE_WINDOW", toast.on_close)

    def _on_verify_catalog(self):
        """Callback for the 'Verify Files' button."""
        if self.callbacks.get("on_verify_catalog_files"):
            self.callbacks["on_verify_catalog_files"]()
    

    def _on_view_log_file(self):
        """Callback for the 'View Full Log' button."""
        if self.callbacks.get("on_view_master_log"):
            self.callbacks["on_view_master_log"]()

    def _update_button_states(self):
        """A single function to control the state of all action buttons."""
        selected_nodes = self._get_selected_nodes()
        selected_group = self._get_selected_group()

        # Define which buttons are for group/node actions vs. node-only actions
        group_and_node_buttons = [self.btn_catalog, self.btn_schedule, self.btn_install, self.btn_disconnect]
        node_only_buttons = [self.btn_inventory, self.btn_add_to_group]

        # Condition: Is an action possible? (Either nodes are selected OR a valid group is selected)
        is_action_possible = selected_nodes or selected_group

        # Enable/disable buttons that work on both groups and nodes
        for btn in group_and_node_buttons:
            btn.config(state="normal" if is_action_possible else "disabled")

        # Handle buttons that ONLY work when individual nodes are selected
        if selected_nodes:
            self.btn_add_to_group.config(state="normal")
            # Inventory is special: it requires the selected node to be online
            first_node_status = self._all_nodes.get(selected_nodes[0], {}).get('status', 'offline')
            self.btn_inventory.config(state="normal" if first_node_status == 'online' else "disabled")
        else:
            # If no nodes are selected, disable the node-only buttons
            for btn in node_only_buttons:
                btn.config(state="disabled")    

    def _on_node_selected(self, event=None):
        """Called when a node is selected; re-evaluates all button states."""
        self._update_button_states()
    


    def _create_scripts_tab_widgets(self, parent):
        """Creates the UI for the Scripts tab: a list of saved scripts plus
        Add/Edit/Delete buttons. Running a script on nodes/groups is done
        from the node/group context menus (Run Script...), not from here."""
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)

        main_frame = ttk.Frame(parent, padding=10)
        main_frame.grid(row=0, column=0, sticky="nsew")
        main_frame.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)

        columns = ("name", "description")
        self.scripts_tree = ttk.Treeview(main_frame, columns=columns, show="headings")
        self.scripts_tree.heading("name", text="Name"); self.scripts_tree.column("name", width=200)
        self.scripts_tree.heading("description", text="Description"); self.scripts_tree.column("description", width=450)
        self.scripts_tree.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=self.scripts_tree.yview)
        self.scripts_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=0, column=1, sticky="ns")

        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(btn_frame, text="Add New...", command=self._on_add_script).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame, text="Edit Selected...", command=self._on_edit_script).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame, text="Delete Selected", command=self._on_delete_script).pack(side=tk.LEFT)

        self._scripts_data = []
        self._refresh_scripts_tree()

    def _refresh_scripts_tree(self):
        for item in self.scripts_tree.get_children():
            self.scripts_tree.delete(item)
        getter = self.callbacks.get("on_get_all_scripts")
        self._scripts_data = getter() if getter else []
        for script in self._scripts_data:
            self.scripts_tree.insert("", "end", iid=str(script["id"]), values=(script.get("name"), script.get("description") or ""))

    def _on_add_script(self):
        dialog = ScriptEditorDialog(self.root)
        result = dialog.show()
        if result:
            cb = self.callbacks.get("on_save_script")
            if cb and cb(result):
                self._refresh_scripts_tree()

    def _on_edit_script(self):
        selected = self.scripts_tree.selection()
        if not selected:
            messagebox.showwarning("No Selection", "Please select a script to edit.", parent=self.root)
            return
        script_id = int(selected[0])
        script = next((s for s in self._scripts_data if s["id"] == script_id), None)
        if not script:
            return
        dialog = ScriptEditorDialog(self.root, script=script)
        result = dialog.show()
        if result:
            result["id"] = script_id
            cb = self.callbacks.get("on_save_script")
            if cb and cb(result):
                self._refresh_scripts_tree()

    def _on_delete_script(self):
        selected = self.scripts_tree.selection()
        if not selected:
            messagebox.showwarning("No Selection", "Please select a script to delete.", parent=self.root)
            return
        script_id = int(selected[0])
        script = next((s for s in self._scripts_data if s["id"] == script_id), None)
        name = script.get("name") if script else str(script_id)
        if messagebox.askyesno("Confirm Deletion", f"Delete saved script '{name}'?", parent=self.root):
            cb = self.callbacks.get("on_delete_script")
            if cb:
                cb(script_id, name)
            self._refresh_scripts_tree()

    def _on_run_command(self, targets):
        """Shared handler for the node and group context menus' 'Run Command...' item."""
        if not targets:
            messagebox.showwarning("No Selection", "No target nodes were found for this action.", parent=self.root)
            return
        dialog = StyledInputDialog(self.root, title="Run Command",
                                    prompt=f"Enter a command to run on {len(targets)} node(s):")
        command = dialog.show()
        if command and command.strip():
            cb = self.callbacks.get("on_run_command_on_nodes")
            if cb:
                cb(targets, command.strip())

    def _on_run_script(self, targets):
        """Shared handler for the node and group context menus' 'Run Script...'
        item. The actual saved-script/file picker lives on the controller side
        (on_run_script_file), mirroring how on_send_file_hosts drives its own
        file-selection dialog."""
        if not targets:
            messagebox.showwarning("No Selection", "No target nodes were found for this action.", parent=self.root)
            return
        cb = self.callbacks.get("on_run_script_file")
        if cb:
            cb(targets)

    def _create_policy_tab_widgets(self, parent):
        """Creates the UI for the Policy Management tab: a policy list (left),
        its rules (right), and compliance-engine controls (bottom)."""
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(0, weight=1)

        # --- Left: Policies list ---
        left_frame = ttk.Frame(parent, padding=10)
        left_frame.grid(row=0, column=0, sticky="nsew")
        left_frame.rowconfigure(1, weight=1)
        left_frame.columnconfigure(0, weight=1)

        ttk.Label(left_frame, text="Policies", font=FONT_LARGE_BOLD).grid(row=0, column=0, sticky="w", pady=(0, 10))

        self.policy_tree = ttk.Treeview(left_frame, columns=("name", "auto_check"), show="headings", selectmode="browse")
        self.policy_tree.heading("name", text="Policy Name"); self.policy_tree.column("name", width=180)
        self.policy_tree.heading("auto_check", text="Auto-Check"); self.policy_tree.column("auto_check", width=90, anchor="center")
        self.policy_tree.grid(row=1, column=0, sticky="nsew")
        self.policy_tree.bind("<<TreeviewSelect>>", self._on_policy_selected)

        policy_btn_frame = ttk.Frame(left_frame)
        policy_btn_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(policy_btn_frame, text="New Policy...", command=self._on_new_policy).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(policy_btn_frame, text="Rename...", command=self._on_rename_policy).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(policy_btn_frame, text="Delete", command=self._on_delete_policy).pack(side=tk.LEFT, padx=(0, 5))

        self.policy_autocheck_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(policy_btn_frame, text="Auto-Check Enabled", variable=self.policy_autocheck_var,
                        command=self._on_toggle_policy_autocheck).pack(side=tk.LEFT, padx=(15, 0))

        # --- Right: Rules for the selected policy ---
        right_frame = ttk.Frame(parent, padding=10)
        right_frame.grid(row=0, column=1, sticky="nsew")
        right_frame.rowconfigure(1, weight=1)
        right_frame.columnconfigure(0, weight=1)

        ttk.Label(right_frame, text="Rules", font=FONT_LARGE_BOLD).grid(row=0, column=0, sticky="w", pady=(0, 10))

        self.rules_tree = ttk.Treeview(right_frame, columns=("type", "software", "version"), show="headings")
        self.rules_tree.heading("type", text="Rule"); self.rules_tree.column("type", width=120)
        self.rules_tree.heading("software", text="Software"); self.rules_tree.column("software", width=220)
        self.rules_tree.heading("version", text="Version"); self.rules_tree.column("version", width=80, anchor="center")
        self.rules_tree.grid(row=1, column=0, sticky="nsew")

        rules_btn_frame = ttk.Frame(right_frame)
        rules_btn_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(rules_btn_frame, text="Add Rule...", command=self._on_add_rule).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(rules_btn_frame, text="Remove Rule", command=self._on_remove_rule).pack(side=tk.LEFT)

        # --- Bottom: Compliance engine controls ---
        # A plain ttk.Checkbutton is used for the on/off toggle rather than a
        # custom image-based switch widget, which sidesteps the exact
        # "fallback path leaves image attrs unset -> AttributeError on click"
        # bug class entirely.
        bottom_frame = ttk.Frame(parent, padding=10)
        bottom_frame.grid(row=1, column=0, columnspan=2, sticky="ew")

        self.compliance_toggle_var = tk.BooleanVar(value=False)
        self.compliance_toggle_check = ttk.Checkbutton(
            bottom_frame, text="Compliance Engine Enabled", variable=self.compliance_toggle_var,
            command=self._on_toggle_compliance_engine
        )
        self.compliance_toggle_check.pack(side=tk.LEFT)

        ttk.Button(bottom_frame, text="Run Compliance Check Now",
                   command=self._on_run_compliance_check).pack(side=tk.LEFT, padx=(20, 0))

        self._policies_data = []
        self._current_policy_id = None
        self._refresh_policy_tree()

    def _refresh_policy_tree(self):
        for item in self.policy_tree.get_children():
            self.policy_tree.delete(item)
        getter = self.callbacks.get("on_get_policies")
        self._policies_data = getter() if getter else []
        for policy in self._policies_data:
            auto_check = "Yes" if policy.get("auto_check_enabled") else "No"
            self.policy_tree.insert("", "end", iid=str(policy["id"]), values=(policy.get("name"), auto_check))

    def _get_selected_policy_id(self):
        selected = self.policy_tree.selection()
        return int(selected[0]) if selected else None

    def _on_policy_selected(self, event=None):
        policy_id = self._get_selected_policy_id()
        self._current_policy_id = policy_id
        if policy_id is None:
            for item in self.rules_tree.get_children():
                self.rules_tree.delete(item)
            return
        policy = next((p for p in self._policies_data if p["id"] == policy_id), None)
        if policy:
            self.policy_autocheck_var.set(bool(policy.get("auto_check_enabled")))
        self._refresh_rules_tree(policy_id)

    def _refresh_rules_tree(self, policy_id):
        for item in self.rules_tree.get_children():
            self.rules_tree.delete(item)
        if policy_id is None:
            return
        getter = self.callbacks.get("on_get_policy_rules")
        rules = getter(policy_id) if getter else []
        for rule in rules:
            rule_label = "Must Have" if rule.get("rule_type") == "must_have" else "Must Not Have"
            self.rules_tree.insert("", "end", iid=str(rule["id"]),
                                    values=(rule_label, rule.get("software_name"), rule.get("software_version") or ""))

    def _on_new_policy(self):
        dialog = StyledInputDialog(self.root, title="New Policy", prompt="Enter a name for the new policy:")
        name = dialog.show()
        if name and name.strip():
            cb = self.callbacks.get("on_create_policy")
            if cb:
                cb(name.strip())
                self._refresh_policy_tree()

    def _on_rename_policy(self):
        policy_id = self._get_selected_policy_id()
        if policy_id is None:
            messagebox.showwarning("No Selection", "Please select a policy to rename.", parent=self.root)
            return
        policy = next((p for p in self._policies_data if p["id"] == policy_id), None)
        dialog = StyledInputDialog(self.root, title="Rename Policy", prompt="Enter a new name:",
                                    initialvalue=policy.get("name", "") if policy else "")
        new_name = dialog.show()
        if new_name and new_name.strip():
            cb = self.callbacks.get("on_rename_policy")
            if cb:
                cb(policy_id, new_name.strip())
                self._refresh_policy_tree()

    def _on_delete_policy(self):
        policy_id = self._get_selected_policy_id()
        if policy_id is None:
            messagebox.showwarning("No Selection", "Please select a policy to delete.", parent=self.root)
            return
        policy = next((p for p in self._policies_data if p["id"] == policy_id), None)
        name = policy.get("name") if policy else str(policy_id)
        if messagebox.askyesno("Confirm Deletion",
                                f"Delete policy '{name}'? This also removes its rules and any group assignments.",
                                parent=self.root):
            cb = self.callbacks.get("on_delete_policy")
            if cb:
                cb(policy_id)
            self._refresh_policy_tree()
            self._on_policy_selected()
            self.update_group_list()

    def _on_toggle_policy_autocheck(self):
        policy_id = self._get_selected_policy_id()
        if policy_id is None:
            return
        cb = self.callbacks.get("on_set_policy_auto_check")
        if cb:
            cb(policy_id, self.policy_autocheck_var.get())
            self._refresh_policy_tree()

    def _on_add_rule(self):
        policy_id = self._get_selected_policy_id()
        if policy_id is None:
            messagebox.showwarning("No Selection", "Please select a policy first.", parent=self.root)
            return
        catalog_getter = self.callbacks.get("on_get_catalog_data")
        catalog_data = catalog_getter() if catalog_getter else []
        dialog = AddRuleDialog(self.root, catalog_data)
        result = dialog.show()
        if result:
            cb = self.callbacks.get("on_add_rule_to_policy")
            if cb:
                cb(policy_id, result)
                self._refresh_rules_tree(policy_id)

    def _on_remove_rule(self):
        selected = self.rules_tree.selection()
        if not selected:
            messagebox.showwarning("No Selection", "Please select a rule to remove.", parent=self.root)
            return
        rule_id = int(selected[0])
        if messagebox.askyesno("Confirm", "Remove this rule?", parent=self.root):
            cb = self.callbacks.get("on_remove_rule")
            if cb:
                cb(rule_id)
            self._refresh_rules_tree(self._current_policy_id)

    def _on_toggle_compliance_engine(self):
        cb = self.callbacks.get("on_set_compliance_state")
        if cb:
            cb(self.compliance_toggle_var.get())

    def _on_run_compliance_check(self):
        cb = self.callbacks.get("on_run_compliance_check")
        if cb:
            cb()
            self.append_log("Manual compliance check triggered.")

    def set_compliance_toggle_state(self, enabled):
        """Called by the controller (on startup, and whenever it needs to sync)
        to reflect the persisted compliance-engine setting in the toggle."""
        if hasattr(self, "compliance_toggle_var"):
            self.compliance_toggle_var.set(bool(enabled))

    def show_compliance_report(self, report_data):
        """Opens the compliance report popup with rows cross-referencing every
        group's assigned policy against the latest inventory."""
        ComplianceReportPopup(self.root, report_data, save_callback=self.callbacks.get("on_save_csv"))

    def _on_assign_policy_to_group(self, group_name):
        getter = self.callbacks.get("on_get_policies")
        policies = getter() if getter else []
        if not policies:
            messagebox.showinfo("No Policies", "No policies have been created yet.", parent=self.root)
            return
        dialog = AssignPolicyDialog(self.root, policies)
        policy_id = dialog.show()
        if policy_id is not None:
            cb = self.callbacks.get("on_assign_policy_to_group")
            if cb:
                cb(group_name, policy_id)
                self.update_group_list()

    def _on_remove_policy_from_group(self, group_name):
        if messagebox.askyesno("Confirm", f"Remove the policy assignment from '{group_name}'?", parent=self.root):
            cb = self.callbacks.get("on_remove_policy_from_group")
            if cb:
                cb(group_name)
                self.update_group_list()

    def _create_audit_log_widgets(self, parent):
        """Creates the UI for the Audit Log tab."""
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        # --- NEW: Header with search controls ---
        header_frame = ttk.Frame(parent, padding=(10, 10, 10, 0))
        header_frame.grid(row=0, column=0, sticky="ew")

        search_entry = ttk.Entry(header_frame, textvariable=self.audit_search_var)
        search_entry.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 5))
        search_entry.bind("<Return>", lambda event: self._refresh_audit_log())

        ttk.Button(header_frame, text="Search", command=self._refresh_audit_log).pack(side=tk.LEFT)
        # --- End of New Section ---

        # Treeview to display the log
        tree_frame = ttk.Frame(parent, padding=(10, 0, 10, 10))
        tree_frame.grid(row=1, column=0, sticky="nsew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        columns = ("time", "user", "action", "target", "detail")
        self.audit_tree = ttk.Treeview(tree_frame, columns=columns, show="headings")
        self.audit_tree.grid(row=0, column=0, sticky="nsew")

        self.audit_tree.heading("time", text="Time"); self.audit_tree.column("time", width=160, anchor="center")
        self.audit_tree.heading("user", text="User"); self.audit_tree.column("user", width=100, anchor="center")
        self.audit_tree.heading("action", text="Action"); self.audit_tree.column("action", width=150, anchor="center")
        self.audit_tree.heading("target", text="Target"); self.audit_tree.column("target", width=150, anchor="center")
        self.audit_tree.heading("detail", text="Details"); self.audit_tree.column("detail", width=300, anchor="center")

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.audit_tree.yview)
        self.audit_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=0, column=1, sticky="ns")

        self.root.after(500, self._refresh_audit_log)


    def _refresh_audit_log(self):
        """Fetches new data from the controller and populates the audit log, applying any search filter."""
        if not self.callbacks.get("on_get_audit_log"): return

        for item in self.audit_tree.get_children():
            self.audit_tree.delete(item)

        # Get the search term from the StringVar
        search_term = self.audit_search_var.get().strip()
        
        # Pass the search term to the controller callback
        log_data = self.callbacks["on_get_audit_log"](search_term=search_term)
        
        for entry in log_data:
            ts = entry['timestamp']
            try: # Prettier timestamp formatting
                date_part = ts.split('T')[0]
                time_part = ts.split('T')[1].split('.')[0]
                ts = f"{date_part} {time_part}"
            except IndexError: pass

            self.audit_tree.insert("", "end", values=(
                ts, entry.get("user"), entry.get("action"), 
                entry.get("target"), entry.get("detail")
            ))

    def _on_set_alias(self):
        """Handles the 'Set Alias' right-click action."""
        selected_nodes = self._get_selected_nodes()
        if not selected_nodes: return
        
        hostname = selected_nodes[0]
        # Get the alias from the cache, which might be None
        current_alias = self._all_nodes.get(hostname, {}).get('alias')

        # Use the new styled dialog
        dialog = StyledInputDialog(
            self.root,
            title="Set Slave Alias",
            prompt=f"Enter a friendly name (alias) for '{hostname}':\n(Leave blank to remove the alias)",
            # --- THIS IS THE FIX: Ensure initialvalue is always a string ---
            initialvalue=(current_alias or "")
        )
        new_alias = dialog.show()

        if new_alias is not None: # Check for cancel, but allow empty strings
            if self.callbacks.get("on_set_slave_alias"):
                self.callbacks["on_set_slave_alias"](hostname, new_alias.strip())
                self._update_node_list()    

    def _on_rename_group(self):
        """Handles the 'Rename Group' right-click action."""
        selected_group = self._get_selected_group()
        if not selected_group or selected_group == "All Nodes":
            return

        # Use the new styled dialog instead of simpledialog
        dialog = StyledInputDialog(
            self.root,
            title="Rename Group",
            prompt=f"Enter a new name for '{selected_group}':",
            initialvalue=selected_group
        )
        new_name = dialog.show()

        if new_name is None:
            return # User cancelled

        new_name = new_name.strip()
        if not new_name:
            messagebox.showwarning("Input Required", "Group name cannot be empty.", parent=self.root)
            return

        if new_name == selected_group:
            return # Name is unchanged

        if new_name in self._all_groups:
            messagebox.showerror("Error", f"A group named '{new_name}' already exists.", parent=self.root)
            return

        if self.callbacks.get("on_rename_group"):
            self.callbacks["on_rename_group"](selected_group, new_name)
            if selected_group in self._all_groups:
                self._all_groups[new_name] = self._all_groups.pop(selected_group)
            self.update_group_list()
            try:
                self.group_tree.selection_set(new_name)
            except tk.TclError:
                pass
   

    def show_slave_log_popup(self, hostname, log_content):
        """Creates and displays the slave log popup window."""
        SlaveLogPopup(self.root, hostname, log_content) 

    def show_config_editor(self, title, content, hostname=None):
        """Displays the config editor for viewing and editing."""
        ConfigEditorDialog(self.root, title, content, hostname, self.callbacks)

    # --- Screenshot Capture ---
    def show_screenshot(self, hostname, image_b64_data):
        """Displays a single host's screenshot in its own popup window."""
        ScreenshotPopup(self.root, hostname, image_b64_data)

    def open_group_screenshot_popup(self, group_name, hostnames):
        """Opens (or refreshes/re-uses) the tabbed screenshot window for a group,
        pre-creating a 'waiting' tab for each host so the admin sees progress
        as replies trickle in."""
        popup = self._screenshot_group_popups.get(group_name)
        if popup is None or not popup.winfo_exists():
            popup = ScreenshotGroupPopup(self.root, group_name, hostnames)
            self._screenshot_group_popups[group_name] = popup
        else:
            popup.reset_for_hosts(hostnames)
            popup.lift()
        return popup

    def update_group_screenshot(self, group_name, hostname, image_b64_data):
        """Feeds one host's screenshot into its group's tabbed window, falling
        back to a standalone popup if that window was closed in the meantime."""
        popup = self._screenshot_group_popups.get(group_name)
        if popup and popup.winfo_exists():
            popup.add_or_update_host(hostname, image_b64_data)
        else:
            self.show_screenshot(hostname, image_b64_data)

    # --- Remote Command / Script Execution ---
    def open_command_results_popup(self, hostnames, label):
        """Opens a new tabbed results window for a run_command/run_script_file
        batch, with one tab per target hostname."""
        popup = CommandResultsPopup(self.root, hostnames, label)
        self._command_results_popups.append(popup)
        return popup

    def append_command_output(self, hostname, command, data):
        """Routes an incoming 'command_output' status to whichever open
        CommandResultsPopup covers this hostname; logs it if none is open."""
        delivered = False
        for popup in list(self._command_results_popups):
            if not popup.winfo_exists():
                self._command_results_popups.remove(popup)
                continue
            if hostname in popup.hostnames:
                popup.append_output(hostname, data)
                delivered = True

        if not delivered:
            stdout = (data.get("stdout") or "").strip()
            stderr = (data.get("stderr") or "").strip()
            summary = " | ".join(filter(None, [stdout, stderr]))
            self.append_log(f"[{hostname}] command output (rc={data.get('returncode')}): {summary}")

    # --- Multi-App Install Batch Summary ---
    def open_install_batch_popup(self, batch_id, items):
        """Opens a summary popup listing every (app, host) pair in a
        multi-app install batch, each starting out 'Queued'."""
        popup = InstallBatchSummaryPopup(self.root, items)
        self._install_batch_popups[batch_id] = popup
        return popup

    def update_install_batch_item(self, batch_id, hostname, friendly_name, status):
        """Updates one row's status in the batch's popup, if it's still open."""
        popup = self._install_batch_popups.get(batch_id)
        if popup and popup.winfo_exists():
            popup.update_item(hostname, friendly_name, status)
        elif popup is not None and not popup.winfo_exists():
            del self._install_batch_popups[batch_id]

    def _on_send_file(self):
        selected_nodes = self._get_selected_nodes()
        if not selected_nodes:
            messagebox.showwarning("No Selection", "Please select one or more slaves to send the file to.", parent=self.root)
            return
        
        if self.callbacks.get("on_send_file_hosts"):
            self.callbacks["on_send_file_hosts"](selected_nodes)    

    def _refresh_catalog_tree(self):
        """Clears and re-populates the catalog tree from the controller."""
        for item in self.catalog_tree.get_children():
            self.catalog_tree.delete(item)
        
        self._catalog_data = self.callbacks.get("on_get_catalog_data")()
        for i, entry in enumerate(self._catalog_data):
            # --- MODIFIED: Add the new fields to the values tuple ---
            self.catalog_tree.insert("", "end", iid=i, values=(
                entry.get("name"),
                entry.get("version"),
                entry.get("filename"),
                entry.get("silent_flags"),
                entry.get("post_install_cmd"),
                entry.get("required_os"),
                entry.get("required_arch"),
                entry.get("pre_install_kill"),      # <-- NEW
                entry.get("post_install_kill"),     # <-- NEW
                entry.get("pre_uninstall_kill"),
                entry.get("install_context")

            ))

    def _on_add_catalog_entry(self):
        """Opens the dialog to add a new catalog entry."""
        dialog = CatalogEditorDialog(self.root)
        new_entry = dialog.show()
        
        if new_entry:
            self._catalog_data.append(new_entry)
            if self.callbacks.get("on_save_catalog_data")(self._catalog_data):
                self._refresh_catalog_tree()

    def _on_edit_catalog_entry(self):
        """Opens the dialog to edit the selected catalog entry."""
        selected = self.catalog_tree.selection()
        if not selected:
            messagebox.showwarning("No Selection", "Please select an entry to edit.", parent=self.root)
            return

        index = int(selected[0])
        entry_to_edit = self._catalog_data[index]

        dialog = CatalogEditorDialog(self.root, entry=entry_to_edit)
        updated_entry = dialog.show()
        
        if updated_entry:
            self._catalog_data[index] = updated_entry
            if self.callbacks.get("on_save_catalog_data")(self._catalog_data):
                self._refresh_catalog_tree()
        #--------------------------------------------------------------------------------  
        # 
    def _create_catalog_widgets(self, parent):
        """Creates the UI for the Software Catalog tab."""
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)

        main_frame = ttk.Frame(parent, padding=10)
        main_frame.grid(row=0, column=0, sticky="nsew")
        main_frame.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)

        # --- MODIFIED: Add new column keys ---
        columns = (
            "name", "version", "filename", "silent", "post", 
            "req_os", "req_arch", "pre_install", "post_install", "pre_uninstall",
            "context" # <-- ADD THIS LINE
        )
        self.catalog_tree = ttk.Treeview(main_frame, columns=columns, show="headings")
        self.catalog_tree.grid(row=0, column=0, sticky="nsew")

        # Define headings and column properties
        self.catalog_tree.heading("name", text="Name"); self.catalog_tree.column("name", width=150)
        self.catalog_tree.heading("version", text="Version"); self.catalog_tree.column("version", width=60)
        self.catalog_tree.heading("filename", text="Filename"); self.catalog_tree.column("filename", width=150)
        self.catalog_tree.heading("silent", text="Silent Flags"); self.catalog_tree.column("silent", width=120)
        self.catalog_tree.heading("post", text="Post-Install Cmd"); self.catalog_tree.column("post", width=120)
        self.catalog_tree.heading("req_os", text="Required OS"); self.catalog_tree.column("req_os", width=80)
        self.catalog_tree.heading("req_arch", text="Required Arch"); self.catalog_tree.column("req_arch", width=80)

        self.catalog_tree.heading("pre_install", text="Pre-Kill"); self.catalog_tree.column("pre_install", width=100)
        self.catalog_tree.heading("post_install", text="Post-Kill"); self.catalog_tree.column("post_install", width=100)
        self.catalog_tree.heading("pre_uninstall", text="Uninstall-Kill"); self.catalog_tree.column("pre_uninstall", width=100)
        self.catalog_tree.heading("context", text="Context"); self.catalog_tree.column("context", width=80)
        

        # Center align the column text
        for col in columns:
            self.catalog_tree.column(col, anchor="center")

        # Add a scrollbar
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=self.catalog_tree.yview)
        self.catalog_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=0, column=1, sticky="ns")

        # Button frame
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(btn_frame, text="Add New...", command=self._on_add_catalog_entry).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame, text="Edit Selected...", command=self._on_edit_catalog_entry).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame, text="Delete Selected", command=self._on_delete_catalog_entry).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="Verify Files", command=self._on_verify_catalog).pack(side=tk.RIGHT)

        self._refresh_catalog_tree()

    def _on_delete_catalog_entry(self):
        """Deletes the selected entry from the catalog."""
        selected = self.catalog_tree.selection()
        if not selected:
            messagebox.showwarning("No Selection", "Please select an entry to delete.", parent=self.root)
            return
            
        index = int(selected[0])
        entry_to_delete = self._catalog_data[index]
        
        if messagebox.askyesno("Confirm Deletion", f"Are you sure you want to delete the entry for '{entry_to_delete.get('name')}'?", parent=self.root):
            self._catalog_data.pop(index)
            if self.callbacks.get("on_save_catalog_data")(self._catalog_data):
                self._refresh_catalog_tree()    

    def _on_remove_from_group(self):
        nodes = self._get_selected_nodes()
        if not nodes:
            messagebox.showwarning("No Selection", "Please select one or more nodes to remove.", parent=self.root)
            return
        
        # Use the groups of the first selected node as the list of choices
        hostname_example = nodes[0]
        node_groups = self._all_nodes.get(hostname_example, {}).get('groups', [])
        
        if not node_groups:
            messagebox.showinfo("Not in Group", f"'{hostname_example}' is not in any groups.", parent=self.root)
            return
            
        dialog = RemoveFromGroupDialog(self.root, node_groups)
        group_to_remove = dialog.show()

        if group_to_remove:
            if self.callbacks.get("on_remove_from_group"):
                for hostname in nodes:
                    # Check if the node is actually in the group before trying to remove
                    if group_to_remove in self._all_nodes.get(hostname, {}).get('groups', []):
                        self.callbacks["on_remove_from_group"](hostname, group_to_remove)    

    def _get_targets(self):
        """
        Determines the target nodes for an action, now correctly handling 'All Nodes'.
        """
        targets = self._get_selected_nodes()
        
        if not targets:
            group = self._get_selected_group()
            if group == "All Nodes":
                # If 'All Nodes' is selected, get all known hostnames from the cache
                targets = list(self._all_nodes.keys())
            elif group:
                # For any other group, get its members
                targets = list(self._all_groups.get(group, []))
        
        return targets    

    def _on_bulk_uninstall_group(self, group_name):
        """Gathers software from a group and shows a dialog to select or enter one for uninstallation."""
        group_members = self._all_groups.get(group_name, [])
        if not group_members:
            messagebox.showinfo("Empty Group", f"The group '{group_name}' is empty.", parent=self.root)
            return

        # Aggregate all software from all nodes in the group (can result in an empty list)
        all_software = Counter()
        for hostname in group_members:
            inventory = self.get_last_inventory(hostname)
            if inventory and 'installed_software' in inventory:
                software_list = inventory['installed_software']
                if isinstance(software_list, list):
                    for app in software_list:
                        if isinstance(app, dict) and app.get("name"):
                            all_software[app.get("name")] += 1
        
        software_data = [{"name": name, "count": count} for name, count in all_software.items()]

        # Show the new dialog, which now works even if software_data is empty
        dialog = BulkUninstallDialog(self.root, software_data, group_name, len(group_members))
        software_name = dialog.show()

        # Proceed if a software name was selected or entered
        if software_name:
            if messagebox.askyesno("Confirm Bulk Uninstall",
                                   f"Are you sure you want to attempt to uninstall '{software_name}' from all nodes in the '{group_name}' group?",
                                   parent=self.root):
                if self.callbacks.get("on_bulk_uninstall"):
                    self.callbacks["on_bulk_uninstall"](group_name, software_name)


    def _on_schedule_install(self):
        """Handles the 'Schedule Install' button click."""
        targets = self._get_targets()
        if not targets: 
            messagebox.showwarning("No Selection", "Please select a node or a group to schedule a task for.", parent=self.root)
            return
        
        if self.callbacks.get("on_schedule_install"):
            self.callbacks["on_schedule_install"](targets)    

    def _show_group_context_menu(self, event):
        iid = self.group_tree.identify_row(event.y)
        if iid:
            self.group_tree.selection_set(iid)
            group_name = iid

            # The old check that disabled the menu is now gone.

            # Reuse a single cached Menu (and its submenus) across invocations
            # instead of building a brand new tk.Menu tree on every right
            # click, which would otherwise leak Menu widgets for the life of
            # the process.
            if self._group_context_menu is None:
                self._group_context_menu = tk.Menu(self.root, tearoff=0, bg=LIST_BG, fg=FG_COLOR,
                                       activebackground=ACCENT_COLOR, activeforeground=FG_COLOR,
                                       relief='flat', borderwidth=0)

            context_menu = self._group_context_menu

            # Clear out entries left over from the previous invocation before rebuilding.
            context_menu.delete(0, "end")

            context_menu.add_command(label=f"Rename '{group_name}'...", command=self._on_rename_group)
            context_menu.add_separator(background=HEADER_BG)

            context_menu.add_command(label=f"Send File to '{group_name}'...",
                                     command=lambda: self.callbacks.get("on_send_file_group")(group_name))
            context_menu.add_command(label=f"Send & Extract ZIP to '{group_name}'...",
                         command=lambda gn=group_name: self._on_send_and_extract_zip(group_name=gn))
            context_menu.add_command(label=f"Bulk Install to '{group_name}'...", command=lambda: self.callbacks.get("on_bulk_install_group")(group_name))
            context_menu.add_command(label=f"Bulk Uninstall from '{group_name}'...", command=lambda: self._on_bulk_uninstall_group(group_name))

            # --- NEW: Disable irrelevant options for "All Nodes" ---
            if group_name == "All Nodes":
                context_menu.entryconfig("Rename 'All Nodes'...", state="disabled")
                context_menu.entryconfig("Send & Extract ZIP to 'All Nodes'...", state="disabled")

            context_menu.add_separator(background=HEADER_BG)

            context_menu.add_command(
                label=f"Update All Agents in '{group_name}'...",
                command=lambda: self.callbacks.get("on_update_agents_group")(group_name)
            )

            context_menu.add_command(label=f"Request Screenshots from '{group_name}'",
                                      command=lambda: self._on_request_group_screenshots(group_name))
            context_menu.add_command(label=f"Run Command on '{group_name}'...",
                                      command=lambda: self._on_run_command(self._resolve_group_hostnames(group_name)))
            context_menu.add_command(label=f"Run Script on '{group_name}'...",
                                      command=lambda: self._on_run_script(self._resolve_group_hostnames(group_name)))

            context_menu.add_separator(background=HEADER_BG)

            # --- Power submenu (cached, cleared and repopulated each invocation) ---
            if self._group_power_menu is None:
                self._group_power_menu = tk.Menu(self.root, tearoff=0, bg=LIST_BG, fg=FG_COLOR,
                                       activebackground=ACCENT_COLOR, activeforeground=FG_COLOR,
                                       relief='flat', borderwidth=0)
            power_menu = self._group_power_menu
            power_menu.delete(0, "end")
            power_menu.add_command(label="Shutdown", command=lambda: self._on_power_action("on_system_shutdown", self._resolve_group_hostnames(group_name)))
            power_menu.add_command(label="Restart", command=lambda: self._on_power_action("on_system_restart", self._resolve_group_hostnames(group_name)))
            power_menu.add_command(label="Sleep", command=lambda: self._on_power_action("on_system_sleep", self._resolve_group_hostnames(group_name)))
            context_menu.add_cascade(label="Power", menu=power_menu)

            context_menu.add_separator(background=HEADER_BG)
            context_menu.add_command(label=f"Assign Policy to '{group_name}'...",
                                      command=lambda: self._on_assign_policy_to_group(group_name))
            context_menu.add_command(label=f"Remove Policy from '{group_name}'...",
                                      command=lambda: self._on_remove_policy_from_group(group_name))

            context_menu.post(event.x_root, event.y_root)

    def _resolve_group_hostnames(self, group_name):
        """Resolves a group name (including the special 'All Nodes' case) into
        a list of hostnames via the controller, for menu actions that fan out
        to every member of a group."""
        getter = self.callbacks.get("on_get_hostnames_for_group")
        return getter(group_name) if getter else []

    def _on_broadcast_message(self):
        """Opens a modal dialog to compose a message broadcast to ALL connected slaves."""
        dialog = BroadcastMessageDialog(self.root)
        message_text = dialog.show()
        if message_text and message_text.strip():
            cb = self.callbacks.get("on_broadcast_message")
            if cb:
                cb(message_text.strip())

    def _on_export_compliance_report(self):
        """Top-bar 'Export Compliance Report' button: asks the controller to
        build the report, which then opens ComplianceReportPopup (the popup's
        own 'Export to CSV' button drives the actual file save)."""
        cb = self.callbacks.get("on_export_compliance")
        if cb:
            cb()

    def _on_request_screenshot(self, hostname):
        """Handler for the node context menu's 'Request Screenshot' item."""
        if not hostname:
            return
        if self._all_nodes.get(hostname, {}).get('status') != 'online':
            messagebox.showwarning("Offline", f"'{hostname}' is offline.", parent=self.root)
            return
        cb = self.callbacks.get("on_request_screenshot")
        if cb:
            cb(hostname)

    def _on_request_group_screenshots(self, group_name):
        """Handler for the group context menu's 'Request Screenshots from Group' item."""
        cb = self.callbacks.get("on_request_group_screenshots")
        if cb:
            cb(group_name)

    def _on_power_action(self, callback_name, targets):
        """Shared handler for Power submenu entries (Shutdown/Restart/Sleep),
        used by both the node and group context menus."""
        if not targets:
            messagebox.showwarning("No Selection", "No target nodes were found for this action.", parent=self.root)
            return
        cb = self.callbacks.get(callback_name)
        if cb:
            cb(targets)

    # Inside class MainGUI:
    def _on_send_and_extract_zip(self, nodes=None, group_name=None):
        """Handles the 'Send & Extract ZIP' action for nodes or groups."""
        targets = []
        target_info = ""
        if nodes:
            targets = nodes
            target_info = f"{len(targets)} selected node(s)"
        elif group_name:
            # Need to get hostnames from the controller for the group
            if self.callbacks.get("on_get_hostnames_for_group"):
                targets = self.callbacks["on_get_hostnames_for_group"](group_name)
                target_info = f"group '{group_name}' ({len(targets)} nodes)"
            else:
                messagebox.showerror("Error", "Cannot resolve group members.", parent=self.root)
                return
        else:
            messagebox.showwarning("Error", "No target specified for ZIP deployment.", parent=self.root)
            return

        if not targets:
            messagebox.showinfo("No Targets", f"No nodes found for {target_info}.", parent=self.root)
            return

        # Ask user to select ONLY a ZIP file
        filepath = filedialog.askopenfilename(
            title=f"Select ZIP Archive to Send & Extract on {target_info}",
            filetypes=[("ZIP Archives", "*.zip"), ("All files", "*.*")], # Prioritize ZIP
            parent=self.root
        )

        if not filepath:
            return # User cancelled

        if not filepath.lower().endswith(".zip"):
            messagebox.showerror("Invalid File", "Please select a valid .ZIP archive file.", parent=self.root)
            return

        # Call the new controller callback
        if self.callbacks.get("on_send_and_extract_zip"):
            self.callbacks["on_send_and_extract_zip"](targets, filepath)

    def _create_group_widgets(self, parent):
        group_label = ttk.Label(parent, text="Groups", font=FONT_LARGE_BOLD)
        group_label.pack(pady=10, padx=10, anchor='w')
        self.group_tree = ttk.Treeview(parent, show="tree", selectmode="browse")
        self.group_tree.pack(fill=tk.BOTH, expand=True, padx=10)
        self.group_tree.tag_configure('group', font=FONT_BOLD)
        self.group_tree.bind("<<TreeviewSelect>>", self._on_group_selected)
        self.group_tree.bind("<Button-3>", self._show_group_context_menu)
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        add_btn = ttk.Button(btn_frame, text="New Group", command=self._on_new_group)
        add_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 5))
        del_btn = ttk.Button(btn_frame, text="Delete Group", command=self._on_delete_group)
        del_btn.pack(side=tk.LEFT, expand=True, fill=tk.X)

    def _create_nodes_widgets(self, parent):
        self.nodes_label = ttk.Label(parent, text="All Nodes", font=FONT_LARGE_BOLD)
        self.nodes_label.pack(side=tk.TOP, pady=10, padx=10, anchor='w')
        
        header_frame = ttk.Frame(parent)
        header_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(0, 10))
        self._create_dashboard(header_frame)
        ttk.Button(header_frame, text="Refresh All", command=self._update_node_list).pack(side=tk.RIGHT)

        search_frame = ttk.Frame(parent)
        search_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(0, 10))
        search_icon = ttk.Label(search_frame, text="🔍", font=("Segoe UI", 12))
        search_icon.pack(side=tk.LEFT, padx=(0, 5))
        self.search_var.trace_add("write", lambda *args: self._update_node_list())
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var, font=FONT_NORMAL, style="TEntry")
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        action_frame = ttk.Frame(parent)
        action_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=10)
        left_button_frame = ttk.Frame(action_frame)
        left_button_frame.pack(side=tk.LEFT)
        right_button_frame = ttk.Frame(action_frame)
        right_button_frame.pack(side=tk.RIGHT)

        # --- CORRECT ORDER: 1. Create the Treeview widget first ---
        self.nodes_tree = ttk.Treeview(parent, columns=("hostname", "status", "ip", "groups", "last_command", "last_result", "last_seen", "remarks"), show="tree headings")

        # --- 2. Configure all its properties (columns, headings, bindings) ---
        self.nodes_tree.column("#0", width=30, stretch=tk.NO, anchor='center')
        self.nodes_tree.heading("#0", text="")
        self.nodes_tree.heading("hostname", text="Slave ID / Hostname", anchor='center'); self.nodes_tree.column("hostname", width=150, anchor='center')
        self.nodes_tree.heading("status", text="Status", anchor='center'); self.nodes_tree.column("status", width=100, anchor='center') 
        self.nodes_tree.heading("ip", text="IP Address", anchor='center'); self.nodes_tree.column("ip", width=120, anchor='center')
        self.nodes_tree.heading("groups", text="Groups", anchor='center'); self.nodes_tree.column("groups", width=150, anchor='center')
        self.nodes_tree.heading("last_command", text="Last Command", anchor='center'); self.nodes_tree.column("last_command", width=150, anchor='center')
        self.nodes_tree.heading("last_result", text="Last Result", anchor='center'); self.nodes_tree.column("last_result", width=120, anchor='center')
        self.nodes_tree.heading("last_seen", text="Last Seen", anchor='center'); self.nodes_tree.column("last_seen", width=150, anchor='center')
        self.nodes_tree.heading("remarks", text="Remarks", anchor='center'); self.nodes_tree.column("remarks", width=250, anchor='center')
        
        self.nodes_tree.bind("<Button-3>", self._show_context_menu)
        self.nodes_tree.bind("<<TreeviewSelect>>", self._on_node_selected)
        
        # --- 3. Place the fully configured Treeview on the screen ---
        self.nodes_tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        # --- 4. Create and pack the action buttons ---
        self.btn_inventory = ttk.Button(left_button_frame, text="Inventory", command=self._on_inventory)
        self.btn_inventory.pack(side=tk.LEFT, padx=(0, 5))
        self.btn_catalog = ttk.Button(left_button_frame, text="Install from Catalog", command=self._on_install_from_catalog)
        self.btn_catalog.pack(side=tk.LEFT, padx=(0, 5))
        self.btn_schedule = ttk.Button(left_button_frame, text="Schedule Install...", command=self._on_schedule_install)
        self.btn_schedule.pack(side=tk.LEFT, padx=(0, 5))
        self.btn_install = ttk.Button(left_button_frame, text="Install from Folder", command=self._on_install_from_folder)
        self.btn_install.pack(side=tk.LEFT, padx=(0, 5))
        self.btn_add_to_group = ttk.Button(left_button_frame, text="Add to Group", command=self._on_add_to_group)
        self.btn_add_to_group.pack(side=tk.LEFT, padx=(0, 5))
        self.btn_pair = ttk.Button(right_button_frame, text="Pair New Slaves...", command=self._on_pair_slaves)
        self.btn_pair.pack(side=tk.LEFT, padx=(0, 5))
        self.btn_disconnect = ttk.Button(right_button_frame, text="Disconnect", command=self._on_disconnect)
        self.btn_disconnect.pack(side=tk.LEFT)

        # --- 5. Set the initial state of the buttons ---
        self._on_node_selected()
    
    # --- Dashboard tab (KPI tiles + deployment outcomes bar) ---
    # Status colors: green/red match this app's existing online/offline
    # convention (mini-strip below); amber is new, used only for "Skipped".
    _DASH_GOOD = "#4CAF50"
    _DASH_CRITICAL = "#F44336"
    _DASH_WARNING = "#fab219"

    def _create_dashboard_tab_widgets(self, parent):
        parent.configure(style="TFrame")

        header = ttk.Frame(parent)
        header.pack(side=tk.TOP, fill=tk.X, padx=20, pady=(20, 10))
        ttk.Label(header, text="Dashboard", font=FONT_LARGE_BOLD).pack(side=tk.LEFT)
        ttk.Button(header, text="Refresh", command=self._refresh_dashboard_tab).pack(side=tk.RIGHT)

        # --- KPI row ---
        kpi_row = ttk.Frame(parent)
        kpi_row.pack(side=tk.TOP, fill=tk.X, padx=20, pady=(0, 20))
        for i in range(4):
            kpi_row.columnconfigure(i, weight=1, uniform="kpi")

        self._dash_total_var = tk.StringVar(value="0")
        self._dash_online_var = tk.StringVar(value="0")
        self._dash_offline_var = tk.StringVar(value="0")
        self._dash_today_var = tk.StringVar(value="0")

        self._make_stat_tile(kpi_row, "TOTAL NODES", self._dash_total_var, FG_COLOR).grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self._make_stat_tile(kpi_row, "ONLINE", self._dash_online_var, self._DASH_GOOD).grid(row=0, column=1, sticky="nsew", padx=8)
        self._make_stat_tile(kpi_row, "OFFLINE", self._dash_offline_var, "#9E9E9E").grid(row=0, column=2, sticky="nsew", padx=8)
        self._make_stat_tile(kpi_row, "DEPLOYMENTS TODAY", self._dash_today_var, ACCENT_COLOR).grid(row=0, column=3, sticky="nsew", padx=(8, 0))

        # --- Deployment outcomes (all-time) ---
        outcomes_card = tk.Frame(parent, bg=LIST_BG)
        outcomes_card.pack(side=tk.TOP, fill=tk.X, padx=20, pady=(0, 20))

        ttk.Label(outcomes_card, text="Deployment Outcomes (All-Time)", font=FONT_BOLD, background=LIST_BG).pack(
            side=tk.TOP, anchor="w", padx=16, pady=(14, 10)
        )

        self._dash_bar_canvas = tk.Canvas(outcomes_card, height=28, bg=LIST_BG, highlightthickness=0)
        self._dash_bar_canvas.pack(side=tk.TOP, fill=tk.X, padx=16, pady=(0, 4))
        self._dash_bar_canvas.bind("<Configure>", lambda e: self._draw_outcome_bar())

        self._dash_empty_label = ttk.Label(outcomes_card, text="No deployments recorded yet.", font=FONT_NORMAL, background=LIST_BG, foreground="#9E9E9E")

        self._dash_legend_frame = tk.Frame(outcomes_card, bg=LIST_BG)
        self._dash_legend_frame.pack(side=tk.TOP, fill=tk.X, padx=16, pady=(4, 14))

        self._dash_outcome_counts = {"Success": 0, "Failed": 0, "Skipped": 0}

    def _make_stat_tile(self, parent, label_text, value_var, accent_color):
        """A small card: muted label on top, large colored value below."""
        card = tk.Frame(parent, bg=LIST_BG, padx=14, pady=12)
        ttk.Label(card, text=label_text, font=("Segoe UI", 9), background=LIST_BG, foreground="#9E9E9E").pack(anchor="w")
        tk.Label(card, textvariable=value_var, font=("Segoe UI", 22, "bold"), bg=LIST_BG, fg=accent_color).pack(anchor="w", pady=(4, 0))
        return card

    def _draw_outcome_bar(self):
        """Redraws the horizontal stacked bar from self._dash_outcome_counts."""
        canvas = getattr(self, "_dash_bar_canvas", None)
        if canvas is None:
            return
        canvas.delete("all")

        counts = self._dash_outcome_counts
        total = sum(counts.values())
        width = canvas.winfo_width()
        height = 24
        if width <= 1:
            return  # not yet laid out

        if total == 0:
            self._dash_empty_label.pack(side=tk.TOP, anchor="w", padx=0, pady=(0, 4))
            return
        self._dash_empty_label.pack_forget()

        segments = [
            ("Success", counts.get("Success", 0), self._DASH_GOOD),
            ("Failed", counts.get("Failed", 0), self._DASH_CRITICAL),
            ("Skipped", counts.get("Skipped", 0), self._DASH_WARNING),
        ]
        segments = [s for s in segments if s[1] > 0]

        gap = 2
        radius = 6
        # Rounded-corner container so the bar reads as one soft, contained
        # shape rather than a hard-edged rectangle.
        self._rounded_rect(canvas, 0, 0, width, height, radius, fill=CANVAS_BG, outline="")

        x = gap
        inner_right = width - gap
        available = inner_right - x - gap * (len(segments) - 1)
        for i, (name, count, color) in enumerate(segments):
            seg_width = available * (count / total)
            x_end = x + seg_width
            canvas.create_rectangle(x, gap, x_end, height - gap, fill=color, outline="")
            x = x_end + gap

        # Legend: colored swatch + label + count, never color alone.
        for widget in self._dash_legend_frame.winfo_children():
            widget.destroy()
        for name, count, color in [
            ("Success", counts.get("Success", 0), self._DASH_GOOD),
            ("Failed", counts.get("Failed", 0), self._DASH_CRITICAL),
            ("Skipped", counts.get("Skipped", 0), self._DASH_WARNING),
        ]:
            item = tk.Frame(self._dash_legend_frame, bg=LIST_BG)
            item.pack(side=tk.LEFT, padx=(0, 20))
            swatch = tk.Canvas(item, width=10, height=10, bg=LIST_BG, highlightthickness=0)
            swatch.create_oval(0, 0, 10, 10, fill=color, outline="")
            swatch.pack(side=tk.LEFT, padx=(0, 6))
            pct = f" ({count / total:.0%})" if total else ""
            ttk.Label(item, text=f"{name}: {count}{pct}", font=FONT_NORMAL, background=LIST_BG).pack(side=tk.LEFT)

    @staticmethod
    def _rounded_rect(canvas, x1, y1, x2, y2, radius, **kwargs):
        points = [
            x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
            x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
            x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1,
        ]
        return canvas.create_polygon(points, smooth=True, **kwargs)

    def _refresh_dashboard_tab(self):
        """Pulls fresh counts and redraws the Dashboard tab. Called on
        startup, when the tab is selected, and via its Refresh button --
        deliberately no background auto-refresh thread/timer."""
        if not hasattr(self, "_dash_total_var"):
            return  # tab not built yet

        total = len(self._all_nodes)
        online = len([n for n in self._all_nodes.values() if n.get('status') == 'online'])
        self._dash_total_var.set(str(total))
        self._dash_online_var.set(str(online))
        self._dash_offline_var.set(str(total - online))

        stats = None
        getter = self.callbacks.get("on_get_dashboard_stats")
        if getter:
            try:
                stats = getter()
            except Exception:
                stats = None

        if stats:
            self._dash_today_var.set(str(stats.get("deployments_today", 0)))
            counts = {"Success": 0, "Failed": 0, "Skipped": 0}
            for row in stats.get("status_summary", []):
                category = row.get("status_category")
                if category in counts:
                    counts[category] = row.get("count", 0)
            self._dash_outcome_counts = counts

        self._draw_outcome_bar()

    def _on_tab_changed(self, event):
        try:
            selected_text = self.notebook.tab(self.notebook.select(), "text")
        except tk.TclError:
            return
        if selected_text == "Dashboard":
            self._refresh_dashboard_tab()

    def _create_dashboard(self, parent):
        self.total_nodes_var = tk.StringVar(value="Total: 0")
        self.online_nodes_var = tk.StringVar(value="Online: 0")
        self.offline_nodes_var = tk.StringVar(value="Offline: 0")

        ttk.Label(parent, textvariable=self.total_nodes_var, font=FONT_BOLD).pack(side=tk.LEFT, padx=10)
        ttk.Label(parent, textvariable=self.online_nodes_var, font=FONT_BOLD, foreground="#4CAF50").pack(side=tk.LEFT, padx=10)
        ttk.Label(parent, textvariable=self.offline_nodes_var, font=FONT_BOLD, foreground="#F44336").pack(side=tk.LEFT, padx=10)

    def _create_log_widgets(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1) # Make the text widget row expandable

        # --- NEW: Header Frame for Title and Button ---
        header = ttk.Frame(parent)
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
        
        ttk.Label(header, text="Live Logs", font=FONT_BOLD).pack(side=tk.LEFT)
        ttk.Button(header, text="View Full Log", command=self._on_view_log_file).pack(side=tk.RIGHT)
        # --- End of New Section ---

        self.log_text = tk.Text(parent, height=10, wrap="word", relief="flat", bg=LIST_BG, fg=FG_COLOR, font=FONT_NORMAL, highlightthickness=1, highlightbackground=HEADER_BG)
        # The text widget now goes in row 1
        self.log_text.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

    def _create_history_widgets(self, parent):
        self.history_tree = ttk.Treeview(parent, columns=("timestamp", "hostname", "action", "details", "status"), show="headings")
        self.history_tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.history_tree.heading("timestamp", text="Time"); self.history_tree.column("timestamp", width=120, anchor="center")
        self.history_tree.heading("hostname", text="Hostname"); self.history_tree.column("hostname", width=150, anchor="center")
        self.history_tree.heading("action", text="Action"); self.history_tree.column("action", width=100, anchor="center")
        self.history_tree.heading("details", text="Details"); self.history_tree.column("details", width=250, anchor="center")
        # --- END OF MODIFICATION ---
        self.history_tree.heading("status", text="Status"); self.history_tree.column("status", width=80, anchor='center')

    # --- Public Methods ---
    def set_user(self, user: dict):
        self.user = user
        if user: self.user_label.config(text=f"{user.get('username', 'User')}")
        else: self.user_label.config(text="Not logged in")

    def add_or_update_slave(self, hostname, ip, status, groups_str):
        """
        Updates the in-memory cache for a slave and triggers a full refresh.
        """
        # Ensure the top-level dictionary for the host exists
        if hostname not in self._all_nodes:
            self._all_nodes[hostname] = {}
        
        # --- THIS IS THE FIX ---
        # Update all relevant keys in the cache, not just the status.
        self._all_nodes[hostname]['ip'] = ip
        self._all_nodes[hostname]['status'] = status
        self._all_nodes[hostname]['groups'] = [g.strip() for g in groups_str.split(',') if g.strip()]

        # Now, trigger the other updates that rely on the cache
        self.update_group_list()
        self.update_dashboard_metrics()
        # self._update_node_list()

    def remove_node_from_group(self, hostname, group_name):
        if hostname in self._all_nodes and group_name in self._all_nodes[hostname]['groups']:
            self._all_nodes[hostname]['groups'].remove(group_name)
        if group_name in self._all_groups and hostname in self._all_groups[group_name]:
            self._all_groups[group_name].remove(hostname)
        self.update_group_list()
        self._update_node_list() # This is the corrected function call
        self.append_log(f"Removed '{hostname}' from group '{group_name}'")

    def update_dashboard_metrics(self):
        total = len(self._all_nodes)
        online = len([n for n in self._all_nodes.values() if n['status'] == 'online'])
        offline = total - online
        self.total_nodes_var.set(f"Total: {total}")
        self.online_nodes_var.set(f"Online: {online}")
        self.offline_nodes_var.set(f"Offline: {offline}")
        # Keep the Dashboard tab's KPI tiles live too (cheap: no callback
        # round-trip, just the same in-memory counts recomputed).
        if hasattr(self, "_dash_total_var"):
            self._dash_total_var.set(str(total))
            self._dash_online_var.set(str(online))
            self._dash_offline_var.set(str(offline))

    def append_log(self, text):
        # First, log the raw message to the master.log file and console
        logging.info(text)

        # Second, display the message in the GUI's text widget with a timestamp
        timestamp = time.strftime('%H:%M:%S')
        log_line = f"{timestamp} - {text}\n"

        # (This is the color-coding enhancement from before)
        tag = "normal"
        if "Success" in text or "Connected" in text:
            tag = "success"
        elif "Failed" in text or "Error" in text or "disconnected" in text:
            tag = "error"
        elif "POLICY" in text or "NOTE" in text:
            tag = "info"
            
        self.log_text.insert(tk.END, log_line, (tag,))
        self.log_text.see(tk.END)

    def add_history_entry(self, hostname, action, details, status):
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        self.history_tree.insert("", 0, values=(timestamp, hostname, action, details, status))

    def get_last_inventory(self, hostname):
        return self._last_inventories.get(hostname)
    
    def update_inventory(self, hostname, info: dict):
        self._last_inventories[hostname] = info or {}
        if hostname in self._inventory_popups and self._inventory_popups[hostname].winfo_exists():
            self._inventory_popups[hostname].load_from_cache()
            
    def handle_status_event(self, hostname, msg: dict):
        software = msg.get("software", "")
        status = msg.get("status", "")
        message = msg.get("message", "")
        progress = msg.get("progress", "")
        
        log_msg = f"[{hostname}]"
        if software: log_msg += f" {software}"
        log_msg += f" → {status}"
        if progress: log_msg += f" {progress}%"
        if message: log_msg += f" | {message}"
            
        self.append_log(log_msg.strip())

        # --- PROGRESS BAR LOGIC ---
        if "install" in status.lower() and progress:
            self.update_node_progress(hostname, int(progress))
        elif status.lower() in ["success", "failed", "skipped", "update: failed"]:
             self.update_node_progress(hostname, -1) # Remove progress bar
        
        # --- HISTORY LOGIC (CORRECTED) ---
        status_lower = status.lower()
        if "success" in status_lower or "failed" in status_lower or "skipped" in status_lower:
            action = "Install" if "install" in status_lower else "Uninstall"
            self.add_history_entry(hostname, action, software, status)


    def update_node_progress(self, hostname, percentage):
        """Updates or removes a progress bar overlay for a specific node.

        ttk.Treeview has no `window_create` method (that only exists on
        tkinter.Text), so embedded-window progress bars are not possible.
        Instead we overlay a real ttk.Progressbar widget on top of the row's
        "status" cell using place(), positioned via the row's bbox().
        """
        if hostname in self._active_progress_bars:
            pb = self._active_progress_bars[hostname]
            if percentage < 0 or percentage >= 100:
                pb.destroy()
                del self._active_progress_bars[hostname]
                self._filter_nodes() # Refresh to show status icon again
            else:
                pb.configure(value=percentage)
                self._position_progress_bar(hostname, pb)
        elif percentage >= 0 and percentage < 100:
            if not self.nodes_tree.exists(hostname):
                return

            pb = ttk.Progressbar(self.nodes_tree, orient="horizontal", mode="determinate", value=percentage)
            self.nodes_tree.set(hostname, "status", "") # Hide text
            self._active_progress_bars[hostname] = pb
            self._position_progress_bar(hostname, pb)

    def _position_progress_bar(self, hostname, pb):
        """Places (or hides, if the row isn't currently visible) a progress bar overlay."""
        bbox = self.nodes_tree.bbox(hostname, "status")
        if bbox:
            x, y, width, height = bbox
            pb.place(x=x, y=y, width=width, height=height)
        else:
            pb.place_forget()


    def _update_node_list(self):
        """
        Updates the node list from the database and is the SINGLE SOURCE OF TRUTH
        for synchronizing the in-memory cache (_all_nodes).
        """
        selected_group = self._get_selected_group()
        search_term = self.search_var.get().lower()

        # Get fresh data from the database and the live network state
        all_slaves_data = self.callbacks.get("on_get_all_slave_statuses")()
        online_hosts = self.callbacks.get("get_online_hosts", lambda: [])()
        
        # --- Create a completely new cache based on the fresh data ---
        refreshed_nodes_cache = {}

        # Clear the visual list before redrawing
        for item in self.nodes_tree.get_children():
            self.nodes_tree.delete(item)

        for slave in all_slaves_data:
            hostname = slave['hostname']
            ip = slave.get('ip', '')
            slave_groups_str = slave.get('groups', '') or ''
            alias = slave.get('alias')
            
            # Determine the true, current status of the slave
            current_status = "online" if hostname in online_hosts else "offline"
            
            # Build the new cache entry with the correct, fresh data
            refreshed_nodes_cache[hostname] = {
                'ip': ip,
                'status': current_status,
                'groups': [g.strip() for g in slave_groups_str.split(',') if g.strip()],
                'alias': alias
            }

            # --- Filtering and Display Logic ---
            search_haystack = f"{hostname} {ip} {slave_groups_str} {alias or ''}".lower()
            if selected_group and selected_group != "All Nodes" and selected_group not in slave_groups_str.split(','):
                continue
            if search_term and search_term not in search_haystack:
                continue
            
            display_name = f"{alias} ({hostname})" if alias else hostname

            display_status_text = "Offline"; status_image = self.red_dot_img
            if current_status == 'online':
                last_result = slave.get('last_result') or ''
                if 'fail' in last_result.lower():
                    display_status_text = "Warning"; status_image = self.yellow_dot_img
                else:
                    display_status_text = "Online"; status_image = self.green_dot_img

            last_result_text = slave.get('last_result') or 'N/A'
            if 'success' in last_result_text.lower(): last_result_text = f"✅ {last_result_text}"
            elif 'fail' in last_result_text.lower(): last_result_text = f"❌ {last_result_text}"
            elif 'pending' in last_result_text.lower() or 'queued' in last_result_text.lower(): last_result_text = f"⏳ {last_result_text}"

            last_seen_str = slave.get('last_seen', 'N/A')
            if last_seen_str and last_seen_str != 'N/A':
                try:
                    date_part = last_seen_str.split('T')[0]
                    time_part = last_seen_str.split('T')[1].split('.')[0]
                    last_seen_str = f"{date_part} {time_part}"
                except IndexError: pass
            
            self.nodes_tree.insert("", "end", iid=hostname,
                                   image=status_image,
                                   values=(display_name, display_status_text, ip, slave_groups_str,
                                           slave.get('last_command', 'N/A'), last_result_text,
                                           last_seen_str, slave.get('remarks', '')))

        # The tree was just rebuilt from scratch, so any tracked progress bar
        # overlays need to be either repositioned (row still exists, but its
        # bbox may have moved/changed) or destroyed (row no longer present),
        # otherwise they'd leak as stale widgets referencing rows that no
        # longer exist.
        for hostname in list(self._active_progress_bars.keys()):
            pb = self._active_progress_bars[hostname]
            if self.nodes_tree.exists(hostname):
                self._position_progress_bar(hostname, pb)
            else:
                pb.destroy()
                del self._active_progress_bars[hostname]

        # --- Finally, overwrite the old cache with the new, perfectly correct one ---
        self._all_nodes = refreshed_nodes_cache
        self.update_dashboard_metrics()
        # Update button states after the refresh is complete
        self._on_node_selected()
            
    def update_group_list(self):
        """Refreshes the group list."""
        if not self.callbacks.get("on_get_all_groups"): return

        self._all_groups = self.callbacks["on_get_all_groups"]()

        # Cross-reference group -> assigned policy name so it can be shown
        # inline (e.g. "GroupName [Policy: PolicyName]"). This is purely
        # cosmetic: the item id (iid) stays the plain group name below, so
        # none of the existing group-selection logic needs to change.
        policy_by_group = {}
        assignments_getter = self.callbacks.get("on_get_group_assignments")
        if assignments_getter:
            try:
                for row in assignments_getter():
                    policy_by_group[row.get("group_name")] = row.get("policy_name")
            except Exception:
                policy_by_group = {}

        selected = self._get_selected_group()
        for item in self.group_tree.get_children():
            self.group_tree.delete(item)

        self.group_tree.insert("", "end", iid="All Nodes", text="All Nodes", open=True, tags=('group',))

        for group in sorted(self._all_groups.keys()):
            # The item ID (iid) remains the simple group name for internal logic,
            # but the 'text' is what the user sees.
            policy_name = policy_by_group.get(group)
            label = f"{group} [Policy: {policy_name}]" if policy_name else group
            self.group_tree.insert("", "end", iid=group, text=label, tags=('group',))

        if selected and selected in self._all_groups:
            try:
                self.group_tree.selection_set(selected)
            except tk.TclError:
                pass # Item might not exist after a refresh

    def _get_selected_nodes(self):
        """
        Returns a list of the true hostnames (the item IDs) of the selected
        nodes in the treeview.
        """
        # The selection() method directly returns the iids, which we set as the hostname.
        return list(self.nodes_tree.selection())

    def _get_selected_group(self):
        """
        Returns the ID of the selected group, which is its actual name.
        """
        selected = self.group_tree.selection()
        # The selection() method returns a tuple of the selected item IDs (iids).
        # We correctly set the iid to be the plain group name, so we just return the first one.
        return selected[0] if selected else None


    def _show_context_menu(self, event):
        iid = self.nodes_tree.identify_row(event.y)
        if iid:
            if iid not in self.nodes_tree.selection():
                self.nodes_tree.selection_clear()
                self.nodes_tree.selection_set(iid)
            
            selected_nodes = self._get_selected_nodes()
            node_status = self._all_nodes.get(iid, {}).get('status', 'offline')

            # Reuse a single cached Menu (and its submenus) across invocations
            # instead of building a brand new tk.Menu tree on every right
            # click. Tk widgets aren't garbage collected when the Python
            # variables holding them go out of scope, so rebuilding from
            # scratch each time would leak Menu widgets for the life of the
            # process on a long-running console with heavy right-click usage.
            if self._context_menu is None:
                self._context_menu = tk.Menu(self.root, tearoff=0, bg=LIST_BG, fg=FG_COLOR,
                                       activebackground=ACCENT_COLOR, activeforeground=FG_COLOR,
                                       relief='flat', borderwidth=0)

            context_menu = self._context_menu

            # Clear out entries left over from the previous invocation before rebuilding.
            context_menu.delete(0, "end")

            # --- START OF MENU ITEMS ---
            context_menu.add_command(label="Get Inventory", command=self._on_inventory)
            context_menu.add_command(label="Send File...", command=self._on_send_file)
            context_menu.add_command(label="Send & Extract ZIP...",
                         command=lambda: self._on_send_and_extract_zip(nodes=[iid])) # Pass selected node
            context_menu.add_separator(background=HEADER_BG)
            context_menu.add_command(label="Set Alias...", command=self._on_set_alias)
            context_menu.add_command(label="Add to Group...", command=self._on_add_to_group)
            context_menu.add_command(label="Remove from Group...", command=self._on_remove_from_group)
            context_menu.add_separator(background=HEADER_BG)
            # --- THIS SECTION CONTAINS THE MISSING ITEMS ---
            context_menu.add_command(label="Request Slave Log...", command=lambda: self.callbacks.get("on_request_slave_log")(iid))
            context_menu.add_command(label="Get Configuration...", command=lambda: self.callbacks.get("on_request_slave_config")(iid))
            context_menu.add_command(label="Request Screenshot", command=lambda: self._on_request_screenshot(iid))
            context_menu.add_command(label="Run Command...", command=lambda: self._on_run_command(selected_nodes))
            context_menu.add_command(label="Run Script...", command=lambda: self._on_run_script(selected_nodes))

            context_menu.add_command(label="Restart Connection", command=self._on_reconnect)
            context_menu.add_command(label="Update Slave Agent...", command=self._on_update_agent)
            context_menu.add_command(label="Disconnect Agent (Permanent)", command=self._on_disconnect)
            context_menu.add_command(label="Revoke Pairing...", command=lambda: self._on_revoke_pairing(iid))
            context_menu.add_separator(background=HEADER_BG)

            # --- Power submenu (cached, cleared and repopulated each invocation) ---
            if self._power_menu is None:
                self._power_menu = tk.Menu(self.root, tearoff=0, bg=LIST_BG, fg=FG_COLOR,
                                       activebackground=ACCENT_COLOR, activeforeground=FG_COLOR,
                                       relief='flat', borderwidth=0)
            power_menu = self._power_menu
            power_menu.delete(0, "end")
            power_menu.add_command(label="Shutdown", command=lambda: self._on_power_action("on_system_shutdown", selected_nodes))
            power_menu.add_command(label="Restart", command=lambda: self._on_power_action("on_system_restart", selected_nodes))
            power_menu.add_command(label="Sleep", command=lambda: self._on_power_action("on_system_sleep", selected_nodes))
            context_menu.add_cascade(label="Power", menu=power_menu)
            # --- END OF SECTION ---

            # Disable options that require the slave to be online
            is_offline = node_status != 'online'
            if is_offline:
                context_menu.entryconfig("Get Inventory", state="disabled")
                context_menu.entryconfig("Send & Extract ZIP...", state="disabled")
                context_menu.entryconfig("Request Slave Log...", state="disabled")
                context_menu.entryconfig("Get Configuration...", state="disabled") # Also disable this if offline
                context_menu.entryconfig("Restart Connection", state="disabled")
                context_menu.entryconfig("Disconnect Agent (Permanent)", state="disabled")
                context_menu.entryconfig("Power", state="disabled")
                context_menu.entryconfig("Request Screenshot", state="disabled")
                context_menu.entryconfig("Run Command...", state="disabled")
                context_menu.entryconfig("Run Script...", state="disabled")

            context_menu.post(event.x_root, event.y_root)

    def _on_group_selected(self, event=None):
        """When a group is selected, update the label and refresh the filtered node list."""
        group = self._get_selected_group()
        if group:
            self.nodes_label.config(text=f"Nodes in '{group}'")
            self._update_node_list()

        self._update_button_states()    

    def _on_new_group(self):
        existing_groups = [g for g in self._all_groups.keys() if g != "All Nodes"]
        
        dialog = CreateGroupDialog(self.root, existing_groups,
                                   title="Create New Group",
                                   prompt="Enter New Group Name:")
        group_name = dialog.show()
        
        if group_name:
            if group_name in self._all_groups or group_name == "All Nodes":
                messagebox.showerror("Error", f"A group named '{group_name}' already exists.", parent=self.root)
            # This now correctly calls the controller to create the group
            elif self.callbacks.get("on_create_group"):
                self.callbacks["on_create_group"](group_name)

    def _on_delete_group(self):
        group = self._get_selected_group()
        if not group or group == "All Nodes":
            messagebox.showwarning("Invalid Selection", "Please select a group to delete.", parent=self.root)
            return
            
        if messagebox.askyesno("Confirm Deletion", f"Are you sure you want to delete the group '{group}'?\nNodes will NOT be disconnected.", parent=self.root):
            # 1. Update the GUI's in-memory cache
            # This loop is for the button-state logic cache, not the display
            for hostname in self._all_groups.get(group, []):
                if hostname in self._all_nodes and group in self._all_nodes[hostname]['groups']:
                    self._all_nodes[hostname]['groups'].remove(group)
            if group in self._all_groups:
                del self._all_groups[group]
            
            # 2. Tell the controller to delete the group from the database
            if self.callbacks.get("on_delete_group"):
                self.callbacks["on_delete_group"](group)
            
            # 3. Refresh BOTH the left-side group list and the main node list
            self.update_group_list()
            self._update_node_list() # This forces the main list to refresh
            self.append_log(f"Deleted group: {group}")

    def _on_inventory(self):
        nodes = self._get_selected_nodes()
        if not nodes: 
            messagebox.showwarning("No Selection", "Please select a node from the list.", parent=self.root)
            return
        
        hostname = nodes[0]
        
        # --- NEW LOGIC: Check if the node is online ---
        node_status = self._all_nodes.get(hostname, {}).get('status', 'offline')
        
        if node_status == 'online':
            # Only send a request for a live update if the slave is online
            if self.callbacks.get("on_request_inventory"):
                self.callbacks["on_request_inventory"](hostname)
        else:
            # Inform the user that they are viewing cached data for an offline slave
            messagebox.showinfo(
                "Slave Offline",
                f"'{hostname}' is offline. Showing the last known inventory.\nA live refresh is not possible.",
                parent=self.root
            )
        
        # The logic to show the popup window remains the same, but we pass it the cache
        if hostname in self._inventory_popups and self._inventory_popups[hostname].winfo_exists():
            self._inventory_popups[hostname].lift()
        else:
            self._inventory_popups[hostname] = InventoryPopup(self.root, hostname, self._all_nodes, {
                "get_last_inventory": self.get_last_inventory,
                "on_request_inventory": self.callbacks.get("on_request_inventory"),
                "on_uninstall": self.callbacks.get("on_uninstall")
            })


    def _on_install_from_catalog(self):
        targets = self._get_targets()
        if not targets: 
            messagebox.showwarning("No Selection", "Please select one or more nodes, or a group, from the list.", parent=self.root)
            return
        
        # This now calls the callback ONCE with the ENTIRE list of nodes.
        if self.callbacks.get("on_deploy_catalog"):
            self.callbacks["on_deploy_catalog"](targets)

    def _on_install_from_folder(self):
        targets = self._get_targets()
        if not targets: 
            messagebox.showwarning("No Selection", "Please select one or more nodes, or a group, from the list.", parent=self.root)
            return
        
        filepath = filedialog.askopenfilename(title="Select Installer File", filetypes=[("Installers", "*.exe *.msi"), ("All files", "*.*")])
        if not filepath: return

        # --- CORRECTION ---
        # Call the callback only ONCE with the entire list of targets
        if self.callbacks.get("on_deploy_file"):
            self.callbacks["on_deploy_file"](targets, filepath)
            self.append_log(f"Queued install of {os.path.basename(filepath)} for {len(targets)} target(s)")

    def _on_add_to_group(self):
        nodes = self._get_selected_nodes()
        if not nodes: 
            messagebox.showwarning("No Selection", "Please select one or more nodes from the list.", parent=self.root)
            return

        existing_groups = [g for g in self._all_groups.keys() if g != "All Nodes"]
        dialog = AddToGroupDialog(self.root, existing_groups)
        group_to_add = dialog.show()
        
        if group_to_add:
            nodes_to_add = []
            nodes_already_in_group = []
            for hostname in nodes:
                current_groups = self._all_nodes.get(hostname, {}).get('groups', [])
                if group_to_add in current_groups:
                    nodes_already_in_group.append(hostname)
                else:
                    nodes_to_add.append(hostname)

            if nodes_already_in_group:
                messagebox.showwarning("Already a Member", 
                                       f"{len(nodes_already_in_group)} selected node(s) are already in '{group_to_add}' and were skipped.",
                                       parent=self.root)

            if nodes_to_add:
                if self.callbacks.get("on_add_group"):
                    for hostname in nodes_to_add:
                        self.callbacks["on_add_group"](hostname, group_to_add)
                    self.append_log(f"Added {len(nodes_to_add)} node(s) to group '{group_to_add}'")

    def _on_pair_slaves(self):
        if self._pairing_dialog is not None and self._pairing_dialog.winfo_exists():
            self._pairing_dialog.lift()
            return
        self._pairing_dialog = PairingDialog(self.root, self.callbacks)

    def _on_revoke_pairing(self, hostname):
        if not messagebox.askyesno(
            "Revoke Pairing",
            f"Revoke the pairing for '{hostname}'?\n\n"
            "It will be disconnected immediately and can't reconnect until it's "
            "paired again by re-running the slave installer with a new pairing code.",
            icon="warning", parent=self.root,
        ):
            return
        if self.callbacks.get("on_revoke_pairing"):
            self.callbacks["on_revoke_pairing"](hostname)

    def _on_disconnect(self):
        nodes_to_disconnect = []
        action_source = ""

        # Prioritize individually selected nodes
        selected_nodes = self._get_selected_nodes()
        if selected_nodes:
            nodes_to_disconnect = selected_nodes
            action_source = "selected node(s)"
        else:
            # Fallback to the selected group
            selected_group = self._get_selected_group()
            if selected_group == "All Nodes":
                nodes_to_disconnect = list(self._all_nodes.keys())
                action_source = "all nodes"
            elif selected_group:
                nodes_to_disconnect = list(self._all_groups.get(selected_group, []))
                action_source = f"node(s) in the '{selected_group}' group"

        if not nodes_to_disconnect:
            messagebox.showwarning("No Selection", "Please select one or more nodes, or a group, to disconnect.", parent=self.root)
            return

        if messagebox.askyesno("Confirm Disconnect", f"Are you sure you want to disconnect {len(nodes_to_disconnect)} {action_source}?", parent=self.root):
            if self.callbacks.get("on_disconnect"):
                for hostname in nodes_to_disconnect:
                    self.callbacks["on_disconnect"](hostname)
                self.append_log(f"Sent disconnect command to {len(nodes_to_disconnect)} node(s).")

class CreateGroupDialog(tk.Toplevel):
    """A styled dialog for creating a new group, which also lists existing ones."""
    def __init__(self, parent, existing_items, title="Create New", prompt="Enter New Name:"):
        super().__init__(parent)
        self.title(title)
        self.geometry("350x400")
        self.result = None
        
        # --- Window Setup ---
        self.configure(bg=BG_COLOR)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.grab_set()

        main_frame = ttk.Frame(self, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Existing Items List (Scrollable) ---
        ttk.Label(main_frame, text="Existing Items", font=FONT_BOLD).pack(anchor='w', pady=(0, 5))
        
        list_frame = ttk.Frame(main_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL)
        listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set,
                                  bg=LIST_BG, fg=FG_COLOR, font=FONT_NORMAL,
                                  highlightthickness=0, selectbackground=ACCENT_COLOR,
                                  activestyle='none', borderwidth=0)
        
        scrollbar.config(command=listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        for item in sorted(existing_items):
            listbox.insert(tk.END, item)

        # --- New Name Entry (Uses the custom prompt) ---
        ttk.Label(main_frame, text=prompt, font=FONT_BOLD).pack(anchor='w', pady=(10, 5))
        self.entry = ttk.Entry(main_frame, style="TEntry", font=FONT_NORMAL)
        self.entry.pack(fill=tk.X)
        self.entry.focus_set()

        # --- Action Buttons ---
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(20, 0))
        
        ttk.Button(btn_frame, text="Create", command=self._on_ok).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(btn_frame, text="Cancel", command=self._on_cancel).pack(side=tk.RIGHT)

        self.bind("<Return>", lambda e: self._on_ok())
        self.bind("<Escape>", lambda e: self._on_cancel())

    def _on_ok(self, event=None):
        self.result = self.entry.get().strip()
        if self.result:
            self.destroy()
        else:
            messagebox.showwarning("Input Required", "Please enter a name for the new group.", parent=self)

    def _on_cancel(self, event=None):
        self.result = None
        self.destroy()

    def show(self):
        """Show the dialog and wait for it to close."""
        self.master.wait_window(self)
        return self.result
    
class AddToGroupDialog(tk.Toplevel):
    """A styled dialog to add nodes to a new or existing group."""
    def __init__(self, parent, existing_groups):
        super().__init__(parent)
        self.title("Add to Group")
        self.geometry("350x400")
        self.result = None
        
        self.configure(bg=BG_COLOR)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.grab_set()

        main_frame = ttk.Frame(self, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Select a group or enter a new one:", font=FONT_BOLD).pack(anchor='w', pady=(0, 5))
        
        list_frame = ttk.Frame(main_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL)
        self.listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set,
                                  bg=LIST_BG, fg=FG_COLOR, font=FONT_NORMAL,
                                  highlightthickness=0, selectbackground=ACCENT_COLOR,
                                  activestyle='none', borderwidth=0, exportselection=False)
        
        scrollbar.config(command=self.listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.listbox.bind("<<ListboxSelect>>", self._on_list_select)

        for group in sorted(existing_groups):
            self.listbox.insert(tk.END, group)

        self.entry = ttk.Entry(main_frame, style="TEntry", font=FONT_NORMAL)
        self.entry.pack(fill=tk.X)
        self.entry.focus_set()

        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(20, 0))
        ttk.Button(btn_frame, text="OK", command=self._on_ok).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(btn_frame, text="Cancel", command=self._on_cancel).pack(side=tk.RIGHT)

        self.bind("<Return>", self._on_ok)
        self.bind("<Escape>", self._on_cancel)

    def _on_list_select(self, event):
        """Copies the selected group from the list to the entry box."""
        selection = self.listbox.curselection()
        if selection:
            self.entry.delete(0, tk.END)
            self.entry.insert(0, self.listbox.get(selection[0]))

    def _on_ok(self, event=None):
        self.result = self.entry.get().strip()
        if self.result:
            self.destroy()
        else:
            messagebox.showwarning("Input Required", "Please select or enter a group name.", parent=self)

    def _on_cancel(self, event=None):
        self.result = None
        self.destroy()

    def show(self):
        self.master.wait_window(self)
        return self.result    
    

class RemoveFromGroupDialog(tk.Toplevel):
    """A styled dialog to select a group to remove a node from."""
    def __init__(self, parent, member_groups):
        super().__init__(parent)
        self.title("Remove from Group")
        self.geometry("350x300")
        self.result = None

        self.configure(bg=BG_COLOR)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.grab_set()

        main_frame = ttk.Frame(self, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Select a group to remove:", font=FONT_BOLD).pack(anchor='w', pady=(0, 5))
        
        list_frame = ttk.Frame(main_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL)
        self.listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set,
                                  bg=LIST_BG, fg=FG_COLOR, font=FONT_NORMAL,
                                  highlightthickness=0, selectbackground=ACCENT_COLOR,
                                  activestyle='none', borderwidth=0, exportselection=False)
        
        scrollbar.config(command=self.listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        for group in sorted(member_groups):
            self.listbox.insert(tk.END, group)

        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(20, 0))
        ttk.Button(btn_frame, text="OK", command=self._on_ok).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(btn_frame, text="Cancel", command=self._on_cancel).pack(side=tk.RIGHT)
        
        self.bind("<Return>", self._on_ok)
        self.bind("<Escape>", self._on_cancel)

    def _on_ok(self, event=None):
        selection = self.listbox.curselection()
        if selection:
            self.result = self.listbox.get(selection[0])
            self.destroy()
        else:
            messagebox.showwarning("Input Required", "Please select a group.", parent=self)

    def _on_cancel(self, event=None):
        self.result = None
        self.destroy()

    def show(self):
        self.master.wait_window(self)
        return self.result    


class ScheduleTimeDialog(tk.Toplevel):
    """A styled dialog to pick a future date and time for a deployment."""
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Schedule Deployment Time")
        self.geometry("300x200")
        self.result = None

        self.configure(bg=BG_COLOR)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.grab_set()

        main_frame = ttk.Frame(self, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Date (YYYY-MM-DD):", font=FONT_BOLD).pack(anchor='w')
        self.date_entry = ttk.Entry(main_frame, style="TEntry", font=FONT_NORMAL)
        self.date_entry.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(main_frame, text="Time (HH:MM, 24-hour format):", font=FONT_BOLD).pack(anchor='w')
        self.time_entry = ttk.Entry(main_frame, style="TEntry", font=FONT_NORMAL)
        self.time_entry.pack(fill=tk.X)

        # Pre-populate with current date and time
        now = datetime.datetime.now()
        self.date_entry.insert(0, now.strftime("%Y-%m-%d"))
        self.time_entry.insert(0, now.strftime("%H:%M"))
        
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(20, 0))
        ttk.Button(btn_frame, text="Schedule", command=self._on_ok).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(btn_frame, text="Cancel", command=self._on_cancel).pack(side=tk.RIGHT)

    def _on_ok(self):
        date_str = self.date_entry.get().strip()
        time_str = self.time_entry.get().strip()
        try:
            dt_obj = datetime.datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            if dt_obj < datetime.datetime.now():
                messagebox.showwarning("Invalid Time", "Scheduled time cannot be in the past.", parent=self)
                return
            self.result = dt_obj.timestamp() # Convert to Unix timestamp
            self.destroy()
        except ValueError:
            messagebox.showerror("Invalid Format", "Please enter the date and time in the correct format (YYYY-MM-DD and HH:MM).", parent=self)

    def _on_cancel(self):
        self.result = None
        self.destroy()

    def show(self):
        self.master.wait_window(self)
        return self.result        

class BulkUninstallDialog(tk.Toplevel):
    """A styled dialog to select or enter a software name for bulk uninstallation."""
    def __init__(self, parent, software_data, group_name, node_count):
        super().__init__(parent)
        self.title(f"Bulk Uninstall from '{group_name}'")
        self.geometry("550x500")
        self.result = None

        self.configure(bg=BG_COLOR)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.grab_set()

        main_frame = ttk.Frame(self, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Pack static widgets from the TOP ---
        info_text = f"Select a common app below, or enter a name manually. ({node_count} nodes in group)"
        ttk.Label(main_frame, text=info_text, font=FONT_BOLD).pack(side=tk.TOP, anchor='w', pady=(0, 10))

        # --- Pack static widgets from the BOTTOM (in reverse order) ---
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(15, 0))
        ttk.Button(btn_frame, text="Uninstall", command=self._on_ok).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(btn_frame, text="Cancel", command=self._on_cancel).pack(side=tk.RIGHT)

        self.entry = ttk.Entry(main_frame, style="TEntry", font=FONT_NORMAL)
        self.entry.pack(side=tk.BOTTOM, fill=tk.X)
        self.entry.focus_set()

        ttk.Label(main_frame, text="Software to Uninstall:", font=FONT_BOLD).pack(side=tk.BOTTOM, anchor='w', pady=(10, 5))

        # --- Pack the expanding Treeview last to fill the remaining middle space ---
        tree_frame = ttk.Frame(main_frame)
        tree_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(0, 10))

        self.tree = ttk.Treeview(tree_frame, columns=("name", "count"), show="headings")
        self.tree.heading("name", text="Software Name")
        self.tree.column("name", width=350)
        self.tree.heading("count", text="Install Count")
        self.tree.column("count", width=100, anchor='center')
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        sorted_software = sorted(software_data, key=lambda x: x['count'], reverse=True)
        for item in sorted_software:
            self.tree.insert("", tk.END, values=(item['name'], f"{item['count']} / {node_count}"))

        self.bind("<Return>", self._on_ok)
        self.bind("<Escape>", self._on_cancel)

    def _on_tree_select(self, event):
        """Copies the selected software name from the tree to the entry box."""
        selection = self.tree.selection()
        if selection:
            software_name = self.tree.item(selection[0], "values")[0]
            self.entry.delete(0, tk.END)
            self.entry.insert(0, software_name)

    def _on_ok(self, event=None):
        self.result = self.entry.get().strip()
        if self.result:
            self.destroy()
        else:
            messagebox.showwarning("Input Required", "Please select or enter a software name to uninstall.", parent=self)

    def _on_cancel(self, event=None):
        self.result = None
        self.destroy()

    def show(self):
        self.master.wait_window(self)
        return self.result
    
class CatalogEditorDialog(tk.Toplevel):
    """A dialog for adding or editing a software catalog entry."""
    def __init__(self, parent, entry=None):
        super().__init__(parent)
        self.entry_data = entry or {}
        self.result = None

        title = "Edit Entry" if entry else "Add New Entry"
        self.title(title)
        # --- MODIFIED: Increased height to fit new fields ---
        self.geometry("450x530")
        self.configure(bg=BG_COLOR)
        self.transient(parent)
        self.grab_set()

        main_frame = ttk.Frame(self, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(1, weight=1)

        # --- MODIFIED: Added new fields to the list ---
        fields = [
                "name", "version", "filename", "silent_flags", 
                "post_install_cmd", "required_os", "required_arch",
                "pre_install_kill", "post_install_kill", "pre_uninstall_kill",
                "install_context"  # <-- ADD THIS LINE
            ]
        self.vars = {}

        for i, field in enumerate(fields):
            # Create label (converts "required_os" to "Required Os")
            if field == "silent_flags":
                label_text = "Silent Flags (optional - auto-detected):"
            else:
                label_text = f"{field.replace('_', ' ').title()}:"
            ttk.Label(main_frame, text=label_text, font=FONT_BOLD).grid(row=i, column=0, sticky="w", padx=5, pady=5)

            
            # Create a StringVar and Entry for each field
            self.vars[field] = tk.StringVar(value=self.entry_data.get(field, ""))
            ttk.Entry(main_frame, textvariable=self.vars[field], style="TEntry").grid(row=i, column=1, sticky="ew", padx=5, pady=5)

        # Buttons
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=len(fields), column=0, columnspan=2, sticky="e", pady=(20, 0))
        ttk.Button(btn_frame, text="Save", command=self._on_save).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)

    def _on_save(self):
        """Validate and return the new data."""
        new_data = {field: var.get().strip() for field, var in self.vars.items()}
        
        if not new_data.get("name") or not new_data.get("filename"):
            messagebox.showwarning("Input Required", "'Name' and 'Filename' are required fields.", parent=self)
            return

        self.result = new_data
        self.destroy()

    def show(self):
        """Show the dialog and wait for the result."""
        self.master.wait_window(self)
        return self.result


class ScriptEditorDialog(tk.Toplevel):
    """A dialog for creating or editing a saved script (Scripts tab)."""
    def __init__(self, parent, script=None):
        super().__init__(parent)
        self.script_data = script or {}
        self.result = None

        self.title("Edit Script" if script else "Add New Script")
        self.geometry("600x520")
        self.configure(bg=BG_COLOR)
        self.transient(parent)
        self.grab_set()

        main_frame = ttk.Frame(self, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(2, weight=1)

        ttk.Label(main_frame, text="Name:", font=FONT_BOLD).grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.name_var = tk.StringVar(value=self.script_data.get("name", ""))
        ttk.Entry(main_frame, textvariable=self.name_var, style="TEntry").grid(row=0, column=1, sticky="ew", padx=5, pady=5)

        ttk.Label(main_frame, text="Description:", font=FONT_BOLD).grid(row=1, column=0, sticky="w", padx=5, pady=5)
        self.desc_var = tk.StringVar(value=self.script_data.get("description", "") or "")
        ttk.Entry(main_frame, textvariable=self.desc_var, style="TEntry").grid(row=1, column=1, sticky="ew", padx=5, pady=5)

        ttk.Label(main_frame, text="Content\n(PowerShell):", font=FONT_BOLD).grid(row=2, column=0, sticky="nw", padx=5, pady=5)
        content_frame = ttk.Frame(main_frame)
        content_frame.grid(row=2, column=1, sticky="nsew", padx=5, pady=5)

        self.content_text = tk.Text(content_frame, wrap="word", relief="flat", bg=LIST_BG, fg=FG_COLOR,
                                     font=("Consolas", 10), highlightthickness=1, highlightbackground=HEADER_BG)
        self.content_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(content_frame, orient="vertical", command=self.content_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.content_text.config(yscrollcommand=scrollbar.set)
        self.content_text.insert("1.0", self.script_data.get("content", "") or "")

        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=3, column=0, columnspan=2, sticky="e", pady=(15, 0))
        ttk.Button(btn_frame, text="Save", command=self._on_save).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)

    def _on_save(self):
        name = self.name_var.get().strip()
        content = self.content_text.get("1.0", tk.END).strip()
        if not name or not content:
            messagebox.showwarning("Input Required", "Name and content are required.", parent=self)
            return
        self.result = {
            "name": name,
            "description": self.desc_var.get().strip(),
            "content": content,
        }
        self.destroy()

    def show(self):
        self.master.wait_window(self)
        return self.result


class SlaveLogPopup(tk.Toplevel):
    """A popup to display the contents of a slave's log file."""
    def __init__(self, parent, hostname, log_content):
        super().__init__(parent)
        self.title(f"Log File - {hostname}")
        self.geometry("800x600")
        self.configure(bg=BG_COLOR)
        self.transient(parent)
        self.grab_set()

        # Header
        ttk.Label(self, text=f"Last 200 lines from {hostname}:", font=FONT_BOLD, padding=(10,10)).pack(anchor="w")

        # Scrollable Text Widget
        text_frame = ttk.Frame(self)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        log_text = tk.Text(text_frame, wrap="word", relief="flat", bg=LIST_BG, fg=FG_COLOR,
                           font=("Consolas", 10), highlightthickness=1, highlightbackground=HEADER_BG)
        log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        log_text.config(yscrollcommand=scrollbar.set)

        log_text.insert("1.0", log_content)
        log_text.config(state="disabled") # Make it read-only
        log_text.see(tk.END) # Scroll to the bottom

        ttk.Button(self, text="Close", command=self.destroy, padding=5).pack(pady=(0, 10))                

class StyledInputDialog(tk.Toplevel):
    """A generic, styled dialog for single-line text input."""
    def __init__(self, parent, title, prompt, initialvalue=""):
        super().__init__(parent)
        self.title(title)
        self.geometry("400x150")
        self.result = None

        self.configure(bg=BG_COLOR)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.grab_set()

        main_frame = ttk.Frame(self, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # The prompt message, with wrapping for longer text
        ttk.Label(main_frame, text=prompt, font=FONT_BOLD, wraplength=370).pack(anchor='w', pady=(0, 10))
        
        self.entry = ttk.Entry(main_frame, style="TEntry", font=FONT_NORMAL)
        self.entry.pack(fill=tk.X, ipady=2)
        self.entry.insert(0, initialvalue)
        self.entry.focus_set()
        if initialvalue:
            self.entry.selection_range(0, tk.END) # Select all text by default

        # --- THIS IS THE FIX ---
        # The button frame must be a child of 'main_frame', not 'self'.
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(20, 0))
        
        ttk.Button(btn_frame, text="OK", command=self._on_ok).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(btn_frame, text="Cancel", command=self._on_cancel).pack(side=tk.RIGHT)

        self.bind("<Return>", self._on_ok)
        self.bind("<Escape>", self._on_cancel)

    def _on_ok(self, event=None):
        self.result = self.entry.get()
        self.destroy()

    def _on_cancel(self, event=None):
        self.result = None # Distinguishes a cancel from an empty string
        self.destroy()

    def show(self):
        """Show the dialog and wait for it to close."""
        self.master.wait_window(self)
        return self.result


class BroadcastMessageDialog(tk.Toplevel):
    """A modal dialog for composing a message to broadcast to ALL connected slaves."""
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Broadcast Message")
        self.geometry("450x260")
        self.result = None

        self.configure(bg=BG_COLOR)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.grab_set()

        main_frame = ttk.Frame(self, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            main_frame,
            text="This message will be shown as a popup on every currently connected slave machine:",
            font=FONT_BOLD, wraplength=410
        ).pack(anchor='w', pady=(0, 10))

        text_frame = ttk.Frame(main_frame)
        text_frame.pack(fill=tk.BOTH, expand=True)
        self.text = tk.Text(text_frame, wrap="word", relief="flat", bg=LIST_BG, fg=FG_COLOR,
                             font=FONT_NORMAL, height=6, highlightthickness=1, highlightbackground=HEADER_BG)
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=self.text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.text.config(yscrollcommand=scrollbar.set)
        self.text.focus_set()

        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(15, 0))
        ttk.Button(btn_frame, text="Send", command=self._on_send).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(btn_frame, text="Cancel", command=self._on_cancel).pack(side=tk.RIGHT)

    def _on_send(self):
        message = self.text.get("1.0", tk.END).strip()
        if not message:
            messagebox.showwarning("Input Required", "Please enter a message to broadcast.", parent=self)
            return
        self.result = message
        self.destroy()

    def _on_cancel(self):
        self.result = None
        self.destroy()

    def show(self):
        self.master.wait_window(self)
        return self.result


class ToastNotification(tk.Toplevel):
    """A styled, self-hiding toast notification."""
    def __init__(self, parent, title, message, notification_type="info"):
        super().__init__(parent)
        self.overrideredirect(True) # Borderless window
        self.geometry("300x100")

        # Colors and icons based on notification type
        color_map = {
            "info": ("#007ACC", "ℹ️"),
            "success": ("#4CAF50", "✅"),
            "error": ("#F44336", "❌")
        }
        bg_color, icon = color_map.get(notification_type, color_map["info"])
        self.configure(bg=bg_color)
        
        # Main frame
        main_frame = tk.Frame(self, bg=bg_color, padx=10, pady=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(1, weight=1)

        # Icon
        icon_label = tk.Label(main_frame, text=icon, font=("Segoe UI Emoji", 20), bg=bg_color, fg="white")
        icon_label.grid(row=0, column=0, rowspan=2, sticky="ns", padx=(0, 10))

        # Title and Message
        title_label = tk.Label(main_frame, text=title, font=FONT_BOLD, bg=bg_color, fg="white", anchor="w")
        title_label.grid(row=0, column=1, sticky="ew")
        
        message_label = tk.Label(main_frame, text=message, font=FONT_NORMAL, bg=bg_color, fg="white", wraplength=240, justify="left", anchor="nw")
        message_label.grid(row=1, column=1, sticky="nsew")

        self.alpha = 1.0
        self.fade_out_delay = 4000 # 4 seconds visible
        self.after(self.fade_out_delay, self._start_fade_out)

    def set_position(self, x, y):
        """Sets the window's position."""
        self.geometry(f"+{x}+{y}")

    def _start_fade_out(self):
        """Initiates the fade-out animation."""
        self.after(50, self._fade_out)

    def _fade_out(self):
        """Recursively lowers alpha to create a fade effect."""
        self.alpha -= 0.1
        if self.alpha <= 0.0:
            self.destroy()
        else:
            self.attributes("-alpha", self.alpha)
            self.after(50, self._fade_out)

    def on_close(self):
        """Immediately destroys the window, to be called by a manager."""
        self.destroy()           


class ConfigEditorDialog(tk.Toplevel):
    """A dialog for viewing and editing a config.py file."""
    def __init__(self, parent, title, content, hostname, callbacks):
        super().__init__(parent)
        self.title(title)
        self.geometry("800x600")
        self.configure(bg=BG_COLOR)
        self.transient(parent)
        self.grab_set()

        self.callbacks = callbacks
        self.hostname = hostname # The slave we are editing

        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)

        self.text_widget = tk.Text(main_frame, wrap="word", relief="flat", bg=LIST_BG, fg=FG_COLOR,
                                   font=("Consolas", 10), highlightthickness=1, highlightbackground=HEADER_BG)
        self.text_widget.grid(row=0, column=0, sticky="nsew")
        self.text_widget.insert("1.0", content)

        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=self.text_widget.yview)
        self.text_widget.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=0, column=1, sticky="ns")

        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=1, column=0, columnspan=2, sticky="e", pady=(10, 0))
        
        # The save button is now enabled for slave configs
        self.save_btn = ttk.Button(btn_frame, text="Save and Close", command=self._on_save)
        self.save_btn.pack(side=tk.RIGHT, padx=(5,0))
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)
        
        # If no hostname is provided, it's the master's config editor
        if not self.hostname:
            self.save_btn.config(text="Save Master Config", command=self._on_save_master)

    def _on_save(self):
        """Saves a slave's config."""
        new_content = self.text_widget.get("1.0", tk.END)
        if self.callbacks.get("on_save_slave_config"):
            self.callbacks["on_save_slave_config"](self.hostname, new_content)
        self.destroy()

    def _on_save_master(self):
        """Saves the master's config."""
        new_content = self.text_widget.get("1.0", tk.END)
        if self.callbacks.get("on_save_config_file"):
            if self.callbacks["on_save_config_file"](new_content):
                messagebox.showinfo("Settings Saved", "Configuration file saved. Please restart the application for changes to take effect.", parent=self)
                self.destroy()


def _decode_screenshot_image(image_b64_data, max_width=1000):
    """Shared helper: base64 JPEG -> a possibly-downscaled PIL Image.
    Raises on bad data; callers are expected to catch and show an error."""
    raw = base64.b64decode(image_b64_data)
    image = Image.open(io.BytesIO(raw))
    width, height = image.size
    if width > max_width:
        ratio = max_width / float(width)
        image = image.resize((max_width, int(height * ratio)), Image.LANCZOS)
    return image


class ScreenshotPopup(tk.Toplevel):
    """Displays a single base64-encoded JPEG screenshot captured from a slave."""
    MAX_WIDTH = 1000

    def __init__(self, parent, hostname, image_b64_data):
        super().__init__(parent)
        self.title(f"Screenshot - {hostname}")
        self.configure(bg=BG_COLOR)
        self.transient(parent)

        self._photo = None  # keep a reference so Tk doesn't garbage-collect the image

        try:
            image = _decode_screenshot_image(image_b64_data, self.MAX_WIDTH)
            self._photo = ImageTk.PhotoImage(image)
            tk.Label(self, image=self._photo, bg=BG_COLOR).pack(padx=10, pady=10)
        except Exception as e:
            ttk.Label(self, text=f"Failed to decode screenshot: {e}", padding=20).pack()

        ttk.Button(self, text="Close", command=self.destroy).pack(pady=(0, 10))


class ScreenshotGroupPopup(tk.Toplevel):
    """A tabbed window that collects screenshots from multiple hosts as they
    arrive asynchronously, one tab per hostname (added incrementally)."""
    MAX_WIDTH = 1000

    def __init__(self, parent, group_name, hostnames):
        super().__init__(parent)
        self.title(f"Screenshots - {group_name}")
        self.geometry("1050x750")
        self.configure(bg=BG_COLOR)
        self.transient(parent)

        ttk.Label(self, text=f"Requesting screenshots from {len(hostnames)} node(s) in '{group_name}'...",
                  font=FONT_BOLD).pack(anchor="w", padx=10, pady=(10, 0))

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        ttk.Button(self, text="Close", command=self.destroy).pack(pady=(0, 10))

        self._tabs = {}  # hostname -> {"frame":..., "photo":...}
        self.reset_for_hosts(hostnames)

    def reset_for_hosts(self, hostnames):
        """Ensures a (possibly 'waiting') tab exists for each given hostname,
        without disturbing tabs that already have results."""
        for hostname in hostnames:
            if hostname not in self._tabs:
                frame = ttk.Frame(self.notebook)
                ttk.Label(frame, text="Waiting for screenshot...", font=FONT_NORMAL).pack(padx=20, pady=20)
                self.notebook.add(frame, text=hostname)
                self._tabs[hostname] = {"frame": frame, "photo": None}

    def add_or_update_host(self, hostname, image_b64_data):
        """Renders (or replaces) the screenshot shown in a host's tab."""
        if hostname not in self._tabs:
            self.reset_for_hosts([hostname])
        tab = self._tabs[hostname]
        frame = tab["frame"]
        for widget in frame.winfo_children():
            widget.destroy()

        try:
            image = _decode_screenshot_image(image_b64_data, self.MAX_WIDTH)
            photo = ImageTk.PhotoImage(image)
            tab["photo"] = photo  # keep a reference so Tk doesn't garbage-collect it
            tk.Label(frame, image=photo, bg=BG_COLOR).pack(padx=10, pady=10)
        except Exception as e:
            ttk.Label(frame, text=f"Failed to decode screenshot: {e}", padding=20).pack()


class PairingDialog(tk.Toplevel):
    """Shows the current pairing code and countdown. Closing the dialog
    leaves the pairing window running; only "Close Pairing Window" ends it."""
    def __init__(self, parent, callbacks):
        super().__init__(parent)
        self.callbacks = callbacks
        self.title("Pair New Slaves")
        self.geometry("660x410")
        self.resizable(False, False)
        self.configure(bg=BG_COLOR)
        self.transient(parent)

        get_ips = self.callbacks.get("on_get_master_ip_addresses")
        try:
            self.master_ip, other_ips = get_ips() if get_ips else (None, [])
        except Exception:
            self.master_ip, other_ips = None, []

        frame = ttk.Frame(self, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Pairing code", font=FONT_LARGE_BOLD).pack(anchor="w")
        self.code_label = ttk.Label(frame, text="", font=("Consolas", 32, "bold"))
        self.code_label.pack(anchor="w", pady=(4, 0))
        self.status_label = ttk.Label(frame, text="", font=FONT_NORMAL)
        self.status_label.pack(anchor="w", pady=(0, 12))

        ttk.Label(frame, text="Master IP address", font=FONT_BOLD).pack(anchor="w")
        ttk.Label(frame, text=self.master_ip or "Not found", font=("Consolas", 16, "bold")).pack(anchor="w")
        if other_ips:
            ttk.Label(frame, font=FONT_NORMAL, wraplength=610, justify="left",
                      text="Other addresses on this PC, if lab PCs can't reach the one above: "
                           + ", ".join(other_ips)).pack(anchor="w")
        ttk.Frame(frame, height=12).pack()

        ttk.Label(
            frame, font=FONT_NORMAL, wraplength=610, justify="left",
            text="Enter the code and IP address in the slave installer on each lab PC. "
                 "To install without typing them on every PC, run the installer "
                 "silently (for example from a batch file on a USB drive):",
        ).pack(anchor="w")
        command_row = ttk.Frame(frame)
        command_row.pack(fill=tk.X, pady=(6, 12))
        self.command_var = tk.StringVar()
        ttk.Entry(command_row, textvariable=self.command_var, state="readonly",
                  font=("Consolas", 10)).pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.copy_button = ttk.Button(command_row, text="Copy", command=self._copy_command)
        self.copy_button.pack(side=tk.LEFT, padx=(6, 0))

        self.paired_label = ttk.Label(frame, text="", font=FONT_NORMAL, wraplength=610, justify="left")
        self.paired_label.pack(anchor="w")

        button_row = ttk.Frame(frame)
        button_row.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Button(button_row, text="Done", command=self.destroy).pack(side=tk.RIGHT)
        self.toggle_button = ttk.Button(button_row, text="", command=self._toggle_window)
        self.toggle_button.pack(side=tk.RIGHT, padx=(0, 6))

        if not self._status().get("open") and self.callbacks.get("on_start_pairing"):
            self.callbacks["on_start_pairing"]()
        self._refresh()

    def _status(self):
        get_status = self.callbacks.get("on_get_pairing_status")
        return get_status() if get_status else {"open": False, "paired_hosts": []}

    def _toggle_window(self):
        if self._status().get("open"):
            self.callbacks["on_stop_pairing"]()
        else:
            self.callbacks["on_start_pairing"]()
        self._refresh()

    def _copy_command(self):
        self.clipboard_clear()
        self.clipboard_append(self.command_var.get())

    def _refresh(self):
        if not self.winfo_exists():
            return
        status = self._status()
        if status.get("open"):
            minutes, seconds = divmod(status["seconds_left"], 60)
            self.code_label.config(text=status["code"])
            self.status_label.config(text=f"Open for another {minutes}:{seconds:02d}")
            command = f"slave.exe /VERYSILENT /PAIRCODE={status['code']}"
            if self.master_ip:
                command += f" /MASTERIP={self.master_ip}"
            self.command_var.set(command)
            self.copy_button.config(state="normal")
            self.toggle_button.config(text="Close Pairing Window")
        else:
            self.code_label.config(text="Closed")
            self.status_label.config(text="No pairing window is open. Slaves can't pair until you open one.")
            self.command_var.set("")
            self.copy_button.config(state="disabled")
            self.toggle_button.config(text="Open Pairing Window")

        paired = status.get("paired_hosts", [])
        if paired:
            self.paired_label.config(text=f"Paired in this window ({len(paired)}): " + ", ".join(paired))
        else:
            self.paired_label.config(text="No slaves have paired in this window yet.")
        self.after(1000, self._refresh)


class InstallBatchSummaryPopup(tk.Toplevel):
    """Summary popup for a multi-app install batch (3+ apps queued together
    via 'Install from Catalog'): one row per (app, host) pair, starting
    'Queued' and updated live to Success/Failed/Skipped as each slave
    reports its outcome. Non-modal, so the admin can keep working while
    installs are still in flight."""
    def __init__(self, parent, items):
        super().__init__(parent)
        self.title("Install Batch Summary")
        self.geometry("600x400")
        self.configure(bg=BG_COLOR)
        self.transient(parent)

        columns = ("app", "host", "status")
        self.tree = ttk.Treeview(self, columns=columns, show="headings")
        self.tree.heading("app", text="Application"); self.tree.column("app", width=250)
        self.tree.heading("host", text="Host"); self.tree.column("host", width=150)
        self.tree.heading("status", text="Status"); self.tree.column("status", width=100, anchor="center")
        self.tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.tree.tag_configure("success", foreground="#4CAF50")
        self.tree.tag_configure("failed", foreground="#F44336")
        self.tree.tag_configure("skipped", foreground="#fab219")
        self.tree.tag_configure("queued", foreground="#9E9E9E")

        for item in items:
            # Keyed by friendly_name, not filename -- that's what the slave
            # echoes back in its status updates (msg["software"]), since it's
            # simply relaying the "friendly_name" the master originally sent
            # it (catalog display name if set, else the raw filename).
            iid = self._row_id(item["hostname"], item["friendly_name"])
            self.tree.insert("", "end", iid=iid,
                              values=(item["friendly_name"], item["hostname"], item["status"]),
                              tags=(item["status"].lower(),))

        ttk.Button(self, text="Close", command=self.destroy).pack(pady=(0, 10))

    @staticmethod
    def _row_id(hostname, friendly_name):
        return f"{hostname}::{friendly_name}"

    def update_item(self, hostname, friendly_name, status):
        """Updates one row's status text/color, if that row is still present."""
        iid = self._row_id(hostname, friendly_name)
        if self.tree.exists(iid):
            values = list(self.tree.item(iid, "values"))
            values[2] = status
            self.tree.item(iid, values=values, tags=(status.lower(),))


class CommandResultsPopup(tk.Toplevel):
    """Tabbed popup showing live command/script output, one tab per hostname.
    Used for both 'Run Command...' and 'Run Script...' batches (including
    single-node runs, for consistency and to avoid a second, near-duplicate
    single-host popup implementation)."""
    def __init__(self, parent, hostnames, label):
        super().__init__(parent)
        self.title(f"Command Output - {label}")
        self.geometry("900x600")
        self.configure(bg=BG_COLOR)
        self.transient(parent)

        self.hostnames = set(hostnames)
        self._text_widgets = {}

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        for hostname in hostnames:
            self._add_tab(hostname)

        ttk.Button(self, text="Close", command=self.destroy).pack(pady=(0, 10))

    def _add_tab(self, hostname):
        frame = ttk.Frame(self.notebook)
        text = tk.Text(frame, wrap="word", relief="flat", bg=LIST_BG, fg=FG_COLOR,
                        font=("Consolas", 10), highlightthickness=1, highlightbackground=HEADER_BG,
                        state="disabled")
        text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.notebook.add(frame, text=hostname)
        self._text_widgets[hostname] = text
        return text

    def append_output(self, hostname, data):
        """Appends one command_output payload ({'stdout','stderr','returncode'})
        to the given hostname's tab, adding the tab first if needed (e.g. a
        host that came online and replied after the popup was first built)."""
        text = self._text_widgets.get(hostname)
        if text is None:
            text = self._add_tab(hostname)
            self.hostnames.add(hostname)

        stdout = data.get("stdout") or ""
        stderr = data.get("stderr") or ""
        returncode = data.get("returncode", "")

        text.config(state="normal")
        if stdout:
            text.insert(tk.END, stdout)
            if not stdout.endswith("\n"):
                text.insert(tk.END, "\n")
        if stderr:
            text.insert(tk.END, stderr)
            if not stderr.endswith("\n"):
                text.insert(tk.END, "\n")
        text.insert(tk.END, f"[exit code: {returncode}]\n\n")
        text.see(tk.END)
        text.config(state="disabled")


class AddRuleDialog(tk.Toplevel):
    """A dialog for adding a Must-Have/Must-Not-Have policy rule that
    references catalog software by its friendly name. Internally, the rule is
    stored against the catalog's FILENAME (not the display name), since that's
    what the compliance-check engine (app.py's _run_compliance_check) uses to
    cross-reference the catalog and detect installed software."""
    def __init__(self, parent, catalog_data):
        super().__init__(parent)
        self.title("Add Policy Rule")
        self.geometry("420x260")
        self.result = None
        self.catalog_data = catalog_data or []

        self.configure(bg=BG_COLOR)
        self.transient(parent)
        self.grab_set()

        main_frame = ttk.Frame(self, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(1, weight=1)

        ttk.Label(main_frame, text="Rule Type:", font=FONT_BOLD).grid(row=0, column=0, sticky="w", pady=5)
        self.rule_type_var = tk.StringVar(value="Must Have")
        rule_type_frame = ttk.Frame(main_frame)
        rule_type_frame.grid(row=0, column=1, sticky="w", pady=5)
        ttk.Radiobutton(rule_type_frame, text="Must Have", variable=self.rule_type_var, value="Must Have").pack(side=tk.LEFT)
        ttk.Radiobutton(rule_type_frame, text="Must Not Have", variable=self.rule_type_var, value="Must Not Have").pack(side=tk.LEFT, padx=(10, 0))

        ttk.Label(main_frame, text="Software:", font=FONT_BOLD).grid(row=1, column=0, sticky="w", pady=5)
        software_names = sorted({row.get("name") for row in self.catalog_data if row.get("name")})
        self.software_var = tk.StringVar()
        combo = ttk.Combobox(main_frame, textvariable=self.software_var, values=software_names, state="readonly")
        combo.grid(row=1, column=1, sticky="ew", pady=5)
        if software_names:
            combo.current(0)

        ttk.Label(main_frame, text="Version (optional):", font=FONT_BOLD).grid(row=2, column=0, sticky="w", pady=5)
        self.version_var = tk.StringVar()
        ttk.Entry(main_frame, textvariable=self.version_var, style="TEntry").grid(row=2, column=1, sticky="ew", pady=5)

        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=3, column=0, columnspan=2, sticky="e", pady=(20, 0))
        ttk.Button(btn_frame, text="Add", command=self._on_add).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)

    def _on_add(self):
        software_name = self.software_var.get().strip()
        if not software_name:
            messagebox.showwarning("Input Required", "Please select a software name.", parent=self)
            return
        catalog_entry = next((row for row in self.catalog_data if row.get("name") == software_name), None)
        filename = catalog_entry.get("filename") if catalog_entry else software_name
        self.result = {
            "rule_type": self.rule_type_var.get(),
            "software_name": filename,
            "version": self.version_var.get().strip() or None,
        }
        self.destroy()

    def show(self):
        self.master.wait_window(self)
        return self.result


class AssignPolicyDialog(tk.Toplevel):
    """A simple picker dialog listing available policies to assign to a group."""
    def __init__(self, parent, policies):
        super().__init__(parent)
        self.title("Assign Policy")
        self.geometry("350x350")
        self.result = None
        self.policies = policies

        self.configure(bg=BG_COLOR)
        self.transient(parent)
        self.grab_set()

        main_frame = ttk.Frame(self, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Select a policy to assign:", font=FONT_BOLD).pack(anchor='w', pady=(0, 5))

        list_frame = ttk.Frame(main_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL)
        self.listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set,
                                  bg=LIST_BG, fg=FG_COLOR, font=FONT_NORMAL,
                                  highlightthickness=0, selectbackground=ACCENT_COLOR,
                                  activestyle='none', borderwidth=0, exportselection=False)
        scrollbar.config(command=self.listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        for policy in policies:
            self.listbox.insert(tk.END, policy.get("name"))

        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="Assign", command=self._on_ok).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)

    def _on_ok(self):
        selection = self.listbox.curselection()
        if not selection:
            messagebox.showwarning("Input Required", "Please select a policy.", parent=self)
            return
        self.result = self.policies[selection[0]]["id"]
        self.destroy()

    def show(self):
        self.master.wait_window(self)
        return self.result


class ComplianceReportPopup(tk.Toplevel):
    """Displays a read-only compliance report: hostname/software/required/
    installed/status, with rows tag-colored by status (green=OK,
    red=Missing/Violation), matching the app's existing Success/Failed color
    convention used elsewhere (e.g. the Dashboard's outcome bar)."""
    def __init__(self, parent, report_data, save_callback=None):
        super().__init__(parent)
        self.title("Compliance Report")
        self.geometry("900x500")
        self.configure(bg=BG_COLOR)
        self.transient(parent)
        self.report_data = report_data or []
        self.save_callback = save_callback

        columns = ("hostname", "software", "required", "installed", "status")
        self.tree = ttk.Treeview(self, columns=columns, show="headings")
        self.tree.heading("hostname", text="Hostname"); self.tree.column("hostname", width=150)
        self.tree.heading("software", text="Software"); self.tree.column("software", width=180)
        self.tree.heading("required", text="Required"); self.tree.column("required", width=200)
        self.tree.heading("installed", text="Installed"); self.tree.column("installed", width=80, anchor="center")
        self.tree.heading("status", text="Status"); self.tree.column("status", width=100, anchor="center")
        self.tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.tree.tag_configure("ok", foreground="#4CAF50")
        self.tree.tag_configure("bad", foreground="#F44336")

        if not self.report_data:
            ttk.Label(self, text="No policy assignments or rules found to report on.", font=FONT_NORMAL).pack(pady=10)

        for row in self.report_data:
            tag = "ok" if row.get("status") == "OK" else "bad"
            self.tree.insert("", "end", values=(
                row.get("hostname"), row.get("software"), row.get("required"),
                row.get("installed"), row.get("status")
            ), tags=(tag,))

        btn_frame = ttk.Frame(self, padding=(10, 0, 10, 10))
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="Export to CSV...", command=self._on_export).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="Close", command=self.destroy).pack(side=tk.RIGHT)

    def _on_export(self):
        filepath = filedialog.asksaveasfilename(
            title="Save Compliance Report",
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
            parent=self
        )
        if filepath and self.save_callback:
            self.save_callback(self.report_data, filepath)
      