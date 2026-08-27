from flask import Flask, render_template, request, jsonify, send_from_directory
import imaplib
import email
import re
import os
import json
import urllib.request
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
        
    clean_text = clean_html(text)
    
    # 1. Direct Regex for "code: 123456", "code 123456", "is 123456", "verification code 123456", "ChatGPT code: 123456"
    match = re.search(r'(?:code|otp|pin|is|verification|passcode|security|login|confirm|auth)?\s*[:\s-]*\b(\d{4,8})\b', clean_text, re.IGNORECASE)
    if match and match.group(1) not in ['2024', '2025', '2026', '2027', '5000', '8080', '3000']:
        return match.group(1)

    # 2. Hyphenated / Spaced OTPs (e.g. 123-456, G-123456)
    formatted_match = re.search(r'\b(?:G-)?(\d{3}[\s-]?\d{3})\b', clean_text)
    if formatted_match:
        digits = formatted_match.group(1).replace('-', '').replace(' ', '')
        if digits not in ['2024', '2025', '2026']:
            return digits

    # 3. Fallback: Any standalone 4 to 8 digit number
    numbers = re.findall(r'\b\d{4,8}\b', clean_text)
    if numbers:
        filtered = [n for n in numbers if n not in ['2024', '2025', '2026', '2027', '5000', '8080']]
        if filtered:
            return filtered[0]
            
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
        mail = imaplib.IMAP4_SSL("imap.gmail.com", timeout=10)
        mail.login(monitor_email, monitor_password)
        
        # Select INBOX
        try:
            mail.select("inbox")
        except:
            mail.select('"[Gmail]/All Mail"')
        
        status, messages = mail.search(None, 'ALL')
        if status == "OK" and messages[0]:
            msg_ids = messages[0].split()[-8:] # Check last 8 emails for sub-second speed
            
            for msg_id in reversed(msg_ids):
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
                        
                        full_content = (subject + " " + body_plain + " " + clean_html(body_html)).strip()
                        
                        otp = extract_otp(full_content)
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

@app.route('/api/tempmail/generate', methods=['GET', 'POST'])
def tempmail_generate():
    try:
        url = "https://www.1secmail.com/api/v1/?action=genRandomMailbox&count=1"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
            if data and len(data) > 0:
                return jsonify({"status": "success", "email": data[0]})
    except Exception as e:
        print(f"Tempmail gen error: {e}")
        
    rand_id = os.urandom(4).hex()
    return jsonify({"status": "success", "email": f"user_{rand_id}@1secmail.com"})

@app.route('/api/tempmail/check', methods=['POST'])
def tempmail_check():
    data = request.json or {}
    email_addr = data.get('email', '')
    if not email_addr or '@' not in email_addr:
        return jsonify({"status": "error", "message": "Email required"}), 400
        
    login, domain = email_addr.split('@')
    messages_out = []
    
    try:
        url = f"https://www.1secmail.com/api/v1/?action=getMessages&login={login}&domain={domain}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            msgs = json.loads(resp.read().decode())
            
            for m in msgs[:10]:
                msg_id = m.get('id')
                detail_url = f"https://www.1secmail.com/api/v1/?action=readMessage&login={login}&domain={domain}&id={msg_id}"
                detail_req = urllib.request.Request(detail_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
                with urllib.request.urlopen(detail_req, timeout=8) as dresp:
                    detail = json.loads(dresp.read().decode())
                    subject = detail.get('subject', '')
                    text_body = detail.get('textBody', '')
                    html_body = detail.get('htmlBody', '')
                    
                    full_text = f"{subject} {text_body} {clean_html(html_body)}"
                    otp = extract_otp(full_text)
                    
                    messages_out.append({
                        'id': msg_id,
                        'from': detail.get('from', m.get('from', 'Unknown')),
                        'subject': subject or 'No Subject',
                        'date': detail.get('date', m.get('date', '')),
                        'otp': otp
                    })
                    
        return jsonify({"status": "success", "messages": messages_out})
    except Exception as e:
        print(f"Tempmail check error: {e}")
        return jsonify({"status": "success", "messages": []})

if __name__ == '__main__':
    app.run(debug=True, port=5000, use_reloader=False)
