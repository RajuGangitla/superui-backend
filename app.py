from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
import os
from pymongo import MongoClient
import jwt

load_dotenv()

app = Flask(__name__)

MONGO_URL = os.getenv("MONOGO_URL")
SECRET_KEY = os.getenv("SECRET_KEY") 
if not MONGO_URL:
    raise Exception("MongoDB URL not found in environment variables!")

# Connect to MongoDB
client = MongoClient(MONGO_URL)
db = client["test"] 
collection = db["users"] 

CORS(app, 
     origins=["http://localhost:3000", "http://localhost:3000/"],
     supports_credentials=True,
     methods=["OPTIONS", "GET", "POST", "PUT", "DELETE"],
     allow_headers=["*"]
)

# Middleware for token validation
@app.before_request
def authenticate():
    if request.path in ["/signup"]:
        return

    token = request.headers.get("Authorization")
    if not token:
        return jsonify({"error": "Authorization token is required"}), 401

    try:
        decoded = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        request.user = decoded  
    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Token has expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token"}), 401

@app.route("/signup", methods=["POST"])
def signup():
    data = request.json
    email = data.get("email")
    if not email:
        return jsonify({"error": "email is needed"}), 400

    user_exists = collection.find_one({"email": email})
    if user_exists:
        user_exists["_id"] = str(user_exists["_id"])  # Convert ObjectId to string
        token = jwt.encode({"user": user_exists}, SECRET_KEY, algorithm="HS256")
        return jsonify({
            "message": "User already exists",
            "user": user_exists,
            "token": token
        }), 200
    else:
        result = collection.insert_one(data)
        user_id = str(result.inserted_id)
        token = jwt.encode({"user": {"_id": user_id, "email": email}}, SECRET_KEY, algorithm="HS256")
        return jsonify({
            "message": "User added",
            "user": {"_id": user_id, "email": email},
            "token": token
        }), 201

@app.route("/getUser", methods=["GET"])
def get_user():
    print(request.user)
    return jsonify({"message": "User fetched successfully", "user": request.user})

if __name__ == "__main__":
    app.run(debug=True, port=8000)
