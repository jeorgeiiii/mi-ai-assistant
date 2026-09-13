import datetime
import os
import json
from datetime import timezone, date, timedelta
import base64
import operator
from typing import TypedDict, Annotated, List, Optional, Literal
import requests
import uuid
import re
import calendar
import sqlite3


from dotenv import load_dotenv
from pydantic import BaseModel, Field
from tzlocal import get_localzone
import parsedatetime as pdt
from dateutil.parser import parse, ParserError


from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.exceptions import RefreshError
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


from langchain_core.tools import tool
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from langchain_groq import ChatGroq
from langchain_tavily import TavilySearch
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.sqlite import SqliteSaver
from langchain_core.messages import ToolCall


from IPython.display import Image, display

load_dotenv()

groq_api_key = os.getenv("GROQ_API_KEY")
tavily_api_key = os.getenv("TAVILY_API_KEY") 

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/presentations",
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/forms.body",
    "https://www.googleapis.com/auth/forms.responses.readonly"
]

if not all([groq_api_key, tavily_api_key]):
    raise ValueError("One or more required API keys (GROQ, TAVILY) are missing from the .env file!")


# For high-quality, reliable, and rule-following responses (the 70b model).
# Use this for testing complex workflows.
llm = ChatGroq(model="openai/gpt-oss-120b", api_key=groq_api_key, temperature=0)

# Vision-capable model for analyzing images the user attaches (text-only models can't read images).
# reasoning_effort="none" skips this model's internal chain-of-thought (it's a "thinking" model by
# default), and max_tokens is capped, to stay under Groq's free-tier output-tokens-per-minute limit.
vision_llm = ChatGroq(
    model="qwen/qwen3.6-27b",
    api_key=groq_api_key,
    temperature=0,
    max_tokens=700,
    reasoning_effort="none",
)

# For rapid development and simple tests (the 8b model).
# Note: This model is much faster but may not follow complex instructions as precisely.
#llm = ChatGroq(model="llama-3.1-8b-instant", api_key=groq_api_key, temperature=0)


print("Groq LLM (Llama) configured and ready.")

def _get_google_credentials():
    """Gets valid Google API credentials, refreshing if necessary."""

    creds = None

    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)

            print("Please click on the link in the terminal and log in to Google...")
            creds = flow.run_local_server(
                port=8090,          
                open_browser=False,
                bind_addr="0.0.0.0"  
            )

        with open("token.json", "w") as token:
            token.write(creds.to_json())

    return creds


def _fetch_google_events(start_date: datetime.datetime, end_date: datetime.datetime) -> List[dict]:
    """Internal function to fetch events from Google Calendar."""

    try:
        creds = _get_google_credentials()
        service = build("calendar", "v3", credentials=creds)
        
        events_result = service.events().list(
            calendarId="primary",
            timeMin=start_date.isoformat(),
            timeMax=end_date.isoformat(),
            maxResults=250,
            singleEvents=True,
            orderBy="startTime"
        ).execute()
        
        return events_result.get("items", [])

    except RefreshError as error:
        print(f"!!! Google Authentication Error: {error}")
        return [{"error_type": "AuthenticationFailed", "details": str(error)}]
    except (requests.exceptions.ConnectionError, ConnectionRefusedError) as error:
        print(f"!!! Network Connection Error: {error}")
        return [{"error_type": "ConnectionFailed", "details": str(error)}]
    except HttpError as error:
        print(f"!!! Google Calendar API HTTP Error: {error}")
        return [{"error_type": "ApiHttpError", "details": str(error)}]
    except Exception as e:
        print(f"!!! An unexpected error occurred in _fetch_google_events: {e}")
        return [{"error_type": "UnknownError", "details": str(e)}]


def _get_email_body(parts):
    """Recursively search for text/plain parts in email body."""

    body = ""
    if parts:
        for part in parts:
            if part['mimeType'] == 'text/plain' and 'data' in part['body']:
                body += base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
            elif 'parts' in part:
                body += _get_email_body(part['parts'])

    return body


def _fetch_gmail_messages(query: str, max_results: int = 10) -> List[dict]:
    """Internal function to fetch and sort emails from Gmail using batch processing."""
    
    try:
        creds = _get_google_credentials()
        service = build("gmail", "v1", credentials=creds)

        message_list = service.users().messages().list(userId='me', q=query, maxResults=max_results).execute()
        messages = message_list.get('messages', [])
        
        if not messages: return []

        output_emails = []

        def gmail_callback(request_id, response, exception):
            if exception is None:
                headers = response['payload']['headers']
                output_emails.append({
                    "id": response['id'],
                    "sender": next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown Sender'),
                    "subject": next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject'),
                    "date": next((h['value'] for h in headers if h['name'] == 'Date'), 'Unknown Date'),
                    "body": _get_email_body(response['payload'].get('parts', []))[:2000],
                    "internalDate": response['internalDate']
                })

        batch_request = service.new_batch_http_request(callback=gmail_callback)
        for msg in messages:
            batch_request.add(service.users().messages().get(userId='me', id=msg['id'], format='full'))
        
        batch_request.execute()
        output_emails.sort(key=lambda e: int(e['internalDate']), reverse=True)
        return output_emails

    except RefreshError as error:
        print(f"!!! Google Authentication Error: {error}")
        return [{"error_type": "AuthenticationFailed", "details": str(error)}]
    except (requests.exceptions.ConnectionError, ConnectionRefusedError) as error:
        print(f"!!! Network Connection Error: {error}")
        return [{"error_type": "ConnectionFailed", "details": str(error)}]
    except HttpError as error:
        print(f"!!! Gmail API HTTP Error: {error}")
        return [{"error_type": "ApiHttpError", "details": str(error)}]
    except Exception as e:
        print(f"!!! An unexpected error occurred in _fetch_gmail_messages: {e}")
        return [{"error_type": "UnknownError", "details": str(e)}]

def _parse_natural_language_time(natural_language_time: str) -> datetime.datetime | None:
    """
    Parses a natural language date and time string into a timezone-aware datetime object.
    Tries with parsedatetime first, then falls back to dateutil.parser for robustness.
    """

    try:
        cal = pdt.Calendar()
        time_struct, parse_status = cal.parse(natural_language_time)

        if parse_status != 0:
            dt_object = datetime.datetime(*time_struct[:6])

            return dt_object.replace(tzinfo=get_localzone())

        try:
            dt_object = parse(natural_language_time)

            if dt_object.tzinfo is None:
                return dt_object.replace(tzinfo=get_localzone())
            return dt_object
        except ParserError:
            return None 

    except Exception as e:
        print(f"!!! Error in _parse_natural_language_time: {e}")
        return None


@tool
def list_upcoming_events(limit: Optional[int] = 15) -> str:
    """Lists the user's upcoming Google Calendar events from today onwards."""

    print(f"--- Tool: list_upcoming_events called with limit={limit} ---")

    now = datetime.datetime.now(timezone.utc)
    search_end = now + datetime.timedelta(days=90)

    google_events = _fetch_google_events(start_date=now, end_date=search_end)

    if not google_events:
        return json.dumps([])

    valid_events = [e for e in google_events if 'error_type' not in e]

    return json.dumps(valid_events[:limit], indent=2)


@tool
def get_events_for_day(natural_language_date: str) -> str:
    """Finds and lists all Google Calendar events for a specific day (like 'tomorrow', 'this Sunday')."""

    dt_obj = _parse_natural_language_time(natural_language_date)

    if not dt_obj:
        return json.dumps([{"error": f"I could not understand the date: '{natural_language_date}'"}])

    target_date = dt_obj.date()
    
    print(f"--- Tool: get_events_for_day called for '{natural_language_date}' -> Resolved to: {target_date.isoformat()} ---")

    try:
        start_of_day = datetime.datetime.combine(target_date, datetime.time.min).replace(tzinfo=get_localzone())
        end_of_day = datetime.datetime.combine(target_date, datetime.time.max).replace(tzinfo=get_localzone())

        google_events = _fetch_google_events(start_date=start_of_day.astimezone(timezone.utc), end_date=end_of_day.astimezone(timezone.utc))
        valid_events = [e for e in google_events if 'error' not in e]

        if not valid_events:
            return json.dumps([])
        return json.dumps(valid_events, indent=2)

    except Exception as e:
        return json.dumps([{"error": f"An unexpected error occurred: {e}"}])

@tool
def tavily_search(query: str) -> str:
    """A search engine tool to find real-time information online."""

    print(f"--- Tool: tavily_search called with query: '{query}' ---")

    try:
        search = TavilySearch(max_results=3, api_key=tavily_api_key)
        results = search.invoke(query)
        return json.dumps(results, indent=2)

    except requests.exceptions.ConnectionError as e:
        print(f"!!! Tavily Connection Error: {e}")
        return json.dumps([{"error_type": "ConnectionFailed", "details": str(e)}])
    except Exception as e:
        print(f"!!! Tavily Unexpected Error: {e}")
        return json.dumps([{"error_type": "UnknownError", "details": str(e)}])
    


