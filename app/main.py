from fastapi import FastAPI
from app.routes import users
from dotenv import load_dotenv
load_dotenv()

app = FastAPI(title="Banking API")


# Include Routes
app.include_router(users.router, prefix="/users", tags=["Users"])

@app.get("/")
async def root():
    return {"message": "Banking API is running!"}



# {
#   "name": "John Doe",
#   "email": "johndoe@example.com",
#   "password": "securepass123"
# }
