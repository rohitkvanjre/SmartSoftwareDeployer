import sqlite3
import os
import json
import threading
from datetime import datetime, timezone
from . import config

# --- Configuration ---
# Use config.MASTER_DIR (frozen-exe aware: resolves to the folder next to the
# real .exe, not PyInstaller's internal bundle dir) so the live database sits
# alongside data/config.json and data/cert.pem where an admin can find it.
DB_FILE = os.path.join(config.MASTER_DIR, "data", "deployer.db")

# Create a thread-local storage object. This will hold a separate connection
# for each thread, preventing conflicts between the GUI and networking threads.
thread_local = threading.local()

# --- Helper Functions ---
def _get_db_connection():
    """
    Establishes and returns a persistent database connection for the current thread.
    If a connection already exists for this thread, it's reused.
    """
    # Check if a connection is already stored for this thread
    conn = getattr(thread_local, 'db_conn', None)
    if conn is None:
        os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
        conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # Store the new connection in the thread-local storage
        thread_local.db_conn = conn
    return conn

def close_db_connection():
    """Closes the connection for the current thread if it exists."""
    conn = getattr(thread_local, 'db_conn', None)
    if conn is not None:
        conn.close()
        thread_local.db_conn = None

# --- Initialization ---
def init_database():
    """Creates all necessary tables if they don't already exist."""
    conn = _get_db_connection()
    # Use 'with conn:' to automatically handle commits and rollbacks
    with conn:
        cur = conn.cursor()
        # Slaves Table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS slaves (
            hostname TEXT PRIMARY KEY, ip TEXT, last_seen TEXT, auth_ok INTEGER, alias TEXT
        )""")
        # Deployments Table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS deployments (
            id INTEGER PRIMARY KEY AUTOINCREMENT, hostname TEXT NOT NULL, software TEXT,
            status TEXT, detail TEXT, progress INTEGER, timestamp TEXT NOT NULL
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            name TEXT PRIMARY KEY
        )""")
        # Group Members Table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS group_members (
            group_name TEXT NOT NULL, hostname TEXT NOT NULL, PRIMARY KEY (group_name, hostname)
        )""")
        # Inventory Table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            hostname TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            info_json TEXT
        )""")
        # Policies Table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS policies (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
            auto_check_enabled INTEGER NOT NULL DEFAULT 1
        )""")
        # Policy Rules Table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS policy_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT, policy_id INTEGER NOT NULL,
            rule_type TEXT NOT NULL, software_name TEXT NOT NULL, software_version TEXT,
            FOREIGN KEY (policy_id) REFERENCES policies (id) ON DELETE CASCADE
        )""")
        # Group Policies Table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS group_policies (
            group_name TEXT PRIMARY KEY, policy_id INTEGER NOT NULL,
            FOREIGN KEY (policy_id) REFERENCES policies (id) ON DELETE CASCADE
        )""")
        # Settings Table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)
        """)
        # Command Queue Table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS command_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT, hostname TEXT NOT NULL,
            command_json TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
        )""")
        # Slave Logs Table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS slave_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, hostname TEXT NOT NULL,
            timestamp TEXT NOT NULL, level TEXT NOT NULL, message TEXT NOT NULL
        )""")
        # Audit Log Table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, user TEXT NOT NULL,
            action TEXT NOT NULL, target TEXT, detail TEXT
        )""")
        # Saved Scripts Table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS saved_scripts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            content TEXT NOT NULL
        )""")
        
    print("Database initialized successfully.")

# --- Data Functions ---
def execute_query(query, params=()):
    """A generic function to execute INSERT, UPDATE, DELETE queries."""
    conn = _get_db_connection()
    with conn:
        conn.execute(query, params)

def read_query(query, params=()):
    """A generic function to execute SELECT queries and return all results."""
    conn = _get_db_connection()
    cur = conn.cursor()
    cur.execute(query, params)
    return [dict(row) for row in cur.fetchall()]   

