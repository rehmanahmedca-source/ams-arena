import os
import logging

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "instance", "ahmed_cement.db")
os.environ.setdefault("HDC_DB_PATH", DB_PATH)
logging.basicConfig(level=logging.INFO)

from main import app

application = app
