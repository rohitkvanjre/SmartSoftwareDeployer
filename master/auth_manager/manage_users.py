# In master/manage_users.py
import json
import os
import getpass
from .auth import generate_salt, hash_password
from .. import config

# config.MASTER_DIR is the one writable data root (frozen-exe aware); in
# dev/source mode this still resolves to master/auth_manager/users.json,
# identical to the previous os.path.dirname(__file__)-based path.
USERS_FILE = os.path.join(config.MASTER_DIR, "auth_manager", "users.json")

def load_users():
    """Loads users from the JSON file, handling empty or corrupted files."""
    if not os.path.exists(USERS_FILE):
        return []
    try:
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
            if not content: # Check if the file is empty
                return []
            return json.loads(content)
    except json.JSONDecodeError:
        print("Warning: users.json file is corrupted. Starting fresh.")
        return [] # Return an empty list if JSON is invalid

def save_users(users):
    """Saves a list of users to the JSON file."""
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=4)
    print("User file updated successfully.")

def list_users():
    """Lists all current users."""
    print("\n--- Current Users ---")
    users = load_users()
    if not users:
        print("No users found.")
        return
    for user in users:
        print(f"- Username: {user['username']}, Role: {user['role']}")

def add_user():
    """Adds a new user to the system."""
    print("\n--- Add New User ---")
    users = load_users()
    username = input("Enter new username: ").strip()

    if any(u['username'] == username for u in users):
        print(f"Error: User '{username}' already exists.")
        return

    password = getpass.getpass("Enter password: ")
    password_confirm = getpass.getpass("Confirm password: ")

    if password != password_confirm:
        print("Error: Passwords do not match.")
        return

    role = input("Enter role (e.g., admin, user): ").strip()
    if not all([username, password, role]):
        print("Error: Username, password, and role cannot be empty.")
        return

    salt = generate_salt()
    password_hash = hash_password(password, salt)

    users.append({
        "username": username,
        "password_hash": password_hash,
        "salt": salt,
        "role": role
    })
    save_users(users)

def delete_user():
    """Deletes a user from the system."""
    print("\n--- Delete User ---")
    users = load_users()
    username_to_delete = input("Enter the username of the account to delete: ").strip()

    user_found = False
    for i, user in enumerate(users):
        if user['username'] == username_to_delete:
            user_found = True
            confirm = input(f"Are you sure you want to delete the user '{username_to_delete}'? (y/n): ").lower()
            if confirm == 'y':
                users.pop(i)
                save_users(users)
            else:
                print("Deletion cancelled.")
            break
    
    if not user_found:
        print(f"Error: User '{username_to_delete}' not found.")


def main():
    """Main function to display the management menu."""
    while True:
        print("\n--- User Management ---")
        print("1. List Users")
        print("2. Add User")
        print("3. Delete User")
        print("4. Exit")
        choice = input("Enter your choice: ")

        if choice == '1':
            list_users()
        elif choice == '2':
            add_user()
        elif choice == '3':
            delete_user()
        elif choice == '4':
            break
        else:
            print("Invalid choice. Please try again.")

if __name__ == "__main__":
    main()