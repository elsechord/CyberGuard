"""Single-worker model boundary; configuration is private and never logged."""
import json
import os
import uvicorn
from cyberguard_investigation.model_guard import create_app

app = create_app(json.loads(os.environ["CYBERGUARD_MODEL_GUARD_CONFIG"]), os.getenv("CYBERGUARD_DATA_DIR", "/data"))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080, access_log=False, workers=1)
