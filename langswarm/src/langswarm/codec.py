"""Fast serialization primitives.

orjson handles untyped, high-throughput JSON (API responses, benchmark
reports). msgspec handles typed envelopes — schemas declared as Struct classes
that validate while decoding — used for the YAML blueprints and available for
compact MessagePack exchange.
"""

__lazy_modules__ = ["orjson"]

import orjson


def json_dumps(obj) -> bytes:
    """Encode to JSON bytes with orjson (naive datetimes normalized to UTC)."""
    return orjson.dumps(obj, option=orjson.OPT_NAIVE_UTC)


def json_loads(raw):
    """Decode JSON with orjson."""
    return orjson.loads(raw)


def msgpack_encode(obj) -> bytes:
    """Encode a msgspec-compatible object to MessagePack."""
    import msgspec

    return msgspec.msgpack.encode(obj)


def msgpack_decode(raw: bytes, schema: type | None = None):
    """Decode MessagePack, validating against a Struct type when given."""
    import msgspec

    if schema is not None:
        return msgspec.msgpack.decode(raw, type=schema)
    return msgspec.msgpack.decode(raw)
