import streamlit as st
from pathlib import Path
import subprocess
import shutil
import os
import aiohttp
import asyncio
import requests
import socket
import time
import logging
import signal
import re
from typing import Dict, List, Tuple, Optional, Generator, Any, Union

# Configuration
STREAMLIT_PASSWORD_FILE = Path(os.environ.get("STREAMLIT_PASSWORD_FILE", "./secrets/streamlit_passwords"))
GITHUB_TOKEN_FILE = Path(os.environ.get("GITHUB_TOKEN_FILE", "./secrets/github_token"))
GITHUB_USER = os.environ.get("GITHUB_USER", "felixscode")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "slides")
LOGLEVEL = logging.INFO


# --- ASYNC API CALLS ---
def _get_github_token() -> str:
    """
    Retrieves the GitHub token from the token file.
    
    Returns:
        str: The GitHub token string
    """
    with open(GITHUB_TOKEN_FILE, "r") as f:
        return f.read().strip()

async def _fetch_github_data() -> Dict[str, Any]:
    """
    Fetches the folder structure from GitHub repository asynchronously.
    
    Returns:
        Dict[str, Any]: JSON response from GitHub API containing repo structure
        or empty list if there was an error
    """
    token = _get_github_token()
    url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/git/trees/main?recursive=1"
    headers = {"Authorization": f"token {token}"}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                st.error(f"GitHub API Error: {response.status}, {await response.text()}")
                return []
            return await response.json()

@st.cache_data
def _get_github_data() -> Dict[str, Any]:
    """
    Runs the async function synchronously and caches the result.
    
    Returns:
        Dict[str, Any]: Cached GitHub repository data
    """
    return asyncio.run(_fetch_github_data())

def _match_pres_data(gh_data: Dict[str, Any]) -> Generator[Tuple[str, Dict[str, Any]], None, None]:
    """
    Extracts the slides and assets for each presentation from GitHub data.
    
    Args:
        gh_data: Dictionary containing GitHub repository structure
        
    Yields:
        Tuple[str, Dict[str, Any]]: Tuples of (presentation name, presentation data)
    """
    items_to_ignore = ["README.md","slidev-dev.sh",'.gitignore']
    for item in gh_data["tree"]:
        if "/" not in item["path"] and item["path"] not in items_to_ignore:
            name = item["path"]
            slides_path_name = f"{name}/slides.md"
            asset_path_name = f"{name}/assets/"
            assets = list(filter(lambda x: x["path"].startswith(asset_path_name), gh_data["tree"]))
            slides = next((x for x in gh_data["tree"] if x["path"] == slides_path_name), None)
            if slides:
                yield name, {"slides": slides, "assets": assets}

 
def get_presentations() -> Dict[str, Dict[str, Any]]:
    """
    Extracts unique folder names from GitHub API response.
    
    Returns:
        Dict[str, Dict[str, Any]]: Dictionary of presentations where keys are presentation
        names and values contain slide data and assets
    """
    slide_data = _get_github_data()
    if not slide_data or "tree" not in slide_data:
        return {}
    
    presentations = dict(_match_pres_data(slide_data))
    return presentations if presentations else {}

# --- AUTHENTICATION ---
import hashlib
import time

def _get_hashed_passwords() -> List[str]:
    """
    Reads hashed passwords from a file.
    
    Returns:
        List[str]: List of valid hashed passwords
    """
    with open(STREAMLIT_PASSWORD_FILE, "r") as f:
        return f.read().splitlines()

def _hash_password(password: str) -> str:
    """
    Creates a SHA-256 hash of the password.
    
    Args:
        password: Plain text password to hash
        
    Returns:
        str: Hashed password
    """
    return hashlib.sha256(password.encode()).hexdigest()

def _is_valid_hash(input_password: str, hashed_passwords: List[str]) -> bool:
    """
    Checks if the hashed input password matches any stored hashed password.
    
    Args:
        input_password: Plain text password from user
        hashed_passwords: List of hashed passwords to check against
        
    Returns:
        bool: True if password is valid, False otherwise
    """
    hashed_input = _hash_password(input_password)
    return hashed_input in hashed_passwords

