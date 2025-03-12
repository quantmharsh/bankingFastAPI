from fastapi import FastAPI
from app.routes import users, accounts, transactions
from slowapi import Limiter
from slowapi.util import get_remote_address
from dotenv import load_dotenv
load_dotenv()

app = FastAPI(title="Banking API")
limiter = Limiter(key_func=get_remote_address)

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



# {
#   "name": "John Doe",
#   "email": "johndoe@example.com",
#   "password": "securepass123"
# }
