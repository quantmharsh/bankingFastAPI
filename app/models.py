from pydantic import BaseModel, EmailStr, Field
from typing import Optional, Dict
from bson import ObjectId
import datetime
from datetime import datetime  
from typing import Optional, Literal

# Pydantic Model for User Registration
class UserCreate(BaseModel):
    name: str = Field(..., min_length=3)
    email: EmailStr
    password: str = Field(..., min_length=6)
     # Default role is "customer", can be changed to "admin", "manager", etc.
    role: str = Field(default="customer")

# Pydantic Model for User Response (excluding password)
class UserResponse(BaseModel):
    id: str
    name: str
    email: str
    role: str  # Include role in user response

# MongoDB Schema for Users
class UserDB(UserResponse):
    hashed_password: str

# Pydantic Model for Account
class Account(BaseModel):
    user_id: str  # Linked to User
    account_number: str
    balance: float = Field(default=0.0, ge=0)
    locked: bool = Field(default=False)  # For pessimistic locking during transactions
    txn_version: Optional[int] = Field(default=1)  # For optimistic locking if needed

# Deposit & Withdraw Request Schema
class TransactionRequest(BaseModel):
    amount: float = Field(gt=0)  # Amount should be greater than 0
    idempotency_key: str  # Unique key for each transaction

# Transaction Log Schema
class TransactionLog(BaseModel):
    user_id: str
    account_number: str
    amount: float
    # "type" can be "deposit", "withdraw", or "transfer"
    type: Literal["deposit", "withdraw", "transfer"]
    timestamp: datetime = datetime.utcnow()
    idempotency_key: str
    # Status can be "success", "pending", "failed", "blocked", etc.
    status: Literal["success", "failed", "blocked", "pending"] = "success"
    # If you want to store the recipient in case of transfers
    to_account: Optional[str] = None


# Transfer Request Schema for Fund Transfer
class TransferRequest(BaseModel):
    to_account: str  # Recipient's account number
    amount: float = Field(..., gt=0)  # Amount to transfer (must be greater than 0)
    idempotency_key: str  # Unique key to prevent duplicate transfers

class AuditLog(BaseModel):
    user_id: str
    action: str  # e.g., "login", "deposit", "withdraw", "transfer", "approve_transaction"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    ip_address: Optional[str] = None
    details: Optional[Dict] = None  # Additional info about the action