@tool
def create_google_event(
    summary: str, 
    start_time_natural: str, 
    duration_minutes: int,
    description: Optional[str] = None, 
    location: Optional[str] = None, 
    attendees: Optional[List[str]] = None
) -> str:
    """
    Creates a new event on Google Calendar using natural language for the start time after checking for conflicts.

    Args:
        summary (str): The title or summary of the event.
        start_time_natural (str): The start time in natural language (e.g., "tomorrow at 4 PM", "next Tuesday at 11am").
        duration_minutes (int): The duration of the event in minutes.
        description (Optional[str]): A detailed description for the event.
        location (Optional[str]): The physical location of the event.
        attendees (Optional[List[str]]): A list of attendee email addresses to invite.
    """

    print(f"--- Tool: create_google_event received natural language query: '{start_time_natural}' ---")

    start_time_obj = _parse_natural_language_time(start_time_natural)

    if not start_time_obj:
        return f"Error: I could not understand the start time '{start_time_natural}'."

    end_time_obj = start_time_obj + datetime.timedelta(minutes=duration_minutes)
    
    try:
        conflicting_events = _fetch_google_events(start_date=start_time_obj, end_date=end_time_obj)

        if conflicting_events:
            conflict_summary = conflicting_events[0].get('summary', 'an existing event')
            return f"Error: Cannot create event. There is a conflicting event at that time: '{conflict_summary}'."

        start_time_iso = start_time_obj.isoformat()
        end_time_iso = end_time_obj.isoformat()

        print(f"--- Finalizing API Call with: summary='{summary}', start='{start_time_iso}', end='{end_time_iso}', description='{description}', location='{location}', attendees='{attendees}' ---")

        creds = _get_google_credentials()
        service = build("calendar", "v3", credentials=creds)
        
        local_timezone = str(get_localzone())
        
        event_body = {
            'summary': summary,
            'start': {'dateTime': start_time_iso, 'timeZone': str(get_localzone())},
            'end': {'dateTime': end_time_iso, 'timeZone': str(get_localzone())},
        }

        if description:
            event_body['description'] = description
        
        if location:
            event_body['location'] = location
        
        if attendees:
            event_body['attendees'] = [{'email': email} for email in attendees]

        created_event = service.events().insert(calendarId='primary', body=event_body).execute()
        
        print(f"--- Success: Event created. ID: {created_event.get('id')} ---")
        return f"Success! Event '{summary}' was created for {start_time_obj.strftime('%Y-%m-%d %H:%M')}."

    except Exception as e:
        print(f"!!! Google Calendar Write Error: {e}")
        return f"An error occurred while creating the event in Google Calendar: {e}"



@tool
def delete_google_event(event_id: str, summary: str) -> str:
    """Deletes an event from the calendar using its unique ID."""

    print(f"--- Tool: delete_google_event called for ID: {event_id} ---")

    try:
        creds = _get_google_credentials()
        service = build("calendar", "v3", credentials=creds)
        service.events().delete(calendarId='primary', eventId=event_id).execute()

        return f"The event '{summary}' was successfully deleted."

    except Exception as e:
        return f"An error occurred while deleting the event: {e}"

@tool
def get_events_for_range(time_range: str) -> str:
    """
    Fetches all Google Calendar events for a specific range like "this week", "next week", or "this month".
    """
    print(f"--- Tool: get_events_for_range called for: {time_range} ---")

    today = datetime.date.today()
    start_date, end_date = None, None

    if time_range == "this week":
        start_date = today - datetime.timedelta(days=today.weekday())
        end_date = start_date + datetime.timedelta(days=6)
    elif time_range == "next week":
        start_date = today + datetime.timedelta(days=(7 - today.weekday()))
        end_date = start_date + datetime.timedelta(days=6)
    elif time_range == "this month":
        start_date = today.replace(day=1)
        _, last_day_of_month = calendar.monthrange(today.year, today.month)
        end_date = today.replace(day=last_day_of_month)
    else:
        return json.dumps([{"error": "Unsupported time range. Please use 'this week', 'next week', or 'this month'."}])

    print(f"--- Calculated Date Range: {start_date.isoformat()} to {end_date.isoformat()} ---")
    
    start_datetime = datetime.datetime.combine(start_date, datetime.time.min).astimezone(timezone.utc)
    end_datetime = datetime.datetime.combine(end_date, datetime.time.max).astimezone(timezone.utc)
    events = _fetch_google_events(start_date=start_datetime, end_date=end_datetime)

    return json.dumps(events, indent=2)


@tool
def find_free_slot(
    duration_minutes: int,
    search_start_natural: str,
    search_end_natural: str,
    max_results: int = 5
) -> str:
    """
    Finds available (free) time slots of a specific duration within a given time range.

    Args:
        duration_minutes (int): The desired duration of the free slot (e.g., 30).
        search_start_natural (str): The natural language start of the search range (e.g., "tomorrow at 9 AM", "today").
        search_end_natural (str): The natural language end of the search range (e.g., "tomorrow at 5 PM", "this evening").
        max_results (int): The maximum number of free slots to return.
    """
    
    print(f"--- Tool: find_free_slot called for {duration_minutes} min duration between '{search_start_natural}' and '{search_end_natural}' ---")

    start_time_obj = _parse_natural_language_time(search_start_natural)
    end_time_obj = _parse_natural_language_time(search_end_natural)

    if not start_time_obj or not end_time_obj:
        return json.dumps([{"error_type": "DateParseError", "details": "I could not understand the start or end time you provided."}])

    if start_time_obj >= end_time_obj:
        return json.dumps([{"error_type": "InvalidRangeError", "details": "The start time must be before the end time."}])

    duration_delta = datetime.timedelta(minutes=duration_minutes)
    
    try:
        google_events = _fetch_google_events(start_date=start_time_obj, end_date=end_time_obj)
        
        busy_slots = [e for e in google_events if 'error_type' not in e]
        
        parsed_busy_slots = []
        for event in busy_slots:
            try:
                event_start = parse(event['start'].get('dateTime'))
                event_end = parse(event['end'].get('dateTime'))
                parsed_busy_slots.append((event_start, event_end))
            except ParserError:
                continue 

        parsed_busy_slots.sort(key=lambda x: x[0])

        found_slots = []
        current_pointer = start_time_obj

        for event_start, event_end in parsed_busy_slots:
            if event_start > current_pointer:
                gap_duration = event_start - current_pointer
                
                if gap_duration >= duration_delta:
                    slot_start = current_pointer
                    slot_end = current_pointer + duration_delta
                    found_slots.append({
                        "start": slot_start.isoformat(),
                        "end": slot_end.isoformat()
                    })
                    if len(found_slots) >= max_results:
                        return json.dumps(found_slots, indent=2)
            
            current_pointer = max(current_pointer, event_end)


        if len(found_slots) < max_results:
            final_gap_duration = end_time_obj - current_pointer
            if final_gap_duration >= duration_delta:
                found_slots.append({
                    "start": current_pointer.isoformat(),
                    "end": (current_pointer + duration_delta).isoformat()
                })

        return json.dumps(found_slots, indent=2)

    except Exception as e:
        print(f"!!! An error occurred in find_free_slot: {e}")
        return json.dumps([{"error_type": "UnknownError", "details": str(e)}])

@tool
def update_google_event(
    event_id: str,
    new_summary: Optional[str] = None,
    new_start_time_natural: Optional[str] = None,
    new_duration_minutes: Optional[int] = None,
    new_description: Optional[str] = None,
    new_location: Optional[str] = None,
    new_attendees: Optional[List[str]] = None
    ) -> str:
    """
    Updates an existing Google Calendar event using its unique ID. 
    Accepts natural language for the new start time.
    If only a new start time is provided, the original duration is maintained
    """

    print(f"--- Tool: update_google_event called for ID: {event_id} ---")

    try:
        creds = _get_google_credentials()
        service = build("calendar", "v3", credentials=creds)

        event = service.events().get(calendarId='primary', eventId=event_id).execute()

        update_body = {}

        if new_summary:
            update_body['summary'] = new_summary

        if new_description:
            update_body['description'] = new_description
            
        if new_location:
            update_body['location'] = new_location
            
        if new_attendees is not None:
            update_body['attendees'] = [{'email': email} for email in new_attendees]

        if new_start_time_natural:
            new_start_obj = _parse_natural_language_time(new_start_time_natural)
            if not new_start_obj:
                return f"Error: I could not understand the new start time '{new_start_time_natural}'."
            
            if new_duration_minutes:
                new_end_obj = new_start_obj + datetime.timedelta(minutes=new_duration_minutes)
            else:
                original_start = parse(event['start'].get('dateTime'))
                original_end = parse(event['end'].get('dateTime'))
                original_duration = original_end - original_start
                new_end_obj = new_start_obj + original_duration

            update_body['start'] = {'dateTime': new_start_obj.isoformat(), 'timeZone': str(get_localzone())}
            update_body['end'] = {'dateTime': new_end_obj.isoformat(), 'timeZone': str(get_localzone())}
        
        if not update_body:
            return "Error: No update information was provided for the event."

        updated_event = service.events().patch(
            calendarId='primary', 
            eventId=event_id, 
            body=update_body
        ).execute()

        return f"Success! Event '{updated_event.get('summary')}' was updated."

    except HttpError as err:
        if err.resp.status == 404:
            return f"Error: The event with ID '{event_id}' was not found."
        return f"An API error occurred: {err}"
    except Exception as e:
        return f"An unexpected error occurred while updating the event: {e}"



