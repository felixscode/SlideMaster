#!/usr/bin/env python3
"""
Password hashing utility for SlideMaster authentication.
This script helps to generate hashed passwords for the password file.
"""

import hashlib
import sys
import os
from pathlib import Path

def hash_password(password: str) -> str:
    """Create a SHA-256 hash of the password."""
    return hashlib.sha256(password.encode()).hexdigest()

def main():
    if len(sys.argv) < 2:
        print("Usage: python hash_password.py [password]")
        print("       python hash_password.py -f [password_file]")
        sys.exit(1)
    
    if sys.argv[1] == "-f" and len(sys.argv) > 2:
        # Hash all passwords in a file
        file_path = sys.argv[2]
        if not os.path.exists(file_path):
            print(f"Error: File {file_path} does not exist.")
            sys.exit(1)
            
        with open(file_path, 'r') as f:
            passwords = f.read().splitlines()
        
        output_path = f"{file_path}"
        # Clear the content of the file before writing hashed passwords
        open(output_path, 'w').close()
        with open(output_path, 'w') as f:
            for password in passwords:
                if password.strip():  # Skip empty lines
                    hashed = hash_password(password)
                    f.write(f"{hashed}\n")
        
        print(f"Hashed passwords written to {output_path}")
        
    else:
        # Hash a single password
        password = sys.argv[1]
        hashed = hash_password(password)
        print(f"Hashed password: {hashed}")
        print("Add this to your secrets/streamlit_passwords file.")

if __name__ == "__main__":
    main()