def read_all(table_name):
    """Reads all rows from a specific table."""
    # Note: Using f-string here is safe because table_name comes from our own code, not user input.
    return read_query(f"SELECT * FROM {table_name}")

def log_deployment(data):
    """Logs a deployment event to the database."""
    query = """
    INSERT INTO deployments (hostname, software, status, detail, progress, timestamp)
    VALUES (:hostname, :software, :status, :detail, :progress, :timestamp)
    """
    execute_query(query, data)

def update_latest_inventory(hostname, timestamp, info_json):
    """Saves the latest inventory report, replacing any old report for the host."""
    query = "INSERT OR REPLACE INTO inventory (hostname, timestamp, info_json) VALUES (?, ?, ?)"
    execute_query(query, (hostname, timestamp, info_json))

def add_group_member(group_name, hostname):
    """Adds a host to a group, creating the group definition if it doesn't exist."""
    # Use a transaction to ensure both operations are atomic (succeed or fail together)
    conn = _get_db_connection()
    with conn:
        # Step 1: Ensure the group exists in the main `groups` table.
        conn.execute("INSERT OR IGNORE INTO groups (name) VALUES (?)", (group_name,))
        
        # Step 2: Add the member to the group's membership list.
        conn.execute("INSERT OR IGNORE INTO group_members (group_name, hostname) VALUES (?, ?)", (group_name, hostname))    

def delete_group(group_name):
    """Deletes an entire group and its members from the database."""
    # Use a transaction to ensure both operations succeed or fail together
    conn = _get_db_connection()
    with conn:
        conn.execute("DELETE FROM group_members WHERE group_name = ?", (group_name,))
        conn.execute("DELETE FROM groups WHERE name = ?", (group_name,))

def update_slave_status(hostname, ip, last_seen):
    """Adds a new slave or updates the IP and last_seen time of an existing one."""
    query = """
    INSERT INTO slaves (hostname, ip, last_seen, auth_ok)
    VALUES (?, ?, ?, 1)
    ON CONFLICT(hostname) DO UPDATE SET
        ip = excluded.ip,
        last_seen = excluded.last_seen;
    """
    execute_query(query, (hostname, ip, last_seen))    

# In master/db.py

def get_deployment_status_summary():
    """Counts deployments by their final status, now including 'Skipped'."""
    query = """
    SELECT 
        CASE 
            WHEN status LIKE '%Success%' THEN 'Success'
            WHEN status LIKE '%fail%' THEN 'Failed'
            WHEN status LIKE '%Skipped%' THEN 'Skipped'
            ELSE 'Other' 
        END as status_category,
        COUNT(*) as count
    FROM deployments
    WHERE status_category != 'Other'
    GROUP BY status_category;
    """
    return read_query(query)

def get_top_installed_software(limit=5):
    """Finds the most frequently installed software packages."""
    query = """
    SELECT software, COUNT(*) as count 
    FROM deployments 
    WHERE status LIKE '%Success%'
    GROUP BY software 
    ORDER BY count DESC 
    LIMIT ?
    """
    return read_query(query, (limit,))

def get_recent_failures(limit=5):
    """Retrieves the most recent deployment failures."""
    query = """
    SELECT hostname, software, detail, timestamp 
    FROM deployments 
    WHERE status LIKE '%fail%' 
    ORDER BY id DESC 
    LIMIT ?
    """
    return read_query(query, (limit,))    

def set_setting(key, value):
    """Saves a setting to the database."""
    query = "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)"
    execute_query(query, (key, str(value)))

def get_setting(key, default=None):
    result = read_query("SELECT value FROM settings WHERE key = ?", (key,))
    return result[0]['value'] if result else default    

