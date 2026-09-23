import sys
import os
import time
import subprocess
import threading

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SERVICES = [
    {"name": "API Gateway", "port": 8000, "cmd": [sys.executable, "-m", "uvicorn", "api_gateway.app.main:app", "--host", "0.0.0.0", "--port", "8000"]},
    {"name": "Ingestion Service", "port": 8001, "cmd": [sys.executable, "-m", "uvicorn", "ingestion_service.app.main:app", "--host", "0.0.0.0", "--port", "8001"]},
    {"name": "Retrieval Service", "port": 8002, "cmd": [sys.executable, "-m", "uvicorn", "retrieval_service.app.main:app", "--host", "0.0.0.0", "--port", "8002"]},
    {"name": "LLM Service", "port": 8003, "cmd": [sys.executable, "-m", "uvicorn", "llm_service.app.main:app", "--host", "0.0.0.0", "--port", "8003"]}
]

processes = []

def run_service(service):
    print(f"[*] Starting {service['name']} on port {service['port']}...")
    proc = subprocess.Popen(service["cmd"], cwd=BASE_DIR)
    processes.append(proc)
    proc.wait()

if __name__ == "__main__":
    print("=====================================================")
    print("      KnowledgeAI - Microservices Launcher           ")
    print("=====================================================")
    print("Initializing SQLite Database...")
    from api_gateway.app.db import init_db
    init_db()

    threads = []
    for s in SERVICES:
        t = threading.Thread(target=run_service, args=(s,), daemon=True)
        t.start()
        threads.append(t)
        time.sleep(1)

    print(f"\n[+] All {len(SERVICES)} Microservices are running!")
    for s in SERVICES:
        print(f" - {s['name']:<20} port {s['port']}")
    print("\nPress Ctrl+C to terminate all services.\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping services...")
        for p in processes:
            p.terminate()
        sys.exit(0)
