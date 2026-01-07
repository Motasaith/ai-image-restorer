# 🧠 Neural Image Restore - Project Documentation

## 1. Project Overview
**Neural Image Restore** is a production-grade AI engine designed for high-quality image upscaling and restoration. It combines **Real-ESRGAN** for general detail enhancement (4x upscaling) and **GFPGAN** for face restoration, providing a robust solution for restoring low-quality, noisy, or old images.

### Key Features
*   **4x Super Resolution**: Upscales images by 400% while hallucinating realistic details.
*   **Face Restoration**: Dedicated GFPGAN model to fix distorted eyes, mouths, and skin textures.
*   **Async Processing**: Queue-based architecture prevents timeouts on slow connections.
*   **Dual Interface**:
    *   **REST API (Port 8001)**: For programmatic access and integration.
    *   **Dashboard (Port 8091)**: User-friendly web interface with Before/After comparison.
*   **Production Ready**: Handles large files, concurrent requests (via queue), and disk cleanup.
*   **Multiple Deployment Options**: Supports Local, Docker (VPS), and Serverless (Modal) deployments.

---

## 2. System Architecture

The system is built as a micro-service using **Python 3.10** and **FastAPI**.

### Components
1.  **FastAPI Server (`app/main.py`)**:
    *   Handles HTTP requests (Uploads, Status checks).
    *   Manages the specialized background threads.
    *   Serves static assets for the dashboard.
2.  **Worker Thread**:
    *   Continuously monitors a generic `queue.Queue`.
    *   Loads the heavy AI models (`app/restoration.py`) only once to save overhead.
    *   Processes images sequentially to avoid OOM (Out of Memory) errors on limited hardware.
    *   Saves results to a persisting `processed_images` directory.
3.  **Janitor Thread**:
    *   Runs every 30 minutes.
    *   Deletes uploaded and processed files older than 1 hour to prevent disk overflow.
4.  **Static Dashboard**:
    *   Served via `http.server` (or FastAPI static mount) depending on the run mode.
    *   Provides a simple drag-and-drop UI to interact with the API.

### Directory Structure
```
ai-restorer/
├── app/
│   ├── main.py              # Core API logic & Worker loops
│   ├── restoration.py       # AI Model Wrapper (RealESRGAN + GFPGAN)
│   └── static/              # Dashboard HTML/CSS/JS
├── modal_app.py             # Serverless deployment config for Modal.com
├── run.py                   # Unified entry point (Auto-detects OS)
├── evaluate.py              # Quality metrics script (SSIM/PSNR)
├── Dockerfile               # Container definition
├── docker-compose.yml       # Production orchestration
├── weights/                 # Binary model files (Must be downloaded manually)
├── requirements.txt         # Python dependencies
└── .env                     # Configuration secrets
```

---

## 3. Installation & Setup

### Prerequisites
*   Python 3.10+
*   NVIDIA GPU (Recommended for speed, but works on CPU)
*   4GB+ RAM

### 1. Model Weights
**Critical**: You must manually download the model weights and place them in the `weights/` directory.
1.  `RealESRGAN_x4plus.pth`
2.  `GFPGANv1.3.pth`

### 2. Local Development
1.  **Clone & Venv**:
    ```bash
    git clone <repo_url>
    cd ai-restorer
    python -m venv venv
    # Windows: venv\Scripts\activate
    # Linux: source venv/bin/activate
    ```
2.  **Install Dependencies**:
    ```bash
    pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118  # If using GPU
    pip install -r requirements.txt
    ```
    *Note: If you encounter `ImportError: functional_tensor`, see Troubleshooting.*

3.  **Run**:
    ```bash
    python run.py
    ```
    *   Dashboard: `http://localhost:8091`
    *   API: `http://localhost:8001`

---

## 4. Deployment

### Option A: Docker (VPS / Production)
Recommended for long-running servers.
1.  **Build**:
    ```bash
    docker build -t ai-restorer .
    ```
2.  **Run (Docker Compose)**:
    ```bash
    docker compose up -d
    ```
    *   Persists images in `./processed_images`.
    *   Limits memory usage to prevent server crashes.

### Option B: Modal (Serverless)
Recommended for high-scale, GPU-on-demand usage without managing servers.
1.  **Install Modal**:
    ```bash
    pip install modal
    modal setup
    ```
2.  **Deploy**:
    ```bash
    modal deploy modal_app.py
    ```
    *   Configures a persistent Volume for storage.
    *   Auto-scales GPU containers.

---

## 5. API Reference

### Headers
*   `X-API-KEY`: Required if `API_KEY` is set in `.env`.

### Endpoints

#### `POST /enhance`
Submit images for processing.
*   **Body**: `multipart/form-data`
    *   `files`: List of images.
    *   `face_enhance`: `true/false` (Default: true)
