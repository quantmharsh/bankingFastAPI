from fastapi import APIRouter, Depends, HTTPException
from app.config import db
from app.models import TransactionRequest, TransactionLog
from app.utils import get_current_user
import datetime

router = APIRouter()

# Deposit Money API
@router.post("/deposit")
async def deposit(transaction: TransactionRequest, current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]

    # Step 1: Check if transaction is already processed (Idempotency Key)
    existing_txn = await db.transactions.find_one({"idempotency_key": transaction.idempotency_key})
    if existing_txn:
        return {"message": "Duplicate transaction ignored", "transaction_id": str(existing_txn["_id"])}

    # Step 2: Add money atomically
    result = await db.accounts.update_one(
        {"user_id": user_id},
        {"$inc": {"balance": transaction.amount}}
    )

    if result.modified_count == 0:
        raise HTTPException(status_code=400, detail="Account not found")
    # Retrieve the updated account to get the new balance.
    account = await db.accounts.find_one({"user_id": user_id})
    new_balance = account.get("balance", 0)
    # Step 3: Log the transaction
    txn_log = {
        "user_id": user_id,
        "account_number": account.get("account_number", "unknown"),  # Updated here!
        "amount": transaction.amount,
        "type": "deposit",
        "timestamp": datetime.datetime.utcnow(),
        "idempotency_key": transaction.idempotency_key
    }
    await db.transactions.insert_one(txn_log)

    return {"message": "Deposit successful", "new_balance": new_balance}

# Withdraw Money API with Locking Uses pessimistic locking to prevent race conditions.
@router.post("/withdraw")
async def withdraw(transaction: TransactionRequest, current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]

    # Step 1: Check for duplicate transactions (Idempotency Key)
    existing_txn = await db.transactions.find_one({"idempotency_key": transaction.idempotency_key})
    if existing_txn:
        return {"message": "Duplicate transaction ignored", "transaction_id": str(existing_txn["_id"])}

    # Step 2: Lock the account before withdrawing (Pessimistic Locking)
    lock_result = await db.accounts.update_one(
        {"user_id": user_id, "locked": False, "balance": {"$gte": transaction.amount}},  # Ensure balance is sufficient
        {"$set": {"locked": True}}  # Lock the account
    )

    if lock_result.modified_count == 0:
        raise HTTPException(status_code=400, detail="Insufficient balance or account locked")

    try:
        # Deduct the amount atomically using $inc.
        withdraw_result = await db.accounts.update_one(
            {"user_id": user_id},
            {"$inc": {"balance": -transaction.amount}}
        )
        if withdraw_result.modified_count == 0:
            raise HTTPException(status_code=400, detail="Withdrawal failed")

        # Retrieve updated account balance.
        account = await db.accounts.find_one({"user_id": user_id})
        new_balance = account.get("balance", 0)

        # Log the withdrawal transaction.
        txn_log = {
            "user_id": user_id,
            "account_number": account.get("account_number", "unknown"),
            "amount": transaction.amount,
            "type": "withdraw",
            "timestamp": datetime.datetime.utcnow(),
            "idempotency_key": transaction.idempotency_key
        }
        await db.transactions.insert_one(txn_log)
    finally:
        # Ensure that the account is unlocked even if an error occurs.
        await db.accounts.update_one({"user_id": user_id}, {"$set": {"locked": False}})

    return {"message": "Withdrawal successful", "new_balance": new_balance}
