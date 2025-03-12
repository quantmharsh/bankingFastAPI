from fastapi import APIRouter, HTTPException, Depends
from app.config import db
from app.utils import get_current_user
import random

router = APIRouter()

# Helper function to generate a random 10-digit account number.
def generate_account_number():
    return str(random.randint(1000000000, 9999999999))

# API to create a bank account for the user.
@router.post("/create-account")
async def create_account(current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]

    # Check if the user already has an account.
    existing_account = await db.accounts.find_one({"user_id": user_id})
    if existing_account:
        raise HTTPException(status_code=400, detail="User already has an account")
    
    account_number = generate_account_number()
    new_account = {
        "user_id": user_id,
        "account_number": account_number,
        "balance": 0.0,
        "locked": False,
        "txn_version": 1
    }
    await db.accounts.insert_one(new_account)
    return {"message": "Bank account created successfully", "account_number": account_number}

# API to get account details.
@router.get("/account")
async def get_account(current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    account = await db.accounts.find_one({"user_id": user_id})
    if not account:
        raise HTTPException(status_code=404, detail="No account found")
    return {
        "account_number": account["account_number"],
        "balance": account["balance"]
    }
