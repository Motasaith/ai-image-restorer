import modal
import os
import shutil
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# Define the Modal App
app = modal.App("motasaith-ai-restorer")

# Define the Image
# We include files directly in the image to avoid Mount class compatibility issues
image = (
    modal.Image.debian_slim()
    .apt_install("libgl1", "libglib2.0-0")
    .pip_install_from_requirements("requirements.txt")
    .add_local_dir("app", remote_path="/root/app")
    .add_local_dir("gfpgan", remote_path="/root/gfpgan")
    .add_local_dir("weights", remote_path="/root/weights")
    .add_local_file(".env", remote_path="/root/.env")
)

# Define a Volume for persisting processed images
volume = modal.Volume.from_name("motasaith-restorer-volume", create_if_missing=True)

# Configuration
PROCESSED_DIR = "/data/processed"
UPLOAD_DIR = "/data/uploads"

@app.function(
    image=image,
    gpu="any",
    volumes={"/data": volume},
    timeout=600,
    max_containers=1, # Renamed from concurrency_limit
)
@modal.asgi_app()
def fastapi_app():
    # Import here to ensure it runs inside the container
    from app.main import app as web_app
    
    # Setup directories
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    
    # Create symlinks if they don't exist
    if not os.path.exists("processed_images"):
        os.symlink(PROCESSED_DIR, "processed_images")
        
    if not os.path.exists("temp_uploads"):
        os.symlink(UPLOAD_DIR, "temp_uploads")

    return web_app
