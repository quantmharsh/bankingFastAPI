from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.routes import users, accounts, transactions
from slowapi import Limiter
from slowapi.util import get_remote_address
from dotenv import load_dotenv
from app.config import db
load_dotenv()

limiter = Limiter(key_func=get_remote_address)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Create indexes
    # Users Collection
    await db.users.create_index("email", unique=True)
    # Accounts Collection
    await db.accounts.create_index("user_id")
    await db.accounts.create_index("account_number", unique=True)
    # Transactions Collection
    await db.transactions.create_index("user_id")
    await db.transactions.create_index("timestamp")
    await db.transactions.create_index("idempotency_key", unique=True)
    await db.transactions.create_index([("type", 1), ("status", 1)])
    print("Indexes created successfully.")
    
    yield  

app = FastAPI(title="Banking API", lifespan=lifespan)

@app.middleware("http")
async def limit_requests(request, call_next):
    response = await limiter.limit("100/minute")(call_next)(request)
    return response

# Include Routes
app.include_router(users.router, prefix="/users", tags=["Users"])
app.include_router(accounts.router, prefix="/bank", tags=["Accounts"])
app.include_router(transactions.router, prefix="/transactions", tags=["Transactions"])

@app.get("/")
async def root():
    return {"message": "Banking API is running!"}
