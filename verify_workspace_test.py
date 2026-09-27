import sys
sys.path.insert(0, r"C:\JARVIS")

from app.brain.orchestrator import JarvisOrchestrator

def verify_workspace_test():
    orchestrator = JarvisOrchestrator()
    session_id = "live-workspace-test-session"
    prompt = "create a folder called workspace_test"

    print(f"USER PROMPT: '{prompt}'")
    resp = orchestrator.process(prompt, session_id=session_id)
    print(f"JARVIS RESPONSE:\n{resp.response}")
    print(f"STATUS: {resp.status}")

    if resp.status == "confirmation_required":
        print("\nCONFIRMING WITH 'y'...")
        resp2 = orchestrator.process("y", session_id=session_id)
        print(f"JARVIS POST-CONFIRMATION RESPONSE:\n{resp2.response}")
        print(f"STATUS: {resp2.status}")

if __name__ == "__main__":
    verify_workspace_test()
