from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from bson import ObjectId
import datetime

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

# Deposit & Withdraw Request Schema
class TransactionRequest(BaseModel):
    amount: float = Field(gt=0)  # Amount should be greater than 0
    idempotency_key: str  # Unique key for each transaction

# Transaction Log Schema
class TransactionLog(BaseModel):
    user_id: str
    account_number: str
    amount: float
    type: str  # "deposit" or "withdraw"
    timestamp: datetime.datetime = datetime.datetime.utcnow()
    idempotency_key: str  # Used to prevent duplicates