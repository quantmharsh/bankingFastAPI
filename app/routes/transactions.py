from fastapi import APIRouter, Depends, HTTPException ,Request
from app.config import db
from app.models import TransactionRequest, TransactionLog
from app.utils import get_current_user  ,log_audit_action

from datetime import datetime, timedelta

from app.utils import require_roles
from bson import ObjectId
from app.models import TransferRequest
from fastapi import Query ,Path
from typing import Optional, Dict, List
from app.tasks import send_email_notification  # Import the Celery task
from app.cache import redis_client  # import the redis client
router = APIRouter()


# ------------------------------
# Fraud Detection Helper Function
# ------------------------------
async def check_fraud(user_id: str, txn_type: str, amount: float, recipient_account: Optional[str] = None) -> Dict:
    """
    Check fraud rules for withdrawals and transfers.
    
    Rules:
      - Daily limit: total withdrawals/transfers (status "success") in a day must not exceed 50,000 Rs.
      - Hourly frequency: maximum 20 withdrawals/transfers in the past hour.
      - For transfers: maximum 5 transfers to the same recipient per day.
      - Single transaction threshold: if amount > 25,000 Rs, block the transaction.
    Returns a dict with keys:
      "block": bool, "reason": str, "status": "blocked" if blocked.
    """
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    one_hour_ago = now - timedelta(hours=1)

    # 1. Daily total (only count successful withdrawals/transfers)
    daily_txns = await db.transactions.find({
        "user_id": user_id,
        "type": {"$in": ["withdraw", "transfer"]},
        "timestamp": {"$gte": today_start, "$lte": today_end},
        "status": "success"
    }).to_list(length=None)
    daily_total = sum(txn["amount"] for txn in daily_txns)
    if daily_total + amount > 50000:
        return {"block": True, "reason": "Daily limit exceeded", "status": "blocked"}

    # 2. Hourly frequency check (count successful transactions in the last hour)
    hourly_txns = await db.transactions.find({
        "user_id": user_id,
        "type": {"$in": ["withdraw", "transfer"]},
        "timestamp": {"$gte": one_hour_ago},
        "status": "success"
    }).to_list(length=None)
    if len(hourly_txns) >= 20:
        return {"block": True, "reason": "Hourly transaction frequency exceeded", "status": "blocked"}

    # 3. For transfers: check if more than 5 transfers to the same recipient today
    if txn_type == "transfer" and recipient_account:
        transfers_to_recipient = await db.transactions.find({
            "user_id": user_id,
            "type": "transfer",
            "to_account": recipient_account,
            "timestamp": {"$gte": today_start, "$lte": today_end},
            "status": "success"
        }).to_list(length=None)
        if len(transfers_to_recipient) >= 5:
            return {"block": True, "reason": "Too many transfers to this recipient today", "status": "blocked"}

    # 4. For large single transactions: if amount > 25,000 Rs then block
    if amount > 25000:
        return {"pending": True, "reason": "Transaction amount exceeds 25,000 Rs , pending admin approval", "status": "pending"}

    return {"block": False}

# Deposit Money API
@router.post("/deposit")
async def deposit(transaction: TransactionRequest, request: Request, current_user: dict = Depends(get_current_user) ):
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
            "timestamp": datetime.utcnow(),
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
        "timestamp": datetime.utcnow(),
        "idempotency_key": transaction.idempotency_key ,
        "status": "success"  # Mark as successful
    }
    await db.transactions.insert_one(txn_log)
      # After logging the successful deposit transaction:
    await log_audit_action(request, user_id, "deposit", {"amount": transaction.amount, "idempotency_key": transaction.idempotency_key})

    return {"message": "Deposit successful", "new_balance": new_balance}

