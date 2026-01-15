#!/usr/bin/env python3
"""
Run the Spredd Markets API locally.

Usage:
    python run_api.py

Or with uvicorn directly:
    uvicorn api.main:app --reload --port 8000
"""
import uvicorn

if __name__ == "__main__":
    print("Starting Spredd Markets API...")
    print("API will be available at http://localhost:8000")
    print("Docs at http://localhost:8000/docs")
    print("")

    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
