from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from bson import ObjectId

# Pydantic Model for User Registration
class UserCreate(BaseModel):
    name: str = Field(..., min_length=3)
    email: EmailStr
    password: str = Field(..., min_length=6)

# Pydantic Model for User Response (excluding password)
class UserResponse(BaseModel):
    id: str
    name: str
    email: str

# MongoDB Schema for Users
class UserDB(UserResponse):
    hashed_password: str

# Pydantic Model for Account
class Account(BaseModel):
    user_id: str  # Linked to User
    account_number: str
    balance: float = 0.0
