"""
MongoDB connection (singleton AsyncMongoClient, as in sdlc-api/utils/mongo_connection.py).

Set mongo_db_url=memory:// to run without a MongoDB server (tests / quick local try-out).
"""

import logging

from pymongo import AsyncMongoClient

from core.settings import MONGO_DB_NAME, MONGO_DB_URL

client = None


async def get_mongo_client():
    """Return the shared client (one connection pool for the app)."""
    global client
    if client is None:
        if MONGO_DB_URL.startswith("memory://"):
            from utils.memory_mongo import MemoryMongoClient

            logging.warning("[Mongo] mongo_db_url=memory:// – data is kept in memory only")
            client = MemoryMongoClient()
        else:
            client = AsyncMongoClient(host=MONGO_DB_URL, maxPoolSize=50, minPoolSize=1, connectTimeoutMS=5000)
    return client


async def get_mongo_db():
    """Return the CIP database."""
    return (await get_mongo_client()).get_database(MONGO_DB_NAME)