def get_latest_inventory(hostname):
    """Retrieves the most recent inventory JSON for a specific host."""
    query = "SELECT info_json FROM inventory WHERE hostname = ? ORDER BY timestamp DESC LIMIT 1"
    result = read_query(query, (hostname,))
    return json.loads(result[0]['info_json']) if result else None

def queue_command(hostname, command_dict):
    """Saves a new command to the queue with a 'pending' status."""
    command_json = json.dumps(command_dict)
    timestamp = datetime.now(timezone.utc).isoformat()
    query = "INSERT INTO command_queue (hostname, command_json, status, created_at) VALUES (?, ?, 'pending', ?)"
    execute_query(query, (hostname, command_json, timestamp))

def get_pending_commands(hostname):
    """Retrieves all pending commands for a specific hostname."""
    query = "SELECT id, command_json FROM command_queue WHERE hostname = ? AND status = 'pending' ORDER BY created_at"
    return read_query(query, (hostname,))

def update_command_status(command_id, new_status):
    """Updates the status of a command in the queue (e.g., to 'dispatched')."""
    query = "UPDATE command_queue SET status = ? WHERE id = ?"
    execute_query(query, (new_status, command_id))    

def add_slave_log(hostname, level, message):
    """Adds a new log entry from a slave to the database."""
    timestamp = datetime.now(timezone.utc).isoformat()
    query = "INSERT INTO slave_logs (hostname, timestamp, level, message) VALUES (?, ?, ?, ?)"
    execute_query(query, (hostname, timestamp, level, message))   

def get_all_slave_statuses():
    """
    Retrieves a consolidated status for every known slave, including their
    last known deployment action, result, and all group memberships.
    """
    query = """
    SELECT
        s.hostname,
        s.ip,
        s.last_seen,
        s.alias, -- <-- ADDED THIS LINE
        d.software AS last_command,
        d.status AS last_result,
        d.detail AS remarks,
        GROUP_CONCAT(gm.group_name) AS groups
    FROM 
        slaves s
    LEFT JOIN (
        -- This subquery finds the ID of the most recent deployment for each host
        SELECT hostname, MAX(id) as max_id
        FROM deployments
        GROUP BY hostname
    ) latest_deploy ON s.hostname = latest_deploy.hostname
    LEFT JOIN deployments d ON d.id = latest_deploy.max_id
    LEFT JOIN group_members gm ON s.hostname = gm.hostname
    GROUP BY s.hostname
    ORDER BY s.hostname;
    """
    return read_query(query)

# In master/db.py

def remove_group_member(group_name, hostname):
    """Removes a specific host from a group."""
    query = "DELETE FROM group_members WHERE group_name = ? AND hostname = ?"
    execute_query(query, (group_name, hostname))

def get_deployments_today_count():
    """Counts all deployments that occurred on the current date using UTC."""
    # The fix is to change 'localtime' to 'now' to compare dates in UTC.
    query = "SELECT COUNT(*) as count FROM deployments WHERE DATE(timestamp) = DATE('now')"
    result = read_query(query)
    return result[0]['count'] if result else 0   

def get_deployments_by_status(status_category):
    """Retrieves all deployments, filtered by status category ('Success', 'Failed', or 'Skipped')."""
    # Use LIKE to catch variations of the status
    query = """
    SELECT hostname, software, detail, timestamp
    FROM deployments
    WHERE status LIKE ?
    ORDER BY id DESC
    """
    params = ("%" + status_category + "%",)
    return read_query(query, params)

def get_hosts_with_software(software_filename):
    """Finds all unique hostnames that have a given software successfully installed."""
    query = """
    SELECT DISTINCT hostname 
    FROM deployments 
    WHERE software = ? AND status LIKE '%Success%'
    ORDER BY hostname
    """
    # The result is a list of dictionaries, e.g., [{'hostname': 'Host1'}, {'hostname': 'Host2'}]
    # We will extract just the names into a simple list.
    results = read_query(query, (software_filename,))
    return [row['hostname'] for row in results]