*   **Response**:
    ```json
    {
        "job_id": "uuid-string",
        "status": "queued",
        "queue_position": 1
    }
    ```

#### `GET /status/{job_id}`
Poll this endpoint to check progress.
*   **Response (Processing/Queued)**:
    ```json
    { "status": "processing", "results": [] }
    ```
*   **Response (Completed)**:
    ```json
    {
        "status": "completed",
        "results": [
            {
                "original_filename": "photo.jpg",
                "url": "/processed/uuid-result.jpg"
            }
        ]
    }
    ```

---

## 6. Configuration (.env)

Create a `.env` file in the root directory:

| Variable | Description | Default |
| :--- | :--- | :--- |
| `API_KEY` | Secret key for API security. | *(None/Open)* |
| `MAX_FILE_SIZE_MB` | Max upload size per image. | `10` |
| `UPLOAD_FOLDER` | Temp storage for uploads. | `temp_uploads` |
| `PROCESSED_FOLDER` | storage for outputs. | `processed_images` |

---

## 7. Quality Evaluation

Run `evaluate.py` to generate a quality report comparing original vs. restored images.
*   **Metrics**:
    *   **SSIM**: Structural Similarity (Sharpness/Structure preservation).
    *   **PSNR**: Peak Signal-to-Noise Ratio.
*   **Usage**:
    1.  Place test images in `test_inputs/`.
    2.  Run `python evaluate.py`.
    3.  Results saved to `test_results/` and stats printed to console.

---

## 8. Troubleshooting

### `ImportError: cannot import name 'functional_tensor' from 'torchvision.transforms'`
*   **Cause**: Incompatibility between newer `torchvision` and `basicsr`.
*   **Fix**:
    Open `basicsr/data/degradations.py` (in your site-packages) and change:
    ```python
    from torchvision.transforms.functional_tensor import rgb_to_grayscale
    ```
    to:
    ```python
    from torchvision.transforms.functional import rgb_to_grayscale
    ```
    *(The Dockerfile does this automatically)*.

### CUDA Out of Memory
*   **Fix**: Edit `app/restoration.py` and reduce the `tile` size in `RealESRGANer`:
    ```python
    tile=200  # Default is 400. Lower to 100-200 for <4GB VRAM.
    ```

### Server Crash on VPS
*   **Cause**: System ran out of RAM.
*   **Fix**: Enable Swap or restrict Docker memory using `deploy.resources.limits.memory` in `docker-compose.yml`.

---

## 9. AI Image Restoration Cost & Performance Analysis (Modal.com)

**(GFPGAN on Modal GPU Infrastructure)**

### 1. Purpose of This Analysis
This section analyzes the **performance** and **cost** of running the restoration engine on Modal.com's serverless GPU infrastructure. The goal is to provide **transparent, defensible numbers** for planning and budgeting.

### 2. Experimental Setup
*   **Model**: GFPGAN (face restoration) + Real-ESRGAN
*   **Infrastructure**: Modal.com (Serverless GPU)
*   **GPU Types**: A10G (Performance) vs T4 (Budget)
*   **Workload**: Single-image inference (No batching)

### 3. Measured Performance
Timings represent **end-to-end inference time** (including overhead).

| Image Size | Processing Time (A10G) | Processing Time (T4 Est.) |
| :--- | :--- | :--- |
| **~90 KB** | ~2 seconds | ~3–4 seconds |
| **~276 KB** | ~7 seconds | ~10–14 seconds |

*   **A10G** is approx **1.5x - 2x faster** than T4.

### 4. Cost Analysis
Modal GPU pricing (approximate):
*   **T4**: ~$0.00018 / sec
*   **A10G**: ~$0.00030 / sec

#### Cost Per Image & Throughput ($1 Budget)

| GPU | Image Size | Cost per Image | Images per $1 |
| :--- | :--- | :--- | :--- |
| **A10G** | Small (~90KB) | $0.0006 | **~1,660** |
| **A10G** | Medium (~276KB) | $0.0021 | **~470** |
| **T4** | Small (~90KB) | ~$0.0006 | **~1,390 - 1,850** |
| **T4** | Medium (~276KB) | ~$0.0022 | **~400 - 550** |

### 5. Key Insights
> **Despite speed differences, T4 and A10G result in similar cost per image.**

*   **T4**: Cheaper per second, but slower (burns more seconds).
*   **A10G**: More expensive per second, but faster (burns fewer seconds).
*   **Conclusion**: GPU choice affects **latency** (user experience), not drastically the **cost**.

### 6. Recommendations
1.  **User-Facing (API)**: Use **A10G** for lowest latency.
2.  **Background Jobs**: Use **T4** if available, mainly to save high-end GPUs for others, though cost is similar.
3.  **Budgeting**: Plan for **~400 - 1,200 images per $1** depending on image size mix.

