import sys
import os
import subprocess

agents_num = input("how much agents do you want to use?> ")
print("agents system is still in building proccess. QUITING")
sys.exit(0)

python_exe = sys.executable

server_process = subprocess.Popen([python_exe, "leader_agent/leader.py"])
main_process = subprocess.Popen([python_exe, "worker_agents/worker_agent_1.py"])

try:
    server_process.wait()
    main_process.wait()
    
except KeyboardInterrupt:
    print("\nStopping scripts...")

    server_process.terminate()
    main_process.terminate()
