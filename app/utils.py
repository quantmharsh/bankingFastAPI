from passlib.context import CryptContext
from fastapi import HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
import os
from app.config import JWT_SECRET, JWT_ALGORITHM  # Import directly
from typing import List

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


# OAuth2 scheme to handle JWT token in Authorization header
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="users/login")

# Decode JWT token and get user details
def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload  # Contains user_id and email
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    


def require_roles(allowed_roles: List[str]):
    """
    Dependency generator that ensures the current user has an allowed role.
    Usage:
      current_user = Depends(require_roles(["admin", "manager"]))
    """
    def role_checker(token: str = Depends(oauth2_scheme)):
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            user_role = payload.get("role", "customer")
            if user_role not in allowed_roles:
                raise HTTPException(
                    status_code=403,
                    detail=f"User role '{user_role}' not allowed to perform this action."
                )
            return payload  # Return the payload so we have user_id, email, role
        except JWTError:
            raise HTTPException(status_code=401, detail="Invalid token")
    return role_checker