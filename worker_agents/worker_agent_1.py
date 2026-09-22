import subprocess
import time
import os
from groq import Groq
from dotenv import load_dotenv
import shlex
import sys
import json
import socket
import ssl

class WorkerAgent:
    def __init__(self, worker_id, host='127.0.0.1', port=9999):
        self.worker_id = worker_id
        self.host = host
        self.port = port
        self.sock = None
        self.session_history = []
        load_dotenv()
        self.api_key = os.getenv("GROQ_API_KEY")
        self.client = Groq(api_key=self.api_key)
        self.system_prompt = """You are an autonomous penetration testing worker agent running on Kali Linux, operating as part of a multi-agent team led by a coordinating leader AI.
            You will be given, for each task: instructions, suggested_tools, look_for, stage, and your own session history (past commands/outputs).

            Your job: decide the SINGLE next command (or a chain) that makes real progress on the current task.

            Rules:
            - Read your own history carefully. NEVER repeat a command that already failed or already gave you the info you needed.
            - Stay focused on the current task's instructions and look_for.
            - ALWAYS respond with ONLY valid JSON, nothing else, in exactly this shape:
            {
            "reason": "one sentence on what you're doing and why",
            "command": "the shell command to run, or a list like [\"cmd1\", \"cmd2\"] for chaining",
            "findings": "what you've learned/found so far, plain text",
            "foothold": "none / user / root",
            "task_complete": false
            }
            - Set task_complete to true ONLY when you have real evidence the task's goal (look_for) is fully satisfied. When true, "command" should be an empty string.
            - Never wrap the JSON in markdown or backticks. Never add commentary outside the JSON object.
            - If leader tells to stop work since flags are found print the flags and indicate that the flags are found by printing them with echo <flag1>..."""

    def parse_leader_json(self, raw_leader_json):
        leader_json = json.loads(raw_leader_json)
        return leader_json
    
    def connect(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock = context.wrap_socket(raw_sock, server_hostname=self.host)
        self.sock.connect((self.host, self.port))
        print(f"[+] Connected to leader as worker {self.worker_id}")
    
    def send_init(self):
        msg = {
            "type": "initiolization",
        }
        self.sock.sendall(json.dumps(msg).encode("utf-8"))
        response = self.sock.recv(8192)
        response = response.decode('utf-8')
        print(f"[+] Leader replied: {response}")
        response_dict = json.loads(response)
        
        if response_dict["status"] == "successfuly initiolized":
            self.worker_id = response_dict["worker_id"]
            print(f"[worker] successfully initialized as worker {self.worker_id}")
        
        else:
            print("[worker] error initializing")

    def call_ai(self, system_prompt, user_content):
        try:
            print(f"[worker {self.worker_id}] calling AI...")
            response = self.client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
            )
            print(f"[worker {self.worker_id}] AI responded.")
            return response.choices[0].message.content
        
        except Exception as e:
            print(f"[worker {self.worker_id}] Error communicating with Groq AI: {e}")
            return None
    
    def read_until_prompt(self, proc):
        output = ""
        while True:
            char = proc.stdout.read(1)
            output += char
            if output.rstrip().endswith("PTAI_DONE_OK") or output.rstrip().endswith("PTAI_DONE_FAIL"):
                break
            
        return output
    
    def send_report(self, conn, worker_id, instructions, command_ran, findings, foothold, status):
        report = {
            "type": "report",
            "worker_id": worker_id,
            "task_instructions": instructions,
            "command_ran": command_ran,
            "findings": findings,
            "foothold": foothold,
            "status": status
        }
        print(f"[worker {worker_id}] sending report: status={status}, cmd={command_ran}")
        conn.sendall(json.dumps(report).encode('utf-8'))

    def command_actually_failed(self, result):
        return result.rstrip().endswith("PTAI_DONE_FAIL")
    
    def parse_result(self, raw):
        lines = raw.split("\n")
        
        echoed_command = lines[0].strip()
        prompt = lines[-1].strip()
        output_lines = lines[1:-1]
        
        while output_lines and output_lines[0].strip() == "":
            output_lines.pop(0)
        while output_lines and output_lines[-1].strip() == "":
            output_lines.pop()
        
        output = "\n".join(output_lines)
        
        return echoed_command, output, prompt
    
    def wait_for_ack(self, conn):
        print(f"[worker {self.worker_id}] waiting for ack...")
        wait_for_ack = conn.recv(8192)
        wait_for_ack_response = wait_for_ack.decode('utf-8')
        
        if wait_for_ack_response == "ack":
            print(f"[worker {self.worker_id}] got ack.")
            return True
        
        else:
            print(f"[worker {self.worker_id}] BAD ack, got: {wait_for_ack_response}")
            return False


