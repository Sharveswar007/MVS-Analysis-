"""
Desktop App Launcher for TLP Result Finder
Manages FastAPI server and opens browser window
"""
import time
import webbrowser
import threading
import socket
from pathlib import Path
import uvicorn

def find_available_port(start_port=5000, end_port=9000):
    """Find an available port"""
    for port in range(start_port, end_port):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(('0.0.0.0', port))
            sock.close()
            return port
        except OSError:
            continue
    return None

def wait_for_server(host, port, timeout=15):
    """Wait for server to be ready"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex((host, port))
            sock.close()
            if result == 0:
                return True
        except:
            pass
        time.sleep(0.5)
    return False

def start_app():
    """Start the FastAPI server and open browser"""
    
    try:
        # Import main FastAPI app
        from main import app
        
        # Find an available port
        port = find_available_port()
        if not port:
            print("ERROR: Could not find an available port!")
            return
        
        print(f"Using port {port}...")
        
        # Create config for uvicorn
        config = uvicorn.Config(
            app=app,
            host="0.0.0.0",
            port=port,
            log_level="error",  # Only show errors
            access_log=False,
            use_colors=False,
            lifespan="off"
        )
        server = uvicorn.Server(config)
        
        # Start server in background thread
        server_thread = threading.Thread(target=server.run, daemon=True)
        server_thread.start()
        
        # Wait for server to be ready
        if wait_for_server("localhost", port):
            # Open browser
            print(f"Opening browser at http://localhost:{port}")
            webbrowser.open(f"http://localhost:{port}")
        else:
            print(f"ERROR: Server failed to start within 15 seconds on port {port}.")
        
        # Keep running
        try:
            server_thread.join()
        except KeyboardInterrupt:
            pass
    except Exception as e:
        import traceback
        print(f"FATAL ERROR: {e}")
        print(traceback.format_exc())

if __name__ == "__main__":
    start_app()
