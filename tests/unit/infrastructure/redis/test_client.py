from redis.asyncio import Redis

from app.infrastructure.redis.client import create_redis_client


def test_create_redis_client_binds_host_and_port_from_url():
    client = create_redis_client("redis://localhost:6379/0")

    assert isinstance(client, Redis)
    assert client.connection_pool.connection_kwargs["host"] == "localhost"
    assert client.connection_pool.connection_kwargs["port"] == 6379


def test_create_redis_client_binds_a_different_url_correctly():
    client = create_redis_client("redis://cache.internal:6380/1")

    assert client.connection_pool.connection_kwargs["host"] == "cache.internal"
    assert client.connection_pool.connection_kwargs["port"] == 6380
    assert client.connection_pool.connection_kwargs["db"] == 1


def test_create_redis_client_binds_password_from_authenticated_url():
    client = create_redis_client("redis://:s3cret@cache.internal:6380/0")

    assert client.connection_pool.connection_kwargs["host"] == "cache.internal"
    assert client.connection_pool.connection_kwargs["port"] == 6380
    assert client.connection_pool.connection_kwargs["password"] == "s3cret"
