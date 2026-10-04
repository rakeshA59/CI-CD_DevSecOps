"""
In-memory stand-in for AsyncMongoClient (mongo_db_url=memory://) – only the calls CIP's repositories use.
Backed by mongomock, wrapped in async methods.
"""

import mongomock


class _Cursor:
    def __init__(self, cursor):
        self._c = cursor

    def sort(self, *a, **k):
        self._c = self._c.sort(*a, **k)
        return self

    def limit(self, n):
        self._c = self._c.limit(n)
        return self

    async def to_list(self, length=None):
        return list(self._c)[: length or None]


class _Collection:
    def __init__(self, col):
        self._c = col

    async def insert_one(self, doc):
        return self._c.insert_one(doc)

    async def find_one(self, *a, **k):
        return self._c.find_one(*a, **k)

    async def update_one(self, *a, **k):
        return self._c.update_one(*a, **k)

    async def delete_one(self, *a, **k):
        return self._c.delete_one(*a, **k)

    def find(self, *a, **k):
        return _Cursor(self._c.find(*a, **k))


class _Database:
    def __init__(self, db):
        self._db = db

    def __getitem__(self, name):
        return _Collection(self._db[name])

    def get_collection(self, name):
        return self[name]


class MemoryMongoClient:
    def __init__(self):
        self._client = mongomock.MongoClient()

    def get_database(self, name):
        return _Database(self._client[name])

    async def close(self):
        pass
