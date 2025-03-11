from passlib.context import CryptContext
from jose import jwt
import os
from app.config import JWT_SECRET, JWT_ALGORITHM  # Import directly

# Password Hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

# JWT Token Generation
# JWT_SECRET = os.getenv("JWT_SECRET")
# JWT_ALGORITHM = os.getenv("JWT_ALGORITHM")

def create_jwt_token(data: dict):
    if not JWT_SECRET or not JWT_ALGORITHM:
        raise ValueError("JWT_SECRET and JWT_ALGORITHM must be set")
    return jwt.encode(data, JWT_SECRET, algorithm=JWT_ALGORITHM)