# Withdraw Money API with Locking Uses pessimistic locking to prevent race conditions.
@router.post("/withdraw")
async def withdraw(transaction: TransactionRequest,  request: Request,current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]

    # Step 1: Check for duplicate transactions (Idempotency Key)
    existing_txn = await db.transactions.find_one({"idempotency_key": transaction.idempotency_key})
    if existing_txn:
        return {"message": "Duplicate transaction ignored", "transaction_id": str(existing_txn["_id"])}
     # Fraud check for withdrawal (no recipient for withdrawals)
    fraud_result = await check_fraud(user_id, "withdraw", transaction.amount)
    if fraud_result.get("block"):
        # Log the blocked withdrawal
        txn_log = {
            "user_id": user_id,
            "account_number": "unknown",
            "amount": transaction.amount,
            "type": "withdraw",
            "timestamp": datetime.utcnow(),
            "idempotency_key": transaction.idempotency_key,
            "status": fraud_result["status"]
        }
        await db.transactions.insert_one(txn_log)
         # Log the fraud event in audit logs as well
        await log_audit_action(request, user_id, "withdraw_blocked", {"amount": transaction.amount, "reason": fraud_result["reason"]})
        raise HTTPException(status_code=400, detail=fraud_result["reason"])
    if fraud_result.get("pending"):
        # Log the blocked withdrawal
        txn_log = {
            "user_id": user_id,
            "account_number": "unknown",
            "amount": transaction.amount,
            "type": "withdraw",
            "timestamp": datetime.utcnow(),
            "idempotency_key": transaction.idempotency_key,
            "status": fraud_result["status"]
        }
        await db.transactions.insert_one(txn_log)
        await log_audit_action(request, user_id, "withdraw_pending", {"amount": transaction.amount})
        return {"message": "Withdrawal pending admin approval"}
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
            "timestamp":datetime.utcnow(),
            "idempotency_key": transaction.idempotency_key,
            "status": "failed"
        }
        await db.transactions.insert_one(fail_txn_log)
        await log_audit_action(request, user_id, "withdraw_pending", {"amount": transaction.amount})
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
            "timestamp": datetime.utcnow(),
            "idempotency_key": transaction.idempotency_key,
            "status": "success"  # Mark as successful
        }
        await db.transactions.insert_one(txn_log)
        await log_audit_action(request, user_id, "withdraw_success", {"amount": transaction.amount})
  
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
    request:Request,
    current_user: dict = Depends(get_current_user)
):
    sender_id = current_user["user_id"]

    # Step 1: Check for duplicate transfer via idempotency key.
    existing_txn = await db.transactions.find_one({"idempotency_key": transfer.idempotency_key})
    if existing_txn:
        return {"message": "Duplicate transaction ignored", "transaction_id": str(existing_txn["_id"])}
    

    # Fraud check for transfer (including recipient-specific rules)
    fraud_result = await check_fraud(sender_id, "transfer", transfer.amount, recipient_account=transfer.to_account)
    if fraud_result.get("block"):
        txn_log = {
            "user_id": sender_id,
            "account_number": "unknown",
            "amount": transfer.amount,
            "type": "transfer",
            "timestamp": datetime.utcnow(),
            "idempotency_key": transfer.idempotency_key,
            "status": fraud_result["status"],
            "to_account": transfer.to_account
        }
        await db.transactions.insert_one(txn_log)
        await log_audit_action(request, sender_id, "transfer_blocked", {"amount": transfer.amount, "to_account": transfer.to_account})
        raise HTTPException(status_code=400, detail=fraud_result["reason"])
    if fraud_result.get("pending"):
        # Log pending transfer and return.
        txn_log = {
            "user_id": sender_id,
            "account_number": "unknown",
            "amount": transfer.amount,
            "type": "transfer",
            "timestamp": datetime.utcnow(),
            "idempotency_key": transfer.idempotency_key,
            "status": fraud_result["status"],
            "to_account": transfer.to_account
        }
        await db.transactions.insert_one(txn_log)
        await log_audit_action(request, sender_id, "transfer_pending", {"amount": transfer.amount, "to_account": transfer.to_account})
        return {"message": "Transfer pending admin approval"}
    
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
            "timestamp": datetime.utcnow(),
            "idempotency_key": transfer.idempotency_key,
            "status": "failed",
             "to_account": transfer.to_account
    }
            await db.transactions.insert_one(fail_txn_log)
            await log_audit_action(request, sender_id, "transfer_failed", {"amount": transfer.amount, "to_account": transfer.to_account})
            raise HTTPException(status_code=400, detail="Failed to credit recipient account")

        # Step 7: Log the transfer transaction with extra details.
        txn_log = {
            "user_id": sender_id,
            "account_number": sender_account.get("account_number", "unknown"),
            "amount": transfer.amount,
            "type": "transfer",
            "timestamp": datetime.utcnow(),
            "idempotency_key": transfer.idempotency_key,
            "to_account": transfer.to_account,
            "status":"success"  # Additional field for transfers
        }
        await db.transactions.insert_one(txn_log)
        await log_audit_action(request, sender_id, "transfer_success", {"amount": transfer.amount, "to_account": transfer.to_account})
        # **Trigger the email notification task** asynchronously.
        # For example, send an email to the sender notifying the transfer.
        send_email_notification.delay(
            current_user["email"],
            "Transfer Confirmation",
            f"You have successfully transferred Rs.{transfer.amount} to account {transfer.to_account}."
        )
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