@tool
def search_emails(
    sender: Optional[str] = None, 
    subject: Optional[str] = None, 
    keywords: Optional[str] = None, 
    status: Optional[str] = "all", 
    time_range: Optional[str] = None, 
    max_results: int = 10
) -> str:
    """
    Searches for emails in the user's Gmail account based on various criteria.
    Returns the raw email data as a structured JSON string for the agent to process.
    """

    print(f"--- Tool: search_emails called with filters: status='{status}', sender='{sender}', subject='{subject}', keywords='{keywords}', time_range='{time_range}' ---")

    query_parts = []
    if status == "unread":
        query_parts.append("is:unread")
    elif status == "read":
        query_parts.append("is:read")
    if sender:
        query_parts.append(f"from:{sender}")
    if subject:
        query_parts.append(f"subject:({subject})")
    if keywords:
        query_parts.append(keywords)
    if time_range:
        query_parts.append(f"newer_than:{time_range}")

    query = " ".join(query_parts)

    emails = _fetch_gmail_messages(query=query, max_results=max_results)
    
    if not emails or all('error_type' in e for e in emails):
        return json.dumps([]) 

    return json.dumps(emails, indent=2)


@tool
def delete_email(message_id: str) -> str:
    """
    Moves a specific email to the trash using its unique message ID.
    To use this tool, you must first find the email and its 'id' using the `search_emails` tool.
    """
    print(f"--- Tool: delete_email called for message ID: {message_id} ---")
    try:
        creds = _get_google_credentials()
        service = build("gmail", "v1", credentials=creds)
        
        service.users().messages().trash(userId='me', id=message_id).execute()
        
        return "Success: The email was moved to the trash."
        
    except HttpError as error:
        if error.resp.status == 404:
            return f"Error: The email with ID '{message_id}' was not found."
        return f"An error occurred with the Gmail API: {error}"
    except Exception as e:
        return f"An unexpected error occurred while trying to delete the email: {e}"


@tool
def archive_email(message_id: str) -> str:
    """
    Archives a specific email by removing it from the inbox, using its unique message ID.
    To use this tool, you must first find the email and its 'id' using the `search_emails` tool.
    """
    print(f"--- Tool: archive_email called for message ID: {message_id} ---")
    try:
        creds = _get_google_credentials()
        service = build("gmail", "v1", credentials=creds)
        
        modify_request = {
            'removeLabelIds': ['INBOX']
        }
        
        service.users().messages().modify(
            userId='me', 
            id=message_id, 
            body=modify_request
        ).execute()
        
        return "Success: The email was archived and removed from the inbox."
        
    except HttpError as error:
        if error.resp.status == 404:
            return f"Error: The email with ID '{message_id}' was not found."
        return f"An error occurred with the Gmail API: {error}"
    except Exception as e:
        return f"An unexpected error occurred while trying to archive the email: {e}"



@tool
def create_email_draft(to: str, subject: str, body: str) -> str:
    """
    Creates a draft of an email and returns its draft ID and content.
    """
    print(f"--- Tool: create_email_draft called for recipient: '{to}' ---")
    try:
        creds = _get_google_credentials()
        service = build("gmail", "v1", credentials=creds)

        message = MIMEMultipart()
        message['to'] = to
        message['subject'] = subject
        msg = MIMEText(body)
        message.attach(msg)

        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        draft_body = {'message': {'raw': raw_message}}

        draft = service.users().drafts().create(userId='me', body=draft_body).execute()

        response = {
            "status": "Success",
            "draft_id": draft['id'],
            "to": to,
            "subject": subject,
            "body": body
        }
        return json.dumps(response)
    
    except Exception as e:
        print(f"!!! An error occurred in create_email_draft: {e}")
        return json.dumps([{"error_type": "UnknownError", "details": str(e)}])


@tool
def send_draft(draft_id: str) -> str:
    """
    Sends a specific email draft using its unique draft ID.
    """
    print(f"--- Tool: send_draft called for draft ID: {draft_id} ---")
    try:
        creds = _get_google_credentials()
        service = build("gmail", "v1", credentials=creds)
        service.users().drafts().send(userId='me', body={'id': draft_id}).execute()
        
        return json.dumps({"status": "Success", "message": "The draft was sent."})

    except HttpError as error:
        return json.dumps({"status": "Error", "details": f"An error occurred with the Gmail API: {error}"})
    except Exception as e:
        return json.dumps({"status": "Error", "details": f"An unexpected error occurred: {e}"})



@tool
def create_reply_draft(original_message_id: str, body: str) -> str:
    """
    Creates a DRAFT of a reply to a specific email, it does NOT send it.  

    Args:
        original_message_id (str): The unique ID of the email to reply to.
        body (str): The main text content of the reply email that the agent composes.
    """
    print(f"--- Tool: create_reply_draft called for message ID: {original_message_id} ---")
    try:
        creds = _get_google_credentials()
        service = build("gmail", "v1", credentials=creds)

        original_message = service.users().messages().get(userId='me', id=original_message_id).execute()
        original_headers = original_message['payload']['headers']
        
        original_subject = next(h['value'] for h in original_headers if h['name'].lower() == 'subject')
        original_from = next(h['value'] for h in original_headers if h['name'].lower() == 'from')
        original_message_id_header = next(h['value'] for h in original_headers if h['name'].lower() == 'message-id')

        reply_message = MIMEMultipart()
        reply_subject = original_subject if original_subject.lower().startswith('re:') else f"Re: {original_subject}"
        reply_message['to'] = original_from
        reply_message['subject'] = reply_subject
        reply_message['In-Reply-To'] = original_message_id_header
        reply_message['References'] = original_message_id_header
        
        reply_message.attach(MIMEText(body))
        
        raw_message = base64.urlsafe_b64encode(reply_message.as_bytes()).decode()
        draft_body = {'message': {'raw': raw_message, 'threadId': original_message['threadId']}}
        
        draft = service.users().drafts().create(userId='me', body=draft_body).execute()
        
        response = {
            "status": "Success",
            "draft_id": draft['id'],
            "to": original_from,
            "subject": reply_subject,
            "body": body
        }
        
        return json.dumps(response)

    except Exception as e:
        print(f"!!! An error occurred in reply_to_email: {e}")
        return json.dumps({"error_type": "UnknownError", "details": str(e)})


@tool
def list_tasks(task_list_name: str = "@default") -> str:
    """
    Lists all incomplete tasks from a specific Google Tasks list.
    If no list name is provided, it uses the user's primary/default task list.
    """
    print(f"--- Tool: list_tasks called for list: '{task_list_name}' ---")
    try:
        creds = _get_google_credentials()
        service = build("tasks", "v1", credentials=creds)

        task_lists_result = service.tasklists().list().execute()
        task_lists = task_lists_result.get("items", [])
        
        target_list_id = None
        if task_list_name == "@default" and task_lists:
            target_list_id = task_lists[0]['id'] 
        else:
            for lst in task_lists:
                if lst['title'].lower() == task_list_name.lower():
                    target_list_id = lst['id']
                    break
        
        if not target_list_id:
            return json.dumps([{"error_type": "TaskListNotFound", "details": f"Task list '{task_list_name}' not found."}])

        tasks_result = service.tasks().list(
            tasklist=target_list_id, 
            showCompleted=False 
        ).execute()
        
        tasks = tasks_result.get("items", [])
        return json.dumps(tasks, indent=2)

    except Exception as e:
        print(f"!!! An error occurred in list_tasks: {e}")
        return json.dumps([{"error_type": "UnknownError", "details": str(e)}])



@tool
def add_task(
    title: str,
    task_list_name: str = "@default",
    due_date_natural: Optional[str] = None
    ) -> str:
    """
    Adds a new task to a specific Google Tasks list, optionally with a due date.

    Args:
        title (str): The title of the task.
        task_list_name (str): The name of the task list. Defaults to the primary list.
        due_date_natural (Optional[str]): The due date in natural language (e.g., "tomorrow", "next Monday").
    """
    print(f"--- Tool: add_task called with title: '{title}', due_date: '{due_date_natural}' ---")

    try:
        creds = _get_google_credentials()
        service = build("tasks", "v1", credentials=creds)

        task_lists_result = service.tasklists().list().execute()
        task_lists = task_lists_result.get("items", [])
        
        target_list_id = None
        if task_list_name == "@default" and task_lists:
            target_list_id = task_lists[0]['id']
        else:
            for lst in task_lists:
                if lst['title'].lower() == task_list_name.lower():
                    target_list_id = lst['id']
                    break
        
        if not target_list_id:
            return json.dumps([{"error_type": "TaskListNotFound", "details": f"Task list '{task_list_name}' not found."}])

        task_body = {'title': title}

        if due_date_natural:
            due_time_obj = _parse_natural_language_time(due_date_natural)
            if due_time_obj:
                task_body['due'] = due_time_obj.astimezone(timezone.utc).isoformat()
            else:
                return json.dumps([{"error_type": "DateParseError", "details": f"I could not understand the due date '{due_date_natural}'."}])

        created_task = service.tasks().insert(
            tasklist=target_list_id, 
            body=task_body
        ).execute()
        
        return f"Success: The task '{created_task.get('title')}' was added."

    except Exception as e:
        print(f"!!! An error occurred in add_task: {e}")
        return json.dumps([{"error_type": "UnknownError", "details": str(e)}])



@tool
def complete_task(task_id: str, task_list_id: str = "@default_id_placeholder") -> str:
    """
    Marks a specific task as completed using its unique ID.
    To use this tool, you must first find the task and its 'id' using the `list_tasks` tool.
    The task_list_id is usually found alongside the task_id from the list_tasks tool.
    """
    print(f"--- Tool: complete_task called for task ID: {task_id} ---")
    try:
        creds = _get_google_credentials()
        service = build("tasks", "v1", credentials=creds)

        task = service.tasks().get(tasklist=task_list_id, task=task_id).execute()
        
        task['status'] = 'completed'
        
        completed_task = service.tasks().update(
            tasklist=task_list_id,
            task=task_id,
            body=task
        ).execute()
        
        return f"Success: The task '{completed_task.get('title')}' was marked as completed."

    except HttpError as error:
        if error.resp.status == 404:
            return f"Error: The task with ID '{task_id}' was not found in the specified list."
        return json.dumps([{"error_type": "ApiHttpError", "details": str(error)}])
    except Exception as e:
        print(f"!!! An error occurred in complete_task: {e}")
        return json.dumps([{"error_type": "UnknownError", "details": str(e)}])


