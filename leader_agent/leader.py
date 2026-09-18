try:
    import os
    import ssl
    import socket
    import json
    import threading
    
    class LeaderServer:
        def __init__(self, host='127.0.0.1', port=9999):
            self.host = host
            self.port = port
            self.db_lock = threading.Lock() 
            self.connected_agents = 0
            self.workers = {}
        
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
            
            conn = self.workers[to]
            conn.sendall(json.dumps(built_json).encode('utf-8'))   
        
        def handle_client(self, conn, addr):
            try:
                print(f"[+] New connection from agent: {addr}")
                with conn:
                    while True:
                        rawDataFromClient = conn.recv(8192)

                        if not rawDataFromClient:
                            return
                        
                        dataFromClient = rawDataFromClient.decode('utf-8').strip()
                        dict_from_client = json.loads(dataFromClient)
                        
                        if dict_from_client["type"] == "initiolization":
                            self.connected_agents += 1
                            self.workers[self.connected_agents] = conn
                            print(f"[*] agent connected. number of connected agents: {self.connected_agents}") 
                            response = {
                                "status": "successfuly initiolized",
                                "worker_id": self.connected_agents
                            }
                            
                            conn.sendall(f"{json.dumps(response)}".encode("utf-8"))
                        
                        elif dict_from_client["type"] == "report":
                            conn.sendall("ack".encode('utf-8'))
            
            except ConnectionAbortedError:
                print("agent aborted the connection.")
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
                            client_thread = threading.Thread(target=self.handle_client, args=(conn, addr))
                            client_thread.start()
                            
                        except Exception as e:
                            print(f"[-] Error accepting connection: {e}")

    if __name__ == "__main__":
        server = LeaderServer()
        server.start()

except KeyboardInterrupt:
    print("\n[+] KeyboardInterrupt! QUITTING...")