import streamlit as st
import google.generativeai as genai
from pymongo import MongoClient, ReturnDocument
from datetime import datetime
import gridfs
from docx import Document
import os
import time

# ----------------------------
# CONFIG (Replace with your keys)
# ----------------------------
MONGO_URI = "mongodb+srv://nexusteam751_db_user:TyPtleJnMk9up8Sc@product-database.6hm9ilm.mongodb.net/"
MAIN_GEMINI_KEY = "AIzaSyBEtyBTP5sreIqit9Gvb1XyvIQZAgf7624"
SUMMARY_GEMINI_KEY = "AIzaSyBGnFufYa4fkxpGi8xw0O5H_PBCxqAij74"
GEMINI_MODEL = "gemini-2.5-flash-lite"

# ----------------------------
# MongoDB Setup
# ----------------------------
client = MongoClient(MONGO_URI)
db = client["Product_Database"]
Order_Database = db["Order_Database"]
Product_Details = db["Product_Details"]
Legal_Compliance = db["Legal_Compliance"]
Policy_Summary_by_Category = db["Policy_Summary_by_Category"]
Policy_Hierarchy = db["Policy_Hierarchy"]
Decision_Tree_Logic = db["Decision_Tree_Logic"]
Risk_Assesment_Matrix = db["Risk_Assesment_Matrix"]
convo_db = client["conversations"]

fs_db = client["file_storage"]
fs = gridfs.GridFS(fs_db)

# Configure Gemini
genai.configure(api_key=MAIN_GEMINI_KEY)
model = genai.GenerativeModel(GEMINI_MODEL)

# ----------------------------
# Helper Functions
# ----------------------------
def fetch_all_documents(collection, limit=100):
    return [{k: v for k, v in doc.items() if k != "_id"} for doc in collection.find().limit(limit)]

def list_user_orders(user_id):
    queries = [{"User_ID": user_id}, {"user_id": user_id}, {"CustomerID": user_id}]
    for q in queries:
        docs = list(Order_Database.find(q, {"_id": 0}))
        if docs:
            return docs
    return []

def load_previous_conversation(user_id, order_id, limit=50):
    collection = convo_db[str(user_id)]
    cursor = collection.find({"order_id": order_id}).sort("last_updated", -1)
    messages = []
    for doc in cursor:
        messages.extend(doc.get("messages", []))
    return messages[-limit:]

def append_message(user_id, order_id, role, text):
    collection = convo_db[str(user_id)]
    doc = collection.find_one_and_update(
        {"order_id": order_id},
        {"$setOnInsert": {
            "user_id": user_id, "order_id": order_id,
            "messages": [], "created_at": datetime.utcnow()
        }},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )

    collection.update_one(
        {"_id": doc["_id"]},
        {"$push": {"messages": {"role": role, "text": text, "timestamp": datetime.utcnow()}},
         "$set": {"last_updated": datetime.utcnow()}}
    )
    return doc["_id"]


def build_prompt(order, decision, policy, hierarchy, legal, risk, history, user_query):
    history_lines = []
    for m in history[-20:]:
        role = "User" if m["role"] == "user" else "Assistant"
        history_lines.append(f"{role}: {m['text']}")

    history_text = "\n".join(history_lines) if history_lines else "No previous messages."

    return f"""
You are SupportBot — polite, expert, and concise.
Use ONLY the provided information.

Conversation History:
{history_text}

[ORDER DETAILS]
{order}

[PRODUCT DECISION LOGIC]
{decision}

[POLICY SUMMARY]
{policy}

[POLICY HIERARCHY]
{hierarchy}

[LEGAL COMPLIANCE]
{legal}

[RISK MATRIX]
{risk}

User Query: {user_query}

Follow the rules:
- Acknowledge briefly
- 2–4 lines of actionable help
- End with ONE next step
"""


def call_gemini(prompt):
    try:
        chat = model.start_chat()
        reply = chat.send_message(prompt)
        return reply.text
    except Exception as e:
        return f"Error: {e}"

# ----------------------------
# STREAMLIT UI
# ----------------------------
st.title("💬 Agentic E-Commerce Customer Support System")

# Store session variables
if "messages" not in st.session_state:
    st.session_state.messages = []
if "selected_order" not in st.session_state:
    st.session_state.selected_order = None
if "user_id" not in st.session_state:
    st.session_state.user_id = None

# ---------------------------------------
# STEP 1 — User ID Input
# ---------------------------------------
user_id = st.text_input("Enter User ID")

if user_id:
    st.session_state.user_id = user_id
    orders = list_user_orders(user_id)

    if len(orders) == 0:
        st.warning("No orders found for this user.")
        st.stop()

    order_choice = st.selectbox("Select an Order", range(len(orders)),
                                format_func=lambda i: f"Order: {orders[i].get('Order_ID')} | Product: {orders[i].get('Product_ID')}")

    st.session_state.selected_order = orders[order_choice]
    order = st.session_state.selected_order

    # Load DB Context
    policy_data = fetch_all_documents(Policy_Hierarchy)
    legal_data = fetch_all_documents(Legal_Compliance)
    risk_data = fetch_all_documents(Risk_Assesment_Matrix)

    policy_summary = Policy_Summary_by_Category.find_one(
        {"Category": order.get("Category")}, {"_id": 0}) or {}

    decision_tree = Decision_Tree_Logic.find_one(
        {"Product_ID": order.get("Product_ID")}, {"_id": 0}) or {}

    # Load old chat
    history = load_previous_conversation(user_id, order.get("Order_ID"))

    st.subheader("Chat")

    # Display previous messages
    for msg in history:
        st.write(f"**{msg['role'].capitalize()}**: {msg['text']}")

    user_query = st.text_area("Your message")

    if st.button("Send"):
        if user_query.strip() == "":
            st.warning("Enter a message.")
            st.stop()

        append_message(user_id, order["Order_ID"], "user", user_query)

        # Build prompt
        prompt = build_prompt(order, decision_tree, policy_summary,
                              policy_data, legal_data, risk_data,
                              history, user_query)

        bot_reply = call_gemini(prompt)
        append_message(user_id, order["Order_ID"], "bot", bot_reply)

        st.success("Reply Generated:")
        st.write(bot_reply)

        st.session_state.messages.append(("user", user_query))
        st.session_state.messages.append(("bot", bot_reply))

        st.experimental_rerun()