@tool
def update_task(
    task_id: str,
    task_list_id: str = "@default_id_placeholder",
    new_title: Optional[str] = None,
    new_due_date_natural: Optional[str] = None
) -> str:
    """
    Updates an existing task's title or due date using its unique ID.
    To use this tool, first find the task and its 'id' and 'task_list_id'.
    """
    print(f"--- Tool: update_task called for task ID: {task_id} ---")
    
    update_body = {}
    if new_title:
        update_body['title'] = new_title
        
    if new_due_date_natural:
        due_time_obj = _parse_natural_language_time(new_due_date_natural)
        if due_time_obj:
            due_date = due_time_obj.date()
            due_datetime_utc = datetime.datetime.combine(due_date, datetime.time.min).astimezone(timezone.utc)
            update_body['due'] = due_datetime_utc.isoformat().replace('+00:00', 'Z')
        else:
            return f"Error: I could not understand the new due date '{new_due_date_natural}'."

    if not update_body:
        return "Error: No new information (title or due date) was provided to update the task."

    try:
        creds = _get_google_credentials()
        service = build("tasks", "v1", credentials=creds)
        
        updated_task = service.tasks().patch(
            tasklist=task_list_id,
            task=task_id,
            body=update_body
        ).execute()
        
        return f"Success: The task was updated to '{updated_task.get('title')}'."

    except HttpError as error:
        if error.resp.status == 404:
            return f"Error: The task with ID '{task_id}' was not found in the specified list."
        return json.dumps([{"error_type": "ApiHttpError", "details": str(error)}])
    except Exception as e:
        print(f"!!! An error occurred in update_task: {e}")
        return json.dumps([{"error_type": "UnknownError", "details": str(e)}])



@tool
def delete_task(task_id: str, task_list_id: str = "@default_id_placeholder") -> str:
    """
    Deletes a specific task using its unique ID.
    To use this tool, you must first find the task and its 'id' and 'task_list_id'.
    This is a permanent action, so user confirmation is required.
    """
    print(f"--- Tool: delete_task called for task ID: {task_id} ---")
    try:
        creds = _get_google_credentials()
        service = build("tasks", "v1", credentials=creds)

        service.tasks().delete(
            tasklist=task_list_id,
            task=task_id
        ).execute()
        
        return "Success: The task was permanently deleted."

    except HttpError as error:
        if error.resp.status == 404:
            return f"Error: The task with ID '{task_id}' was not found in the specified list."
        return json.dumps([{"error_type": "ApiHttpError", "details": str(error)}])
    except Exception as e:
        print(f"!!! An error occurred in delete_task: {e}")
        return json.dumps([{"error_type": "UnknownError", "details": str(e)}])



@tool
def search_drive_files(query: str, max_results: int = 10) -> str:
    """
    Searches for files and folders in Google Drive by name.
    Returns each file's name, id, type, and a link to view it.
    """
    print(f"--- Tool: search_drive_files called with query: '{query}' ---")
    try:
        creds = _get_google_credentials()
        service = build("drive", "v3", credentials=creds)

        results = service.files().list(
            q=f"name contains '{query}' and trashed = false",
            pageSize=max_results,
            fields="files(id, name, mimeType, webViewLink)"
        ).execute()

        return json.dumps(results.get("files", []), indent=2)

    except Exception as e:
        print(f"!!! An error occurred in search_drive_files: {e}")
        return json.dumps([{"error_type": "UnknownError", "details": str(e)}])


@tool
def list_recent_drive_files(max_results: int = 10) -> str:
    """Lists the most recently modified files in the user's Google Drive."""
    print(f"--- Tool: list_recent_drive_files called with max_results={max_results} ---")
    try:
        creds = _get_google_credentials()
        service = build("drive", "v3", credentials=creds)

        results = service.files().list(
            q="trashed = false",
            pageSize=max_results,
            orderBy="modifiedTime desc",
            fields="files(id, name, mimeType, modifiedTime, webViewLink)"
        ).execute()

        return json.dumps(results.get("files", []), indent=2)

    except Exception as e:
        print(f"!!! An error occurred in list_recent_drive_files: {e}")
        return json.dumps([{"error_type": "UnknownError", "details": str(e)}])


@tool
def create_drive_folder(folder_name: str, parent_folder_id: Optional[str] = None) -> str:
    """Creates a new folder in Google Drive, optionally inside a parent folder."""
    print(f"--- Tool: create_drive_folder called with name: '{folder_name}' ---")
    try:
        creds = _get_google_credentials()
        service = build("drive", "v3", credentials=creds)

        file_metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder"
        }
        if parent_folder_id:
            file_metadata["parents"] = [parent_folder_id]

        folder = service.files().create(body=file_metadata, fields="id, name, webViewLink").execute()

        return f"Success! Folder '{folder.get('name')}' was created. Link: {folder.get('webViewLink')}"

    except Exception as e:
        print(f"!!! An error occurred in create_drive_folder: {e}")
        return f"An error occurred while creating the folder: {e}"


@tool
def share_drive_file(file_id: str, email: str, role: str = "reader") -> str:
    """
    Shares a Google Drive file or folder with a specific person by email.
    The role can be 'reader', 'commenter', or 'writer'.
    """
    print(f"--- Tool: share_drive_file called for file_id={file_id}, email={email}, role={role} ---")
    try:
        creds = _get_google_credentials()
        service = build("drive", "v3", credentials=creds)

        permission = {"type": "user", "role": role, "emailAddress": email}
        service.permissions().create(fileId=file_id, body=permission, sendNotificationEmail=True).execute()

        return f"Success! The file was shared with {email} as a {role}."

    except HttpError as error:
        if error.resp.status == 404:
            return f"Error: The file with ID '{file_id}' was not found."
        return f"An error occurred with the Drive API: {error}"
    except Exception as e:
        return f"An unexpected error occurred while sharing the file: {e}"


@tool
def delete_drive_file(file_id: str, file_name: str) -> str:
    """
    Permanently deletes a file or folder from Google Drive using its unique ID.
    To use this tool, you must first find the file and its 'id' using `search_drive_files` or `list_recent_drive_files`.
    """
    print(f"--- Tool: delete_drive_file called for file_id={file_id} ---")
    try:
        creds = _get_google_credentials()
        service = build("drive", "v3", credentials=creds)
        service.files().delete(fileId=file_id).execute()

        return f"Success: '{file_name}' was permanently deleted from Drive."

    except HttpError as error:
        if error.resp.status == 404:
            return f"Error: The file with ID '{file_id}' was not found."
        return f"An error occurred with the Drive API: {error}"
    except Exception as e:
        return f"An unexpected error occurred while deleting the file: {e}"


@tool
def create_spreadsheet(title: str) -> str:
    """Creates a new, empty Google Sheet with the given title."""
    print(f"--- Tool: create_spreadsheet called with title: '{title}' ---")
    try:
        creds = _get_google_credentials()
        service = build("sheets", "v4", credentials=creds)

        spreadsheet = service.spreadsheets().create(
            body={"properties": {"title": title}},
            fields="spreadsheetId,spreadsheetUrl"
        ).execute()

        return f"Success! Spreadsheet '{title}' was created. Link: {spreadsheet.get('spreadsheetUrl')} (ID: {spreadsheet.get('spreadsheetId')})"

    except Exception as e:
        print(f"!!! An error occurred in create_spreadsheet: {e}")
        return f"An error occurred while creating the spreadsheet: {e}"


@tool
def read_sheet_values(spreadsheet_id: str, cell_range: str) -> str:
    """
    Reads values from a Google Sheet within a given A1 notation range (e.g., "Sheet1!A1:C10").
    """
    print(f"--- Tool: read_sheet_values called for spreadsheet_id={spreadsheet_id}, range={cell_range} ---")
    try:
        creds = _get_google_credentials()
        service = build("sheets", "v4", credentials=creds)

        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, range=cell_range
        ).execute()

        return json.dumps(result.get("values", []), indent=2)

    except HttpError as error:
        return f"An error occurred with the Sheets API: {error}"
    except Exception as e:
        return f"An unexpected error occurred while reading the sheet: {e}"


@tool
def write_sheet_values(spreadsheet_id: str, cell_range: str, values: List[List[str]]) -> str:
    """
    Writes (overwrites) values into a Google Sheet within a given A1 notation range (e.g., "Sheet1!A1:C2").
    'values' must be a list of rows, where each row is a list of cell values.
    """
    print(f"--- Tool: write_sheet_values called for spreadsheet_id={spreadsheet_id}, range={cell_range} ---")
    try:
        creds = _get_google_credentials()
        service = build("sheets", "v4", credentials=creds)

        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=cell_range,
            valueInputOption="USER_ENTERED",
            body={"values": values}
        ).execute()

        return "Success! The spreadsheet was updated."

    except HttpError as error:
        return f"An error occurred with the Sheets API: {error}"
    except Exception as e:
        return f"An unexpected error occurred while writing to the sheet: {e}"


