import logging
from datetime import datetime, timedelta, timezone
import database as db
import llm_service
import memory_vector_service

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DementiaCompanion:
    def __init__(self, patient_id):
        self.patient_id = patient_id
        self.patient_name = self.get_patient_name()
        
    def get_patient_name(self):
        conn = db.get_db_connection()
        try:
            patient = conn.execute("SELECT name FROM patients WHERE id = ?", (self.patient_id,)).fetchone()
            return patient['name'] if patient else "friend"
        finally:
            conn.close()
    
    def process_input(self, user_speech):
        try:
            # 1. Gather Real-time Context
            all_tasks = db.get_all_tasks(self.patient_id)
            pending_tasks = [t for t in all_tasks if not t['completed']]
            recent_history = db.get_recent_conversations(self.patient_id, limit=3)
            
            # 2. Router: Ask LLM what the user wants
            ai_decision = llm_service.get_ai_response(user_speech, pending_tasks, recent_history)
            
            intent = ai_decision.get("intent")
            initial_response = ai_decision.get("response_text")
            params = ai_decision.get("parameters", {})
            
            logger.info(f"User: {user_speech} | Intent: {intent} | Action: {params.get('action')}")

            # 3. Execute Logic based on Intent
            if intent == "manage_task":
                return self._handle_task_logic(params, initial_response, pending_tasks)
            
            elif intent == "save_memory":
                return self._handle_memory_save(user_speech, initial_response, params)
                
            elif intent == "recall_memory":
                return self._handle_memory_recall(user_speech)

            elif intent == "delete_memory":
                return self._handle_memory_delete(initial_response)
            
            elif intent == "danger":
                return "I understand you are upset. I am going to contact your caregiver to help you right now."

            return initial_response

        except Exception as e:
            logger.error(f"Error processing input: {str(e)}")
            return "I'm sorry, I'm having a little trouble thinking right now. Let's try again in a moment."
        
    # ------------------------------------------------------------------
    # UTILITY FUNCTIONS
    # ------------------------------------------------------------------

    def _parse_time_safely(self, time_str, raw_time_str=""):
        """
        Robust time parsing with proper validation
        Returns: HH:MM format string or None if invalid
        """
        try:
            clean_time = str(time_str).lower().strip()

            # Already in HH:MM format?
            if ":" in clean_time:
                parts = clean_time.replace("am", "").replace("pm", "").strip().split(":")
                hour = int(parts[0])
                minute = int(parts[1]) if len(parts) > 1 else 0
            else:
                # Just a number like "9" or "nine"
                hour = int(clean_time.replace("am", "").replace("pm", "").strip())
                minute = 0

            # Handle PM conversion
            if ("pm" in clean_time or "pm" in raw_time_str.lower()) and hour < 12:
                hour += 12

            # Handle midnight/noon edge cases
            if hour == 12 and ("am" in clean_time or "am" in raw_time_str.lower()):
                hour = 0

            # Validate 24-hour format
            if not (0 <= hour <= 23) or not (0 <= minute <= 59):
                logger.warning(f"Invalid time: hour={hour}, minute={minute}")
                return None

            return f"{hour:02d}:{minute:02d}"

        except (ValueError, AttributeError, IndexError) as e:
            logger.warning(f"Time parsing failed for '{time_str}': {e}")
            return None

    def _validate_date_format(self, date_str):
        """
        Validates date string is in YYYY-MM-DD format
        """
        if not date_str:
            return False
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
            return True
        except ValueError:
            return False

    def _is_valid_memory_note(self, note_content):
        """
        Validates memory note content
        """
        if not note_content or not isinstance(note_content, str):
            return False

        cleaned = note_content.strip().lower().replace(".", "").replace("?", "")

        # Check for empty/whitespace only
        if not cleaned or len(cleaned) < 3:
            return False

        # Check if it's actually a command disguised as a note
        command_keywords = ["delete", "clear", "remove", "add task", "schedule", "complete"]
        for keyword in command_keywords:
            if keyword in cleaned:
                return False

        return True

    # ------------------------------------------------------------------
    # ACTION HANDLERS
    # ------------------------------------------------------------------

    def _handle_task_logic(self, params, response_text, all_tasks, pending_tasks):
        """
        Enhanced task management with better error handling
        """
        action = params.get("action")
        target_task = params.get("task_name")
        time_param = params.get("time")
        date_param = params.get("task_date")

        # Validate and default date
        if not date_param or not self._validate_date_format(date_param):
            utc_now = datetime.now(timezone.utc)
            ist_now = utc_now + timedelta(hours=5, minutes=30)
            date_param = ist_now.strftime("%Y-%m-%d")

        # 1. COMPLETION LOGIC
        if action == "complete" and target_task:
            task_exists = any(t['task_name'].lower() == target_task.lower() for t in pending_tasks)

            if task_exists:
                # Find exact task name from database
                db_task_name = next(
                    (t['task_name'] for t in pending_tasks if t['task_name'].lower() == target_task.lower()), 
                    target_task
                )
                db.mark_task_completed(self.patient_id, db_task_name)
                return response_text
            else:
                return "You've already finished that task today!"

        # 2. CREATION LOGIC
        elif action == "create":
            if target_task and not time_param:
                return f"At what time would you like to schedule {target_task.replace('_', ' ')}?"

            if target_task and time_param:
                # Use robust time parsing
                parsed_time = self._parse_time_safely(
                    time_param, 
                    raw_time_str=params.get("raw_time", str(time_param))
                )

                if not parsed_time:
                    return f"I didn't understand that time. Could you say it again? For example, '9am' or '2:30pm'."

                # Create task with improved return handling
                result = db.create_task(self.patient_id, target_task, parsed_time, task_date=date_param)

                date_msg = "today"
                utc_now = datetime.now(timezone.utc)
                ist_today = (utc_now + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")

                if date_param != ist_today:
                    date_msg = f"on {date_param}"

                # Handle different return codes
                if result == 1:
                    return f"Okay, I've added {target_task.replace('_', ' ')} for {parsed_time} {date_msg}."
                elif result == 0:
                    return f"You already have {target_task.replace('_', ' ')} on your list for {date_msg}."
                else:
                    return "I had trouble adding that task. Could you try again?"

        # 3. DELETION LOGIC
        elif action == "delete" and target_task:
            # Check ALL tasks (not just pending)
            task_match = next(
                (t for t in all_tasks if t['task_name'].lower() == target_task.lower()), 
                None
            )

            if task_match:
                db_task_name = task_match['task_name']
                success = db.delete_task(self.patient_id, db_task_name, task_date=date_param)

                if success:
                    return f"I have removed {target_task.replace('_', ' ')} from your schedule."
                else:
                    return f"I had trouble removing that task. Could you try again?"
            else:
                return f"I couldn't find a task named {target_task.replace('_', ' ')}."

        # 4. DELETE ALL TASKS
        elif action == "delete_all":
            # Validate date before deletion
            if not self._validate_date_format(date_param):
                return "I had trouble understanding which day you meant. Could you be more specific?"

            count = db.delete_all_tasks(self.patient_id, task_date=date_param)

            if count > 0:
                return f"I have cleared all {count} scheduled tasks for that day."
            return "Your task list is already empty for that day."

        return response_text
    
    def _handle_memory_save(self, user_speech, response_text, params):
        """
        Enhanced memory note validation
        """
        note_content = params.get("note_content")

        # 1. Define Forbidden Trigger Phrases
        triggers = [
            "add a memory note", "add a note", "save a note", "save memory",
            "take a note", "remember something", "write this down", "note",
            "create a note", "make a note", "add note"
        ]

        # 2. Check strictly with improved validation
        if not self._is_valid_memory_note(note_content):
            return "Okay, what specific memory note would you like to add?"

        # Check against trigger phrases
        cleaned_content = note_content.lower().strip().replace(".", "")
        if cleaned_content in triggers:
            return "Okay, what specific memory note would you like to add?"

        # 3. If valid, save it
        final_content = note_content

        # SQL Log
        reminder_time = params.get("due_datetime")
        db.add_memory_note(self.patient_id, final_content, reminder_time)

        # Vector Store
        metadata = {
            "patient_id": self.patient_id,
            "date": datetime.now().isoformat(),
            "type": "general_note"
        }

        try:
            memory_vector_service.save_vector_memory(final_content, metadata)
        except Exception as e:
            logger.error(f"Vector save failed: {e}")
            # Continue even if vector save fails

        return f"Okay, I've saved that note: {final_content}"

    def _handle_memory_recall(self, user_query):
        """
        Recalls memories based on user query
        """
        try:
            found_notes = memory_vector_service.search_similar_memories(user_query)
        except Exception as e:
            logger.error(f"Memory search failed: {e}")
            found_notes = []

        if not found_notes:
            return "I don't have a note about that, but I can write it down if you tell me."

        context_str = "\n".join([
            f"- {n['text']} (Date: {n['metadata'].get('date', 'Unknown')[:10]})" 
            for n in found_notes
        ])

        final_answer = llm_service.synthesize_memory_answer(user_query, context_str)
        return final_answer

    def _handle_memory_delete(self, response_text):
        """
        Deletes ALL memory notes.
        """
        # 1. Delete from SQLite and get count
        deleted_count = db.delete_all_memory_notes(self.patient_id)

        # 2. Delete from Vector DB
        try:
            memory_vector_service.delete_patient_memories(self.patient_id)
        except Exception as e:
            logger.error(f"Vector deletion failed: {e}")

        # 3. Return explicit confirmation
        if deleted_count > 0:
            return f"I have cleared your memory. {deleted_count} notes were removed."
        else:
            return "Your memory notes are already empty."

    def check_missed_tasks(self):
        """
        Checks for tasks that are overdue by more than 1 hour
        """
        tasks = db.get_all_tasks(self.patient_id)
        current_time = datetime.now()
        missed = []

        for task in tasks:
            if not task['completed']:
                try:
                    task_time = datetime.strptime(task['scheduled_time'], '%H:%M').time()
                    scheduled_datetime = datetime.combine(datetime.today(), task_time)

                    if current_time > scheduled_datetime + timedelta(hours=1):
                        missed.append(task['task_name'].replace('_', ' '))
                except ValueError as e:
                    logger.warning(f"Invalid time format for task {task.get('id')}: {e}")
                    continue

        return missed