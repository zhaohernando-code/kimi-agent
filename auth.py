"""
认证模块 - HMAC-SHA256 签名验证
"""
import hmac
import hashlib
import time
from functools import wraps
from typing import Optional

from flask import request, jsonify

from config import config


class AuthError(Exception):
    """认证错误"""
    pass


def generate_signature(
    method: str,
    path: str,
    timestamp: str,
    body: str,
    api_key: str
) -> str:
    """
    生成请求签名
    
    签名算法: HMAC-SHA256
    签名内容: method + path + timestamp + body
    密钥: api_key
    
    Args:
        method: HTTP 方法 (GET, POST, etc.)
        path: 请求路径
        timestamp: Unix 时间戳字符串
        body: 请求体 (GET 请求为空字符串)
        api_key: API 密钥
    
    Returns:
        十六进制签名字符串
    """
    message = f"{method.upper()}:{path}:{timestamp}:{body}"
    signature = hmac.new(
        api_key.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return signature


def verify_request(
    method: str,
    path: str,
    timestamp: str,
    signature: str,
    body: str = "",
    max_age_seconds: int = 300
) -> bool:
    """
    验证请求签名
    
    Args:
        method: HTTP 方法
        path: 请求路径
        timestamp: 请求时间戳
        signature: 请求签名
        body: 请求体
        max_age_seconds: 最大允许的时间差（防重放）
    
    Returns:
        验证是否通过
    
    Raises:
        AuthError: 验证失败时抛出
    """
    # 检查时间戳
    try:
        request_time = int(timestamp)
        current_time = int(time.time())
        time_diff = abs(current_time - request_time)
        
        if time_diff > max_age_seconds:
            raise AuthError(f"Request timestamp too old: {time_diff}s > {max_age_seconds}s")
    except ValueError:
        raise AuthError("Invalid timestamp format")
    
    # 验证签名
    expected_signature = generate_signature(method, path, timestamp, body, config.API_KEY)
    
    if not hmac.compare_digest(signature, expected_signature):
        raise AuthError("Invalid signature")
    
    return True


def require_auth(f):
    """
    Flask 装饰器 - 要求请求必须携带有效签名
    
    请求头要求:
        X-Timestamp: <Unix 时间戳>
        X-Signature: <HMAC-SHA256 签名>
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 获取认证头
        timestamp = request.headers.get('X-Timestamp')
        signature = request.headers.get('X-Signature')
        
        if not timestamp or not signature:
            return jsonify({
                "error": "Missing authentication headers",
                "required": ["X-Timestamp", "X-Signature"]
            }), 401
        
        # 获取请求体
        body = ""
        if request.method in ['POST', 'PUT', 'PATCH']:
            body = request.get_data(as_text=True)
        
        try:
            verify_request(
                method=request.method,
                path=request.path,
                timestamp=timestamp,
                signature=signature,
                body=body
            )
        except AuthError as e:
            return jsonify({"error": str(e)}), 401
        
        return f(*args, **kwargs)
    
    return decorated_function


def create_signed_headers(method: str, path: str, body: str = "") -> dict:
    """
    创建带签名的请求头（用于客户端）
    
    Args:
        method: HTTP 方法
        path: 请求路径
        body: 请求体
    
    Returns:
        包含认证头的字典
    """
    timestamp = str(int(time.time()))
    signature = generate_signature(method, path, timestamp, body, config.API_KEY)
    
    return {
        'X-Timestamp': timestamp,
        'X-Signature': signature,
        'Content-Type': 'application/json'
    }


# 测试代码
if __name__ == "__main__":
    # 测试签名生成和验证
    method = "POST"
    path = "/api/v1/projects"
    body = '{"name": "test", "repo_url": "https://github.com/test/repo.git"}'
    
    # 生成签名
    headers = create_signed_headers(method, path, body)
    print(f"Generated headers: {headers}")
    
    # 验证签名
    try:
        verify_request(
            method=method,
            path=path,
            timestamp=headers['X-Timestamp'],
            signature=headers['X-Signature'],
            body=body
        )
        print("Signature verification: PASSED")
    except AuthError as e:
        print(f"Signature verification: FAILED - {e}")
    
    # 测试过期时间戳
    try:
        old_timestamp = str(int(time.time()) - 400)  # 6 分钟前
        verify_request(
            method=method,
            path=path,
            timestamp=old_timestamp,
            signature="dummy",
            body=body
        )
        print("Old timestamp test: FAILED (should have been rejected)")
    except AuthError as e:
        print(f"Old timestamp test: PASSED - {e}")
    
    print("\nAll auth tests completed!")