#  For ADMIN to get all pending transaactions
@router.get("/pending", dependencies=[Depends(require_roles(["admin"]))])
async def list_pending_transactions():
    pending_txns = await db.transactions.find({"status": "pending"}).to_list(length=None)
    pending_txns = [convert_objectids(txn) for txn in pending_txns]
    return {"pending_transactions": pending_txns}


@router.post("/pending/{txn_id}" )
async def process_pending_transaction(
    txn_id: str,
    request:Request, 
    action: str = Query(..., description="Action to perform: approve or reject"),
    
    current_user: dict = Depends(require_roles(["admin"]))
):
    # Find the pending transaction by its ObjectId
    pending_txn = await db.transactions.find_one({"_id": ObjectId(txn_id), "status": "pending"})
    if not pending_txn:
        raise HTTPException(status_code=404, detail="Pending transaction not found")

    if action not in ["approve", "reject"]:
        raise HTTPException(status_code=400, detail="Action must be either 'approve' or 'reject'.")

    if action == "reject":
        await db.transactions.update_one({"_id": ObjectId(txn_id)}, {"$set": {"status": "failed"}})
        await log_audit_action(request, pending_txn["user_id"], "pending_rejected", {"txn_id": txn_id})
        return {"message": "Transaction rejected"}

    # If approving, then perform the funds movement based on transaction type
    txn_type = pending_txn["type"]
    if txn_type == "withdraw":
        user_id = pending_txn["user_id"]
        # Check if sufficient funds now exist
        account = await db.accounts.find_one({"user_id": user_id})
        if not account or account["balance"] < pending_txn["amount"]:
            await db.transactions.update_one({"_id": ObjectId(txn_id)}, {"$set": {"status": "failed"}})
            raise HTTPException(status_code=400, detail="Insufficient funds at approval time")
        # Deduct the funds
        debit_result = await db.accounts.update_one({"user_id": user_id}, {"$inc": {"balance": -pending_txn["amount"]}})
        if debit_result.modified_count == 0:
            await db.transactions.update_one({"_id": ObjectId(txn_id)}, {"$set": {"status": "failed"}})
            raise HTTPException(status_code=400, detail="Failed to debit funds on approval")
        # Mark as approved (success)
        await db.transactions.update_one({"_id": ObjectId(txn_id)}, {"$set": {"status": "success"}})
        await log_audit_action(request, user_id, "pending_withdraw_approved", {"txn_id": txn_id})
        return {"message": "Withdrawal approved and funds deducted"}
    
    elif txn_type == "transfer":
        sender_id = pending_txn["user_id"]
        recipient_account_number = pending_txn.get("to_account")
        # Check sender account
        sender_account = await db.accounts.find_one({"user_id": sender_id})
        if not sender_account or sender_account["balance"] < pending_txn["amount"]:
            await db.transactions.update_one({"_id": ObjectId(txn_id)}, {"$set": {"status": "failed"}})
            raise HTTPException(status_code=400, detail="Insufficient funds for transfer at approval time")
        # Debit sender
        debit_result = await db.accounts.update_one({"user_id": sender_id}, {"$inc": {"balance": -pending_txn["amount"]}})
        if debit_result.modified_count == 0:
            await db.transactions.update_one({"_id": ObjectId(txn_id)}, {"$set": {"status": "failed"}})
            raise HTTPException(status_code=400, detail="Failed to debit sender on approval")
        # Credit recipient
        credit_result = await db.accounts.update_one({"account_number": recipient_account_number}, {"$inc": {"balance": pending_txn["amount"]}})
        if credit_result.modified_count == 0:
            # Rollback debit
            await db.accounts.update_one({"user_id": sender_id}, {"$inc": {"balance": pending_txn["amount"]}})
            await db.transactions.update_one({"_id": ObjectId(txn_id)}, {"$set": {"status": "failed"}})
            raise HTTPException(status_code=400, detail="Failed to credit recipient on approval")
        # Mark as approved (success)
        await db.transactions.update_one({"_id": ObjectId(txn_id)}, {"$set": {"status": "success"}})
        await log_audit_action(request, sender_id, "pending_transfer_approved", {"txn_id": txn_id})
        return {"message": "Transfer approved; funds debited and credited"}
    else:
        raise HTTPException(status_code=400, detail="Unsupported transaction type for approval")