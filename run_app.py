import os
import sys
import webbrowser
import threading
import time
import uvicorn

def open_browser(url: str):
    time.sleep(1.2)
    print(f"\n[INFO] Dang mo trinh duyet tai: {url}")
    webbrowser.open(url)

if __name__ == "__main__":
    host = "127.0.0.1"
    port = 8000
    url = f"http://{host}:{port}"
    
    print("=" * 65)
    print("  🚀 YOUTUBE TREND & CHANNEL ANALYZER - UNIFIED DASHBOARD")
    print(f"  🌐 May chu san sang: {url}")
    print("=" * 65)
    
    # Auto launch browser in background thread
    threading.Thread(target=open_browser, args=(url,), daemon=True).start()
    
    # Run Uvicorn server with auto-reload
    uvicorn.run("backend.main:app", host=host, port=port, reload=True, log_level="info")
