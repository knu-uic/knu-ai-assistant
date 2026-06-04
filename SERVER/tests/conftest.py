import os

# Minimum env vars needed so db/schema.py and model.py can be imported
# without a live .env file during unit tests.
os.environ.setdefault("EMBEDDING_DIM", "768")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_USER", "knu-uic")
os.environ.setdefault("DB_NAME", "knu-uic")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("EMBEDDING_PROVIDER", "local")
os.environ.setdefault("RERANKER_PROVIDER", "local")
os.environ.setdefault("VLM_PROVIDER", "local")
