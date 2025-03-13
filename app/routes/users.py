from fastapi import APIRouter, HTTPException, Depends, Request
from app.models import UserCreate, UserResponse, UserDB
from app.utils import hash_password, verify_password, create_jwt_token , log_audit_action
from app.config import db
from app.utils import require_roles
from bson import ObjectId
from typing import  Dict
router = APIRouter()

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
    if not db_user or not verify_password(user.password, db_user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
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