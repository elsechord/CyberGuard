import os

import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8080")),
        log_level=os.getenv("CYBERGUARD_LOG_LEVEL", "INFO").lower(),
    )

