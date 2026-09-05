import os

import aiomysql


_pool: aiomysql.Pool | None = None


class PooledConnection:
    """Connexion aiomysql rendue au pool lorsque close() est appelé."""

    def __init__(self, pool: aiomysql.Pool, connection: aiomysql.Connection):
        self._pool = pool
        self._connection = connection
        self._released = False

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def close(self) -> None:
        if not self._released:
            self._pool.release(self._connection)
            self._released = True

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


async def create_db_pool() -> aiomysql.Pool:
    global _pool
    if _pool is None:
        _pool = await aiomysql.create_pool(
            host=os.getenv("DB_HOST"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            db=os.getenv("DB_NAME"),
            port=int(os.getenv("DB_PORT", 3306)),
            charset="utf8mb4",
            autocommit=True,
            minsize=int(os.getenv("DB_POOL_MIN_SIZE", 1)),
            maxsize=int(os.getenv("DB_POOL_MAX_SIZE", 10)),
            pool_recycle=int(os.getenv("DB_POOL_RECYCLE_SECONDS", 1800)),
            connect_timeout=int(os.getenv("DB_CONNECT_TIMEOUT_SECONDS", 10)),
        )
        print(f"[DB] Pool MySQL prêt ({_pool.minsize}-{_pool.maxsize} connexions)")
    return _pool


async def get_db_connection() -> PooledConnection:
    if _pool is None:
        raise RuntimeError("Le pool MySQL n'est pas initialisé")
    connection = await _pool.acquire()
    return PooledConnection(_pool, connection)


async def close_db_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        await _pool.wait_closed()
        _pool = None
        print("[DB] Pool MySQL fermé")
