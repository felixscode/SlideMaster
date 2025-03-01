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

# Configuration
STREAMLIT_PASSWORD_FILE = Path("./secrets/streamlit_passwords")
GITHUB_TOKEN_FILE = Path("./secrets/github_token")
GITHUB_USER = "felixscode"
GITHUB_REPO = "slides"
LOGLEVEL = logging.INFO
SLIDEV_PID_ENV_VAR = "SLIDEV_PID"


# --- ASYNC API CALLS ---
def get_github_token():
    with open(GITHUB_TOKEN_FILE, "r") as f:
        return f.read().strip()

async def fetch_github_data():
    """Fetches the folder structure from GitHub repository asynchronously."""
    token = get_github_token()
    url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/git/trees/main?recursive=1"
    headers = {"Authorization": f"token {token}"}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                st.error(f"GitHub API Error: {response.status}, {await response.text()}")
                return []
            return await response.json()

@st.cache_data
def get_github_data():
    """Runs the async function synchronously and caches the result."""
    return asyncio.run(fetch_github_data())

def match_pres_data(gh_data):
    """Extracts the slides and assets for each presentation."""
    items_to_ignore = ["README.md"]
    for item in gh_data["tree"]:
        if "/" not in item["path"] and item["path"] not in items_to_ignore:
            name = item["path"]
            slides_path_name = f"{name}/slides.md"
            asset_path_name = f"{name}/assets/"
            assets = list(filter(lambda x: x["path"].startswith(asset_path_name),gh_data["tree"]))
            slides = next((x for x in gh_data["tree"] if x["path"] == slides_path_name),None)
            if slides:
                yield name, {"slides":slides,"assets":assets}

 
def get_presentations():
    """Extracts unique folder names from GitHub API response."""
    slide_data = get_github_data()
    if not slide_data or "tree" not in slide_data:
        return []
    
    presentations = dict(match_pres_data(slide_data))

    return presentations if presentations else {}

# --- AUTHENTICATION ---
def get_passwords():
    """Reads valid passwords from a file."""
    with open(STREAMLIT_PASSWORD_FILE, "r") as f:
        return f.read().splitlines()

def authenticate():
    """Handles user authentication with password input."""
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated:
        password = st.text_input("Password", type="password")
        if st.button("Login"):
            valid_passwords = get_passwords()
            if password in valid_passwords:
                st.session_state.authenticated = True  # Store authentication state
            else:
                st.error("Invalid credentials.")
                st.stop()

# --- PRESENTATION BUILD & VIEW ---

def download_from_github(local_filename,repo_dict):
    token = get_github_token()
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
            print("Download successful!")
        else:
            print("Failed to download file:", file_response.status_code)

    

def cache_presentation(presentation:dict):
    if os.path.exists('./slides.md'):
        os.remove('./slides.md')
    if os.path.exists('./assets'):
        shutil.rmtree('./assets')
    os.makedirs('./assets')
    download_from_github("./slides.md",presentation["slides"])
    for asset in presentation["assets"]:
        download_from_github(f"./assets/{asset["path"].split("/")[-1]}",asset)  

def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def start_slidev():
    """Start the Slidev server if not already running."""

    stop_slidev()
    logging.info("Starting Slidev")
    proc = subprocess.Popen(
        ['npx', 'slidev', '--remote'],
        cwd=str(Path("./").absolute()),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    st.info("Slidev started...")
    logging.info("...Slidev started")

def extract_pid(command_output):
    # Regex pattern to match the PID from the command output
    lines = command_output.split("\n")[1:-1]
    name_proc_tuples = [re.split(r"\s+", line) for line in lines]
    
    if name_proc_tuples:
        # Return the first PID found
        return name_proc_tuples[0][1]
    else:
        return None
    
def find_process_using_port(port):
    command = f"lsof -i :{port}"
    result = subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    if result.returncode == 0:
        print("Process using the port:")
        port = extract_pid(result.stdout)
        print(extract_pid(result.stdout))
        return int(port)
    else:
        print(f"No process found using port {port}")


def stop_slidev():
    """Stop Slidev using the PID stored in the environment variable"""
    while is_port_in_use(3030):
        pid = find_process_using_port(3030)
        if pid:
            os.kill(pid, signal.SIGKILL)
        time.sleep(0.5)

def build_slidev(presentation: dict):
    """Builds a Slidev presentation on demand."""
    st.info(f"downloading files from github...")
    try:
        st.progress(0)
        cache_presentation(presentation)
        st.progress(0.3)
        start_slidev()
        st.progress(0.6)
        counter = 0.6
        while not is_port_in_use(3030):
            time.sleep(0.1)
            counter += 0.05
            st.progress(min(1,counter))
    except Exception as e:
        st.error(f"Sorry something went wrong")
        raise e # comment for prod

def view_presentation(presentation):
    """Embeds the Slidev presentation into Streamlit using an iframe."""
    build_slidev(presentation)
    slidev_url = f"http://localhost:3030/"
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
def main():
    st.title("Felix's Presentations :fire:")

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

    
