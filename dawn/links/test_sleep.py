#!/usr/bin/env python3
import time
import sys
import json
import os

def main():
    print("Starting sleep test...")
    for i in range(10):
        print(f"Step {i+1}/10: Working...")
        sys.stdout.flush()
        time.sleep(1)
    print("Sleep test complete.")

if __name__ == "__main__":
    main()