def authenticate() -> None:
    """
    Handles user authentication with secure password hashing.
    Sets authenticated state in Streamlit session state.
    Implements basic session timeout and failed login tracking.
    """
    # Initialize session state variables
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if "login_time" not in st.session_state:
        st.session_state.login_time = None
    if "failed_attempts" not in st.session_state:
        st.session_state.failed_attempts = 0
    if "last_attempt_time" not in st.session_state:
        st.session_state.last_attempt_time = 0
        
    # Check for session timeout (30 minutes)
    if st.session_state.authenticated and st.session_state.login_time:
        if time.time() - st.session_state.login_time > 1800:  # 30 minutes
            st.session_state.authenticated = False
            st.warning("Your session has expired. Please login again.")
    
    # Check for login attempt rate limiting
    if st.session_state.failed_attempts >= 5:
        time_since_last = time.time() - st.session_state.last_attempt_time
        if time_since_last < 60:  # 1 minute lockout
            st.error(f"Too many failed attempts. Please try again in {60 - int(time_since_last)} seconds.")
            st.stop()
        else:
            # Reset counter after lockout period
            st.session_state.failed_attempts = 0
    
    if not st.session_state.authenticated:
        password = st.text_input("Password", type="password")
        if st.button("Login"):
            st.session_state.last_attempt_time = time.time()
            hashed_passwords = _get_hashed_passwords()
            
            if _is_valid_hash(password, hashed_passwords):
                st.session_state.authenticated = True
                st.session_state.login_time = time.time()
                st.session_state.failed_attempts = 0
            else:
                st.session_state.failed_attempts += 1
                st.error(f"Invalid credentials. Attempts remaining: {5 - st.session_state.failed_attempts}")
                st.stop()

# --- PRESENTATION BUILD & VIEW ---

def _download_from_github(local_filename: str, repo_dict: Dict[str, Any]) -> None:
    """
    Downloads a file from GitHub repository.
    
    Args:
        local_filename: The local path where the file will be saved
        repo_dict: Dictionary containing GitHub file information
    """
    token = _get_github_token()
    headers = {"Authorization": f"token {token}"}
    file_path = repo_dict["path"]
    url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/{file_path}?ref={'main'}"
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        file_data = response.json()
        download_url = file_data["download_url"]

        # Download the actual file
        file_response = requests.get(download_url, headers=headers)
        if file_response.status_code == 200:
            with open(local_filename, "wb") as file:
                file.write(file_response.content)
            logging.info(f"Download successful: {file_path}")
        else:
            logging.error(f"Failed to download file: {file_response.status_code}")


def _cache_presentation(presentation: Dict[str, Any]) -> None:
    """
    Downloads and caches presentation files locally.
    
    Args:
        presentation: Dictionary containing presentation data
    """
    if os.path.exists('./slides.md'):
        os.remove('./slides.md')
    if os.path.exists('./assets'):
        shutil.rmtree('./assets')
    os.makedirs('./assets')
    _download_from_github("./slides.md", presentation["slides"])
    for asset in presentation["assets"]:
        _download_from_github(f"./assets/{asset['path'].split('/')[-1]}", asset)  

