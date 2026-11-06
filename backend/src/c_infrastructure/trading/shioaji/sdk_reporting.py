"""
The Shioaji SDK's reporting, off unless the environment turns it on. The SDK reads two variables at its first import:
LOG_SENTRY, unless empty (False included), sends its errors with the login's person id to Sinopac's Sentry after a
production login, and SJ_LOG_PATH names the file its logger writes the server's error answers to, shioaji.log in the
working directory unless set. Every module that imports the SDK imports this one before it.
"""

import os

os.environ.setdefault("LOG_SENTRY", "")
os.environ.setdefault("SJ_LOG_PATH", os.devnull)
