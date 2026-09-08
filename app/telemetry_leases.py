"""Atomic Redis leases. New dirty writes remain independent of in-flight work."""

CLAIM = """
local now = tonumber(ARGV[1])
local expired = redis.call('ZRANGEBYSCORE', KEYS[2], '-inf', now)
for _, id in ipairs(expired) do
  redis.call('ZADD', KEYS[1], 'NX', 0, id)
  redis.call('ZREM', KEYS[2], id)
  redis.call('HDEL', KEYS[3], id)
end
local result = {}
for _, id in ipairs(redis.call('ZRANGE', KEYS[1], 0, -1)) do
  if not redis.call('ZSCORE', KEYS[2], id) then
    redis.call('ZREM', KEYS[1], id)
    redis.call('ZADD', KEYS[2], now + tonumber(ARGV[2]), id)
    redis.call('HSET', KEYS[3], id, ARGV[3])
    table.insert(result, id)
    if #result >= tonumber(ARGV[4]) then break end
  end
end
return result
"""

SETTLE = """
if redis.call('HGET', KEYS[3], ARGV[1]) ~= ARGV[2] then return 0 end
redis.call('ZREM', KEYS[2], ARGV[1])
redis.call('HDEL', KEYS[3], ARGV[1])
if ARGV[3] == 'retry' then redis.call('ZADD', KEYS[1], 'NX', 0, ARGV[1]) end
return 1
"""