def _is_port_in_use(port: int) -> bool:
    """
    Checks if a port is currently in use.
    
    Args:
        port: Port number to check
        
    Returns:
        bool: True if port is in use, False otherwise
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def _start_slidev() -> None:
    """
    Build and serve Slidev in production mode.
    Stops any existing Slidev process first.
    """
    _stop_slidev()
    logging.info("Building and starting Slidev")
    
    # Run the build and serve script
    subprocess.Popen(
        ['bash', 'build_and_serve.sh'],
        cwd=str(Path("./").absolute()),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    logging.info("...Slidev build process started")

def _extract_pid(command_output: str) -> Optional[str]:
    """
    Extracts process ID from lsof command output.
    
    Args:
        command_output: Output string from lsof command
        
    Returns:
        Optional[str]: Process ID if found, None otherwise
    """
    lines = command_output.split("\n")[1:-1]
    name_proc_tuples = [re.split(r"\s+", line) for line in lines]
    
    if name_proc_tuples:
        # Return the first PID found
        return name_proc_tuples[0][1]
    else:
        return None
    
def _find_process_using_port(port: int) -> Optional[int]:
    """
    Finds the process using a specific port.
    
    Args:
        port: Port number to check
        
    Returns:
        Optional[int]: Process ID using the port or None if not found
    """
    command = f"lsof -i :{port}"
    result = subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    if result.returncode == 0:
        logging.info("Process using the port found")
        port_pid = _extract_pid(result.stdout)
        if port_pid:
            return int(port_pid)
    else:
        logging.info(f"No process found using port {port}")
    return None


def _stop_slidev() -> None:
    """
    Stops any running Slidev process by finding and killing its PID.
    Continuously checks until port 3030 is free.
    """
    # Check if port is in use
    if _is_port_in_use(3030):
        logging.info("Port 3030 is in use, stopping process")
        
        # Try to find and kill the process
        pid = _find_process_using_port(3030)
        if pid:
            try:
                os.kill(pid, signal.SIGKILL)
                logging.info(f"Killed process with PID {pid}")
            except OSError as e:
                logging.error(f"Failed to kill process: {e}")
        
        # Also try to kill Python HTTP server processes that might be serving on port 3030
        try:
            subprocess.run(
                "pkill -f 'python -m http.server 3030'", 
                shell=True, 
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.DEVNULL
            )
            logging.info("Killed Python HTTP server processes")
        except Exception as e:
            logging.error(f"Failed to kill Python HTTP server: {e}")
            
        # Give processes time to shut down
        time.sleep(1)

def _build_slidev(presentation: Dict[str, Any]) -> None:
    """
    Builds a Slidev presentation on demand.
    
    Args:
        presentation: Dictionary containing presentation data
    
    Raises:
        Exception: If presentation build fails
    """
    try:
        with st.spinner("⏲️ Preparing presentation..."):
            _cache_presentation(presentation)
            _start_slidev()
            counter = 0
            while not _is_port_in_use(3030):
                counter += 0.1
                time.sleep(counter)
                logging.info("Waiting for Slidev to start...")
         
    except Exception as e:
        st.error("Sorry something went wrong")
        raise e # comment for prod

def _generate_presentation_token(presentation_name: str) -> str:
    """
    Generate a secure token for accessing a presentation
    
    Args:
        presentation_name: Name of the presentation this token grants access to
        
    Returns:
        str: The generated token
    """
    import secrets
    import json
    
    # Create a secure random token
    token = secrets.token_urlsafe(32)
    
    # Set expiration time (10 hour from now)
    expiry = int(time.time()) + 36000
    
    # Define token data
    token_data = {
        "presentation": presentation_name,
        "created": int(time.time()),
        "expires": expiry,
        "user": st.session_state.get("user", "unknown")
    }
    
    # Load existing tokens
    tokens_file = os.environ.get("SLIDEV_TOKENS_FILE", "./secrets/slidev_tokens.json")
    try:
        if os.path.exists(tokens_file):
            with open(tokens_file, "r") as f:
                tokens = json.load(f)
        else:
            tokens = {}
    except Exception as e:
        logging.error(f"Error reading tokens file: {e}")
        tokens = {}
    
    # Add the new token
    tokens[token] = token_data
    
    # Save updated tokens
    os.makedirs(os.path.dirname(tokens_file), exist_ok=True)
    with open(tokens_file, "w") as f:
        json.dump(tokens, f)
    
    return token

def view_presentation(presentation: Dict[str, Any]) -> None:
    """
    Opens the Slidev presentation in a new tab with a secure access token.
    
    Args:
        presentation: Dictionary containing presentation data
    """
    # Get the presentation name
    presentations = get_presentations()
    presentation_name = next(name for name, data in presentations.items() if data == presentation)
    
    # Build the slidev presentation
    _build_slidev(presentation)
    
    # Generate a secure access token
    token = _generate_presentation_token(presentation_name)
    
    # Use the domain name instead of localhost for production
    domain = os.environ.get("SLIDEV_HOST_URL", "http://localhost:3030/")
    slidev_url = f"{domain}?access_token={token}"
    logging.info(f"Presentation ready at: {slidev_url}")
    
    # Display instructions to the user
    st.success(f"Presentation '{presentation_name}' is ready.")

    # Create a button that redirects using HTML anchor behavior
    html_button = f"""
    <a href="{slidev_url}" target="_blank" style="
        display: inline-block;
        padding: 0.5rem 1rem;
        background-color: #4CAF50;
        color: white;
        text-align: center;
        text-decoration: none;
        font-size: 16px;
        border-radius: 8px;
        cursor: pointer;
        margin-top: 10px;">
        Open Slides
    </a>
    """
    st.markdown(html_button, unsafe_allow_html=True)


# --- STREAMLIT MAIN APP ---
def main() -> None:
    """
    Main Streamlit application function.
    Handles authentication, fetches presentations, and displays the selected presentation.
    """
    st.title("SlideMaster3000 :rocket:")

    # Authenticate user
    authenticate()

    # Fetch presentations
    if st.session_state.authenticated:
        presentations = get_presentations()
        if not presentations:
            st.error("No presentations found.")
            st.stop()

        # Dropdown to select a presentation
        presentation = st.selectbox("Select Presentation", list(presentations.keys()))


        show = st.button("Show Presentation", use_container_width=True)

        if show:
            view_presentation(presentations[presentation])

if __name__ == '__main__':
    logging.basicConfig(level=LOGLEVEL)
    main()