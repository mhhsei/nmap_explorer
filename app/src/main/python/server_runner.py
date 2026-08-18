import threading
import socket
from bottle import run

def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def start_server_in_background(host="127.0.0.1", port=8000):
    if is_port_in_use(port):
        import logging
        logging.warning(f"Port {port} is already in use, skipping server start.")
        return None
        
    from server import app
    def _run():
        try:
            run(app, host=host, port=port, quiet=True)
        except OSError as e:
            if "Address already in use" in str(e):
                pass
            else:
                raise e
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t
