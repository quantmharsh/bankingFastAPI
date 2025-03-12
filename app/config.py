import os
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

# Load environment variables from .env file
# Load environment variables from .env file
load_dotenv()

# Get values from .env without defaults
JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM")
MONGO_URI = os.getenv("MONGO_URI")

# Debugging: Print values to verify (optional; remove in production)
print(f"JWT_SECRET: {JWT_SECRET}")
print(f"JWT_ALGORITHM: {JWT_ALGORITHM}")
print(f"MONGO_URI: {MONGO_URI}")


# Ensure required environment variables are set
if not JWT_SECRET or not JWT_ALGORITHM:
    raise ValueError("Missing JWT_SECRET or JWT_ALGORITHM in .env file")
if not MONGO_URI:
    raise ValueError("Missing MONGO_URI in .env file")

# MongoDB Connection
MONGO_URI = os.getenv("MONGO_URI")
client = AsyncIOMotorClient(MONGO_URI)
db = client.banking  # Database name