@tool
def append_sheet_row(spreadsheet_id: str, sheet_name: str, values: List[str]) -> str:
    """
    Appends a single new row of values to the end of a sheet (e.g., sheet_name="Sheet1").
    """
    print(f"--- Tool: append_sheet_row called for spreadsheet_id={spreadsheet_id}, sheet_name={sheet_name} ---")
    try:
        creds = _get_google_credentials()
        service = build("sheets", "v4", credentials=creds)

        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=sheet_name,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [values]}
        ).execute()

        return "Success! The row was added to the spreadsheet."

    except HttpError as error:
        return f"An error occurred with the Sheets API: {error}"
    except Exception as e:
        return f"An unexpected error occurred while appending the row: {e}"


@tool
def create_google_doc(title: str, content: Optional[str] = None) -> str:
    """Creates a new Google Doc with the given title and optional initial text content."""
    print(f"--- Tool: create_google_doc called with title: '{title}' ---")
    try:
        creds = _get_google_credentials()
        service = build("docs", "v1", credentials=creds)

        doc = service.documents().create(body={"title": title}).execute()
        document_id = doc.get("documentId")

        if content:
            service.documents().batchUpdate(
                documentId=document_id,
                body={"requests": [{"insertText": {"location": {"index": 1}, "text": content}}]}
            ).execute()

        return f"Success! Document '{title}' was created. Link: https://docs.google.com/document/d/{document_id}/edit"

    except Exception as e:
        print(f"!!! An error occurred in create_google_doc: {e}")
        return f"An error occurred while creating the document: {e}"


@tool
def read_google_doc(document_id: str) -> str:
    """Reads and returns the plain text content of a Google Doc using its document ID."""
    print(f"--- Tool: read_google_doc called for document_id={document_id} ---")
    try:
        creds = _get_google_credentials()
        service = build("docs", "v1", credentials=creds)

        doc = service.documents().get(documentId=document_id).execute()

        text = ""
        for element in doc.get("body", {}).get("content", []):
            paragraph = element.get("paragraph")
            if paragraph:
                for run in paragraph.get("elements", []):
                    text_run = run.get("textRun")
                    if text_run:
                        text += text_run.get("content", "")

        return text if text else "The document appears to be empty."

    except HttpError as error:
        if error.resp.status == 404:
            return f"Error: The document with ID '{document_id}' was not found."
        return f"An error occurred with the Docs API: {error}"
    except Exception as e:
        return f"An unexpected error occurred while reading the document: {e}"


@tool
def append_to_google_doc(document_id: str, text: str) -> str:
    """Appends text to the end of an existing Google Doc using its document ID."""
    print(f"--- Tool: append_to_google_doc called for document_id={document_id} ---")
    try:
        creds = _get_google_credentials()
        service = build("docs", "v1", credentials=creds)

        doc = service.documents().get(documentId=document_id).execute()
        end_index = doc.get("body", {}).get("content", [])[-1].get("endIndex", 1) - 1

        service.documents().batchUpdate(
            documentId=document_id,
            body={"requests": [{"insertText": {"location": {"index": max(end_index, 1)}, "text": text}}]}
        ).execute()

        return "Success! The text was appended to the document."

    except HttpError as error:
        if error.resp.status == 404:
            return f"Error: The document with ID '{document_id}' was not found."
        return f"An error occurred with the Docs API: {error}"
    except Exception as e:
        return f"An unexpected error occurred while updating the document: {e}"


@tool
def create_presentation(title: str) -> str:
    """Creates a new, empty Google Slides presentation with the given title."""
    print(f"--- Tool: create_presentation called with title: '{title}' ---")
    try:
        creds = _get_google_credentials()
        service = build("slides", "v1", credentials=creds)

        presentation = service.presentations().create(body={"title": title}).execute()
        presentation_id = presentation.get("presentationId")

        return f"Success! Presentation '{title}' was created. Link: https://docs.google.com/presentation/d/{presentation_id}/edit"

    except Exception as e:
        print(f"!!! An error occurred in create_presentation: {e}")
        return f"An error occurred while creating the presentation: {e}"


@tool
def add_slide_to_presentation(presentation_id: str, title: str, body_text: Optional[str] = None) -> str:
    """Adds a new slide with a title and optional body text to an existing presentation."""
    print(f"--- Tool: add_slide_to_presentation called for presentation_id={presentation_id} ---")
    try:
        creds = _get_google_credentials()
        service = build("slides", "v1", credentials=creds)

        slide_id = f"slide_{uuid.uuid4().hex[:8]}"
        title_id = f"title_{uuid.uuid4().hex[:8]}"
        body_id = f"body_{uuid.uuid4().hex[:8]}"

        requests_body = [{
            "createSlide": {
                "objectId": slide_id,
                "slideLayoutReference": {"predefinedLayout": "TITLE_AND_BODY"},
                "placeholderIdMappings": [
                    {"layoutPlaceholder": {"type": "TITLE"}, "objectId": title_id},
                    {"layoutPlaceholder": {"type": "BODY"}, "objectId": body_id}
                ]
            }
        }, {
            "insertText": {"objectId": title_id, "text": title}
        }]

        if body_text:
            requests_body.append({"insertText": {"objectId": body_id, "text": body_text}})

        service.presentations().batchUpdate(
            presentationId=presentation_id, body={"requests": requests_body}
        ).execute()

        return f"Success! A new slide titled '{title}' was added."

    except HttpError as error:
        if error.resp.status == 404:
            return f"Error: The presentation with ID '{presentation_id}' was not found."
        return f"An error occurred with the Slides API: {error}"
    except Exception as e:
        return f"An unexpected error occurred while adding the slide: {e}"


@tool
def list_presentation_slides(presentation_id: str) -> str:
    """Lists the slides of a presentation along with their titles, using the presentation ID."""
    print(f"--- Tool: list_presentation_slides called for presentation_id={presentation_id} ---")
    try:
        creds = _get_google_credentials()
        service = build("slides", "v1", credentials=creds)

        presentation = service.presentations().get(presentationId=presentation_id).execute()

        slides_summary = []
        for i, slide in enumerate(presentation.get("slides", []), start=1):
            title_text = ""
            for element in slide.get("pageElements", []):
                shape = element.get("shape")
                if shape and shape.get("placeholder", {}).get("type") == "TITLE":
                    for text_element in shape.get("text", {}).get("textElements", []):
                        text_run = text_element.get("textRun")
                        if text_run:
                            title_text += text_run.get("content", "")
            slides_summary.append({"slide_number": i, "object_id": slide.get("objectId"), "title": title_text.strip()})

        return json.dumps(slides_summary, indent=2)

    except HttpError as error:
        if error.resp.status == 404:
            return f"Error: The presentation with ID '{presentation_id}' was not found."
        return f"An error occurred with the Slides API: {error}"
    except Exception as e:
        return f"An unexpected error occurred while listing slides: {e}"


@tool
def search_contacts(query: str, max_results: int = 10) -> str:
    """Searches the user's Google Contacts by name, email, or phone number."""
    print(f"--- Tool: search_contacts called with query: '{query}' ---")
    try:
        creds = _get_google_credentials()
        service = build("people", "v1", credentials=creds)

        results = service.people().searchContacts(
            query=query,
            readMask="names,emailAddresses,phoneNumbers",
            pageSize=max_results
        ).execute()

        contacts = []
        for result in results.get("results", []):
            person = result.get("person", {})
            names = person.get("names", [])
            emails = person.get("emailAddresses", [])
            phones = person.get("phoneNumbers", [])
            contacts.append({
                "name": names[0].get("displayName") if names else "Unknown",
                "emails": [e.get("value") for e in emails],
                "phones": [p.get("value") for p in phones]
            })

        return json.dumps(contacts, indent=2)

    except Exception as e:
        print(f"!!! An error occurred in search_contacts: {e}")
        return json.dumps([{"error_type": "UnknownError", "details": str(e)}])


@tool
def list_contacts(max_results: int = 20) -> str:
    """Lists the user's Google Contacts, showing their names and email addresses."""
    print(f"--- Tool: list_contacts called with max_results={max_results} ---")
    try:
        creds = _get_google_credentials()
        service = build("people", "v1", credentials=creds)

        results = service.people().connections().list(
            resourceName="people/me",
            pageSize=max_results,
            personFields="names,emailAddresses"
        ).execute()

        contacts = []
        for person in results.get("connections", []):
            names = person.get("names", [])
            emails = person.get("emailAddresses", [])
            contacts.append({
                "name": names[0].get("displayName") if names else "Unknown",
                "emails": [e.get("value") for e in emails]
            })

        return json.dumps(contacts, indent=2)

    except Exception as e:
        print(f"!!! An error occurred in list_contacts: {e}")
        return json.dumps([{"error_type": "UnknownError", "details": str(e)}])


@tool
def get_contact_email(name: str) -> str:
    """
    Looks up a contact by name and returns their email address(es).
    Useful for resolving a person's name into an email address before sending an email or inviting them to an event.
    """
    print(f"--- Tool: get_contact_email called for name: '{name}' ---")
    try:
        creds = _get_google_credentials()
        service = build("people", "v1", credentials=creds)

        results = service.people().searchContacts(
            query=name,
            readMask="names,emailAddresses",
            pageSize=5
        ).execute()

        matches = []
        for result in results.get("results", []):
            person = result.get("person", {})
            names = person.get("names", [])
            emails = person.get("emailAddresses", [])
            if emails:
                matches.append({
                    "name": names[0].get("displayName") if names else name,
                    "emails": [e.get("value") for e in emails]
                })

        if not matches:
            return json.dumps({"error_type": "NotFound", "details": f"No contact found matching '{name}'."})

        return json.dumps(matches, indent=2)

    except Exception as e:
        print(f"!!! An error occurred in get_contact_email: {e}")
        return json.dumps({"error_type": "UnknownError", "details": str(e)})


