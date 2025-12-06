import os
from dotenv import load_dotenv
import google.generativeai as genai
import json
from datetime import datetime, timedelta, timezone
import re
import logging

load_dotenv()

# Configure the SDK with your API key from .env
genai.configure(api_key=os.getenv('GOOGLE_API_KEY'))

# System instructions for the persona "Kaya"
SYSTEM_INSTRUCTION = """
You are Kaya, a compassionate memory assistant.

CURRENT CONTEXT:
Time: {current_time}
Pending Tasks: {pending_tasks}

Output strict JSON.

RULES FOR INTENTS:

1. **MANAGE_TASK** (Schedule/Calendar):
   - Trigger: "Add [Task]", "Delete [Task]", "Clear all tasks".
   - Action: "create", "complete", "delete", "delete_all".
   - Include "task_name", "time", "task_date".
   - **DATE CALCULATION**: If user says "tomorrow", calculate date based on CURRENT CONTEXT Time.
   
   - **CRITICAL OVERRIDE**: Before classifying as MANAGE_TASK, look at the "RECENT CONVERSATION HISTORY". 
     - If the last thing YOU said was a question asking for a note (e.g., "What memory note would you like to add?"), you **MUST** classify the user's reply as **SAVE_MEMORY**, even if it contains a time like "9pm". The user is answering your question.

2. **SAVE_MEMORY** (Facts/Notes):
   - Trigger: "Note that...", "Remember that...", "My daughter visited".
   - **NEGATIVE CONSTRAINT**: "Delete tasks" or "Clear list" is ALWAYS manage_task.
   - **CONTEXT PRIORITY**: If you just asked the user for a note, their reply IS the note. Classify as 'save_memory'.
   - Action: "save".
   - Parameter "note_content": The user's entire sentence.

3. **RECALL_MEMORY**:
   - Trigger: "What did I do today?", "Who visited me?", "Do I have any notes?".
   - Action: "recall".

4. **DELETE_MEMORY**:
   - Trigger: "Delete all my notes", "Clear my memory".
   - Action: "delete_all".

5. **TIME FORMAT**: Convert to 24-hour HH:MM.
"""

def get_ai_response(user_text, pending_tasks_list, recent_history):
    try:
        utc_now = datetime.now(timezone.utc)
        ist_now = utc_now + timedelta(hours=5, minutes=30)
        current_time = ist_now.strftime("%A, %Y-%m-%d, %I:%M %p")
        
        tasks_str = ", ".join([t['task_name'] for t in pending_tasks_list]) or "None"
        
        history_str = ""
        if recent_history:
            # Reverse history so it flows chronologically (Oldest -> Newest)
            for turn in reversed(recent_history):
                history_str += f"User: {turn['user_message']}\nKaya: {turn['agent_response']}\n"
        
        # Inject history into the prompt
        formatted_system_prompt = SYSTEM_INSTRUCTION.format(
            current_time=current_time, 
            pending_tasks=tasks_str
        )
        
        # We append the history strictly to the context
        full_prompt = f"""
        {formatted_system_prompt}

        RECENT CONVERSATION HISTORY:
        {history_str}
        
        USER'S NEW INPUT:
        {user_text}
        """

        model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            generation_config={"response_mime_type": "application/json"}
        )

        response = model.generate_content(full_prompt)
        
        # Robust JSON cleaning/parsing
        try:
            return json.loads(response.text)
        except json.JSONDecodeError:
            clean_text = re.sub(r"```(json)?", "", response.text, flags=re.IGNORECASE).strip()
            return json.loads(clean_text)

    except Exception as e:
        print(f"!!! GEMINI API ERROR: {str(e)}")
        logging.error(f"Gemini API Error: {e}")
        return {
            "intent": "chat", 
            "response_text": "I'm having a little trouble connecting, but I'm here with you.",
            "parameters": {}
        }

def synthesize_memory_answer(user_query, context_str):
    try:
        model = genai.GenerativeModel("gemini-2.0-flash")
        
        prompt = f"""
        You are Kaya. Answer the user's question gently, using ONLY the context below.
        If the context doesn't have the answer, say "I don't see a note about that."

        USER QUESTION: "{user_query}"
        
        MEMORY CONTEXT:
        {context_str}
        """
        
        response = model.generate_content(prompt)
        return response.text.strip()

    except Exception as e:
        logging.error(f"Gemini Memory Synthesis Error: {e}")
        return "I found a note, but I'm having trouble reading it right now."