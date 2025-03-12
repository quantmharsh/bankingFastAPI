from fastapi import APIRouter, HTTPException, Depends
from app.models import UserCreate, UserResponse, UserDB
from app.utils import hash_password, verify_password, create_jwt_token
from app.config import db
from app.utils import require_roles

router = APIRouter()

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
async def login(user: UserCreate):
    db_user = await db.users.find_one({"email": user.email})
    print("db_user" , db_user)
    if not db_user or not verify_password(user.password, db_user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    print("Reached here")
    token = create_jwt_token({"user_id": str(db_user["_id"]), "email": db_user["email"] , "role": db_user.get("role", "customer")})
    return {"access_token": token, "token_type": "bearer"}


@router.get("/audit-logs")
async def get_audit_logs(current_user: dict = Depends(require_roles(["admin"]))):
    # Only an admin can access this
    # Query the audit logs from DB
    logs = await db.audit_logs.find().to_list(None)
    return logs