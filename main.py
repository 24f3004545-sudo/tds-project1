# main.py
import os
import base64
import time
import requests
import datetime 
import json
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import List, Optional
from dotenv import load_dotenv
import google.generativeai as genai
from github import Github, GithubException
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# --- Configuration & Setup ---
# Load environment variables from .env file
load_dotenv()

MY_SECRET = os.getenv("MY_SECRET")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# Check if essential variables are set
if not all([MY_SECRET, GITHUB_TOKEN, GOOGLE_API_KEY]):
    raise ValueError("Missing one or more required environment variables: MY_SECRET, GITHUB_TOKEN, GOOGLE_API_KEY")

# Configure the Gemini client
genai.configure(api_key=GOOGLE_API_KEY)

# Initialize other clients
github_client = Github(GITHUB_TOKEN)
app = FastAPI()

# --- Pydantic Models for Data Validation ---
class Attachment(BaseModel):
    name: str
    url: str

class ProjectRequest(BaseModel):
    email: str
    secret: str
    task: str
    round: int
    nonce: str
    brief: str
    checks: List[str]
    evaluation_url: str
    attachments: Optional[List[Attachment]] = None

# --- Helper Functions ---

def generate_app_code(brief: str, attachments: Optional[List[Attachment]]) -> dict:
    """Uses Google's Gemini LLM to generate the code files for the web app."""
    # ENHANCED LOGGING
    print(f"🤖 Generating code from brief using Gemini (Round {os.environ.get('ROUND', 'N/A')})...")
    print(f"   Brief: {brief[:80]}...") 

    # Decode attachments if they exist
    attachment_content = ""
    if attachments:
        for att in attachments:
            # ENHANCED LOGGING
            print(f"   Decoding attachment: {att.name}")
            try:
                header, encoded = att.url.split(",", 1)
                decoded_data = base64.b64decode(encoded).decode('utf-8')
                attachment_content += f"\n\n--- Attachment: {att.name} ---\n{decoded_data}\n--- End Attachment ---"
            except Exception as e:
                print(f"   🚨 Could not decode attachment {att.name}: {e}")
                attachment_content += f"\n\n--- Attachment: {att.name} (could not be decoded) ---"

    prompt = f"""
    You are an expert web developer. Your task is to generate the complete code for a single-page web application based on a user's brief.
    You must generate all necessary HTML, CSS, and JavaScript.
    - The HTML file MUST be named 'index.html'.
    - Place CSS inside <style> tags in the HTML head.
    - Place JavaScript inside <script> tags at the end of the HTML body.
    - If the brief mentions attached files (like CSV or JSON), assume their content is provided and use it directly.
    - Ensure the generated code is clean, efficient, and directly addresses all requirements in the brief.

    Respond ONLY with a valid JSON object where keys are filenames (e.g., "index.html") and values are the complete string content of the files.
    Do not include ```json markdown delimiters or any other explanatory text in your response.

    Example response format:
    {{
      "index.html": "<!DOCTYPE html><html>...</html>"
    }}

    Here is the user's request:
    Brief: {brief}
    {attachment_content}
    """

    try:
        safety_config = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,   
        }

        model = genai.GenerativeModel('models/gemini-pro-latest')
        start_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"The Gemini model creation started at: {start_time}")
        response = model.generate_content(prompt, safety_settings=safety_config)
        end_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"The Gemini model creation ended at: {end_time}")
        
        raw_text = response.text.strip()
        
        # --- NEW CLEANING LOGIC ---
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:] 
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
        
        # ENHANCED LOGGING
        print("   ✅ Gemini response received and cleaned.") 
        
        # Now, try to parse the cleaned text
        return json.loads(raw_text)

    except Exception as e:
        # ENHANCED LOGGING
        print(f"   🚨 ERROR during Gemini call or JSON parsing: {e}") 
        # Provide a fallback error page
        return {
            "index.html": f"<h1>Error</h1><p>Could not generate the application code. Gemini API error: {e}</p>"
        }

def create_and_populate_repo(repo_name: str, files: dict, brief: str, commit_message: str) -> tuple:
    """Creates a GitHub repo, populates it with files, and returns URLs and commit SHA."""
    print(f"🚀 Creating/Updating GitHub repo: {repo_name}")
    try:
        user = github_client.get_user()
        repo = user.create_repo(repo_name, private=False)
        print(f"   ✅ Repo '{repo.full_name}' created successfully.")
        # ENHANCED LOGGING
        print(f"   Repo URL: {repo.html_url}")
    except GithubException as e:
        if e.status == 422 and "name already exists" in str(e.data):
            print(f"   ⚠️ Repo '{repo_name}' already exists. Will update it.")
            repo = user.get_repo(repo_name)
        else:
            # ENHANCED LOGGING
            print(f"   🚨 FATAL GitHub Creation Error: {e}")
            raise
    
    # --- Add/Update Standard Files ---
    mit_license = "MIT License\n\nCopyright (c) 2025\n\nPermission is hereby granted, free of charge, to any person obtaining a copy...\n" 
    readme_content = f"# {repo_name}\n\n## Project Brief\n{brief}\n\n## Setup\nNo setup required.\n\n## License\nMIT License."
    
    # Add generated files to the list of files to be created/updated
    files_to_commit = {
        "LICENSE": mit_license,
        "README.md": readme_content,
        **files 
    }

    latest_commit_sha = ""
    # ENHANCED LOGGING
    print(f"   Committing {len(files_to_commit)} files...") 

    for file_name, content in files_to_commit.items():
        try:
            existing_file = repo.get_contents(file_name)
            commit = repo.update_file(
                path=file_name,
                message=commit_message,
                content=content,
                sha=existing_file.sha,
            )
            # ENHANCED LOGGING
            print(f"     -> Updated {file_name}")
        except GithubException:
            commit = repo.create_file(
                path=file_name,
                message=commit_message,
                content=content,
            )
            # ENHANCED LOGGING
            print(f"     -> Created {file_name}")
        
        latest_commit_sha = commit['commit'].sha
        print(f"   Current SHA: {latest_commit_sha}") 

    return repo, latest_commit_sha

