from fastapi import APIRouter, HTTPException, Depends
from app.models import UserCreate, UserResponse, UserDB
from app.utils import hash_password, verify_password, create_jwt_token
from app.config import db

router = APIRouter()

# Register User API
@router.post("/register", response_model=UserResponse)
async def register(user: UserCreate):
    existing_user = await db.users.find_one({"email": user.email})
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed_password = hash_password(user.password)
    user_data = {"name": user.name, "email": user.email, "hashed_password": hashed_password}
    new_user = await db.users.insert_one(user_data)

    return UserResponse(id=str(new_user.inserted_id), name=user.name, email=user.email)

# Login API
@router.post("/login")
async def login(user: UserCreate):
    db_user = await db.users.find_one({"email": user.email})
    print("db_user" , db_user)
    if not db_user or not verify_password(user.password, db_user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    print("Reached here")
    token = create_jwt_token({"user_id": str(db_user["_id"]), "email": db_user["email"]})
    return {"access_token": token, "token_type": "bearer"}