@tool
def create_google_form(title: str, description: Optional[str] = None) -> str:
    """Creates a new Google Form with the given title and optional description."""
    print(f"--- Tool: create_google_form called with title: '{title}' ---")
    try:
        creds = _get_google_credentials()
        service = build("forms", "v1", credentials=creds)

        form = service.forms().create(body={"info": {"title": title}}).execute()
        form_id = form.get("formId")

        if description:
            service.forms().batchUpdate(
                formId=form_id,
                body={"requests": [{
                    "updateFormInfo": {
                        "info": {"description": description},
                        "updateMask": "description"
                    }
                }]}
            ).execute()

        responder_uri = form.get("responderUri", f"https://docs.google.com/forms/d/{form_id}/viewform")
        return f"Success! Form '{title}' was created. Edit link: https://docs.google.com/forms/d/{form_id}/edit | Share link: {responder_uri} (ID: {form_id})"

    except Exception as e:
        print(f"!!! An error occurred in create_google_form: {e}")
        return f"An error occurred while creating the form: {e}"


@tool
def add_question_to_form(
    form_id: str,
    question_title: str,
    question_type: str = "TEXT",
    options: Optional[List[str]] = None,
    required: bool = False
) -> str:
    """
    Adds a question to an existing Google Form.

    Args:
        form_id (str): The unique ID of the form.
        question_title (str): The text of the question.
        question_type (str): One of "TEXT" (short answer), "PARAGRAPH", "MULTIPLE_CHOICE", or "CHECKBOX".
        options (Optional[List[str]]): The list of choices, required for "MULTIPLE_CHOICE" or "CHECKBOX".
        required (bool): Whether an answer to this question is mandatory.
    """
    print(f"--- Tool: add_question_to_form called for form_id={form_id}, type={question_type} ---")

    try:
        if question_type in ("MULTIPLE_CHOICE", "CHECKBOX"):
            if not options:
                return f"Error: 'options' must be provided for a {question_type} question."
            question_body = {
                "choiceQuestion": {
                    "type": "RADIO" if question_type == "MULTIPLE_CHOICE" else "CHECKBOX",
                    "options": [{"value": opt} for opt in options]
                }
            }
        elif question_type == "PARAGRAPH":
            question_body = {"textQuestion": {"paragraph": True}}
        elif question_type == "TEXT":
            question_body = {"textQuestion": {"paragraph": False}}
        else:
            return f"Error: Unsupported question_type '{question_type}'. Use TEXT, PARAGRAPH, MULTIPLE_CHOICE, or CHECKBOX."

        creds = _get_google_credentials()
        service = build("forms", "v1", credentials=creds)

        request_body = {
            "requests": [{
                "createItem": {
                    "item": {
                        "title": question_title,
                        "questionItem": {"question": {**question_body, "required": required}}
                    },
                    "location": {"index": 0}
                }
            }]
        }

        service.forms().batchUpdate(formId=form_id, body=request_body).execute()

        return f"Success! The question '{question_title}' was added to the form."

    except HttpError as error:
        if error.resp.status == 404:
            return f"Error: The form with ID '{form_id}' was not found."
        return f"An error occurred with the Forms API: {error}"
    except Exception as e:
        print(f"!!! An error occurred in add_question_to_form: {e}")
        return f"An unexpected error occurred while adding the question: {e}"


@tool
def read_google_form(form_id: str) -> str:
    """Reads a Google Form's title, description, and list of questions using its form ID."""
    print(f"--- Tool: read_google_form called for form_id={form_id} ---")
    try:
        creds = _get_google_credentials()
        service = build("forms", "v1", credentials=creds)

        form = service.forms().get(formId=form_id).execute()

        info = form.get("info", {})
        questions = []
        for item in form.get("items", []):
            question_item = item.get("questionItem", {}).get("question", {})
            questions.append({
                "title": item.get("title"),
                "required": question_item.get("required", False),
                "type": next(iter(question_item.keys()), "unknown") if question_item else None
            })

        summary = {
            "title": info.get("title"),
            "description": info.get("description"),
            "responder_uri": form.get("responderUri"),
            "questions": questions
        }
        return json.dumps(summary, indent=2)

    except HttpError as error:
        if error.resp.status == 404:
            return f"Error: The form with ID '{form_id}' was not found."
        return f"An error occurred with the Forms API: {error}"
    except Exception as e:
        return f"An unexpected error occurred while reading the form: {e}"


@tool
def list_form_responses(form_id: str, max_results: int = 20) -> str:
    """Lists the submitted responses to a Google Form using its form ID."""
    print(f"--- Tool: list_form_responses called for form_id={form_id} ---")
    try:
        creds = _get_google_credentials()
        service = build("forms", "v1", credentials=creds)

        result = service.forms().responses().list(formId=form_id, pageSize=max_results).execute()
        responses = result.get("responses", [])

        if not responses:
            return json.dumps([])

        parsed_responses = []
        for response in responses:
            answers = {}
            for question_id, answer in response.get("answers", {}).items():
                text_answers = answer.get("textAnswers", {}).get("answers", [])
                answers[question_id] = [a.get("value") for a in text_answers]
            parsed_responses.append({
                "response_id": response.get("responseId"),
                "submitted_at": response.get("createTime"),
                "answers": answers
            })

        return json.dumps(parsed_responses, indent=2)

    except HttpError as error:
        if error.resp.status == 404:
            return f"Error: The form with ID '{form_id}' was not found."
        return f"An error occurred with the Forms API: {error}"
    except Exception as e:
        return f"An unexpected error occurred while listing responses: {e}"


calendar_tools = [
    list_upcoming_events,
    get_events_for_day,
    create_google_event,
    delete_google_event,
    get_events_for_range,
    update_google_event,
    find_free_slot]

email_tools = [
    search_emails,
    delete_email,
    archive_email,
    create_email_draft,
    send_draft,
    create_reply_draft]

search_tools = [tavily_search]

task_tools = [list_tasks, add_task, complete_task, update_task, delete_task]

drive_tools = [
    search_drive_files,
    list_recent_drive_files,
    create_drive_folder,
    share_drive_file,
    delete_drive_file]

sheets_tools = [
    create_spreadsheet,
    read_sheet_values,
    write_sheet_values,
    append_sheet_row]

docs_tools = [
    create_google_doc,
    read_google_doc,
    append_to_google_doc]

slides_tools = [
    create_presentation,
    add_slide_to_presentation,
    list_presentation_slides]

contacts_tools = [
    search_contacts,
    list_contacts,
    get_contact_email]

forms_tools = [
    create_google_form,
    add_question_to_form,
    read_google_form,
    list_form_responses]


print(f"Defined {len(calendar_tools)} tools for the Calendar Expert.")
print(f"Defined {len(email_tools)} tools for the Email Expert.")
print(f"Defined {len(search_tools)} tools for the Search Expert.")
print(f"Defined {len(task_tools)} tools for the Task Expert.")
print(f"Defined {len(drive_tools)} tools for the Drive Expert.")
print(f"Defined {len(sheets_tools)} tools for the Sheets Expert.")
print(f"Defined {len(docs_tools)} tools for the Docs Expert.")
print(f"Defined {len(slides_tools)} tools for the Slides Expert.")
print(f"Defined {len(contacts_tools)} tools for the Contacts Expert.")
print(f"Defined {len(forms_tools)} tools for the Forms Expert.")


class AgentState(TypedDict):
    messages: Annotated[list, operator.add]
    route: Literal["calendar", "email", "search", "conversational", "tasks", "drive", "sheets", "docs", "slides", "contacts", "forms", "vision"]
    error: str


class RouteQuery(BaseModel):
    """Route the user's query to the correct expert."""

    route: Literal["calendar", "email", "search", "tasks", "conversational", "drive", "sheets", "docs", "slides", "contacts", "forms"] = Field(
        description="""The category to route the user's request to, based on their intent.
        - 'calendar': For managing calendar events.
        - 'email': For managing emails.
        - 'search': For general knowledge questions.
        - 'tasks': For managing to-do lists and tasks (e.g., "add a to-do", "list my tasks").
        - 'drive': For managing files and folders in Google Drive (search, share, create folders, delete files).
        - 'sheets': For creating or reading/writing data in Google Sheets spreadsheets.
        - 'docs': For creating, reading, or editing Google Docs documents.
        - 'slides': For creating or editing Google Slides presentations.
        - 'contacts': For looking up or listing entries in Google Contacts (e.g., finding someone's email address).
        - 'forms': For creating Google Forms, adding questions, or checking form responses.
        - 'conversational': For simple chit-chat."""
    )


