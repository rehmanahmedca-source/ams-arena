import os
import logging

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "instance", "ahmed_cement.db")
# The application factory reads APP_DB_PATH.  HDC_DB_PATH is a legacy name
# and made WSGI deployments silently ignore their configured database path.
os.environ.setdefault("APP_DB_PATH", DB_PATH)
logging.basicConfig(level=logging.INFO)

from main import app

application = app