def rename_group(old_name, new_name):
    """Renames a group across all relevant tables within a transaction."""
    conn = _get_db_connection()
    # Use 'with conn:' to automatically handle commits and rollbacks without closing the connection.
    try:
        with conn:
            # Update the main groups table (this was a missing step)
            conn.execute("UPDATE groups SET name = ? WHERE name = ?", (new_name, old_name))
            # Update the group_members table
            conn.execute("UPDATE group_members SET group_name = ? WHERE group_name = ?", (new_name, old_name))
            # Update the group_policies table
            conn.execute("UPDATE group_policies SET group_name = ? WHERE group_name = ?", (new_name, old_name))
    except sqlite3.IntegrityError:
        # This will be caught if a group with the new name already exists
        raise ValueError(f"A group with the name '{new_name}' already exists.")
    except Exception as e:
        # The 'with' block automatically handles the rollback on any other error
        raise e

def set_slave_alias(hostname, alias):
    """Updates the alias for a specific slave."""
    query = "UPDATE slaves SET alias = ? WHERE hostname = ?"
    execute_query(query, (alias, hostname))

def log_audit_event(user, action, target, detail):
    """Logs a new event to the audit log."""
    timestamp = datetime.now(timezone.utc).isoformat()
    query = "INSERT INTO audit_log (timestamp, user, action, target, detail) VALUES (?, ?, ?, ?, ?)"
    execute_query(query, (timestamp, user, action, target, detail))

def get_audit_log(search_term=None):
    """
    Retrieves audit log events, optionally filtering by a search term.
    The search term is checked against the user, action, target, and detail fields.
    """
    # Base query
    query = "SELECT * FROM audit_log"
    params = {}

    # If a search term is provided, add a WHERE clause
    if search_term:
        # The '||' concatenates fields, so we can search them all at once.
        # The '%' are wildcards, so it finds the term anywhere in the text.
        query += " WHERE user || action || target || detail LIKE :term"
        params['term'] = f"%{search_term}%"

    # Always order by the most recent event first
    query += " ORDER BY id DESC"
    
    return read_query(query, params)

def get_all_groups():
    """Returns a dictionary of all groups and their members, including empty groups."""
    query = """
    SELECT g.name AS group_name, gm.hostname
    FROM groups g
    LEFT JOIN group_members gm ON g.name = gm.group_name
    ORDER BY g.name, gm.hostname
    """
    rows = read_query(query)
    groups = {}
    for row in rows:
        group_name = row['group_name']
        if group_name not in groups:
            groups[group_name] = []
        # Add the hostname only if it's not NULL (i.e., the group is not empty)
        if row['hostname']:
            groups[group_name].append(row['hostname'])
    return groups

def create_group(group_name):
    """Adds a new group definition to the groups table."""
    query = "INSERT OR IGNORE INTO groups (name) VALUES (?)"
    execute_query(query, (group_name,))

# --- Saved Scripts ---
def create_script(name, description, content):
    """Adds a new saved script."""
    query = "INSERT INTO saved_scripts (name, description, content) VALUES (?, ?, ?)"
    execute_query(query, (name, description, content))

def get_all_scripts():
    """Returns every saved script, ordered by name."""
    return read_query("SELECT * FROM saved_scripts ORDER BY name")

def update_script(script_id, name, description, content):
    """Updates an existing saved script."""
    query = "UPDATE saved_scripts SET name = ?, description = ?, content = ? WHERE id = ?"
    execute_query(query, (name, description, content, script_id))

def delete_script(script_id):
    """Deletes a saved script."""
    query = "DELETE FROM saved_scripts WHERE id = ?"
    execute_query(query, (script_id,))

# --- Policy Management ---
def get_policies():
    """Returns every policy (id, name, auto_check_enabled), ordered by name."""
    return read_query("SELECT id, name, auto_check_enabled FROM policies ORDER BY name")

