
import threading
import time
import random
import sys
import os
from pathlib import Path

# Add root to sys.path
sys.path.append(str(Path(__file__).parent.parent))

from utils.diagnostic_logger import get_diagnostic_logger

def worker(worker_id, num_events):
    logger = get_diagnostic_logger()
    for i in range(num_events):
        try:
            logger.log_ui_event(
                action="stress_test_click",
                label=f"Worker {worker_id}",
                metadata={"event_num": i, "random_val": random.random()}
            )
            if i % 10 == 0:
                print(f"Worker {worker_id}: Logged {i} events")
            # Minimal sleep to simulate rapid but slightly staggered clicks
            time.sleep(random.uniform(0.01, 0.05))
        except Exception as e:
            print(f"Worker {worker_id} FAILED at event {i}: {e}")

def run_stress_test(num_workers=10, events_per_worker=50):
    print(f"🚀 Starting Stress Test: {num_workers} workers, {events_per_worker} events each")
    threads = []
    start_time = time.time()
    
    for i in range(num_workers):
        t = threading.Thread(target=worker, args=(i, events_per_worker))
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()
        
    end_time = time.time()
    total_events = num_workers * events_per_worker
    duration = end_time - start_time
    print("-" * 40)
    print(f"✅ Stress Test Completed!")
    print(f"Total Events: {total_events}")
    print(f"Total Duration: {duration:.2f}s")
    print(f"Throughput: {total_events/duration:.2f} events/sec")
    print("-" * 40)

if __name__ == "__main__":
    run_stress_test()
