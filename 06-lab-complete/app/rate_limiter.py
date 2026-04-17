import time
import redis
from fastapi import HTTPException
from .config import settings

# Kết nối Redis
# Chế độ: decode_responses=True giúp đọc string thay vì bytes
if settings.redis_url and settings.redis_url.startswith(("redis://", "rediss://", "unix://")):
    r = redis.from_url(settings.redis_url, decode_responses=True)
else:
    # Fallback: Nếu không có Redis, dùng một Mock object để không crash
    # Trong thực tế có thể dùng memory-based limiter, ở đây ta để r là None 
    # và handle trong hàm check_rate_limit.
    print("WARNING: Redis URL is not set or invalid. Rate limiting is DISABLED.")
    r = None

def check_rate_limit(user_id: str):
    """
    Sliding Window Rate Limiter bằng Redis Sorted Set.
    Mỗi user có một bucket (Set) chứa timestamp các request trong 60 giây qua.
    """
    now = time.time()
    key = f"ratelimit:{user_id}"
    window_start = now - 60
    
    if r is None:
        return
        
    try:
        # Pipeline để đảm bảo tính nguyên tố (Atomicity)
        pipe = r.pipeline()
        # 1. Xóa các request cũ ngoài cửa sổ 60s
        pipe.zremrangebyscore(key, 0, window_start)
        # 2. Đếm số request hiện có trong cửa sổ
        pipe.zcard(key)
        # 3. Thêm request mới
        pipe.zadd(key, {str(now): now})
        # 4. Set expire để tự dọn dẹp key nếu không dùng
        pipe.expire(key, 60)
        
        results = pipe.execute()
        request_count = results[1]
        
        if request_count >= settings.rate_limit_per_minute:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: {settings.rate_limit_per_minute} req/min",
                headers={"Retry-After": "60"}
            )
            
    except redis.RedisError as e:
        # Nếu Redis lỗi, trong production có thể cho qua (fail-open) 
        # hoặc chặn lại (fail-close). Ở đây ta log lại.
        print(f"Redis Error in Rate Limiter: {e}")
        pass
