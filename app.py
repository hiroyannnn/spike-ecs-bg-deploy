import os
from fastapi import FastAPI
import uvicorn

app = FastAPI()

VERSION = os.getenv("APP_VERSION", "2.0.0")

@app.get("/")
def root():
    return {"message": "Hello from ECS!", "version": VERSION}

@app.get("/health")
def health():
    return {"status": "healthy", "version": VERSION}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
