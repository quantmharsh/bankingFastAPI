from fastapi import APIRouter, Depends, HTTPException
from app.config import db
from app.models import TransactionRequest, TransactionLog
from app.utils import get_current_user

from datetime import datetime, timedelta

from app.utils import require_roles
from bson import ObjectId
from app.models import TransferRequest
from fastapi import Query
from typing import Optional, Dict, List

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
         # Log a "failed" deposit transaction if the update didn't affect any documents
        fail_txn_log = {
            "user_id": user_id,
            "account_number": "unknown",  # We don’t have a valid account number
            "amount": transaction.amount,
            "type": "deposit",
            "timestamp": datetime.datetime.utcnow(),
            "idempotency_key": transaction.idempotency_key,
            "status": "failed"
        }
        await db.transactions.insert_one(fail_txn_log)
        raise HTTPException(status_code=400, detail="Account not found or invalid ")
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
        "idempotency_key": transaction.idempotency_key ,
        "status": "success"  # Mark as successful
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
        fail_txn_log = {
            "user_id": user_id,
            "account_number": "unknown",
            "amount": transaction.amount,
            "type": "withdraw",
            "timestamp": datetime.datetime.utcnow(),
            "idempotency_key": transaction.idempotency_key,
            "status": "failed"
        }
        await db.transactions.insert_one(fail_txn_log)
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
            "idempotency_key": transaction.idempotency_key,
            "status": "success"  # Mark as successful
        }
        await db.transactions.insert_one(txn_log)
    finally:
        # Ensure that the account is unlocked even if an error occurs.
        await db.accounts.update_one({"user_id": user_id}, {"$set": {"locked": False}})

    return {"message": "Withdrawal successful", "new_balance": new_balance}


def convert_objectids(item):
    """
    Recursively convert ObjectId fields in a dictionary to strings.
    """
    if isinstance(item, dict):
        for key, value in item.items():
            if isinstance(value, ObjectId):
                item[key] = str(value)
            elif isinstance(value, list):
                item[key] = [convert_objectids(i) for i in value]
            elif isinstance(value, dict):
                item[key] = convert_objectids(value)
    return item

@router.get("/all-transactions")
async def all_transactions(current_user: dict = Depends(require_roles(["admin"]))):
    # Only admin can see all transaction logs
    transactions = await db.transactions.find().to_list(None)
    # Convert ObjectId fields to strings for JSON serialization
    transactions = [convert_objectids(txn) for txn in transactions]
    return {"transactions": transactions}

@router.post("/transfer")
async def transfer_funds(
    transfer: TransferRequest,
    current_user: dict = Depends(get_current_user)
):
    sender_id = current_user["user_id"]

    # Step 1: Check for duplicate transfer via idempotency key.
    existing_txn = await db.transactions.find_one({"idempotency_key": transfer.idempotency_key})
    if existing_txn:
        return {"message": "Duplicate transaction ignored", "transaction_id": str(existing_txn["_id"])}

    # Step 2: Retrieve the sender's account.
    sender_account = await db.accounts.find_one({"user_id": sender_id})
    if not sender_account:
        raise HTTPException(status_code=404, detail="Sender account not found")

    # Ensure sender has enough funds.
    if sender_account["balance"] < transfer.amount:
        raise HTTPException(status_code=400, detail="Insufficient funds")

    # Step 3: Retrieve the recipient's account using the provided account number.
    recipient_account = await db.accounts.find_one({"account_number": transfer.to_account})
    if not recipient_account:
        raise HTTPException(status_code=404, detail="Recipient account not found")

    # Step 4: Lock the sender's account (pessimistic locking) to prevent race conditions.
    lock_result = await db.accounts.update_one(
        {"user_id": sender_id, "locked": False, "balance": {"$gte": transfer.amount}},
        {"$set": {"locked": True}}
    )
    if lock_result.modified_count == 0:
        raise HTTPException(status_code=400, detail="Sender account is currently locked or insufficient funds")

    try:
        # Step 5: Debit sender's account atomically.
        debit_result = await db.accounts.update_one(
            {"user_id": sender_id},
            {"$inc": {"balance": -transfer.amount}}
        )
        if debit_result.modified_count == 0:
            raise HTTPException(status_code=400, detail="Failed to debit sender account")

        # Step 6: Credit recipient's account atomically.
        credit_result = await db.accounts.update_one(
            {"account_number": transfer.to_account},
            {"$inc": {"balance": transfer.amount}}
        )
        if credit_result.modified_count == 0:
            # Rollback debit if credit fails.
            await db.accounts.update_one(
                {"user_id": sender_id},
                {"$inc": {"balance": transfer.amount}}
            )
              # Log a failed transaction
            fail_txn_log = {
            "user_id": sender_id,
            "account_number": sender_account.get("account_number", "unknown"),
            "amount": transfer.amount,
            "type": "transfer",
            "timestamp": datetime.datetime.utcnow(),
            "idempotency_key": transfer.idempotency_key,
            "status": "failed"
    }
            await db.transactions.insert_one(fail_txn_log)
            raise HTTPException(status_code=400, detail="Failed to credit recipient account")

        # Step 7: Log the transfer transaction with extra details.
        txn_log = {
            "user_id": sender_id,
            "account_number": sender_account.get("account_number", "unknown"),
            "amount": transfer.amount,
            "type": "transfer",
            "timestamp": datetime.datetime.utcnow(),
            "idempotency_key": transfer.idempotency_key,
            "to_account": transfer.to_account  # Additional field for transfers
        }
        await db.transactions.insert_one(txn_log)
    finally:
        # Step 8: Unlock the sender's account regardless of success or error.
        await db.accounts.update_one({"user_id": sender_id}, {"$set": {"locked": False}})

    return {"message": "Transfer successful"}

@router.get("/balance")
async def check_balance(current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    account = await db.accounts.find_one({"user_id": user_id})
    if not account:
        raise HTTPException(status_code=404, detail="No account found")
    return {"account_number": account["account_number"], "balance": account["balance"]}

@router.get("/")
async def filter_transactions(
    current_user: dict = Depends(get_current_user),
    txn_type: Optional[str] = Query(None, description="Filter by transaction type: deposit, withdraw, transfer"),
    status: Optional[str] = Query(None, description="Filter by transaction status: success, failed, blocked, pending"),
    start_date: Optional[str] = Query(None, description="Start date in YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="End date in YYYY-MM-DD")
):
    # Only retrieve transactions for the logged-in user
    query = {"user_id": current_user["user_id"]}
    
    if txn_type:
        query["type"] = txn_type
    if status:
        query["status"] = status
    try:
        if start_date and end_date:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            # Extend end_dt to cover the entire day (23:59:59)
            end_dt = end_dt.replace(hour=23, minute=59, second=59)
            query["timestamp"] = {"$gte": start_dt, "$lte": end_dt}
        elif start_date:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            query["timestamp"] = {"$gte": start_dt}
        elif end_date:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            end_dt = end_dt.replace(hour=23, minute=59, second=59)
            query["timestamp"] = {"$lte": end_dt}
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
    
    transactions: List[Dict] = await db.transactions.find(query).to_list(length=None)
    transactions = [convert_objectids(txn) for txn in transactions]
    return {"transactions": transactions}
