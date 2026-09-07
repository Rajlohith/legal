"""
Entry point.

Run with:
    python main.py

This launches the desktop GUI. The old terminal-prompt workflow has
been replaced by the form in gui/app.py; the scraping logic itself
lives in scraper/search_engine.py unchanged in behavior.
"""

from gui.app import launch

if __name__ == "__main__":
    launch()
