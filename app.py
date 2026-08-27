from flask import Flask, render_template, request, jsonify, send_from_directory
import imaplib
import email
import re
import os
from email.header import decode_header
from datetime import datetime

app = Flask(__name__, static_folder='static', static_url_path='/static')

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

def extract_otp(text):
    match = re.search(r'\b\d{6}\b', text)
    if match:
        return match.group(0)
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
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
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
        mail.select("inbox")
        
        status, messages = mail.search(None, 'UNSEEN')
        
        if status == "OK" and messages[0]:
            for msg_id in messages[0].split():
                status, msg_data = mail.fetch(msg_id, "(RFC822)")
                
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        sender = decode_mime_words(msg.get("From", "Unknown"))
                        
                        body = ""
                        if msg.is_multipart():
                            for part in msg.walk():
                                if part.get_content_type() == "text/plain":
                                    body = part.get_payload(decode=True).decode(errors='ignore')
                                    break
                        else:
                            body = msg.get_payload(decode=True).decode(errors='ignore')
                        
                        otp = extract_otp(body)
                        if otp:
                            otps_found.append({
                                'sender': sender,
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
    app.run(debug=True, port=5000)
