from tinydb.storages import JSONStorage
import pg_storage

class PostgresBackedStorage(JSONStorage):
    """Mirrors TinyDB writes to Postgres automatically."""
    def write(self, data):
        super().write(data)              # normal write to trades.json
        pg_storage.save_db_json(data)    # copy to Postgres
