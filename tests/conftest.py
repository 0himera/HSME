import os
import pytest

# Ensure isolated database is used for all tests before any imports happen
os.environ["HSME_DATABASE_FILE"] = "test_db_state.pkl"

# Clean up test database file before starting
if os.path.exists("test_db_state.pkl"):
    try:
        os.remove("test_db_state.pkl")
    except Exception:
        pass
