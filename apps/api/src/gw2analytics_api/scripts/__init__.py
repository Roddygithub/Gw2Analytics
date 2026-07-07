"""CLI scripts for the gw2analytics_api package.

Each module in this package is a thin ``argparse`` wrapper around
an importable function in the main package. The pattern is
``python -m gw2analytics_api.scripts.<name>`` so the package
context (and the project's installed dependencies) is on
``sys.path`` without requiring ``PYTHONPATH`` manipulation.
"""
