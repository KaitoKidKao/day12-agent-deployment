from fastapi import Security, HTTPException
from fastapi.security.api_key import APIKeyHeader
from starlette.status import HTTP_401_UNAUTHORIZED
from .config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    """
    Xác định danh tính user dựa trên API Key.
    TRONG PRODUCTION: Nên query DB để map API Key -> UserID/Role.
    TRONG LAB: Chúng ta dùng API Key tĩnh.
    """
    if not api_key or api_key != settings.agent_api_key:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Please set 'X-API-Key' header.",
        )
    # Trả về một ID định danh (giả lập là subset của key để phân biệt các bucket trong Redis)
    return api_key[:8]