def router_node(state: AgentState):
    """
    Analyzes the user's latest message AND the assistant's last message
    to route the task to the appropriate expert, especially for multi-step tasks.
    """
    print("--- Smart Router Node ---")

    messages = state['messages']
    last_message_content = messages[-1].content

    if isinstance(last_message_content, list) and any(
        isinstance(part, dict) and part.get("type") == "image_url" for part in last_message_content
    ):
        print("Smart Router Decision: 'vision' (image attachment detected)")
        return {"route": "vision"}

    structured_llm_router = llm.with_structured_output(RouteQuery, method="json_schema")

    user_message = last_message_content
    
    last_ai_message_content = ""
    if len(messages) > 1 and isinstance(messages[-2], AIMessage):
        last_ai_message_content = messages[-2].content

    router_prompt_template = f"""You are an expert task router. Your job is to classify the user's latest message based on the conversation history.

    Here is the context of the last turn:
    Assistant's previous message: "{last_ai_message_content}"
    User's latest message: "{user_message}"

    **CRITICAL RULES:**
    1.  If the assistant's previous message was a **confirmation question** (e.g., "Are you sure you want to delete...?"), and the user's message is a confirmation (e.g., "yes", "confirm"), you MUST route this to the original task's category (e.g., 'calendar').
    2.  If the assistant's previous message was a **clarification question** asking for more information (e.g., "Which one do you mean?", "Could you please clarify which task?"), and the user's message provides an answer, you MUST also route this to the original task's category (e.g., 'tasks').

    Otherwise, classify the user's latest message based on its own content.
    """
    
    route_decision = structured_llm_router.invoke(router_prompt_template)
    
    print(f"Smart Router Decision: '{route_decision.route}'")
    return {"route": route_decision.route}



today_str = datetime.date.today().isoformat()
today_day_name = datetime.date.today().strftime('%A')

GENERAL_RULES = """
**General Rules:**
- After a tool runs, you MUST summarize the result in a friendly, natural sentence. Do not show raw data.
- If a tool returns an empty list `[]`, inform the user in a helpful way (e.g., "It looks like you have no events.").
- When an action is successful, confirm it reassuringly (e.g., "All set! I've added that to your list.").
"""


calendar_system_prompt = f"""You are a Google Calendar expert. Today is {today_str} ({today_day_name}).

Your instructions are:
- To answer the user's request, you must use one of the provided tools.
- For a specific day (e.g., "tomorrow", "Sep 15"), use the `get_events_for_day` tool.
- For a date range (e.g., "this week"), use the `get_events_for_range` tool.
- For general future queries (e.g., "what's next?"), use `list_upcoming_events`.
- If the user asks for a specific NUMBER of events (e.g., "next 5 events"), you MUST use the `list_upcoming_events` tool with the `limit` parameter. Do not interpret this as a time range.
- **CRITICAL RULE for finding free time:** You are FORBIDDEN from calling `find_free_slot` if the user has not provided ALL three of these: `duration_minutes`, `search_start_natural`, AND `search_end_natural`.
    - If `duration_minutes` is missing, you MUST ask: "For how long?"
    - If `search_start_natural` or `search_end_natural` are missing, you MUST ask: "For what day and time range should I look?"
    - You are NOT allowed to assume "today" or any other default value.
- **CRITICAL RULE for event creation: The `duration_minutes` parameter is required. You are FORBIDDEN from calling the `create_google_event` tool if the user has not provided a duration. If the duration is missing, you MUST stop and ask the user a clarifying question like "How long will the event last?". DO NOT call the tool with a null duration.**
- **If a tool returns an error that a date could not be understood, you must inform the user that you could not understand the date they provided.**
- CRITICAL RULE for updates and deletions: You are FORBIDDEN from calling `update_google_event` or `delete_google_event` until you have followed this exact sequence:
    1. First, find the specific event the user is referring to and get its `event_id`. If there is any ambiguity (e.g., multiple events with the same name), you MUST ask the user to clarify which one they mean.
    2. Second, clearly state the action you are about to take (e.g., "So, you want to move 'Project Sync' to 4 PM?") and ask for explicit confirmation.
    3. Only after the user has clearly confirmed (e.g., "Yes, please do"), you may call the appropriate tool.
{GENERAL_RULES}
"""


email_system_prompt = f"""You are an expert at managing a Gmail account.

Your instructions are:
- To answer the user's request, you must use one of the provided tools.
- For searching emails, use the `search_emails` tool with appropriate filters.
- CRITICAL RULE for deletions and archiving: ... (bu kural aynı kalıyor) ...
- CRITICAL RULE for sending email: You are FORBIDDEN from sending an email directly. You MUST follow this exact sequence:
    1. First, use the `create_email_draft` tool to prepare the email.
    2. **After the draft is created, the tool will return its content (to, subject, body). You MUST show this preview to the user and then ask for their explicit confirmation to send it.**
    3. Only after the user has clearly confirmed, you may call the `send_draft` tool.

{GENERAL_RULES}
"""


search_system_prompt = f"""You are an expert researcher. Your only function is to answer questions using the `tavily_search` tool.

CRITICAL RULES:
- You are FORBIDDEN from answering from your memory. You MUST use the `tavily_search` tool for every factual query.
- Do not show raw JSON output. You must read the `content` of the search results, synthesize the information, and provide a single, coherent answer.
- **When possible, cite your sources by including the source URL from the search results in your answer (e.g., "[Source: URL]").**
- If the tool finds nothing, state that you could not find any information online.

{GENERAL_RULES}
"""


tasks_system_prompt = f"""You are an expert at managing a Google Tasks to-do list.

Your instructions are:
- To answer the user's request, you must use one of the provided tools.
- To show the user their tasks, use the `list_tasks` tool.
- CRITICAL RULE for listing tasks: When you receive the list of tasks from the tool, you MUST present it as a clear, itemized list. Each item must show the task's full `title` and its `due` date if one exists.
- For adding a task, use the `add_task` tool.
- CRITICAL RULE for updates and deletions: You are FORBIDDEN from calling `update_task` or `delete_task` until you have followed this exact sequence:
    1. First, find the specific task the user is referring to and get its `id` and `task_list_id`. If there is any ambiguity (e.g., multiple similar tasks), you MUST ask the user to clarify which one they mean.
    2. Second, clearly state the action you are about to take (e.g., "So, you want to change 'Buy milk' to 'Buy groceries'?") and ask for explicit confirmation.
    3. Only after the user has clearly confirmed, you may call the appropriate tool.

{GENERAL_RULES}
"""


drive_system_prompt = f"""You are an expert at managing Google Drive.

Your instructions are:
- To answer the user's request, you must use one of the provided tools.
- Use `search_drive_files` to find files by name, and `list_recent_drive_files` to show recently modified files.
- CRITICAL RULE for deletion and sharing: You are FORBIDDEN from calling `delete_drive_file` or `share_drive_file` until you have followed this exact sequence:
    1. First, find the specific file the user is referring to and get its `id`. If there is any ambiguity, you MUST ask the user to clarify which one they mean.
    2. Second, clearly state the action you are about to take (e.g., "So, you want to share 'Q3 Report' with jane@example.com as a viewer?") and ask for explicit confirmation.
    3. Only after the user has clearly confirmed, you may call the appropriate tool.

{GENERAL_RULES}
"""


sheets_system_prompt = f"""You are an expert at working with Google Sheets.

Your instructions are:
- To answer the user's request, you must use one of the provided tools.
- Use `create_spreadsheet` to make a brand new spreadsheet.
- Use `read_sheet_values` to read data from a range (A1 notation, e.g. "Sheet1!A1:C10").
- Use `write_sheet_values` to overwrite a range, and `append_sheet_row` to add a new row at the end.
- CRITICAL RULE: You are FORBIDDEN from calling `write_sheet_values` if you do not have the `spreadsheet_id`. If you don't have it, ask the user for the spreadsheet ID or link.
- Before overwriting existing data with `write_sheet_values`, confirm with the user that overwriting is intended.

{GENERAL_RULES}
"""


docs_system_prompt = f"""You are an expert at working with Google Docs.

Your instructions are:
- To answer the user's request, you must use one of the provided tools.
- Use `create_google_doc` to make a new document, `read_google_doc` to read one, and `append_to_google_doc` to add text to an existing one.
- CRITICAL RULE: You are FORBIDDEN from calling `append_to_google_doc` if you do not have the `document_id`. If you don't have it, ask the user for the document ID or link.

{GENERAL_RULES}
"""


slides_system_prompt = f"""You are an expert at working with Google Slides.

Your instructions are:
- To answer the user's request, you must use one of the provided tools.
- Use `create_presentation` to make a new presentation, `add_slide_to_presentation` to add a slide, and `list_presentation_slides` to see existing slides.
- CRITICAL RULE: You are FORBIDDEN from calling `add_slide_to_presentation` or `list_presentation_slides` if you do not have the `presentation_id`. If you don't have it, ask the user for the presentation ID or link.

{GENERAL_RULES}
"""


contacts_system_prompt = f"""You are an expert at looking up Google Contacts.

Your instructions are:
- To answer the user's request, you must use one of the provided tools.
- Use `get_contact_email` when the goal is to resolve a person's name into an email address (e.g., before sending an email or inviting them to an event).
- Use `search_contacts` for broader lookups, and `list_contacts` to show the user's contacts.
- If a name matches multiple contacts, list the matches and ask the user to clarify which one they mean.
- This is a read-only expert; you cannot create, edit, or delete contacts.

{GENERAL_RULES}
"""


forms_system_prompt = f"""You are an expert at working with Google Forms.

Your instructions are:
- To answer the user's request, you must use one of the provided tools.
- Use `create_google_form` to make a new form, `add_question_to_form` to add a question to it, `read_google_form` to see its current questions, and `list_form_responses` to check submitted responses.
- CRITICAL RULE: You are FORBIDDEN from calling `add_question_to_form`, `read_google_form`, or `list_form_responses` if you do not have the `form_id`. If you don't have it, ask the user for the form ID or link, or create a new form first.
- When adding a question, if the type is "MULTIPLE_CHOICE" or "CHECKBOX", you MUST have the list of options before calling the tool; if missing, ask the user for the options.

{GENERAL_RULES}
"""