def enable_and_verify_pages(repo) -> str:
    """Enables GitHub Pages and waits for it to become active."""
    print("🌍 Enabling GitHub Pages...")
    pages_url = f"https://{repo.owner.login}.github.io/{repo.name}/"

    try:
        payload = {
            "source": {"branch": "main", "path": "/"}
        }
        repo._requester.requestJsonAndCheck(
            "POST",
            f"/repos/{repo.full_name}/pages",
            input=payload
        )
        print(f"   ✅ Pages source set to 'main' branch, root directory.")
    except Exception as e:
        print(f"   ⚠️ Could not enable GitHub pages automatically (may already be on): {e}")

    # --- Wait for deployment ---
    print(f"⏳ Waiting for Pages site to go live at {pages_url}...")
    max_retries = 15
    for i in range(max_retries):
        try:
            response = requests.get(pages_url, timeout=10)
            if response.status_code == 200:
                print(f"   ✅ Attempt {i+1}/{max_retries}: Pages site is LIVE!")
                return pages_url
            else:
                # ENHANCED LOGGING
                print(f"   - Attempt {i+1}/{max_retries}: Status code {response.status_code}. Site not ready.")
        except requests.exceptions.RequestException:
            # ENHANCED LOGGING
            print(f"   - Attempt {i+1}/{max_retries}: Connection failed. Retrying...")
        time.sleep(10)

    print("   🚨 GitHub Pages did not become active in time.")
    return pages_url

def notify_evaluation_api(url: str, payload: dict):
    """Sends the final results to the evaluation API with exponential backoff."""
    print(f"📣 Notifying evaluation API at {url}")
    # ENHANCED LOGGING
    print(f"   Payload: {json.dumps(payload, indent=2)}") 
    
    delay = 1
    max_retries = 5
    for i in range(max_retries):
        try:
            response = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=15)
            if response.status_code == 200:
                print("   ✅ Successfully notified evaluation API (Status 200).")
                return
            else:
                # ENHANCED LOGGING
                print(f"   - Attempt {i+1}/{max_retries}: API returned status {response.status_code}. Body: {response.text[:100]}... Retrying...")
        except requests.exceptions.RequestException as e:
            print(f"   - Attempt {i+1}/{max_retries}: Failed to connect to API. Error: {e}. Retrying...")
        time.sleep(delay)
        delay *= 2
    print("🚨 Failed to notify evaluation API after multiple retries.")

def process_project(req: ProjectRequest):
    """The main background task to handle the entire build and deploy process."""
    print("\n" + "="*40)
    print("--- STARTING BACKGROUND PROJECT PROCESS ---")
    # ENHANCED LOGGING
    print(f"   Task: {req.task} | Round: {req.round} | Secret Match: YES") 
    print(f"   Evaluation URL: {req.evaluation_url}")
    print("="*40 + "\n")
    
    generated_files = generate_app_code(req.brief, req.attachments)
    repo_name = req.task
    commit_message = f"feat: Handle round {req.round} requirements"
    
    try:
        repo, commit_sha = create_and_populate_repo(repo_name, generated_files, req.brief, commit_message)
    except Exception as e:
        print(f"\nFATAL: Could not create or populate GitHub repo. Aborting. Error: {e}")
        return
        
    pages_url = enable_and_verify_pages(repo)
    
    notification_payload = {
        "email": req.email, "task": req.task, "round": req.round, "nonce": req.nonce,
        "repo_url": repo.html_url, "commit_sha": commit_sha, "pages_url": pages_url,
    }
    
    notify_evaluation_api(req.evaluation_url, notification_payload)
    
    print("\n" + "="*40)
    print("--- PROJECT PROCESS FINISHED ---")
    print(f"Final Repo URL: {repo.html_url}")
    print(f"Final Pages URL: {pages_url}")
    print("="*40)

# --- API Endpoint ---
@app.post("/build-my-app")
async def handle_build_request(request: ProjectRequest, background_tasks: BackgroundTasks):
    """Accepts a project request, verifies it, and starts the build process in the background."""
    print(f"Received request for task: {request.task}, round: {request.round}")
    
    # Check secret synchronously before starting background task
    if request.secret != MY_SECRET:
        # ENHANCED LOGGING
        print(f"   🚨 Secret Mismatch! Request secret: {request.secret[:8]}... | Expected secret: {MY_SECRET[:8]}...") 
        raise HTTPException(status_code=403, detail="Invalid secret provided.")
    
    background_tasks.add_task(process_project, request)
    return {"status": "success", "message": "Request received and processing started in the background."}

@app.get("/")
def read_root():
    return {"status": "ok", "message": "LLM Code Deployment Agent is running!"}
