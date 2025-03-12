from fastapi import APIRouter, HTTPException, Depends
from app.config import db
from app.utils import get_current_user
from typing import List, Dict
from bson import ObjectId  
import random

router = APIRouter()

# Helper function to generate a random 10-digit account number.
def generate_account_number():
    return str(random.randint(1000000000, 9999999999))

def convert_objectids(item: Dict) -> Dict:
    """
    Recursively convert ObjectId fields in a dictionary to strings.
    """
    if isinstance(item, dict):
        for key, value in item.items():
            if isinstance(value, ObjectId):
                item[key] = str(value)
            elif isinstance(value, list):
                item[key] = [convert_objectids(i) if isinstance(i, dict) else i for i in value]
            elif isinstance(value, dict):
                item[key] = convert_objectids(value)
    return item


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
@router.get("/details")
async def account_details(current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]

    # Retrieve the user's account information
    account = await db.accounts.find_one({"user_id": user_id})
    if not account:
        raise HTTPException(status_code=404, detail="No account found")
    
    # Retrieve all transactions for the user
    transactions: List[Dict] = await db.transactions.find({"user_id": user_id}).to_list(length=None)
    
    # Convert ObjectIds in account and transactions
    account = convert_objectids(account)
    transactions = [convert_objectids(txn) for txn in transactions]
    
    return {
        "account_number": account.get("account_number"),
        "balance": account.get("balance"),
        "transactions": transactions
    }