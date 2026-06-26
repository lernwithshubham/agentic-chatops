import os
import json
import paramiko
import uvicorn
from fastapi import FastAPI, Request
from dotenv import load_dotenv
from typing import TypedDict

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

# === CONFIG & SECRETS ===
#load_dotenv()
load_dotenv(override=True)
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID")
EC2_HOST = os.getenv("EC2_HOST", "127.0.0.1")
EC2_USER = os.getenv("EC2_USER", "root")
EC2_KEY_PATH = os.getenv("EC2_KEY_PATH", "/root/.ssh/id_rsa")

app = FastAPI()
slack_client = WebClient(token=SLACK_BOT_TOKEN)
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)

# === 1. TOOLS ===
def run_ssh_command(command: str) -> str:
    """Executes a bash command on the EC2 instance."""
    try:
        key = paramiko.Ed25519Key.from_private_key_file(EC2_KEY_PATH)
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(hostname=EC2_HOST, username=EC2_USER, pkey=key, timeout=30)
        
        stdin, stdout, stderr = client.exec_command(command)
        output = stdout.read().decode().strip()
        error = stderr.read().decode().strip()
        client.close()
        return output if output else error
    except Exception as e:
        return f"SSH Error: {str(e)}"

def send_slack_message(text: str, blocks: list = None):
    """Sends a message or interactive blocks to Slack."""
    try:
        slack_client.chat_postMessage(channel=SLACK_CHANNEL_ID, text=text, blocks=blocks)
    except SlackApiError as e:
        print(f"Slack API Error: {e.response['error']}")
        print(f"Slack Details: {e.response.get('response_metadata', {}).get('messages', [])}")

def read_company_runbook() -> str:
    """Reads the internal Standard Operating Procedure (SOP)."""
    try:
        with open("/root/project/runbook.md", "r") as file:
            return file.read()
    except Exception as e:
        return "Error reading runbook."

# === 2. GRAPH STATE ===
class SREState(TypedDict):
    incident_report: str
    investigation_logs: str
    proposed_fix: str
    status: str

# === 3. AGENT NODES ===
def diagnostics_agent(state: SREState) -> SREState:
    print("--- STARTING DIAGNOSTICS ---")
    send_slack_message(f"🔍 *Investigating Incident:* {state['incident_report']}\nFetching logs and cross-referencing internal Runbooks...")
    
    print("1. Slack message sent. Attempting SSH...")
    logs = run_ssh_command("docker logs nginx-web --tail 100 2>&1")
    print(f"2. SSH complete. Logs fetched: {logs[:50]}...")
    runbook_content = read_company_runbook()
    print("3. Runbook read. Asking Gemini for the fix...")

    prompt = (
        f"You are a Senior SRE Agent. Here are the latest server logs:\n{logs}\n\n"
        f"Here is the company SOP manual:\n{runbook_content}\n\n"
        f"TASK: Ignore standard web traffic, 404s, and bot probes. Find the critical system alert in the logs. "
        f"Cross-reference that specific alert with the SOP manual. "
        f"Return ONLY the exact terminal command required to fix it. Do not include any other text."
    )

    response = llm.invoke(prompt)
    proposed_command = response.content.strip()
    
    print(f"4. Gemini replied with: {proposed_command}")
    return {
        "investigation_logs": logs,
        "proposed_fix": proposed_command, 
        "status": "waiting_for_approval"
    }

def human_in_the_loop(state: SREState) -> SREState:
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"🚨 *Investigation Complete*\n\n*Recommended Action:* Run `{state['proposed_fix']}`"
            }
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Approve Restart",
                        "emoji": True
                    },
                    "style": "primary",
                    "value": "approve_fix",
                    "action_id": "approve_fix_action"
                }
            ]
        }
    ]
    send_slack_message(text="Approval Required", blocks=blocks)
    return state

def execution_agent(state: SREState) -> SREState:
    send_slack_message("⚙️ *Approval received. Executing remediation...*")
    result = run_ssh_command(state["proposed_fix"])
    send_slack_message(f"✅ *Incident Resolved!*\nCommand Output: `{result}`")
    return {"status": "resolved"}

# === 4. BUILD THE GRAPH ===
workflow = StateGraph(SREState)
workflow.add_node("diagnostics", diagnostics_agent)
workflow.add_node("human_in_the_loop", human_in_the_loop)
workflow.add_node("execution", execution_agent)

workflow.add_edge(START, "diagnostics")
workflow.add_edge("diagnostics", "human_in_the_loop")
workflow.add_edge("human_in_the_loop", "execution")
workflow.add_edge("execution", END)

memory = MemorySaver()
sre_graph = workflow.compile(
    checkpointer=memory,
    interrupt_before=["execution"] 
)

# === 5. FASTAPI WEBSERVER ===
@app.get("/slack/trigger")
def trigger_incident():
    thread_config = {"configurable": {"thread_id": "incident_101"}}
    initial_state = {
        "incident_report": "Alert: 502 Bad Gateway on Nginx Production",
        "investigation_logs": "",
        "proposed_fix": "",
        "status": "investigating"
    }
    sre_graph.invoke(initial_state, config=thread_config)
    return {"message": "Incident triggered. Check Slack!"}

@app.post("/slack/actions")
async def slack_actions(request: Request):
    form_data = await request.form()
    payload = json.loads(form_data.get("payload"))
    
    if payload["type"] == "block_actions" and payload["actions"][0]["action_id"] == "approve_fix_action":
        thread_config = {"configurable": {"thread_id": "incident_101"}}
        sre_graph.invoke(None, config=thread_config)
        
    return {"status": 200}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)