"""Console entrypoint; run with `uvicorn entrypoint:app` on port 8080."""
import uvicorn

from app.main import app

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080, access_log=False, workers=1)
