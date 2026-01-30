# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
"""
__main__.py — Entry point to run Hashall as `python3 -m hashall`
"""

import click
from .cli import cli

if __name__ == "__main__":
    cli()

# # src/hashall/cli.py or __main__.py
# from hashall import __version__
# @click.version_option(__version__)
