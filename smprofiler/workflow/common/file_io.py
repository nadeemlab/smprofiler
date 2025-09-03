"""Basic file analysis functionality."""
import hashlib

def compute_sha256(input_file):
    buffer_size = 65536
    sha = hashlib.sha256()
    with open(input_file, 'rb') as file:
        while True:
            data = file.read(buffer_size)
            if not data:
                break
            sha.update(data)
    return sha.hexdigest()
