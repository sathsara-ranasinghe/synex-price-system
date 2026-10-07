"""Start the portal. On Windows use the selector event loop: the default proactor loop can stop
accepting connections after a network change (asyncio "WinError 64"), leaving the portal hung."""

import asyncio
import os
import sys

import uvicorn

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=os.getenv("HOST", "0.0.0.0"), port=int(sys.argv[1]) if len(sys.argv) > 1 else int(os.getenv("PORT", "8000")),
                proxy_headers=True, forwarded_allow_ips="*", loop="asyncio")
