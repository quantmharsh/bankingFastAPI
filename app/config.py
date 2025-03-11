import os
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

# Load environment variables from .env file
# Load environment variables from .env file
load_dotenv()


# Get values from .env
JWT_SECRET = os.getenv("JWT_SECRET", "your_super_secret_key")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

# Debugging: Print values to verify
print(f"JWT_SECRET: {JWT_SECRET}")
print(f"JWT_ALGORITHM: {JWT_ALGORITHM}")

# Ensure values are not None
if not JWT_SECRET or not JWT_ALGORITHM:
    raise ValueError("Missing JWT_SECRET or JWT_ALGORITHM in .env file")

# MongoDB Connection
MONGO_URI = os.getenv("MONGO_URI")
client = AsyncIOMotorClient(MONGO_URI)
db = client.banking  # Database name
