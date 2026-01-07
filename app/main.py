from fastapi import FastAPI, File, UploadFile, HTTPException, Depends, Security
from fastapi.security.api_key import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from typing import List
import cv2
import numpy as np
import os
import uuid
import queue
import threading
import time
import shutil
from dotenv import load_dotenv  # REQUIRED: pip install python-dotenv
from app.restoration import ImageRestorer

# --- CONFIGURATION ---
# Load environment variables from .env file
load_dotenv()

# 1. SECURITY: Load API Key from environment or use a safe fallback warning
API_KEY = os.getenv("API_KEY")
API_KEY_NAME = "X-API-KEY"

if not API_KEY:
    print("⚠️ WARNING: API_KEY not set in .env file! Security is disabled or using default.")

# 2. LIMITS: Prevent RAM explosion
# Load max size from env, default to 10MB if missing
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", 10))
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

# 3. STORAGE
# 3. STORAGE
UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "temp_uploads")
PROCESSED_FOLDER = os.getenv("PROCESSED_FOLDER", "processed_images")
os.makedirs(PROCESSED_FOLDER, exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = FastAPI(title="AI Image Restoration API - Production")

# CORS (Adjust allow_origins in production if you have a specific frontend domain)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.responses import FileResponse

app.mount("/processed", StaticFiles(directory=PROCESSED_FOLDER), name="processed")
# Serve other static assets if any exist (e.g., css/js referenced by index.html)
# app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def serve_dashboard():
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Dashboard not found"}

# --- GLOBAL VARIABLES ---
restorer = None
job_queue = queue.Queue()
job_store = {}

# --- SECURITY DEPENDENCY ---
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

async def get_api_key(api_key_header: str = Security(api_key_header)):
    """Validates the API Key header"""
    if api_key_header == API_KEY:
        return api_key_header
    raise HTTPException(
        status_code=403, 
        detail="Could not validate credentials. Please provide valid X-API-KEY header."
    )

# --- BACKGROUND TASKS ---

def cleanup_loop():
    """
    JANITOR TASK:
    Runs every 30 minutes. Deletes files older than 1 hour.
    Prevents the VPS disk from filling up.
    """
    print("🧹 Cleanup Janitor Started")
    while True:
        time.sleep(1800) # Sleep 30 minutes
        print("🧹 Running Disk Cleanup...")
        now = time.time()
        expiration = 3600 # 1 Hour
        
        folders = [UPLOAD_FOLDER, PROCESSED_FOLDER]
        for folder in folders:
            if not os.path.exists(folder): continue
            
            for filename in os.listdir(folder):
                file_path = os.path.join(folder, filename)
                try:
                    # Check if file is older than 1 hour
                    if os.path.isfile(file_path) and os.stat(file_path).st_mtime < now - expiration:
                        os.remove(file_path)
                        # Optionally remove from job_store here if memory is tight
                except Exception as e:
                    print(f"⚠️ Error deleting {file_path}: {e}")

def worker_loop():
    """
    WORKER TASK:
    Processes images one-by-one from the queue.
    """
    global restorer
    print("👷 Worker Thread Started - Waiting for jobs...")
    
    # Load model inside the worker thread (or globally before loop)
    if restorer is None:
        print("--- Loading AI Models (Worker) ---")
        try:
            restorer = ImageRestorer()
            print("--- Models Loaded Successfully ---")
        except Exception as e:
            print(f"CRITICAL MODEL LOAD ERROR: {e}")
            return

    while True:
        # Blocks here until a job is available
        job_data = job_queue.get()
        job_id = job_data['job_id']
        
        try:
            print(f"⚙️ Processing Job: {job_id}")
            if job_id in job_store:
                job_store[job_id]['status'] = 'processing'
            
            results = []
            file_paths = job_data['file_paths']
            filenames = job_data['filenames']
            face_enhance = job_data['face_enhance']

            for i, temp_path in enumerate(file_paths):
                try:
                    if not os.path.exists(temp_path):
                        continue

                    img = cv2.imread(temp_path, cv2.IMREAD_COLOR)
                    if img is None:
                        raise ValueError("Could not decode image")

                    # Heavy AI Processing
                    processed_img = restorer.process_image(img, face_enhance=face_enhance)

                    if processed_img is not None:
                        out_name = f"{uuid.uuid4()}.jpg"
                        out_path = os.path.join(PROCESSED_FOLDER, out_name)
                        cv2.imwrite(out_path, processed_img)
                        
                        results.append({
                            "original_filename": filenames[i],
                            "url": f"/processed/{out_name}"
                        })
                except Exception as inner_e:
                    print(f"Error on file {filenames[i]}: {inner_e}")
                finally:
                    # Delete Input File Immediately after processing to save space
                    if os.path.exists(temp_path):
                        os.remove(temp_path)

            if job_id in job_store:
                job_store[job_id]['results'] = results
                job_store[job_id]['status'] = 'completed'
            print(f"✅ Job {job_id} Completed")

        except Exception as e:
            print(f"❌ Job {job_id} Failed: {e}")
            if job_id in job_store:
                job_store[job_id]['status'] = 'failed'
                job_store[job_id]['error'] = str(e)
        
        finally:
            job_queue.task_done()

# --- LIFECYCLE ---
@app.on_event("startup")
async def startup_event():
    # 1. Start Processing Worker
    threading.Thread(target=worker_loop, daemon=True).start()
    # 2. Start Disk Cleanup Janitor
    threading.Thread(target=cleanup_loop, daemon=True).start()

# --- ENDPOINTS ---

@app.post("/enhance", dependencies=[Depends(get_api_key)])
async def submit_job(
    files: List[UploadFile] = File(...), 
    face_enhance: bool = True
):
    """
    Secured Endpoint. Requires Header 'X-API-KEY'.
    Validates file size before queueing.
    """
    job_id = str(uuid.uuid4())
    temp_file_paths = []
    original_filenames = []
    
    try:
        for file in files:
            if file.content_type.startswith('image/'):
                ext = file.filename.split('.')[-1]
                temp_filename = f"{job_id}_{uuid.uuid4()}.{ext}"
                temp_path = os.path.join(UPLOAD_FOLDER, temp_filename)
                
                # Write to disk
                with open(temp_path, "wb") as buffer:
                    shutil.copyfileobj(file.file, buffer)
                
                # VALIDATION: Check file size immediately
                file_size = os.path.getsize(temp_path)
                if file_size > MAX_FILE_SIZE_BYTES:
                    os.remove(temp_path) # Delete immediately
                    raise HTTPException(
                        status_code=400, 
                        detail=f"File {file.filename} exceeds {MAX_FILE_SIZE_MB}MB limit."
                    )
                
                temp_file_paths.append(temp_path)
                original_filenames.append(file.filename)
                
    except HTTPException as he:
        # Cleanup any files already written for this failed job
        for p in temp_file_paths:
            if os.path.exists(p): os.remove(p)
        raise he
    except Exception as e:
        for p in temp_file_paths:
            if os.path.exists(p): os.remove(p)
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")

    if not temp_file_paths:
         raise HTTPException(status_code=400, detail="No valid images found.")

    # Create Job
    job_data = {
        "job_id": job_id,
        "file_paths": temp_file_paths,
        "filenames": original_filenames,
        "face_enhance": face_enhance
    }

    job_store[job_id] = { 
        "status": "queued", 
        "queue_position": job_queue.qsize() + 1,
        "results": [] 
    }
    
    job_queue.put(job_data)

    return {
        "job_id": job_id,
        "status": "queued",
        "message": "Ticket created.",
        "queue_position": job_queue.qsize()
    }

@app.get("/status/{job_id}")
async def check_status(job_id: str):
    if job_id not in job_store:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    return job_store[job_id]