vision_system_prompt = """You are an expert at analyzing images the user shares with you.

Your instructions are:
- Carefully look at the image and respond to whatever the user asked about it.
- If the user didn't ask a specific question, give a clear, useful description of what the image shows: notable objects, text, setting, colors, and anything else relevant.
- If the image contains text, transcribe the relevant parts accurately.
- Be concise but thorough. Do not guess at the identity of real people in photos.
"""


llm_with_calendar_tools = llm.bind_tools(calendar_tools)
calendar_tool_node = ToolNode(calendar_tools)


def calendar_agent_node(state: AgentState):
    print("--- Calendar Expert Node ---")
    messages = [SystemMessage(content=calendar_system_prompt)] + state['messages']
    response = llm_with_calendar_tools.invoke(messages)
    return {"messages": [response]}

llm_with_email_tools = llm.bind_tools(email_tools)
email_tool_node = ToolNode(email_tools)


def email_agent_node(state: AgentState):
    print("--- Email Expert Node ---")
    messages = [SystemMessage(content=email_system_prompt)] + state['messages']
    response = llm_with_email_tools.invoke(messages)
    return {"messages": [response]}

llm_with_search_tools = llm.bind_tools(search_tools)
search_tool_node = ToolNode(search_tools)



def search_agent_node(state: AgentState):
    print("--- Search Expert Node ---")
    messages = [SystemMessage(content=search_system_prompt)] + state['messages']
    response = llm_with_search_tools.invoke(messages)
    return {"messages": [response]}


    
llm_with_task_tools = llm.bind_tools(task_tools)
task_tool_node = ToolNode(task_tools)


def task_agent_node(state: AgentState):
    print("--- Task Expert Node ---")
    messages = [SystemMessage(content=tasks_system_prompt)] + state['messages']
    response = llm_with_task_tools.invoke(messages)
    return {"messages": [response]}


llm_with_drive_tools = llm.bind_tools(drive_tools)
drive_tool_node = ToolNode(drive_tools)


def drive_agent_node(state: AgentState):
    print("--- Drive Expert Node ---")
    messages = [SystemMessage(content=drive_system_prompt)] + state['messages']
    response = llm_with_drive_tools.invoke(messages)
    return {"messages": [response]}


llm_with_sheets_tools = llm.bind_tools(sheets_tools)
sheets_tool_node = ToolNode(sheets_tools)


def sheets_agent_node(state: AgentState):
    print("--- Sheets Expert Node ---")
    messages = [SystemMessage(content=sheets_system_prompt)] + state['messages']
    response = llm_with_sheets_tools.invoke(messages)
    return {"messages": [response]}


llm_with_docs_tools = llm.bind_tools(docs_tools)
docs_tool_node = ToolNode(docs_tools)


def docs_agent_node(state: AgentState):
    print("--- Docs Expert Node ---")
    messages = [SystemMessage(content=docs_system_prompt)] + state['messages']
    response = llm_with_docs_tools.invoke(messages)
    return {"messages": [response]}


llm_with_slides_tools = llm.bind_tools(slides_tools)
slides_tool_node = ToolNode(slides_tools)


def slides_agent_node(state: AgentState):
    print("--- Slides Expert Node ---")
    messages = [SystemMessage(content=slides_system_prompt)] + state['messages']
    response = llm_with_slides_tools.invoke(messages)
    return {"messages": [response]}


llm_with_contacts_tools = llm.bind_tools(contacts_tools)
contacts_tool_node = ToolNode(contacts_tools)


def contacts_agent_node(state: AgentState):
    print("--- Contacts Expert Node ---")
    messages = [SystemMessage(content=contacts_system_prompt)] + state['messages']
    response = llm_with_contacts_tools.invoke(messages)
    return {"messages": [response]}


llm_with_forms_tools = llm.bind_tools(forms_tools)
forms_tool_node = ToolNode(forms_tools)


def forms_agent_node(state: AgentState):
    print("--- Forms Expert Node ---")
    messages = [SystemMessage(content=forms_system_prompt)] + state['messages']
    response = llm_with_forms_tools.invoke(messages)
    return {"messages": [response]}


def vision_agent_node(state: AgentState):
    print("--- Vision Expert Node ---")
    # Only the current turn is sent (not the full thread history): keeps each image
    # analysis independent, avoids re-sending old images, and stays under the
    # vision model's per-request image-count limit as a conversation grows.
    last_message = state['messages'][-1]
    messages = [SystemMessage(content=vision_system_prompt), last_message]
    try:
        response = vision_llm.invoke(messages)
    except Exception as e:
        print(f"!!! Vision model error: {e}")
        error_text = str(e)
        if "rate_limit" in error_text.lower() or "429" in error_text or "413" in error_text:
            friendly = (
                "I'm hitting the image-analysis rate limit right now (the free tier only allows a "
                "handful of image requests per minute). Please wait about a minute and try again."
            )
        else:
            friendly = "Sorry, I couldn't analyze that image right now. Please try again with a different image."
        response = AIMessage(content=friendly)
    return {"messages": [response]}


def conversational_node(state: AgentState):

    print("--- Conversational Node ---")
    response = llm.invoke(state['messages'])
    return {"messages": [response]}


def should_call_tools(state: AgentState) -> Literal["tools", END]:
    """
    Checks if the last message is an AIMessage with tool calls.
    """
    if not state['messages']:
        return END

    last_message = state['messages'][-1]
    
    if isinstance(last_message, AIMessage):
        if last_message.tool_calls:
            return "tools"
        else:
            return END
    else:
        return END


workflow = StateGraph(AgentState)

workflow.add_node("router", router_node)
workflow.add_node("calendar_agent", calendar_agent_node)
workflow.add_node("calendar_tools", calendar_tool_node)
workflow.add_node("email_agent", email_agent_node)
workflow.add_node("email_tools", email_tool_node)
workflow.add_node("search_agent", search_agent_node)
workflow.add_node("search_tools", search_tool_node)
workflow.add_node("conversational_agent", conversational_node)
workflow.add_node("task_agent", task_agent_node)
workflow.add_node("task_tools", task_tool_node)
workflow.add_node("drive_agent", drive_agent_node)
workflow.add_node("drive_tools", drive_tool_node)
workflow.add_node("sheets_agent", sheets_agent_node)
workflow.add_node("sheets_tools", sheets_tool_node)
workflow.add_node("docs_agent", docs_agent_node)
workflow.add_node("docs_tools", docs_tool_node)
workflow.add_node("slides_agent", slides_agent_node)
workflow.add_node("slides_tools", slides_tool_node)
workflow.add_node("contacts_agent", contacts_agent_node)
workflow.add_node("contacts_tools", contacts_tool_node)
workflow.add_node("forms_agent", forms_agent_node)
workflow.add_node("forms_tools", forms_tool_node)
workflow.add_node("vision_agent", vision_agent_node)

workflow.set_entry_point("router")

workflow.add_conditional_edges(
    "router",
    lambda state: state["route"],
    {
        "calendar": "calendar_agent",
        "email": "email_agent",
        "search": "search_agent",
        "tasks": "task_agent",
        "drive": "drive_agent",
        "sheets": "sheets_agent",
        "docs": "docs_agent",
        "slides": "slides_agent",
        "contacts": "contacts_agent",
        "forms": "forms_agent",
        "vision": "vision_agent",
        "conversational": "conversational_agent"
    }
)

workflow.add_edge("vision_agent", END)

workflow.add_edge("conversational_agent", END)


workflow.add_conditional_edges("calendar_agent", should_call_tools, {"tools": "calendar_tools", END: END})
workflow.add_edge("calendar_tools", "calendar_agent")

workflow.add_conditional_edges("email_agent", should_call_tools, {"tools": "email_tools", END: END})
workflow.add_edge("email_tools", "email_agent")

workflow.add_conditional_edges("task_agent", should_call_tools, {"tools": "task_tools", END: END})
workflow.add_edge("task_tools", "task_agent")

workflow.add_conditional_edges("search_agent", should_call_tools, {"tools": "search_tools", END: END})
workflow.add_edge("search_tools", "search_agent")

workflow.add_conditional_edges("drive_agent", should_call_tools, {"tools": "drive_tools", END: END})
workflow.add_edge("drive_tools", "drive_agent")

workflow.add_conditional_edges("sheets_agent", should_call_tools, {"tools": "sheets_tools", END: END})
workflow.add_edge("sheets_tools", "sheets_agent")

workflow.add_conditional_edges("docs_agent", should_call_tools, {"tools": "docs_tools", END: END})
workflow.add_edge("docs_tools", "docs_agent")

workflow.add_conditional_edges("slides_agent", should_call_tools, {"tools": "slides_tools", END: END})
workflow.add_edge("slides_tools", "slides_agent")

workflow.add_conditional_edges("contacts_agent", should_call_tools, {"tools": "contacts_tools", END: END})
workflow.add_edge("contacts_tools", "contacts_agent")

workflow.add_conditional_edges("forms_agent", should_call_tools, {"tools": "forms_tools", END: END})
workflow.add_edge("forms_tools", "forms_agent")

DATA_DIR = "data"

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

db_path = os.path.join(DATA_DIR, "conversations.sqlite")

print(f"Backend is using database at: {db_path}")

conn = sqlite3.connect(db_path, check_same_thread=False)

cursor = conn.cursor()
cursor.execute("""
    CREATE TABLE IF NOT EXISTS chat_metadata (
        thread_id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")
conn.commit()

memory = SqliteSaver(conn=conn)
app = workflow.compile(checkpointer=memory)
print("\nLangGraph application compiled successfully and is ready.")