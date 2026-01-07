
import modal

try:
    print("Testing Volume.from_name with create_if_missing...")
    v = modal.Volume.from_name("test-vol", create_if_missing=True)
    print("Success")
except TypeError as e:
    print("TypeError:", e)
except Exception as e:
    # It might fail to connect or find it, but we just want to know if the ARGUMENT is valid
    print("Other Error:", e)