if __name__ == "__main__":
    proc = subprocess.Popen(   
        ["bash"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    worker = WorkerAgent(worker_id=1)
    worker.connect()
    worker.send_init()
    
    while True:
        print(f"[worker {worker.worker_id}] requesting new task...")
        msg = {
            "type": "ready for new task",
            "worker_id": worker.worker_id
        }
        
        worker.sock.sendall(json.dumps(msg).encode("utf-8"))
        response = worker.sock.recv(8192).decode('utf-8')
        
        if not response:
            print("[worker] leader disconnected or sent nothing. exiting.")
            sys.exit(1)

        if response == "emptyResponseError":
            print("got emptyResponseError from leader.")
            time.sleep(5)
            continue
        
        if json.loads(response)["status"] == "finished":
            print("FINISHED WORKING ON SESSION: FOUND FLAGS")
            sys.exit(0)
        
        task = worker.parse_leader_json(response)
        print(f"[worker {worker.worker_id}] received task: {task}")

        worker.sock.sendall("ack".encode("utf-8"))
        
        user_content = f"Task: {json.dumps(task)}\nYour session history: {json.dumps(worker.session_history)}"
        ai_raw = worker.call_ai(worker.system_prompt, user_content)

        if not ai_raw:
            sys.exit(1)

        ai_task_output = json.loads(ai_raw)
        print(f"[worker {worker.worker_id}] AI decided: {ai_task_output}")

        if ai_task_output["task_complete"]:
            worker.send_report(
                worker.sock, worker.worker_id, task.get("instructions"),
                command_ran=None, findings=ai_task_output["findings"],
                foothold=ai_task_output["foothold"], status="done"
            )
            
            if worker.wait_for_ack(worker.sock):
                continue
            
            else:
                sys.exit(1)

        command = ai_task_output["command"]
        commands = command if isinstance(command, list) else [command]

        for cmd in commands:
            print(f"[worker {worker.worker_id}] running: {cmd}")
            real_cmd = cmd + "; if [ $? -eq 0 ]; then echo PTAI_DONE_OK; else echo PTAI_DONE_FAIL; fi\n"
            proc.stdin.write(real_cmd)
            proc.stdin.flush()
            time.sleep(0.5)
            result = worker.read_until_prompt(proc)
            _, output, prompt = worker.parse_result(result)
            success = not worker.command_actually_failed(result)
            clean_output = "\n".join(l for l in output.strip().split("\n") if l.strip() not in ("PTAI_DONE_OK", "PTAI_DONE_FAIL"))
            print(f"[worker {worker.worker_id}] output: {clean_output}")

            worker.session_history.append({"command": cmd, "output": clean_output, "success": success})

            worker.send_report(
                worker.sock, worker.worker_id, task.get("instructions"),
                command_ran=cmd, findings=ai_task_output["findings"],
                foothold=ai_task_output["foothold"],
                status="ok" if success else "failed"
            )
            
        if worker.wait_for_ack(worker.sock):
            continue
        
        else:
            sys.exit(1)