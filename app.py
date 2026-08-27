from flask import Flask, render_template, request, jsonify, send_from_directory
import imaplib
import email
import re
import os
from email.header import decode_header
from datetime import datetime

app = Flask(__name__, static_folder='static', static_url_path='/static')

@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET,PUT,POST,DELETE,OPTIONS'
    return response

def generate_dot_emails(email_address):
    if '@' not in email_address:
        return []
    username, domain = email_address.split('@')
    username = username.replace('.', '')
    
    n = len(username)
    emails = []
    
    for i in range(2**(n-1)):
        binary = bin(i)[2:].zfill(n-1)
        current_email = username[0]
        for j in range(n-1):
            if binary[j] == '1':
                current_email += '.'
            current_email += username[j+1]
        emails.append(f"{current_email}@{domain}")
    return emails

def decode_mime_words(s):
    return u''.join(
        word.decode(encoding or 'utf-8') if isinstance(word, bytes) else word
        for word, encoding in decode_header(s))

def clean_html(html_content):
    if not html_content:
        return ""
    text = re.sub(r'<[^>]+>', ' ', html_content)
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&gt;', '>').replace('&lt;', '<')
    return text

def extract_otp(text):
    if not text:
        return None
    
    # 1. Hyphenated / Spaced OTPs (e.g. 123-456, G-123456)
    formatted_match = re.search(r'\b(?:G-)?(\d{3}[\s-]?\d{3})\b', text)
    if formatted_match:
        return formatted_match.group(1).replace('-', '').replace(' ', '')

    # 2. Contextual OTP match (e.g. "code is 849201", "OTP: 849201", "pin: 1234")
    context_match = re.search(r'(?:code|otp|pin|is|verification|passcode|security)\s*[:\s]*\b(\d{4,8})\b', text, re.IGNORECASE)
    if context_match:
        return context_match.group(1)
        
    # 3. Fallback: Any standalone 4 to 8 digit number
    numbers = re.findall(r'\b\d{4,8}\b', text)
    if numbers:
        filtered = [n for n in numbers if n not in ['2024', '2025', '2026', '2027']]
        return filtered[0] if filtered else numbers[0]
        
    return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/logo.png')
def serve_logo_root():
    return send_from_directory('static', 'logo.png')

@app.route('/static/<path:filename>')
def serve_static_files(filename):
    return send_from_directory('static', filename)

@app.route('/api/generate', methods=['POST'])
def api_generate():
    data = request.json
    email_addr = data.get('email', '')
    emails = generate_dot_emails(email_addr)
    return jsonify({"emails": emails})

@app.route('/api/verify_connection', methods=['POST'])
def verify_connection():
    data = request.json
    monitor_email = data.get('email', '')
    monitor_password = data.get('password', '')
    
    if not monitor_email or not monitor_password:
        return jsonify({"status": "error", "message": "Email and password required"}), 400

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", timeout=10)
        mail.login(monitor_email, monitor_password)
        mail.logout()
        return jsonify({"status": "success", "message": "Connection verified"})
    except imaplib.IMAP4.error:
        return jsonify({"status": "error", "message": "Invalid Email or App Password"}), 401
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/check_emails', methods=['POST'])
def check_emails():
    data = request.json
    monitor_email = data.get('email', '')
    monitor_password = data.get('password', '')
    
    if not monitor_email or not monitor_password:
        return jsonify({"status": "error", "message": "Email and password required"}), 400

    otps_found = []
    
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(monitor_email, monitor_password)
        
        # Select INBOX first, fallback to All Mail
        try:
            mail.select("inbox")
        except:
            mail.select('"[Gmail]/All Mail"')
        
        status, messages = mail.search(None, 'UNSEEN')
        msg_ids = messages[0].split() if (status == "OK" and messages[0]) else []
        
        if not msg_ids:
            status_all, messages_all = mail.search(None, 'ALL')
            if status_all == "OK" and messages_all[0]:
                msg_ids = messages_all[0].split()[-20:] # Check last 20 emails
        
        for msg_id in msg_ids:
            status, msg_data = mail.fetch(msg_id, "(RFC822)")
            
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    subject = decode_mime_words(msg.get("Subject", ""))
                    sender = decode_mime_words(msg.get("From", "Unknown"))
                    receiver = decode_mime_words(msg.get("To", ""))
                    
                    body_plain = ""
                    body_html = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            content_type = part.get_content_type()
                            disp = str(part.get("Content-Disposition"))
                            if content_type == "text/plain" and "attachment" not in disp:
                                body_plain = part.get_payload(decode=True).decode(errors='ignore')
                            elif content_type == "text/html" and "attachment" not in disp:
                                body_html = part.get_payload(decode=True).decode(errors='ignore')
                    else:
                        body_plain = msg.get_payload(decode=True).decode(errors='ignore')
                    
                    body = body_plain if body_plain.strip() else clean_html(body_html)
                    
                    # Extract from Subject first, then Body
                    otp = extract_otp(subject) or extract_otp(body)
                    if otp:
                        otps_found.append({
                            'sender': sender,
                            'receiver': receiver,
                            'time': datetime.now().strftime("%I:%M:%S %p"),
                            'otp': otp
                        })
        
        mail.close()
        mail.logout()
        return jsonify({"status": "success", "otps": otps_found})
        
    except Exception as e:
        print(f"IMAP Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000, use_reloader=False)
