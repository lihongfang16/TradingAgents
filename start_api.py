#!/usr/bin/env python3
"""
Start FastAPI server for TradingAgents Web API.
"""
import subprocess
import sys
import signal
import os
import platform

# Windows-specific asyncio fix: must be set BEFORE any asyncio imports
# This prevents [Errno 22] Invalid argument errors with ThreadPoolExecutor
if platform.system() == "Windows":
    import asyncio
    # Use WindowsSelectorEventLoopPolicy to avoid issues with ProactorEventLoop
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

def main():
    # Get the directory of this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    print("\n" + "=" * 60)
    print("  TradingAgents API Server")
    print("=" * 60)
    print("\n  API Server:  http://localhost:8000")
    print("  Docs:       http://localhost:8000/docs")
    print("  ReDoc:      http://localhost:8000/redoc")
    print("\n  Press Ctrl+C to stop")
    print("=" * 60 + "\n")
    
    # Run uvicorn
    cmd = [
        sys.executable, "-m", "uvicorn",
        "webapi.server:app",
        "--host", "0.0.0.0",
        "--port", "8001",
        "--reload"
    ]
    
    try:
        subprocess.run(cmd, cwd=script_dir)
    except KeyboardInterrupt:
        print("\n\n  Shutting down API server...")
        sys.exit(0)

if __name__ == "__main__":
    main()
