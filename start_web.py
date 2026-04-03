#!/usr/bin/env python3
"""
Start Streamlit web UI for TradingAgents.
"""
import subprocess
import sys
import signal
import os

def main():
    # Get the directory of this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    print("\n" + "=" * 60)
    print("  TradingAgents Web UI")
    print("=" * 60)
    print("\n  Web UI:     http://localhost:8501")
    print("  API:        http://localhost:8000")
    print("\n  Press Ctrl+C to stop")
    print("=" * 60 + "\n")
    
    # Run streamlit
    cmd = [
        sys.executable, "-m", "streamlit", "run",
        "web/app.py",
        "--server.port=8501",
        "--server.address=0.0.0.0"
    ]
    
    try:
        subprocess.run(cmd, cwd=script_dir)
    except KeyboardInterrupt:
        print("\n\n  Shutting down Web UI...")
        sys.exit(0)

if __name__ == "__main__":
    main()
