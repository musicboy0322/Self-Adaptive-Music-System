"""
Main entry point for CarTunes adaptive backend system
- app.py: Main API server and WebSocket server (port 5000)
"""

import sys
import uvicorn
import utilities as utils


def main():
    """Run the main FastAPI app (app.py)"""
    config = utils.read_config()

    print("Starting CarTunes Adaptive Backend System...")
    print(f"🚀 Main API Server will run on port {config['api_endpoints_port']}\n")

    try:
        uvicorn.run(
            "app:app",
            host="0.0.0.0",
            port=config["api_endpoints_port"],
            reload=False
        )
    except KeyboardInterrupt:
        print("\n🛑 Stopping server gracefully...")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Error occurred: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()