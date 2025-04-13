#REPLACE YOURISD with your actual ISD name

import os
import json
import time
import uuid
import threading
import requests
from datetime import datetime, date, timedelta
from flask import (
    Flask, request, jsonify, make_response, render_template_string,
    Response, redirect, url_for, send_file
)
import io
from groq import Groq

###############################################################################
# CONFIG & GLOBALS
###############################################################################

app = Flask(__name__)
app.secret_key = "replace_with_strong_secret"  # Important: use a secure secret key in production!

CANVAS_BASE_URL = "https://YOURISD.instructure.com"  # UPDATE to your Canvas domain
CHUNK_SIZE = 5000

DB_FOLDER = "db"  # subfolder for storing user data
if not os.path.exists(DB_FOLDER):
    os.makedirs(DB_FOLDER)

# Groq client (Update your key/model as needed)
GROQ_API_KEY = "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"
groq_client = Groq(api_key=GROQ_API_KEY)

###############################################################################
# FILE-BASED "DB" HELPER FUNCTIONS
###############################################################################

def get_user_path(cookie_id):
    return os.path.join(DB_FOLDER, cookie_id)

def create_user_folder_if_needed(cookie_id):
    """
    Create a folder for this cookie if it doesn't exist.
    Initialize minimal metadata.json, empty extracted_data.json, empty conversation.json.
    Also create a subfolder for submissions_downloads (where file attachments go).
    """
    user_path = get_user_path(cookie_id)
    if not os.path.exists(user_path):
        os.makedirs(user_path)
        # Create the user's default subfolders
        downloads_path = os.path.join(user_path, "submissions_downloads")
        os.makedirs(downloads_path, exist_ok=True)

        # Initialize metadata
        meta = {
            "canvas_token": "",
            "logs": [],
            "in_progress": False,
            "in_progress_submissions": False,
            "styling": "hacker",
            "ai_instructions": (
                "You are an advanced AI that has access to a summary chart of Canvas data. "
                "Each row shows: [CourseName | AssignmentName | DueDate | Attempts | Submitted? | Score | LockedDate]. "
                "You should first try to solve the user's question from your own reasoning, then consult the chart. "
                "The user sees the chart differently, but you see it as a structured table. "
                "Don't rely too heavily on the chart unless it's truly relevant to the question. "
                "Always provide direct answers without asking for further questions or clarification. "
                "If you need to ask the user a question, make sure it's a simple yes/no or multiple-choice question. "
                "ANYTHIING GIVEN BY (SYSTEM) IS NOT TO BE USED IN THE YOUR RESPONSES ONLY FAINTLY KEPT IN MIND"
            ),
            "last_extraction_time": None,
            "chart_summary": ""
        }
        save_metadata(cookie_id, meta)

        # Initialize extracted_data.json
        with open(os.path.join(user_path, "extracted_data.json"), "w", encoding="utf-8") as f:
            json.dump([], f)

        # Initialize submissions_data.json
        with open(os.path.join(user_path, "submissions_data.json"), "w", encoding="utf-8") as f:
            json.dump([], f)

        # Initialize conversation.json
        with open(os.path.join(user_path, "conversation.json"), "w", encoding="utf-8") as f:
            json.dump([], f)

