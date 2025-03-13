from fastapi import APIRouter, HTTPException, Depends, Request
from app.models import UserCreate, UserResponse, UserDB
from app.utils import hash_password, verify_password, create_jwt_token , log_audit_action
from app.config import db
from app.utils import require_roles
from bson import ObjectId
from typing import  Dict
from datetime import datetime, timedelta

router = APIRouter()


FAILED_ATTEMPTS_THRESHOLD = 5  # Maximum allowed failed attempts
LOCK_TIME_MINUTES = 10         # Lock account for 10 minutes if threshold exceeded
FAILED_WINDOW_MINUTES = 10     # Consider failed attempts within a 10-minute window

def convert_objectids(item: Dict) -> Dict:
    if isinstance(item, dict):
        for key, value in item.items():
            if isinstance(value, ObjectId):
                item[key] = str(value)
            elif isinstance(value, list):
                item[key] = [convert_objectids(i) if isinstance(i, dict) else i for i in value]
            elif isinstance(value, dict):
                item[key] = convert_objectids(value)
    return item


# Register User API
@router.post("/register", response_model=UserResponse)
async def register(user: UserCreate):
    existing_user = await db.users.find_one({"email": user.email})
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed_password = hash_password(user.password)
    user_data = {"name": user.name, "email": user.email, "hashed_password": hashed_password , "role": user.role }
    new_user = await db.users.insert_one(user_data)

    return UserResponse(id=str(new_user.inserted_id), name=user.name, email=user.email , role=user.role)

# Login API
@router.post("/login")
async def login(user: UserCreate ,request: Request):
    db_user = await db.users.find_one({"email": user.email})
    print("db_user" , db_user)
    if not db_user:
        # For security, you might not want to reveal whether the email exists.
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Check if account is locked
    lock_until = db_user.get("lock_until")
    if lock_until:
        lock_until_dt = datetime.fromisoformat(lock_until) if isinstance(lock_until, str) else lock_until
        if datetime.utcnow() < lock_until_dt:
            raise HTTPException(
                status_code=403,
                detail=f"Account locked until {lock_until_dt.isoformat()}. Please try later."
            )
    
    # Verify password
    if not verify_password(user.password, db_user["hashed_password"]):
        # On failed login, update failed_attempts and last_failed_attempt
        failed_attempts = db_user.get("failed_attempts", 0) + 1
        update_fields = {"failed_attempts": failed_attempts, "last_failed_attempt": datetime.utcnow().isoformat()}
        
        # If threshold reached within the time window, set lock_until
        last_failed_str = db_user.get("last_failed_attempt")
        if last_failed_str:
            last_failed = datetime.fromisoformat(last_failed_str)
        else:
            last_failed = datetime.utcnow()
        
        if failed_attempts >= FAILED_ATTEMPTS_THRESHOLD and (datetime.utcnow() - last_failed) < timedelta(minutes=FAILED_WINDOW_MINUTES):
            lock_until_time = datetime.utcnow() + timedelta(minutes=LOCK_TIME_MINUTES)
            update_fields["lock_until"] = lock_until_time.isoformat()
        
        await db.users.update_one({"_id": db_user["_id"]}, {"$set": update_fields})
        await log_audit_action(request, str(db_user["_id"]), "login_failed", {"failed_attempts": failed_attempts})
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Successful login: reset failed_attempts and lock_until
    await db.users.update_one(
        {"_id": db_user["_id"]},
        {"$set": {"failed_attempts": 0}, "$unset": {"lock_until": ""}}
    )
    

    print("Reached here")
    token = create_jwt_token({"user_id": str(db_user["_id"]), "email": db_user["email"] , "role": db_user.get("role", "customer")})
    # Log the login action
    await log_audit_action(request, str(db_user["_id"]), "login", {"email": user.email})
    return {"access_token": token, "token_type": "bearer"}


@router.get("/audit-logs", dependencies=[Depends(require_roles(["admin"]))])
async def get_audit_logs():
    logs = await db.audit_logs.find().to_list(length=None)
    # Convert ObjectId fields in each log entry
    logs = [convert_objectids(log) for log in logs]
    return {"audit_logs": logs}