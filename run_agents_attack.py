import sys
import os
import subprocess
import argparse

def main():
    parser = argparse.ArgumentParser(description="PTAI multi-agent attack launcher")
    parser.add_argument("--target-ip", required=True, help="Target IP address")
    parser.add_argument("--worker-num", type=int, required=True, help="Number of worker agents to spawn")
    args = parser.parse_args()
    
    if args.worker_num > 5:
        print(f"max --worker-num is 5. you demanded: {args.worker_num}")
        sys.exit(1)
        
    python_exe = sys.executable

    print(f"[+] Starting leader against {args.target_ip}...")
    leader_process = subprocess.Popen(
        [python_exe, "leader_agent/leader.py", args.target_ip],
        stdout=subprocess.PIPE,
        text=True,
        bufsize=1
    )

    print("[+] Waiting for leader to finish initial scan and start listening...")
    for line in leader_process.stdout:
        print(line, end="")
        if "Server is listening" in line:
            break

    worker_processes = []
    for i in range(1, args.worker_num + 1):
        worker_file = f"worker_agents/worker_agent_{i}.py"
        wp = subprocess.Popen([python_exe, worker_file])
        worker_processes.append(wp)

    try:
        leader_process.wait()
        for wp in worker_processes:
            wp.wait()

    except KeyboardInterrupt:
        print("\nStopping all agents...")
        leader_process.terminate()
        for wp in worker_processes:
            wp.terminate()

if __name__ == "__main__":
    main()