def get_policy_rules(policy_id):
    """Returns every rule belonging to a policy."""
    query = "SELECT * FROM policy_rules WHERE policy_id = ? ORDER BY id"
    return read_query(query, (policy_id,))

def create_policy(name):
    """Creates a new policy, auto-check enabled by default."""
    query = "INSERT INTO policies (name, auto_check_enabled) VALUES (?, 1)"
    execute_query(query, (name,))

def add_rule_to_policy(policy_id, rule_type, software_name, version=None):
    """Adds a must_have/must_not_have rule to a policy."""
    query = """
    INSERT INTO policy_rules (policy_id, rule_type, software_name, software_version)
    VALUES (?, ?, ?, ?)
    """
    execute_query(query, (policy_id, rule_type, software_name, version))

def assign_policy_to_group(group_name, policy_id):
    """Assigns a policy to a group. Mirrors the 'one row per key' pattern used
    by update_slave_status/update_latest_inventory: a group can only have one
    policy assigned at a time, so a repeat assignment simply replaces it."""
    query = "INSERT OR REPLACE INTO group_policies (group_name, policy_id) VALUES (?, ?)"
    execute_query(query, (group_name, policy_id))

def get_group_assignments():
    """Returns every group -> assigned policy mapping (group_name, policy_id, policy_name)."""
    query = """
    SELECT gp.group_name, p.id AS policy_id, p.name AS policy_name
    FROM group_policies gp
    JOIN policies p ON gp.policy_id = p.id
    ORDER BY gp.group_name
    """
    return read_query(query)

def delete_policy(policy_id):
    """Deletes a policy along with its rules and any group assignments, in a
    single transaction - mirrors delete_group's multi-table cleanup."""
    conn = _get_db_connection()
    with conn:
        conn.execute("DELETE FROM policy_rules WHERE policy_id = ?", (policy_id,))
        conn.execute("DELETE FROM group_policies WHERE policy_id = ?", (policy_id,))
        conn.execute("DELETE FROM policies WHERE id = ?", (policy_id,))

def rename_policy(policy_id, new_name):
    """Renames a policy. Mirrors rename_group's IntegrityError handling for
    the UNIQUE constraint on policies.name."""
    conn = _get_db_connection()
    try:
        with conn:
            conn.execute("UPDATE policies SET name = ? WHERE id = ?", (new_name, policy_id))
    except sqlite3.IntegrityError:
        raise ValueError(f"A policy with the name '{new_name}' already exists.")

def remove_rule_from_policy(rule_id):
    """Removes a single rule from a policy."""
    query = "DELETE FROM policy_rules WHERE id = ?"
    execute_query(query, (rule_id,))

def set_policy_auto_check(policy_id, enabled):
    """Enables/disables automatic (scheduled/startup) enforcement of a policy.
    Manual compliance checks always run regardless of this flag."""
    query = "UPDATE policies SET auto_check_enabled = ? WHERE id = ?"
    execute_query(query, (1 if enabled else 0, policy_id))

def get_all_group_policy_rules():
    """Every hostname + rule combination currently in effect, joining
    group_policies -> group_members -> policies -> policy_rules. This is what
    the compliance-check engine iterates over."""
    query = """
    SELECT gm.hostname, gp.group_name, p.id AS policy_id, p.name AS policy_name,
           p.auto_check_enabled, pr.id AS rule_id, pr.rule_type,
           pr.software_name, pr.software_version
    FROM group_policies gp
    JOIN group_members gm ON gp.group_name = gm.group_name
    JOIN policies p ON gp.policy_id = p.id
    JOIN policy_rules pr ON pr.policy_id = p.id
    ORDER BY gm.hostname
    """
    return read_query(query)

def remove_policy_from_group(group_name):
    """Removes any policy assignment from a group."""
    query = "DELETE FROM group_policies WHERE group_name = ?"
    execute_query(query, (group_name,))

