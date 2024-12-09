from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
import os
from pymongo import MongoClient
import jwt
from bs4 import BeautifulSoup
import requests
from urllib.parse import urljoin
import aiohttp
from bson import ObjectId  # Import ObjectId to handle MongoDB's ObjectId type

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
scraped_docs_collection = db["scraped_docs"]

CORS(app, 
     resources={
         r"/*": {
             "origins": ["http://localhost:3000"],
             "allow_headers": [
                 "Content-Type", 
                 "Authorization", 
                 "Access-Control-Allow-Origin", 
                 "Access-Control-Allow-Credentials"
             ],
             "supports_credentials": True,
             "methods": ["OPTIONS", "GET", "POST", "PUT", "DELETE"]
         }
     }
)

# Middleware for token validation
@app.before_request
def authenticate():
    if request.method == 'OPTIONS' or request.path in ["/signup"]:
        return

    auth_header = request.headers.get("Authorization")    
    if not auth_header:
        return jsonify({"error": "Authorization token is required"}), 401

    # Remove "Bearer " prefix
    token = auth_header.split(" ")[1] if " " in auth_header else auth_header

    try:
        decoded = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        print(decoded)
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

async def fetch_content(session, link):
    """Fetch and clean content from all <p> tags in the given URL asynchronously."""
    try:
        async with session.get(link) as response:
            response_text = await response.text()
            soup = BeautifulSoup(response_text, "html.parser")
            # Extract all <p> tags' text content
            paragraphs = soup.find_all('p')
            # Join and clean text from all <p> tags
            content = " ".join(p.get_text(strip=True) for p in paragraphs)
            return content if content else "No content found"
    except Exception as e:
        return f"Error fetching content: {str(e)}"

async def parse_sidebar_item(item, base_url, session):
    """Recursively parse sidebar items into the desired format, with content."""
    link_tag = item.find("a")
    if not link_tag or not link_tag.get("href"):  # Skip items without links
        return None

    name = item.get_text(strip=True)
    relative_link = link_tag["href"]
    full_link = urljoin(base_url, relative_link)  # Construct the full URL
    content = await fetch_content(session, full_link)  # Fetch content asynchronously
    children = []

    sublist = item.find("ul")  # Look for nested lists
    if sublist:
        for subitem in sublist.find_all("li", recursive=False):
            parsed_child = await parse_sidebar_item(subitem, base_url, session)
            if parsed_child:  # Only add children that have links
                children.append(parsed_child)

    return {"name": name, "link": full_link, "content": content, "children": children}

@app.route("/scrape_website", methods=["POST"])
async def scrape_website():
    data = request.json
    url = data.get('url')

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    try:
        async with aiohttp.ClientSession() as session:
            # Fetch the HTML content of the website
            async with session.get(url) as response:
                response_text = await response.text()
                soup = BeautifulSoup(response_text, "html.parser")

            # Adjust the selector based on the sidebar structure
            sidebar = soup.select_one(".nextra-menu-desktop")
            if not sidebar:
                return jsonify({"error": "Sidebar not found"}), 404

            # Parse sidebar items
            parsed_items = []
            for item in sidebar.find_all("li", recursive=False):
                parsed_item = await parse_sidebar_item(item, url, session)
                if parsed_item:  # Only add items that have links
                    parsed_items.append(parsed_item)

            result = {
                "name": url, 
                "baselink": url, 
                "tree": parsed_items, 
                "user_id":ObjectId(request.user.get("_id"))
            }
            insert_result = scraped_docs_collection.insert_one(result)

            return jsonify({
                "acknowledged": True,
                "inserted_id": str(insert_result.inserted_id)
            })
    except Exception as e:
        return jsonify({"error": "Scraping failed", "details": str(e)}), 500
    

if __name__ == "__main__":
    app.run(debug=True, port=8000)