def load_metadata(cookie_id):
    path = os.path.join(get_user_path(cookie_id), "metadata.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_metadata(cookie_id, meta):
    path = os.path.join(get_user_path(cookie_id), "metadata.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

def load_extracted_data(cookie_id):
    path = os.path.join(get_user_path(cookie_id), "extracted_data.json")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_extracted_data(cookie_id, data):
    path = os.path.join(get_user_path(cookie_id), "extracted_data.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def load_submissions_data(cookie_id):
    path = os.path.join(get_user_path(cookie_id), "submissions_data.json")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_submissions_data(cookie_id, data):
    path = os.path.join(get_user_path(cookie_id), "submissions_data.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def load_conversation(cookie_id):
    path = os.path.join(get_user_path(cookie_id), "conversation.json")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_conversation(cookie_id, conversation):
    path = os.path.join(get_user_path(cookie_id), "conversation.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(conversation, f, indent=2)

def save_chart(cookie_id, chart_text):
    """
    Save the actual chart in a file, but also store it in metadata for easy AI access.
    """
    user_path = get_user_path(cookie_id)
    with open(os.path.join(user_path, "chart.txt"), "w", encoding="utf-8") as f:
        f.write(chart_text)

    meta = load_metadata(cookie_id)
    if meta:
        meta["chart_summary"] = chart_text
        save_metadata(cookie_id, meta)

def load_chart(cookie_id):
    user_path = get_user_path(cookie_id)
    path = os.path.join(user_path, "chart.txt")
    if not os.path.exists(path):
        return "(No chart generated.)"
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def append_log(cookie_id, message):
    meta = load_metadata(cookie_id)
    if not meta:
        return
    meta["logs"].append(message)
    save_metadata(cookie_id, meta)
    print(f"[{cookie_id}] {message}")

def get_logs(cookie_id):
    meta = load_metadata(cookie_id)
    if not meta:
        return []
    return meta["logs"]

def set_in_progress(cookie_id, value: bool):
    meta = load_metadata(cookie_id)
    if meta:
        meta["in_progress"] = value
        save_metadata(cookie_id, meta)

def is_in_progress(cookie_id) -> bool:
    meta = load_metadata(cookie_id)
    return meta["in_progress"] if meta else False

def update_extraction_time(cookie_id):
    """
    Store the current UTC time as last_extraction_time in metadata.
    """
    meta = load_metadata(cookie_id)
    if meta:
        meta["last_extraction_time"] = datetime.utcnow().isoformat()
        save_metadata(cookie_id, meta)

###############################################################################
# 48-HOUR TOKEN REUSE LOGIC
###############################################################################

def find_cookie_by_token(token):
    """
    Check all db/<cookie_id>/metadata.json. If any has the same token AND
    last_extraction_time is within 48 hours, return that cookie_id.
    """
    now = datetime.utcnow()
    cutoff = now - timedelta(hours=48)

    if not os.path.exists(DB_FOLDER):
        return None

    for cookie_id in os.listdir(DB_FOLDER):
        user_path = os.path.join(DB_FOLDER, cookie_id)
        if not os.path.isdir(user_path):
            continue
        meta_path = os.path.join(user_path, "metadata.json")
        if not os.path.isfile(meta_path):
            continue

        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        if meta.get("canvas_token") == token:
            last_extraction_str = meta.get("last_extraction_time")
            if last_extraction_str:
                try:
                    last_extract_dt = datetime.fromisoformat(last_extraction_str)
                    if last_extract_dt > cutoff:
                        return cookie_id
                except ValueError:
                    pass
    return None

###############################################################################
# GRAPHQL EXTRACTION
###############################################################################

def extract_via_graphql(token):
    """
    Attempt to extract courses & assignments using Canvas's GraphQL endpoint.
    If successful, return a list of courses. If it fails, raise an Exception.
    """
    graph_url = f"{CANVAS_BASE_URL}/api/graphql"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # Example GraphQL query
    query = """
    query MyCourses {
      allCourses {
        _id
        id
        name
        assignmentsConnection {
          nodes {
            _id
            id
            name
            dueAt
            lockAt
            pointsPossible
            hasSubmittedSubmissions
            description
          }
        }
      }
    }
    """

    resp = requests.post(graph_url, headers=headers, json={"query": query})
    resp.raise_for_status()  # raise if 4xx/5xx

    data = resp.json()
    if "errors" in data:
        raise Exception(f"GraphQL errors: {data['errors']}")

    courses_data = data["data"]["allCourses"]
    all_data = []
    for c in courses_data:
        course_id = c.get("id")
        course_name = c.get("name", "Unnamed GraphQL")
        assignments_list = c.get("assignmentsConnection", {}).get("nodes", [])
        course_info = {
            "course_id": course_id,
            "course_name": course_name,
            "assignments": []
        }
        for a in assignments_list:
            assignment_id = a.get("id")
            assignment_name = a.get("name", "Unnamed Assignment")
            due_at = a.get("dueAt")
            details = {
                "lock_at": a.get("lockAt"),
                "points_possible": a.get("pointsPossible"),
                "has_submitted_submissions": a.get("hasSubmittedSubmissions"),
                "description": a.get("description"),
            }
            course_info["assignments"].append({
                "assignment_id": assignment_id,
                "assignment_name": assignment_name,
                "due_at": due_at,
                "details": details
            })
        all_data.append(course_info)

    return all_data

###############################################################################
# REST EXTRACTION
###############################################################################

def get_paginated_data(url, headers):
    data = []
    while url:
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        data.extend(resp.json())
        if "Link" in resp.headers:
            links = resp.headers["Link"].split(",")
            url = None
            for link in links:
                if 'rel="next"' in link:
                    url = link[link.find("<") + 1 : link.find(">")]
                    break
        else:
            url = None
    return data

def extract_via_rest(cookie_id, token):
    all_data = []
    headers = {"Authorization": f"Bearer {token}"}
    try:
        courses_url = f"{CANVAS_BASE_URL}/api/v1/courses"
        append_log(cookie_id, f"Fetching courses via REST: {courses_url}")
        courses = get_paginated_data(courses_url, headers)

        for course in courses:
            cid = course.get("id")
            cname = course.get("name", "Unnamed")
            if not cid:
                continue

            append_log(cookie_id, f"Fetching assignments for course {cid} ({cname})...")
            try:
                assignments_url = f"{CANVAS_BASE_URL}/api/v1/courses/{cid}/assignments"
                assignments = get_paginated_data(assignments_url, headers)
            except requests.HTTPError as e:
                if e.response.status_code == 403:
                    append_log(cookie_id, f"403 Forbidden for course {cid}. Skipping.")
                    continue
                else:
                    append_log(cookie_id, f"Error fetching assignments for {cid}: {str(e)}")
                    continue

            course_info = {
                "course_id": cid,
                "course_name": cname,
                "assignments": []
            }
            for a in assignments:
                aid = a.get("id")
                aname = a.get("name", "Unnamed Assignment")
                due = a.get("due_at")
                if not aid:
                    continue

                detail_url = f"{CANVAS_BASE_URL}/api/v1/courses/{cid}/assignments/{aid}"
                try:
                    detail_resp = requests.get(detail_url, headers=headers)
                    detail_resp.raise_for_status()
                except requests.HTTPError as e:
                    if e.response.status_code == 403:
                        append_log(cookie_id, f"403 Forbidden for assignment {aid} in course {cid}. Skipping.")
                        continue
                    else:
                        append_log(cookie_id, f"Error fetching assignment {aid}: {str(e)}")
                        continue

                details = detail_resp.json()
                course_info["assignments"].append({
                    "assignment_id": aid,
                    "assignment_name": aname,
                    "due_at": due,
                    "details": details
                })

            all_data.append(course_info)
    except Exception as e:
        append_log(cookie_id, f"REST extraction error: {str(e)}")

    return all_data

###############################################################################
# MASTER EXTRACTION
###############################################################################

def do_extraction(cookie_id, token):
    """
    1) Attempt GraphQL for speed, fallback to REST.
    2) Save data, store last_extraction_time.
    3) No chunk summarization; we rely on the chart now.
    """
    set_in_progress(cookie_id, True)
    append_log(cookie_id, "Starting extraction... (attempting GraphQL)")

    all_data = []
    try:
        # Try GraphQL first
        all_data = extract_via_graphql(token)
        append_log(cookie_id, f"GraphQL extraction successful. Found {len(all_data)} courses.")
    except Exception as gql_err:
        append_log(cookie_id, f"GraphQL extraction failed: {str(gql_err)}. Fallback to REST.")
        all_data = extract_via_rest(cookie_id, token)

    if not all_data:
        append_log(cookie_id, "No data extracted from GraphQL or REST.")
        set_in_progress(cookie_id, False)
        return

    # Save data, update extraction time
    save_extracted_data(cookie_id, all_data)
    update_extraction_time(cookie_id)
    append_log(cookie_id, "Extraction complete.")
    set_in_progress(cookie_id, False)

###############################################################################
# SUBMISSIONS EXTRACTION (with file downloads)
###############################################################################

def do_submissions_extraction(cookie_id, token):
    """
    Fetch all submissions for each course in the user’s Canvas,
    store them in submissions_data.json,
    AND physically download the attached files from each submission
    into a subfolder for that user.
    """
    # Mark as in progress
    meta = load_metadata(cookie_id)
    meta["in_progress_submissions"] = True
    save_metadata(cookie_id, meta)

    append_log(cookie_id, "[Submissions] Starting submissions extraction...")

    headers = {"Authorization": f"Bearer {token}"}
    all_submissions = []

    # Base folder to store downloaded attachments
    user_path = get_user_path(cookie_id)
    downloads_base = os.path.join(user_path, "submissions_downloads")

    try:
        # 1) Get the user's courses
        courses_url = f"{CANVAS_BASE_URL}/api/v1/courses"
        append_log(cookie_id, f"[Submissions] Fetching courses: {courses_url}")
        courses = get_paginated_data(courses_url, headers)

        total_courses = len(courses)
        courses_processed = 0

        # 2) For each course, list all submissions
        for c in courses:
            cid = c.get("id")
            cname = c.get("name", "Unnamed")
            if not cid:
                continue

            subs_url = f"{CANVAS_BASE_URL}/api/v1/courses/{cid}/students/submissions"
            append_log(cookie_id, f"[Submissions] Fetching from {cname} (id={cid}) => {subs_url}")

            try:
                subs_data = get_paginated_data(subs_url, headers)
            except requests.HTTPError as e:
                append_log(cookie_id, f"[Submissions] Error fetching subs for course {cid}: {str(e)}")
                courses_processed += 1
                continue

            # 3) For each submission, if it has attachments, download them
            for submission in subs_data:
                submission_id = submission.get("id")
                assignment_id = submission.get("assignment_id")
                downloaded_paths = []

                # Canvas typically stores submission attachments in submission["attachments"]
                attachments = submission.get("attachments", [])
                for attach in attachments:
                    file_url = attach.get("url")
                    file_name = attach.get("filename") or "unnamed_file"

                    if not file_url:
                        continue  # skip if no direct URL

                    # Make folder e.g. db/<cookie_id>/submissions_downloads/course_123/submission_456/
                    sub_folder = os.path.join(
                        downloads_base,
                        f"course_{cid}",
                        f"submission_{submission_id}"
                    )
                    os.makedirs(sub_folder, exist_ok=True)

                    local_path = os.path.join(sub_folder, file_name)
                    try:
                        # Download file
                        r = requests.get(file_url, headers=headers, stream=True)
                        r.raise_for_status()

                        with open(local_path, "wb") as f:
                            for chunk in r.iter_content(chunk_size=8192):
                                f.write(chunk)

                        downloaded_paths.append(local_path)
                        append_log(cookie_id, f"[Submissions] Downloaded file => {local_path}")
                    except Exception as dl_err:
                        append_log(cookie_id, f"[Submissions] Failed to download {file_url}: {dl_err}")

                # Store the local file paths in the submission data
                submission["downloaded_files"] = downloaded_paths

            # 4) Append all submissions for this course
            all_submissions.append({
                "course_id": cid,
                "course_name": cname,
                "submissions": subs_data
            })

            courses_processed += 1
            progress_percent = int((courses_processed / total_courses) * 100)
            append_log(cookie_id, f"[Submissions] Progress: {progress_percent}%")

        # 5) Save to file
        save_submissions_data(cookie_id, all_submissions)
        append_log(cookie_id, "[Submissions] Extraction complete. Files have been downloaded.")

    except Exception as err:
        append_log(cookie_id, f"[Submissions] Unexpected error: {str(err)}")

    # Mark extraction done
    meta = load_metadata(cookie_id)
    meta["in_progress_submissions"] = False
    save_metadata(cookie_id, meta)

###############################################################################
# SMART FILTERING & CHART
###############################################################################

def get_current_quarter():
    today = date.today()
    if date(2024, 8, 13) <= today <= date(2024, 10, 14):
        return 1, "2024-08-13", "2024-10-14"
    elif date(2024, 10, 15) <= today <= date(2025, 1, 6):
        return 2, "2024-10-15", "2025-01-06"
    elif date(2025, 1, 7) <= today <= date(2025, 3, 23):
        return 3, "2025-01-07", "2025-03-23"
    elif date(2025, 3, 24) <= today <= date(2025, 5, 30):
        return 4, "2025-03-24", "2025-05-30"
    return None, None, None

def generate_chart(cookie_id, extracted_data, quarter, user_options):
    """
    quarter: int 1-4 or 0 for auto-detect
    user_options: { keep_locked, keep_missing, keep_submitted }
    Remove courses that have no assignments after filtering.
    """
    if quarter == 0:
        current_quarter, start_date, end_date = get_current_quarter()
        if not current_quarter:
            append_log(cookie_id, "Date not in any defined quarter.")
            return "No valid quarter found."
    else:
        if quarter == 1:
            current_quarter, start_date, end_date = 1, "2024-08-13", "2024-10-14"
        elif quarter == 2:
            current_quarter, start_date, end_date = 2, "2024-10-15", "2025-01-06"
        elif quarter == 3:
            current_quarter, start_date, end_date = 3, "2025-01-07", "2025-03-23"
        elif quarter == 4:
            current_quarter, start_date, end_date = 4, "2025-03-24", "2025-05-30"
        else:
            return "Invalid quarter selection."

    student_name = cookie_id
    school_name = "Your School Name"

    chart_header = f"{student_name} - {school_name} - {date.today()} - Quarter {current_quarter}\n"
    chart_rows = []
    footnotes = []
    footnote_counter = 1

    def within_quarter(d):
        return (d >= start_date) and (d <= end_date)

    filtered_data = []
    for course in extracted_data:
        course_name = course["course_name"][:20].ljust(20)
        new_assignments = []
        for assignment in course["assignments"]:
            due_date = assignment.get("due_at", "")
            if not due_date or not within_quarter(due_date[:10]):
                continue

            details = assignment.get("details", {})
            locked = details.get("locked_for_user", False)
            if locked and not user_options["keep_locked"]:
                continue

            submitted = details.get("has_submitted_submissions", False)
            if submitted and not user_options["keep_submitted"]:
                continue
            if not submitted and not user_options["keep_missing"]:
                continue

            # format date
            try:
                due_date_formatted = datetime.strptime(due_date, "%Y-%m-%dT%H:%M:%SZ").strftime("%m/%d/%y")
            except:
                due_date_formatted = due_date

            assignment_name = assignment["assignment_name"][:50].ljust(50)
            attempts = details.get("allowed_attempts", -1)
            attempts_display = "∞" if attempts == -1 else f"00/{str(attempts).zfill(2)}"
            points_possible = details.get("points_possible", 0)
            points_earned = "N/A"
            score = f"{str(points_earned).zfill(3)}/{str(points_possible).zfill(3)}"

            locked_at = details.get("lock_at", "")
            locked_date = ""
            if locked_at:
                try:
                    locked_date = datetime.strptime(locked_at, "%Y-%m-%dT%H:%M:%SZ").strftime("%m/%d")
                except:
                    locked_date = locked_at

            row = (
                f"{course_name} | {assignment_name} | {due_date_formatted.rjust(8)} | "
                f"{attempts_display.rjust(5)} | {('Yes' if submitted else 'No').rjust(5)} | {score.rjust(8)} | {locked_date.rjust(5)}"
            )
            chart_rows.append(row)
            new_assignments.append(assignment)

            teacher_comments = details.get("description", "")
            if teacher_comments:
                footnotes.append(f"{footnote_counter}: {teacher_comments}")
                footnote_counter += 1

        if new_assignments:
            filtered_data.append({
                "course_id": course["course_id"],
                "course_name": course["course_name"],
                "assignments": new_assignments
            })

    chart_body = "\n".join(chart_rows) if chart_rows else "(No assignments matched.)"
    footnotes_text = "\n".join(footnotes)

    final_chart = f"{chart_header}\n{chart_body}\n\nFOOTNOTES:\n{footnotes_text}"
    save_chart(cookie_id, final_chart)
    append_log(cookie_id, "Chart generated successfully (and filtered out empty courses).")
    return final_chart

###############################################################################
# MANAGE CONVERSATION SIZE
###############################################################################

def prune_conversation(conversation, max_chars=2000):
    """
    Keep removing oldest user+assistant pairs until the total text is under max_chars.
    We'll preserve any system messages at the front.
    """
    def conv_length(conv):
        total = 0
        for m in conv:
            total += len(m.get("content",""))
        return total

    system_msgs = []
    user_assistant_msgs = []
    for m in conversation:
        if m["role"] == "system":
            system_msgs.append(m)
        else:
            user_assistant_msgs.append(m)

    if conv_length(conversation) <= max_chars:
        return conversation

    new_pairs = []
    pair_buffer = []
    for msg in user_assistant_msgs:
        pair_buffer.append(msg)
        if len(pair_buffer) == 2:
            new_pairs.append(pair_buffer)
            pair_buffer = []
    if pair_buffer:
        new_pairs.append(pair_buffer)

    while True:
        combined = system_msgs[:]
        for pair in new_pairs:
            combined.extend(pair)
        if conv_length(combined) <= max_chars or len(new_pairs) == 0:
            return combined
        new_pairs.pop(0)

###############################################################################
# CSS & TEMPLATES
###############################################################################

BASE_CSS = """
<style>
body {
  margin: 0; padding: 0;
  font-family: sans-serif;
  background-color: #111;
  color: #0f0;
}
.modules-container {
  display: flex;
  flex-wrap: wrap;
  margin: 10px;
  gap: 10px;
}
.module-box {
  border: 2px solid #0f0;
  background-color: #000;
  padding: 10px;
  flex: 1 1 calc(400px);
  min-width: 300px;
  position: relative;
}
.module-header {
  font-weight: bold;
  margin-bottom: 10px;
  border-bottom: 1px dashed #0f0;
  padding-bottom: 5px;
}
.textarea {
  width: 100%;
  height: 60px;
  background-color: #000;
  color: #0f0;
  border: 2px solid #0f0;
}
button {
  background-color: #000;
  color: #0f0;
  border: 2px solid #0f0;
  padding: 5px 10px;
  cursor: pointer;
  margin-top: 5px;
}
button:hover {
  background-color: #0f0;
  color: #000;
}
input[type="text"], select {
  background-color: #000;
  color: #0f0;
  border: 2px solid #0f0;
  width: 100%;
  box-sizing: border-box;
  margin-bottom: 5px;
  padding: 5px;
}
.checkbox-row {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 5px;
}
#cookieDisplay {
  position: absolute; top: 10px; left: 10px;
  border: 1px solid #0f0;
  padding: 5px;
  font-size: 12px;
  background: #000;
}
.log-box {
  background-color: #000;
  border: 1px solid #0f0;
  height: 200px;
  overflow-y: auto;
  padding: 5px;
  font-size: 12px;
  white-space: pre-wrap;
}
.modal-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0,0,0,0.8);
  display: none; 
  justify-content: center;
  align-items: center;
  z-index: 9999;
}
.modal-content {
  background: #222;
  border: 2px solid #0f0;
  padding: 20px;
  max-width: 600px;
}
.modal-content h3 {
  margin-top: 0;
}
.close-btn {
  float: right;
  background: #0f0;
  color: #000;
  border: none;
  padding: 5px;
  cursor: pointer;
}
.close-btn:hover {
  background-color: #000;
  color: #0f0;
  border: 1px solid #0f0;
}
</style>
"""

HOME_TEMPLATE = """
<!doctype html>
<html>
<head>
<meta charset="utf-8"/>
<title>Canvas Helper - Smart Filtering</title>
""" + BASE_CSS + """
</head>
<body>
<div id="cookieDisplay">
  <b>Cookie:</b> {{ user_cookie }}
</div>
<div class="modules-container">
  <!-- Module: Cookie Options -->
  <div class="module-box">
    <div class="module-header">Cookie Options</div>
    <p>If you already have a cookie from another device, enter it here:</p>
    <input type="text" id="cookieField" placeholder="Paste existing cookie if any..."/>
    <button onclick="submitCookie()">Use This Cookie</button>
  </div>

  <!-- Module: Canvas Token -->
  <div class="module-box">
    <div class="module-header">Canvas Token</div>
    <textarea id="tokenInput" class="textarea" placeholder="Enter your Canvas Access Token..."></textarea>
    <button onclick="startExtraction()">Extract & Summarize</button>

    <!-- Extract Submissions + progress bar + Download button -->
    <button onclick="startSubmissionsExtraction()">Extract Submissions</button>
    <br/><br/>
    <progress id="submissionsProgress" value="0" max="100" style="display:none; width:100%;"></progress>
    <button id="downloadSubmissionsBtn" style="display:none; margin-top:5px;"
            onclick="downloadSubmissions()">Download Submissions</button>
  </div>

  <!-- Module: Settings -->
  <div class="module-box">
    <div class="module-header">Settings <button onclick="showSettings()">⚙</button></div>
    <div class="log-box" id="logsBox">Logs will appear here in real-time...</div>
  </div>

  <!-- Module: Filtering / Chart -->
  <div class="module-box">
    <div class="module-header">Smart Filtering</div>
    <label for="quarterSelect">Select Quarter:</label>
    <select id="quarterSelect">
      <option value="0">Auto-detect</option>
      <option value="1">Quarter 1</option>
      <option value="2">Quarter 2</option>
      <option value="3">Quarter 3</option>
      <option value="4">Quarter 4</option>
    </select>
    <div class="checkbox-row">
      <input type="checkbox" id="keepLocked" checked/>
      <label for="keepLocked">Keep Locked</label>
    </div>
    <div class="checkbox-row">
      <input type="checkbox" id="keepMissing" checked/>
      <label for="keepMissing">Keep Missing</label>
    </div>
    <div class="checkbox-row">
      <input type="checkbox" id="keepSubmitted" checked/>
      <label for="keepSubmitted">Keep Submitted</label>
    </div>
    <button onclick="applyFilter()">Generate Chart</button>
    <pre id="chartArea" style="max-height:200px; overflow-y:auto; border:1px solid #0f0;"></pre>
  </div>

  <!-- Module: AI Chat -->
  <div class="module-box" style="flex:1 1 100%;">
    <div class="module-header">AI Chat</div>
    <button onclick="window.location.href='{{ url_for('chat') }}'">Open Chat Page</button>
  </div>
</div>

<!-- Settings Modal -->
<div id="settingsModal" class="modal-overlay">
  <div class="modal-content">
    <button class="close-btn" onclick="hideSettings()">X</button>
    <h3>Site & AI Settings</h3>
    <label for="stylingSelect">Styling Mode:</label>
    <select id="stylingSelect">
      <option value="hacker">Hacker</option>
      <option value="light">Light</option>
    </select>
    <br/><br/>
    <label for="instructionsArea">AI System Instructions:</label><br/>
    <textarea id="instructionsArea" rows="4" style="width:100%;"></textarea><br/>
    <button onclick="saveSettings()">Save Settings</button>
  </div>
</div>

<script>
let evtSource = null;

function submitCookie() {
  const newCookie = document.getElementById('cookieField').value.trim();
  if(!newCookie) {
    alert("Empty cookie field.");
    return;
  }
  fetch("/use_cookie", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ cookie: newCookie })
  })
  .then(r => r.json())
  .then(data => {
    alert(data.message);
    window.location.reload();
  })
  .catch(err => alert("Error: " + err));
}

function startExtraction() {
  const tokenValue = document.getElementById('tokenInput').value.trim();
  if(!tokenValue) {
    alert("Please provide a Canvas Access Token!");
    return;
  }
  // Stop any existing SSE
  if(evtSource) {
    evtSource.close();
  }
  // Start extraction
  fetch("/extract", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ token: tokenValue })
  })
  .then(res => {
    if(!res.ok) throw new Error("Extraction start failed.");
    // SSE for logs
    evtSource = new EventSource("/stream_logs");
    evtSource.onmessage = e => {
      const logsBox = document.getElementById('logsBox');
      logsBox.textContent += "\\n" + e.data;
      logsBox.scrollTop = logsBox.scrollHeight;
    };
    evtSource.onerror = e => {
      console.log("SSE error", e);
      evtSource.close();
    };
  })
  .catch(err => alert(err.message));
}

// Start Submissions Extraction (with file downloads)
function startSubmissionsExtraction() {
  // Reset progress bar + show it
  const progressEl = document.getElementById('submissionsProgress');
  progressEl.style.display = 'block';
  progressEl.value = 0;

  // Hide the download button
  document.getElementById('downloadSubmissionsBtn').style.display = 'none';

  fetch("/submissions", {
    method: "POST"
  })
  .then(res => {
    if(!res.ok) throw new Error("Failed to start submissions extraction.");
    // Reuse the same SSE logs or create a new one. We'll reuse "/stream_logs".
    evtSource = new EventSource("/stream_logs");
    evtSource.onmessage = (e) => {
      const logsBox = document.getElementById('logsBox');
      logsBox.textContent += "\\n" + e.data;
      logsBox.scrollTop = logsBox.scrollHeight;

      // If the log line has "[Submissions] Progress: XX%", update progress
      if (e.data.includes("[Submissions] Progress:")) {
        const match = e.data.match(/Progress:\\s(\\d+)%/);
        if (match) {
          progressEl.value = parseInt(match[1]);
        }
      }
      // Done indicator
      if (e.data.includes("[Submissions] Extraction complete.")) {
        evtSource.close();
        progressEl.value = 100;
        document.getElementById('downloadSubmissionsBtn').style.display = 'inline-block';
      }
    };
    evtSource.onerror = (err) => {
      console.log("Submissions SSE error", err);
      evtSource.close();
    };
  })
  .catch(err => alert("Error: " + err.message));
}

function downloadSubmissions() {
  window.location.href = "/download_submissions";
}

function applyFilter() {
  const quarter = parseInt(document.getElementById('quarterSelect').value);
  const keepLocked = document.getElementById('keepLocked').checked;
  const keepMissing = document.getElementById('keepMissing').checked;
  const keepSubmitted = document.getElementById('keepSubmitted').checked;

  fetch("/filter", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      quarter: quarter,
      keep_locked: keepLocked,
      keep_missing: keepMissing,
      keep_submitted: keepSubmitted
    })
  })
  .then(res => res.json())
  .then(data => {
    if(data.error) {
      alert(data.error);
    } else {
      document.getElementById('chartArea').textContent = data.chart;
    }
  })
  .catch(err => alert("Error: " + err));
}

function showSettings() {
  fetch("/settings", {method: "GET"})
    .then(r => r.json())
    .then(s => {
      document.getElementById('stylingSelect').value = s.styling;
      document.getElementById('instructionsArea').value = s.ai_instructions;
      document.getElementById('settingsModal').style.display = "flex";
    })
    .catch(err => console.log(err));
}
function hideSettings() {
  document.getElementById('settingsModal').style.display = "none";
}
function saveSettings() {
  const styling = document.getElementById('stylingSelect').value;
  const instr = document.getElementById('instructionsArea').value;
  fetch("/settings", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ styling: styling, ai_instructions: instr })
  })
  .then(r => r.json())
  .then(d => {
    alert(d.message);
    hideSettings();
  })
  .catch(err => alert("Error saving settings: " + err));
}
</script>

</body>
</html>
"""

CHAT_TEMPLATE = """
<!doctype html>
<html>
<head>
<meta charset="utf-8"/>
<title>AI Chat</title>
""" + BASE_CSS + """
</head>
<body>
<div id="cookieDisplay">
  <b>Cookie:</b> {{ user_cookie }}
</div>


<!-- COOKIES FOR EXTENSION START -->

    {% if is_ext %}
    <div id="cookieForm">
        <h3>Set 'my_app_cookie'</h3>
        <form method="POST">
            <label for="cookie_value">Enter Cookie Value:</label><br/>
            <input type="text" id="cookie_value" name="cookie_value" placeholder="New cookie value" required /><br/><br/>
            <button type="submit">Set my_app_cookie</button>
        </form>
    </div>
    {% endif %}
    

<!-- COOKIES FOR EXTENSION END -->


<div class="modules-container">
  <div class="module-box" style="flex:1 1 60%;">
    <div class="module-header">Chat</div>
    <div id="chatBody" style="border:1px solid #0f0; height:300px; overflow-y:auto; padding:5px;"></div>
    <textarea id="chatInput" class="textarea" style="height:60px;" placeholder="Type your message..."></textarea>
    <button onclick="sendChat()">Send</button>
  </div>
  <div class="module-box" style="flex:1 1 35%;">
    <div class="module-header">Current Extracted Data</div>
    <p>(Raw JSON from your Canvas data)</p>
    <pre id="dataView" style="max-height:200px; overflow-y:auto; border:1px solid #0f0;"></pre>
    <div class="module-header">Chart</div>
    <pre id="chartView" style="max-height:150px; overflow-y:auto; border:1px solid #0f0;"></pre>
  </div>
</div>

<script>
async function loadChatHistory() {
  const res = await fetch("/chat_history");
  const data = await res.json();
  const chatBody = document.getElementById('chatBody');
  chatBody.innerHTML = "";
  data.conversation.forEach(msg => {
    const d = document.createElement('div');
    if(msg.role === 'user') {
      d.textContent = "You: " + msg.content;
    } else if(msg.role === 'assistant') {
      d.textContent = "AI: " + msg.content;
    } else {
      d.textContent = "(System) " + msg.content;
      d.style.fontStyle = "italic";
    }
    chatBody.appendChild(d);
  });
  chatBody.scrollTop = chatBody.scrollHeight;
}

function sendChat() {
  const chatInput = document.getElementById('chatInput');
  const text = chatInput.value.trim();
  if(!text) return;
  const chatBody = document.getElementById('chatBody');
  const userDiv = document.createElement('div');
  userDiv.textContent = "You: " + text;
  chatBody.appendChild(userDiv);
  chatInput.value = "";
  chatBody.scrollTop = chatBody.scrollHeight;

  fetch("/chat", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ message: text })
  })
  .then(r => r.json())
  .then(data => {
    const aiDiv = document.createElement('div');
    aiDiv.textContent = "AI: " + data.reply;
    chatBody.appendChild(aiDiv);
    chatBody.scrollTop = chatBody.scrollHeight;
  })
  .catch(err => {
    const errDiv = document.createElement('div');
    errDiv.textContent = "Error: " + err;
    chatBody.appendChild(errDiv);
  });
}

async function loadDataAndChart() {
  const dataRes = await fetch("/raw_data");
  const dataJson = await dataRes.json();
  document.getElementById('dataView').textContent = JSON.stringify(dataJson, null, 2);

  const chartRes = await fetch("/chart_data");
  const chartTxt = await chartRes.json();
  document.getElementById('chartView').textContent = chartTxt.chart;
}

// On page load
loadChatHistory();
loadDataAndChart();
</script>
</body>
</html>
"""

###############################################################################
# FLASK ROUTES
###############################################################################

@app.route("/")
def home():
    cookie_id = request.cookies.get("my_app_cookie")
    if not cookie_id or not os.path.exists(get_user_path(cookie_id)):
        cookie_id = str(uuid.uuid4())
        create_user_folder_if_needed(cookie_id)

    resp = make_response(render_template_string(HOME_TEMPLATE, user_cookie=cookie_id))
    resp.set_cookie("my_app_cookie", cookie_id)
    return resp

@app.route("/use_cookie", methods=["POST"])
def use_cookie():
    data = request.get_json() or {}
    new_cookie = data.get("cookie", "").strip()
    if not new_cookie:
        return jsonify({"message": "No cookie provided."}), 400
    create_user_folder_if_needed(new_cookie)
    resp = make_response(jsonify({"message": f"Cookie set to {new_cookie}"}))
    resp.set_cookie("my_app_cookie", new_cookie)
    return resp

@app.route("/extract", methods=["POST"])
def extract_data():
    """
    Receives JSON { "token": "<Canvas access token>" }.
    1) Check if the token was used within 48h => reuse same cookie
    2) Otherwise, re-extract.
    """
    data = request.get_json() or {}
    token = data.get("token", "").strip()
    if not token:
        return "No Canvas token provided", 400

    # Check if this token was used in last 48 hours
    existing_cookie = find_cookie_by_token(token)
    if existing_cookie:
        append_log(existing_cookie, "Reusing existing data (<48h).")
        resp = make_response("Reused existing data (extracted <48h ago).", 200)
        resp.set_cookie("my_app_cookie", existing_cookie)
        return resp
    else:
        # Not found or older than 48 hours => re-extract
        user_cookie = request.cookies.get("my_app_cookie")
        if not user_cookie or not os.path.exists(get_user_path(user_cookie)):
            user_cookie = str(uuid.uuid4())
            create_user_folder_if_needed(user_cookie)

        # Store token, clear logs
        meta = load_metadata(user_cookie)
        meta["canvas_token"] = token
        meta["logs"] = []
        save_metadata(user_cookie, meta)

        # Start thread
        t = threading.Thread(target=do_extraction, args=(user_cookie, token))
        t.start()

        resp = make_response("Started extraction (fresh or older than 48h).", 200)
        resp.set_cookie("my_app_cookie", user_cookie)
        return resp

@app.route("/stream_logs")
def stream_logs():
    cookie_id = request.cookies.get("my_app_cookie")
    if not cookie_id:
        return "No cookie", 400

    def event_stream():
        last_len = 0
        while True:
            logs = get_logs(cookie_id)
            if len(logs) > last_len:
                new_entries = logs[last_len:]
                last_len = len(logs)
                for entry in new_entries:
                    yield f"data: {entry}\n\n"
            # If not in_progress and not in_progress_submissions, we can break.
            meta = load_metadata(cookie_id)
            still_extracting = meta and (meta.get("in_progress") or meta.get("in_progress_submissions"))
            if not still_extracting:
                break
            time.sleep(1)

    return Response(event_stream(), mimetype="text/event-stream")

@app.route("/filter", methods=["POST"])
def filter_chart():
    cookie_id = request.cookies.get("my_app_cookie")
    if not cookie_id:
        return jsonify({"error": "No cookie found."})

    data = request.get_json() or {}
    quarter = data.get("quarter", 0)
    keep_locked = data.get("keep_locked", True)
    keep_missing = data.get("keep_missing", True)
    keep_submitted = data.get("keep_submitted", True)

    extracted_data = load_extracted_data(cookie_id)
    if not extracted_data:
        return jsonify({"error": "No extracted data found. Please run extraction first."})

    user_options = {
        "keep_locked": keep_locked,
        "keep_missing": keep_missing,
        "keep_submitted": keep_submitted
    }
    chart_text = generate_chart(cookie_id, extracted_data, quarter, user_options)
    if chart_text.startswith("No valid quarter found"):
        return jsonify({"error": chart_text})
    return jsonify({"chart": chart_text})

@app.route("/settings", methods=["GET","POST"])
def settings():
    cookie_id = request.cookies.get("my_app_cookie")
    if not cookie_id:
        return jsonify({"error": "No cookie found"}), 400

    if request.method == "GET":
        meta = load_metadata(cookie_id)
        return jsonify({
            "styling": meta.get("styling", "hacker"),
            "ai_instructions": meta.get("ai_instructions", "")
        })
    else:
        data = request.get_json() or {}
        new_styling = data.get("styling", "hacker")
        new_instr = data.get("ai_instructions", "")
        meta = load_metadata(cookie_id)
        meta["styling"] = new_styling
        meta["ai_instructions"] = new_instr
        save_metadata(cookie_id, meta)
        return jsonify({"message": "Settings saved."})

@app.route("/chat", methods=["GET","POST"])
def chat():
    cookie_id = request.cookies.get("my_app_cookie")
    if not cookie_id:
        # Extension flow or fallback
        if request.method == "POST":
            new_value = request.form.get("cookie_value", "").strip()
            if new_value:
                resp = make_response("my_app_cookie has been set! <a href='/chat?ext=1'>Go back to Chat</a>")
                resp.set_cookie(
                    "my_app_cookie",
                    value=new_value,
                    httponly=False,
                    samesite="None",
                    secure=False,
                    max_age=86400
                )
                return resp
            else:
                return "No cookie value provided. <a href='/chat?ext=1'>Back</a>", 400
        is_ext = request.args.get("ext") == "1"
        return render_template_string(CHAT_TEMPLATE, is_ext=is_ext)

    if request.method == "GET":
        return render_template_string(CHAT_TEMPLATE, user_cookie=cookie_id)

    data = request.json
    if not data:
        append_log(cookie_id, "No JSON data in /chat POST.")
        return jsonify({"reply": "(No data)"}), 400

    msg = data.get("message", "").strip()
    if not msg:
        append_log(cookie_id, "Empty user message in /chat POST.")
        return jsonify({"reply": "(No message)"}), 400

    conversation = load_conversation(cookie_id) or []
    append_log(cookie_id, f"Before building new system msgs, conversation length: {len(conversation)}")

    meta = load_metadata(cookie_id)
    instructions = meta.get("ai_instructions", "")
    chart_summary = meta.get("chart_summary", "(No chart)")

    system_msgs = [
        {"role": "system", "content": instructions},
        {"role": "system", "content": f"Here is the chart summary:\n\n{chart_summary}\n\n"}
    ]
    stripped_conv = [m for m in conversation if m["role"] != "system"]
    new_conv = system_msgs + stripped_conv
    new_conv.append({"role": "user", "content": msg})

    pruned = prune_conversation(new_conv, max_chars=16000)
    append_log(cookie_id, f"Pruned conversation length: {len(pruned)}")

    try:
        response = groq_client.chat.completions.create(
            messages=pruned,
            model="llama3-8b-8192"
        )
        ai_reply = response.choices[0].message.content
    except Exception as e:
        ai_reply = f"(Error calling AI) {str(e)}"

    pruned.append({"role": "assistant", "content": ai_reply})
    save_conversation(cookie_id, pruned)
    append_log(cookie_id, f"Saved conversation length: {len(pruned)} after AI reply.")
    return jsonify({"reply": ai_reply})

@app.route("/chat_history")
def chat_history():
    cookie_id = request.cookies.get("my_app_cookie")
    if not cookie_id:
        return jsonify({"conversation":[]})
    conv = load_conversation(cookie_id) or []
    return jsonify({"conversation": conv})

@app.route("/raw_data")
def raw_data():
    cookie_id = request.cookies.get("my_app_cookie")
    if not cookie_id:
        return jsonify([])
    data = load_extracted_data(cookie_id)
    return jsonify(data)

@app.route("/chart_data")
def chart_data():
    cookie_id = request.cookies.get("my_app_cookie")
    if not cookie_id:
        return jsonify({"chart":"(No cookie)"})
    chart_txt = load_chart(cookie_id)
    return jsonify({"chart": chart_txt})

# Submissions extraction route (file downloads included)
@app.route("/submissions", methods=["POST"])
def submissions():
    cookie_id = request.cookies.get("my_app_cookie")
    if not cookie_id:
        return "No cookie set.", 400

    meta = load_metadata(cookie_id)
    token = meta.get("canvas_token", "").strip()
    if not token:
        return "No token found in your cookie. Please provide a Canvas token first.", 400

    append_log(cookie_id, "[Submissions] Starting new extraction job...")

    t = threading.Thread(target=do_submissions_extraction, args=(cookie_id, token))
    t.start()

    return "Submissions extraction started", 200

# Download Submissions route
@app.route("/download_submissions", methods=["GET"])
def download_submissions():
    cookie_id = request.cookies.get("my_app_cookie")
    if not cookie_id:
        return "No cookie", 400

    user_path = get_user_path(cookie_id)
    file_path = os.path.join(user_path, "submissions_data.json")
    if not os.path.isfile(file_path):
        return "No submissions data found. Run extraction first.", 400

    with open(file_path, "rb") as f:
        file_bytes = f.read()

    return send_file(
        io.BytesIO(file_bytes),
        as_attachment=True,
        mimetype="application/json",
        download_name="submissions_data.json"
    )

#### EXTENSION ONLY ACCESS ####
@app.route("/set_my_cookie")
def set_my_cookie():
    resp = make_response("my_app_cookie is set! <a href='/chat?ext=1'>Go to Chat</a>")
    resp.set_cookie(
        "my_app_cookie",
        value="test_cookie_value",
        httponly=False,
        samesite="None",
        secure=False,
        max_age=86400
    )
    return resp

@app.route("/receive_cookies", methods=["POST"])
def receive_cookies():
    data = request.json or {}
    cookies = data.get("cookies", [])
    
    if not cookies:
        return jsonify({"status": "No cookies received."}), 400

    with open("received_cookies.json", "w") as f:
        json.dump(cookies, f, indent=2)

    print("Received cookies:", cookies)
    return jsonify({"status": "Cookies received and saved."}), 200
#### EXTENSION ONLY ACCESS ####


###############################################################################
# RUN
###############################################################################

if __name__ == "__main__":
    app.run(debug=True, port=5000)
