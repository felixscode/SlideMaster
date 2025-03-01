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
STREAMLIT_PASSWORD_FILE = Path("./secrets/streamlit_passwords")
GITHUB_TOKEN_FILE = Path("./secrets/github_token")
GITHUB_USER = "felixscode"
GITHUB_REPO = "slides"
LOGLEVEL = logging.INFO
SLIDEV_PID_ENV_VAR = "SLIDEV_PID"


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
    items_to_ignore = ["README.md"]
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
def _get_passwords() -> List[str]:
    """
    Reads valid passwords from a file.
    
    Returns:
        List[str]: List of valid passwords
    """
    with open(STREAMLIT_PASSWORD_FILE, "r") as f:
        return f.read().splitlines()

def authenticate() -> None:
    """
    Handles user authentication with password input.
    Sets authenticated state in Streamlit session state.
    """
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated:
        password = st.text_input("Password", type="password")
        if st.button("Login"):
            valid_passwords = _get_passwords()
            if password in valid_passwords:
                st.session_state.authenticated = True  # Store authentication state
            else:
                st.error("Invalid credentials.")
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
            with open(file_path.split("/")[-1], "wb") as file:
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
    Start the Slidev server if not already running.
    Stops any existing Slidev process first.
    """
    _stop_slidev()
    logging.info("Starting Slidev")
    subprocess.Popen(
        ['npx', 'slidev', '--remote'],
        cwd=str(Path("./").absolute()),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    st.info("Slidev started...")
    logging.info("...Slidev started")

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
    while _is_port_in_use(3030):
        pid = _find_process_using_port(3030)
        if pid:
            os.kill(pid, signal.SIGKILL)
        time.sleep(0.5)

def _build_slidev(presentation: Dict[str, Any]) -> None:
    """
    Builds a Slidev presentation on demand.
    
    Args:
        presentation: Dictionary containing presentation data
    
    Raises:
        Exception: If presentation build fails
    """
    st.info("downloading files from github...")
    try:
        st.progress(0)
        _cache_presentation(presentation)
        st.progress(0.3)
        _start_slidev()
        st.progress(0.6)
        counter = 0.6
        while not _is_port_in_use(3030):
            time.sleep(0.1)
            counter += 0.05
            st.progress(min(1, counter))
    except Exception as e:
        st.error("Sorry something went wrong")
        raise e # comment for prod

def view_presentation(presentation: Dict[str, Any]) -> None:
    """
    Embeds the Slidev presentation into Streamlit using an iframe.
    
    Args:
        presentation: Dictionary containing presentation data
    """
    _build_slidev(presentation)
    slidev_url = "http://localhost:3030/"
    st.markdown("""
        <style>
            /* Hide Streamlit header and menu */
            header {display: none !important;}
            .st-emotion-cache-1v0mbdj {display: none !important;}  /* Hides the menu */

            /* Hide footer */
            footer {visibility: hidden;}

            /* Ensure iframe takes full screen */
            .fullscreen-iframe {
                position: fixed;
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%);
                width: 100vw;
                height: 100vh;
                border: none;
                z-index: 999;
            }
        </style>
    """, unsafe_allow_html=True)

    st.markdown(f"""
        <iframe src="{slidev_url}" class="fullscreen-iframe" 
            allowfullscreen 
            allow="fullscreen"
        ></iframe>
    """, unsafe_allow_html=True)


# --- STREAMLIT MAIN APP ---
def main() -> None:
    """
    Main Streamlit application function.
    Handles authentication, fetches presentations, and displays the selected presentation.
    """
    st.title("SlideMaster :rocket:")

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

        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            show = st.button("Show Presentation", use_container_width=True)

        if show:
            view_presentation(presentations[presentation])

if __name__ == '__main__':
    logging.basicConfig(level=LOGLEVEL)
    main()