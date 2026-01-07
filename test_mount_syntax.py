
import modal.mount

try:
    print("Testing Mount syntax...")
    m = modal.mount.Mount().add_local_dir("app", remote_path="/root/app")
    print("Success:", m)
except Exception as e:
    print("Error:", e)
