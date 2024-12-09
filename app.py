from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
import os
from pymongo import MongoClient
import jwt
import json
import trafilatura
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
from urllib.parse import urlparse, urljoin
from bson.objectid import ObjectId
from datetime import datetime


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

@app.route("/scrape_website", methods=["POST"])
def scrape_website():
    data = request.json
    url = data.get('url')
    
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    
    try:
        # Get the current user from the request
        current_user = request.user.get('user', {})
        user_id = current_user.get('_id')
        
        if not user_id:
            return jsonify({"error": "User not authenticated"}), 401

        # Use requests to fetch the page
        import requests
        from bs4 import BeautifulSoup
        import re

        # Send a request with user agent to mimic browser
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers)
        
        # Parse the HTML
        soup = BeautifulSoup(response.text, 'html.parser')

        def extract_doc_tree(soup):
            # Try multiple selectors for sidebar
            sidebar_selectors = [
                'nav.sidebar',
                'div.sidebar',
                'aside.sidebar',
                'nav.docs-sidebar',
                'div.documentation-menu',
                'aside'
            ]

            sidebar = None
            for selector in sidebar_selectors:
                sidebar = soup.select_one(selector)
                if sidebar:
                    break

            if not sidebar:
                return []

            def build_tree(element):
                tree = []
                
                # Find all links in the sidebar
                links = element.find_all('a', href=True)
                
                for link in links:
                    href = link.get('href')
                    # Handle relative URLs
                    if href.startswith('/'):
                        href = f"{url.rstrip('/')}{href}"
                    
                    # Try to get full page content
                    try:
                        page_response = requests.get(href, headers=headers)
                        page_soup = BeautifulSoup(page_response.text, 'html.parser')
                        
                        # Try multiple content selectors
                        content_selectors = [
                            'main', 
                            'article', 
                            'div.content', 
                            'div.documentation'
                        ]
                        
                        content_element = None
                        for content_selector in content_selectors:
                            content_element = page_soup.select_one(content_selector)
                            if content_element:
                                break
                        
                        # Extract text content
                        content = content_element.get_text(strip=True) if content_element else "No content found"
                    
                    except Exception as e:
                        content = f"Error extracting content: {str(e)}"
                    
                    # Create node
                    node = {
                        "name": link.get_text(strip=True),
                        "content": content,
                        "children": []  # You can expand this for nested structures
                    }
                    
                    tree.append(node)
                
                return tree

            # Build and return the documentation tree
            return build_tree(sidebar)

        # Extract document tree
        doc_tree = extract_doc_tree(soup)
        
        # Prepare document for MongoDB
        scrape_document = {
            "user_id": ObjectId(user_id),
            "url": url,
            "doc_tree": doc_tree,
            "scraped_at": datetime.utcnow(),
            "metadata": {
                "total_pages": len(doc_tree),
                "status": "completed"
            }
        }
        
        # Insert into MongoDB
        result = scraped_docs_collection.insert_one(scrape_document)
        
        return jsonify({
            "message": "Documentation site scraped successfully",
            "document_id": str(result.inserted_id),
            "doc_tree": doc_tree,
            "pages_count": len(doc_tree)
        }), 200
    
    except Exception as e:
        return jsonify({
            "error": f"Scraping failed: {str(e)}",
            "details": str(e)
        }), 500
    

if __name__ == "__main__":
    app.run(debug=True, port=8000)
