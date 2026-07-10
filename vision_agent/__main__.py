"""
Vision Agent — Module Runner

Allows running the vision agent as a module:
    python -m vision_agent
"""

import asyncio
from vision_agent.vision_agent import VisionAgent


def main():
    """Entry point for the vision agent CLI."""
    agent = VisionAgent()
    asyncio.run(agent.run())


if __name__ == "__main__":
    main()
