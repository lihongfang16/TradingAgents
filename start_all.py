#!/usr/bin/env python3
"""
Start both TradingAgents API and Web UI concurrently.
"""
import subprocess
import sys
import signal
import os

try:
    import colorama
    colorama.init(autoreset=True)
    GREEN = colorama.Fore.GREEN
    CYAN = colorama.Fore.CYAN
    YELLOW = colorama.Fore.YELLOW
    RED = colorama.Fore.RED
    RESET = colorama.Fore.RESET
    BOLD = colorama.Style.BRIGHT
except ImportError:
    _green = _cyan = _yellow = _red = _reset = _bold = ""  # noqa: E741
    GREEN = CYAN = YELLOW = RED = RESET = BOLD = ""  # pyright: ignore[reportConstantRedefinition]

processes = []

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def signal_handler(signum, frame):
    print(f"\n\n{YELLOW}  Shutting down services...{RESET}\n")
    for p in processes:
        p.terminate()
    for p in processes:
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
    print(f"{GREEN}  All services stopped.{RESET}")
    sys.exit(0)

def main():
    global processes
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    # Register signal handler
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    clear_screen()
    
    print(f"\n{BOLD}{CYAN}{'=' * 60}{RESET}")
    print(f"  {BOLD}{CYAN}TradingAgents - AI股票分析系统{RESET}")
    print(f"{'=' * 60}\n")
    
    print(f"{BOLD}  Starting services...{RESET}\n")
    
    # Start API server
    print(f"{GREEN}[API]{RESET}  Starting FastAPI server on port 8000...")
    api_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "webapi.server:app",
         "--host", "0.0.0.0", "--port", "8000", "--reload"],
        cwd=script_dir
    )
    processes.append(api_proc)

    # Start Workers
    worker_count = int(os.getenv("WORKER_COUNT", "2"))
    poll_interval = os.getenv("WORKER_POLL_INTERVAL", "1.0")
    print(f"{GREEN}[WORKER]{RESET} Starting {worker_count} analysis workers (poll={poll_interval}s)...")
    for i in range(worker_count):
        worker_proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "webapi.worker",
                "--worker-id",
                f"worker-{i+1}",
                "--poll-interval",
                poll_interval,
            ],
            cwd=script_dir
        )
        processes.append(worker_proc)

    # Start Web UI
    print(f"{GREEN}[WEB]{RESET}  Starting Streamlit on port 8501...\n")
    web_proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "web/app.py",
         "--server.port=8501", "--server.address=0.0.0.0"],
        cwd=script_dir
    )
    processes.append(web_proc)
    
    # Print URLs
    print(f"{BOLD}{'=' * 60}")
    print(f"  {GREEN}API Server:{RESET}  http://localhost:8000")
    print(f"  {GREEN}Docs:{RESET}       http://localhost:8000/docs")
    print(f"  {GREEN}Web UI:{RESET}     http://localhost:8501")
    print(f"  {GREEN}Workers:{RESET}    {worker_count} running")
    print(f"{'=' * 60}\n")
    
    print(f"{YELLOW}  Press Ctrl+C to stop all services{RESET}\n")
    
    # Wait for processes
    try:
        while True:
            alive = [p for p in processes if p.poll() is None]
            if not alive:
                break
            try:
                alive[0].wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
    except KeyboardInterrupt:
        signal_handler(None, None)

if __name__ == "__main__":
    main()
