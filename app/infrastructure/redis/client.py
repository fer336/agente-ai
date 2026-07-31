from redis.asyncio import Redis


def create_redis_client(redis_url: str) -> Redis:
    """Builds the async Redis client for the given connection URL."""
    return Redis.from_url(redis_url)
