def main():
    import subprocess
    import time
    import os
    from groq import Groq
    from dotenv import load_dotenv
    import shlex
    import sys
    import json

    proc = subprocess.Popen(
        ["bash"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    def read_until_prompt(proc):
        output = ""
        while True:
            char = proc.stdout.read(1)
            output += char
            if output.rstrip().endswith("PTAI_DONE_OK") or output.rstrip().endswith("PTAI_DONE_FAIL"):
                break
            
        return output

    def command_actually_failed(result):
        return result.rstrip().endswith("PTAI_DONE_FAIL")

    def parse_result(raw):
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


    print("loading API key...")
    load_dotenv()
    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        print("Error: api key not found in your environment variables (.env file).")
        sys.exit(1)
        
    print("successfuly finished loading API key")
    client = Groq(api_key=api_key)

    session_history = []

    def build_context(target_ip, session_history):
        if not session_history:
            return f"Target: {target_ip}\nNo actions taken yet."
        
        history_text = "\n\n".join(
            f"Step {i+1}:\nCommand: {h['command']}\nOutput: {h['output']}\nSuccess: {h['success']}"
            for i, h in enumerate(session_history)
        )
        return f"Target: {target_ip}\n\nHistory so far:\n{history_text}"

    def call_ai(system_prompt, user_content):
        """Helper function to send data to Groq AI."""
        try:
            print("AI proccessing request...")
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
            )
            print("AI finished proccessing request")
            return response.choices[0].message.content

        except Exception as e:
            print(f"Error communicating with Groq AI: {e}")  
            sys.exit(1)


    system_prompt = (
        """You are an autonomous CTF penetration testing agent running on Kali Linux.
    You are given a target IP and a history of commands you've already run and their outputs.
    Your job: decide the SINGLE next command (or a chain) that moves you closer to getting the user flag and root flag.

    Rules:
    - Look at the history carefully. NEVER repeat a command that already failed or already gave you the info you needed.
    - If the last attempts show a dead end, try a genuinely different approach, not a small variation.
    - Output ONLY a raw shell command to run next. No explanation, no markdown, no backticks.
    - If multiple commands are needed in sequence, output: CHAINING: cmd1;cmd2;cmd3
    - Never put ";" inside a command's own content when chaining.
    - When you have found BOTH the user flag and root flag, output ONLY this JSON (nothing else):
    {"completed": true, "user": "<user_flag>", "root": "<root_flag>"}
    - If you only found one flag so far, keep working — do not output the JSON until both are found.
    - Assume standard CTF flag format unless the target's files tell you otherwise (e.g. flag.txt, user.txt, root.txt, proof.txt)."""
    )

    shell = "echo hi; echo PTAI_DONE_OK\n"
    os.system("clear")
    proc.stdin.write(shell)
    proc.stdin.flush()
    time.sleep(0.5)
    result = read_until_prompt(proc)
    cmd, output, prompt = parse_result(result)

    past_requests = []
    session_history = []

    target_ip = sys.argv[1] if len(sys.argv) > 1 else input("Target IP: ")

    while True:
        user_content = build_context(target_ip, session_history)
        ai_response = call_ai(system_prompt, user_content)

        try:
            result_json = json.loads(ai_response)
            if isinstance(result_json, dict) and result_json.get("completed"):
                print("DONE")
                print(f"user flag: {result_json.get('user')}")
                print(f"root flag: {result_json.get('root')}")
                break
        except json.JSONDecodeError:
            pass  # not a completion signal, treat as a normal command

        # otherwise treat ai_response as a command (or CHAINING: cmd1;cmd2)
        if ai_response.startswith("CHAINING:"):
            commands = [c.strip() for c in ai_response.split(":", 1)[1].split(";")]
        else:
            commands = [ai_response.strip()]

        for cmd in commands:
            real_cmd = cmd + "; if [ $? -eq 0 ]; then echo PTAI_DONE_OK; else echo PTAI_DONE_FAIL; fi\n"
            proc.stdin.write(real_cmd)
            proc.stdin.flush()
            time.sleep(0.5)
            result = read_until_prompt(proc)
            _, output, prompt = parse_result(result)
            success = not command_actually_failed(result)
            clean_output = "\n".join(l for l in output.strip().split("\n") if l.strip() not in ("PTAI_DONE_OK", "PTAI_DONE_FAIL"))

            session_history.append({"command": cmd, "output": clean_output, "success": success})
            print(f"$ {cmd}\n{clean_output}\n")

main()