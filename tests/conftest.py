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

@pytest.fixture(autouse=True)
def reset_db_state():
    from backend.repository.database import db
    from backend.repository.seeding import seed_database
    db.experiments.clear()
    db.vector_store.clear()
    db.codebook.clear()
    
    # Re-initialize roles
    db.roles = ["Material", "Process", "Equipment", "Property", "Publication", "Expert", "Facility"]
    for role in db.roles:
        db.codebook[f"Role:{role}"] = db.vsa.generate_vector()
        
    # Seed the database
    seed_database(db)
    db.save_to_disk(db.db_filepath)

