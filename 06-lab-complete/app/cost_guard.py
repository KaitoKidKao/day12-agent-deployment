import time
import redis
from fastapi import HTTPException
from .config import settings

# Sử dụng chung kết nối Redis
if settings.redis_url and settings.redis_url.startswith(("redis://", "rediss://", "unix://")):
    r = redis.from_url(settings.redis_url, decode_responses=True)
else:
    print("WARNING: Redis URL is not set or invalid. Cost Guard is DISABLED.")
    r = None

def check_and_record_cost(user_id: str, input_tokens: int = 0, output_tokens: int = 0):
    """
    Theo dõi chi phí theo ngày sử dụng Redis.
    Chi phí được tính dựa trên số lượng token giả lập.
    """
    today = time.strftime("%Y-%m-%d")
    cost_key = f"cost:{user_id}:{today}"
    
    # Giả lập giá: 0.01$ mỗi 1k tokens
    estimated_cost = ((input_tokens + output_tokens) / 1000) * 0.01
    
    if r is None:
        return
        
    try:
        # 1. Kiểm tra budget hiện tại
        current_cost = float(r.get(cost_key) or 0.0)
        
        if current_cost >= settings.daily_budget_usd:
            raise HTTPException(
                status_code=402,
                detail=f"Daily budget exhausted (${settings.daily_budget_usd}). Contact admin."
            )
        
        # 2. Ghi nhận chi phí mới (Atomic increment)
        if estimated_cost > 0:
            r.incrbyfloat(cost_key, estimated_cost)
            r.expire(cost_key, 86400 * 2) # Giữ log trong 2 ngày để debug
            
    except redis.RedisError as e:
        print(f"Redis Error in Cost Guard: {e}")
        pass
