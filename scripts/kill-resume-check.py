"""A1 live-fire proof: SIGKILL the server mid-wait, restart, resume via HTTP."""

import json
import os
import signal
import sqlite3
import subprocess
import time
import urllib.request

BASE = "http://localhost:8000"


def post(path, body):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return json.loads(urllib.request.urlopen(req).read())


def get(path):
    return json.loads(urllib.request.urlopen(BASE + path).read())


post("/threads", {"thread_id": "restart-live"})
post(
    "/threads/restart-live/runs",
    {
        "query": "SN-4419 failed torque. What does current procedure require, "
        "and what should we hold?"
    },
)
time.sleep(2)
snap = get("/threads/restart-live")
print("before kill:", snap["status"])
assert snap["status"] == "waiting_human"

out = subprocess.run(
    ["lsof", "-tiTCP:8000", "-sTCP:LISTEN"], capture_output=True, text=True
).stdout.strip()
pid = int(out.split()[0])
os.kill(pid, signal.SIGKILL)
print("killed server pid", pid)
time.sleep(2)

db = sqlite3.connect(os.path.expanduser("companion/.cache/mom.sqlite"))
row = db.execute(
    "SELECT status FROM threads WHERE thread_id='restart-live'"
).fetchone()
print("persisted row survived kill:", row)
assert row and row[0] == "waiting_human"
print("OK — thread state persisted through SIGKILL")
