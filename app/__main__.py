"""Launch the Persian dictation app."""

from __future__ import annotations

import argparse
import os

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Persian speech typing app")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--models-dir", default=os.environ.get("MODELS_DIR"))
    args = parser.parse_args()
    if args.models_dir:
        os.environ["MODELS_DIR"] = args.models_dir
    uvicorn.run("app.server:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
