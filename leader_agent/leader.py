try:
    import os
    import ssl
    import socket
    import json
    import threading
    import subprocess as sp
    import sys
    from dotenv import load_dotenv
    from groq import Groq
    
    class LeaderServer:
        def __init__(self, host='127.0.0.1', port=9999):
            load_dotenv()
            self.api_key = os.getenv("GROQ_API_KEY")
            self.client = Groq(api_key=self.api_key)
            self.host = host
            self.port = port
            self.db_lock = threading.Lock() 
            self.connected_agents = 0
            self.workers = {}
            self.initial_scan_results = None
            self.workers_no_conn = {}
            self.leader_task_prompt = """You are the leader AI coordinating
            a team of autonomous penetration testing worker agents on Kali Linux, working together against a single target.
            You will be given:
            - The initial nmap scan results for the target
            - The full state of ALL workers: their status, current/past task instructions, all their reports (commands run, findings, foothold), for every worker on the team
            - Which specific worker is now asking for a new task

            Your job: decide the next task for THAT specific worker only.

            Rules:
            - always use non-interactive flags for tools that can prompt (e.g. mysql ... < /dev/null or ensure -p"$pass" is used correctly — actually the real bug here is -p"$pass" with an EMPTY string still
            triggers a password prompt in some mysql client versions instead of "no password", depends on syntax).
            - Read every worker's reports carefully, not just the requesting worker's. Findings from one worker can and should inform tasks you give to another.
            - NEVER assign a task that duplicates work already done (by any worker) or a command that already failed with no new angle.
            - NEVER use a command that can prompt for interactive input (passwords, confirmations, y/n prompts). Always use non-interactive flags or redirect stdin from /dev/null
            (e.g. command < /dev/null) for any tool that might prompt.
            - Prioritize investigating the most promising untried leads over repeating similar recon.
            - If a worker has already made strong progress (e.g. found a specific foothold) on the current stage, consider assigning the next logical stage instead of more of the same.
            - Respond with ONLY valid JSON, nothing else, in exactly this shape:
            {
            "target_IP": "TARGET IP",
            "instructions": "clear, specific goal for this one task",
            "suggested_tools": ["tool1", "tool2", ...],
            "look_for": "what result or information matters for this task",
            "estimated_tasks_remaining": <int>,
            "stage": "enumeration / exploitation / privilege-escalation / post-exploitation",
            "status": ongoing / finished
            }
            - Never wrap the JSON in markdown or backticks. Never add commentary outside the JSON object.
            - If, based on all workers' findings so far, BOTH the user flag and root flag have been found, respond with EXACTLY
            this instead of a task: {"status": "finished", "user_flag": "<flag>", "root_flag": "<flag>"}"""

        def call_ai(self, system_prompt, user_content):
            try:
                print("[leader] calling Groq AI to decide next task...")
                response = self.client.chat.completions.create(
                    model="openai/gpt-oss-120b",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content}
                    ],
                )
                print("[leader] AI responded.")
                return response.choices[0].message.content
            
            except Exception as e:
                print(f"[leader] Error communicating with Groq AI: {e}")
                return None
        
        def wait_for_ack(self, conn):
            print("[leader] waiting for ack...")
            wait_for_ack = conn.recv(8192)
            wait_for_ack_response = wait_for_ack.decode('utf-8')
            
            if wait_for_ack_response == "ack":
                print("[leader] got ack.")
                return True
            
            else:
                print(f"[leader] BAD ack, got: {wait_for_ack_response}")
                return False
            
        def send_leader_json(self, send_type, to, instructions, sugg_tools, look_for, estimated_tasks_till_done, stage):
            built_json =  {
                "type": send_type,
                "to": to,
                "instructions": instructions,
                "suggested_tools": sugg_tools,
                "look_for": look_for,
                "estimated_tasks_remaining": estimated_tasks_till_done,
                "stage": stage
            }
            
            conn = self.workers[to]["conn"]
            conn.sendall(json.dumps(built_json).encode('utf-8')) 
        
        def run_initial_scan(self, target_ip):
            print(f"[leader] running initial nmap scan on {target_ip} (this can take a while)...")
            command = f"nmap -sV -sC --open -p- {target_ip}"
            result = sp.run(command.split(), capture_output=True, text=True)
            print("[leader] initial scan complete.")
            return result.stdout
        
        def handle_worker(self, conn, addr):
            try:
                print(f"[+] New connection from agent: {addr}")
                with conn:
                    while True:
                        rawDataFromClient = conn.recv(8192)

                        if not rawDataFromClient:
                            print(f"[leader] connection closed by {addr}")
                            return
                        
                        dataFromClient = rawDataFromClient.decode('utf-8').strip()
                        dict_from_worker = json.loads(dataFromClient)
                        print(f"[leader] received message type: {dict_from_worker.get('type')} from {addr}")
                        try:
                            worker_id = dict_from_worker["worker_id"] 
                        except KeyError:
                            pass
                        
                        if dict_from_worker["type"] == "initiolization":
                            with self.db_lock:
                                self.connected_agents += 1
                                self.workers[self.connected_agents] = {
                                    "conn": conn,
                                    "status": "intiolized",
                                    "current_task": None,
                                    "reports": [],
                                    "foothold": None,
                                    "rating": None
                                }
                                
                                self.workers_no_conn[self.connected_agents] = {
                                    "status": "intiolized",
                                    "current_task": None,
                                    "reports": [],
                                    "foothold": None,
                                    "rating": None
                                }
                            
                            print(f"[*] agent connected. number of connected agents: {self.connected_agents}") 
                            response = {
                                "status": "successfuly initiolized",
                                "worker_id": self.connected_agents
                            }
                            
                            conn.sendall(f"{json.dumps(response)}".encode("utf-8"))
                            print(f"[leader] assigned id {self.connected_agents} to new worker")
                        
                        elif dict_from_worker["type"] == "report":
                            with self.db_lock:
                                conn.sendall("ack".encode('utf-8'))
                                formated_report = {
                                    "task_instructions": dict_from_worker["task_instructions"],
                                    "command_ran": dict_from_worker["command_ran"],
                                    "findings": dict_from_worker["findings"],
                                    "foothold": dict_from_worker["foothold"]
                                }
                                
                                self.workers[worker_id]["reports"].append(formated_report)
                                self.workers[worker_id]["status"] = dict_from_worker["status"]
                                self.workers_no_conn[worker_id]["reports"].append(formated_report)
                                self.workers_no_conn[worker_id]["status"] = dict_from_worker["status"]
                                print(f"[leader] worker {worker_id} reported: {dict_from_worker['status']} | cmd: {dict_from_worker.get('command_ran')}")
                                
                        elif dict_from_worker["type"] == "ready for new task":
                            try:
                                with self.db_lock:
                                    print(f"[leader] worker {worker_id} is ready for a new task, asking AI...")
                                    worker_data = self.workers_no_conn[worker_id]
                                    task = self.call_ai(self.leader_task_prompt, f"NMAP SCAN RESULTS START : {self.initial_scan_results} : NMAP SCAN RESULTS END. WORKERS STATES START : {self.workers_no_conn} : WORKERS STATES END. WORKER ASKING FOR TASK START : {worker_id}: {worker_data} : WORKER ASKING FOR TASK END.")
                                    
                                    if task:
                                        print(f"[leader] sending task to worker {worker_id}: {task}")
                                        conn.sendall(task.encode("utf-8"))
                                        if self.wait_for_ack(conn):
                                            continue
                                        else:
                                            sys.exit(1)
                                    else:
                                        conn.sendall("emptyResponseError".encode("utf-8"))
                                        continue
                            except Exception as e:
                                print(f"[leader] error handling task request for worker {worker_id}: {e}")
                                try:
                                    conn.sendall("emptyResponseError".encode("utf-8"))
                                except Exception:
                                    print(f"[leader] connection to worker {worker_id} is dead, cannot notify.")
                                continue
            
            except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
                print("agent disconnected.")
                self.connected_agents -= 1
                return
                                            
        def start(self):
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            print("opening server key and crt")
            context.load_cert_chain("keys/server.crt", "keys/server.key") 
            
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((self.host, self.port))
                s.listen()
                os.system("cls" if os.name == "nt" else "clear")
                print(f"[+] Server is listening on port: '{self.port}'")
                
                with context.wrap_socket(s, server_side=True) as ss:
                    while True:
                        try:
                            conn, addr = ss.accept()
                            client_thread = threading.Thread(target=self.handle_worker, args=(conn, addr))
                            client_thread.start()
                            
                        except Exception as e:
                            print(f"[-] Error accepting connection: {e}")

    if __name__ == "__main__":
        server = LeaderServer()
        target_ip = sys.argv[1]
        server.initial_scan_results = server.run_initial_scan(target_ip)
        server.start()

except KeyboardInterrupt:
    print("\n[+] KeyboardInterrupt! QUITTING...")