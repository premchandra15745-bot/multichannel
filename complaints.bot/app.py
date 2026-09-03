import os
import pymysql
import pandas as pd
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, send_file
from datetime import datetime
from contextlib import contextmanager
import io

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'super_secret_key_mcn_complaints')

# --- MYSQL CONFIGURATION ---
MYSQL_HOST = os.getenv('MYSQL_HOST', 'localhost')
MYSQL_USER = os.getenv('MYSQL_USER', 'root')
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', '')
MYSQL_DB = os.getenv('MYSQL_DB', 'multichannel_db')

ALLOWED_AREAS = ['Haldwani', 'Century', 'Someshwar', 'Jyolikote', 'Ramgarh', 'Bhowali']
ADMIN_USER = os.getenv('ADMIN_USER', 'admin')
ADMIN_PASS = os.getenv('ADMIN_PASS', 'admin')

def detect_area_from_text(*texts):
    combined_text = " ".join([str(t) for t in texts if t]).lower()
    for area in ALLOWED_AREAS:
        if area.lower() in combined_text:
            return area
    return "Other"

@contextmanager
def get_db_cursor():
    conn = pymysql.connect(
        host=MYSQL_HOST,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DB,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True
    )
    cursor = conn.cursor()
    try:
        yield cursor
    finally:
        cursor.close()
        conn.close()

def init_db():
    try:
        conn = pymysql.connect(host=MYSQL_HOST, user=MYSQL_USER, password=MYSQL_PASSWORD)
        cursor = conn.cursor()
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {MYSQL_DB}")
        cursor.close()
        conn.close()

        with get_db_cursor() as cursor:
            # 1. Customers Table Create
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS customers (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    subscriber_id VARCHAR(100),
                    username VARCHAR(100) UNIQUE,
                    name VARCHAR(100),
                    address TEXT,
                    package VARCHAR(100),
                    renewal_date VARCHAR(100),
                    balance VARCHAR(50),
                    mobile VARCHAR(20),
                    email VARCHAR(100),
                    reg_date VARCHAR(50),
                    status VARCHAR(20) DEFAULT 'Active',
                    last_updated VARCHAR(50)
                )
            ''')

            # 2. AUTOMATIC DUPLICATE CLEANUP (Purane 24,000 extra records ko saaf karega)
            cursor.execute('''
                DELETE c1 FROM customers c1
                INNER JOIN customers c2 
                WHERE c1.id < c2.id AND c1.username = c2.username
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS complaints (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    complaint_id VARCHAR(50) UNIQUE,
                    customer_name VARCHAR(100),
                    username VARCHAR(100),
                    mobile VARCHAR(20),
                    area VARCHAR(100),
                    category VARCHAR(100),
                    type VARCHAR(100),
                    priority VARCHAR(50),
                    description TEXT,
                    preferred_contact VARCHAR(100),
                    additional_info TEXT,
                    status VARCHAR(50) DEFAULT 'Pending',
                    created_at VARCHAR(100),
                    resolved_at VARCHAR(100),
                    employee_name VARCHAR(100)
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS ont_details (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    sno VARCHAR(100),
                    mac VARCHAR(100),
                    emp_name VARCHAR(100),
                    username VARCHAR(100),
                    address TEXT,
                    date VARCHAR(100),
                    remark TEXT
                )
            ''')
        print(">>> MYSQL DATABASE CLEANED & INITIALIZED SUCCESSFULLY! <<<")
    except Exception as e:
        print("Database Init Error:", e)

init_db()

# Helper function to parse dates and calculate inactive days
def parse_date(date_str):
    if not date_str or date_str == 'N/A':
        return None
    for fmt in ('%d-%b-%y', '%d-%b-%Y', '%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y'):
        try:
            return datetime.strptime(str(date_str).strip(), fmt)
        except ValueError:
            pass
    return None

# --- AUTHENTICATION ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if request.form.get('username') == ADMIN_USER and request.form.get('password') == ADMIN_PASS:
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        else:
            error = "Invalid Username or Password."
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

# --- DASHBOARD & INACTIVE DATA BREAKDOWN ---
@app.route('/')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    today = datetime.now()

    with get_db_cursor() as cursor:
        cursor.execute("SELECT COUNT(*) as cnt FROM customers WHERE status = 'Active'")
        active_cust = cursor.fetchone()['cnt']
        
        cursor.execute("SELECT renewal_date FROM customers WHERE status = 'Inactive'")
        inactive_rows = cursor.fetchall()
        
        cursor.execute("SELECT COUNT(*) as cnt FROM complaints")
        total_comp = cursor.fetchone()['cnt']
        
        cursor.execute("SELECT COUNT(*) as cnt FROM complaints WHERE status = 'Pending'")
        pending_comp = cursor.fetchone()['cnt']

        cursor.execute("SELECT COUNT(*) as cnt FROM complaints WHERE status = 'Resolved'")
        resolved_today = cursor.fetchone()['cnt']

        cursor.execute("SELECT COUNT(*) as cnt FROM ont_details")
        total_ont = cursor.fetchone()['cnt']

        cursor.execute("SELECT complaint_id, customer_name, mobile, area, type, status, created_at FROM complaints ORDER BY id DESC LIMIT 10")
        rows = cursor.fetchall()

    cnt_30 = 0
    cnt_60 = 0
    cnt_90 = 0

    for r in inactive_rows:
        exp_date = parse_date(r['renewal_date'])
        if exp_date:
            days_inactive = (today - exp_date).days
            if days_inactive >= 90:
                cnt_90 += 1
            elif days_inactive >= 60:
                cnt_60 += 1
            elif days_inactive >= 30:
                cnt_30 += 1

    complaints_list = [
        {
            "id": r['complaint_id'], "name": r['customer_name'], "mobile": r['mobile'], 
            "area": r['area'], "type": r['type'], "status": r['status'], "date": r['created_at']
        } for r in rows
    ]

    stats = {
        "total_complaints": total_comp,
        "pending_complaints": pending_comp,
        "resolved_today": resolved_today,
        "active_customers": active_cust,
        "inactive_customers": len(inactive_rows),
        "inactive_30_days": cnt_30,
        "inactive_60_days": cnt_60,
        "inactive_90_days": cnt_90,
        "total_customers": active_cust + len(inactive_rows),
        "total_ont": total_ont
    }
    return render_template('index.html', stats=stats, complaints=complaints_list, upload_summary=None)

# --- EXCEL DOWNLOAD ROUTE FOR INACTIVE DAYS ---
@app.route('/download-inactive/<int:days>')
def download_inactive_excel(days):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    today = datetime.now()
    with get_db_cursor() as cursor:
        cursor.execute("SELECT subscriber_id, username, name, package, renewal_date, balance, mobile, email, address, reg_date FROM customers WHERE status = 'Inactive'")
        rows = cursor.fetchall()

    filtered_data = []
    for r in rows:
        exp_date = parse_date(r['renewal_date'])
        if exp_date:
            days_diff = (today - exp_date).days
            if days == 30 and (30 <= days_diff < 60):
                filtered_data.append(r)
            elif days == 60 and (60 <= days_diff < 90):
                filtered_data.append(r)
            elif days == 90 and (days_diff >= 90):
                filtered_data.append(r)

    df = pd.DataFrame(filtered_data)
    if df.empty:
        df = pd.DataFrame(columns=['subscriber_id', 'username', 'name', 'package', 'renewal_date', 'balance', 'mobile', 'email', 'address', 'reg_date'])

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name=f'Inactive {days} Days')
    output.seek(0)

    return send_file(
        output,
        download_name=f'Inactive_Customers_{days}_Days_{datetime.now().strftime("%Y%m%d")}.xlsx',
        as_attachment=True,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

# --- PAGES ---
@app.route('/all-customers')
def all_customers_page():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('all_customers.html')

@app.route('/active-customers')
def active_customers_page():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    try:
        return render_template('active_customers.html')
    except Exception:
        return redirect(url_for('all_customers_page'))

@app.route('/inactive-customers')
def inactive_customers_page():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    try:
        return render_template('inactive_customers.html')
    except Exception:
        return redirect(url_for('all_customers_page'))

@app.route('/new-complaint')
def new_complaint():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('new_complaint.html')

@app.route('/complaint-list')
def complaint_list_page():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('complaint_list.html')

@app.route('/ont-details')
def ont_details_page():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('ont_details.html')

# --- EXCEL UPLOADER (NO DUPLICATE ENTRIES) ---
@app.route('/upload-excel', methods=['POST'])
def upload_excel():
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "No file uploaded"})
    
    file = request.files['file']
    upload_status = request.args.get('target_status', 'Active') 
    today_date = datetime.now().strftime("%d-%b-%Y")

    try:
        df = pd.read_csv(file) if file.filename.endswith('.csv') else pd.read_excel(file)
        df.columns = [str(c).strip().lower().replace(" ", "_").replace(".", "") for c in df.columns]

        def get_val(row, possible_keys, default='N/A'):
            for key in possible_keys:
                for col in row.index:
                    if key in str(col).lower():
                        val = str(row[col]).strip()
                        return val if val and val != 'nan' else default
            return default

        processed_count = 0
        with get_db_cursor() as cursor:
            for _, row in df.iterrows():
                sub_id = get_val(row, ['subscriber', 'sub_id', 'cust_id', 'id'])
                user = get_val(row, ['user', 'username'])
                name = get_val(row, ['name', 'customer_name'])
                addr = get_val(row, ['addr', 'address'])
                pack = get_val(row, ['package', 'plan', 'pack'])
                renew = get_val(row, ['expiry_date', 'renew', 'validity', 'expiry'])
                bal = get_val(row, ['account_balance', 'balance', 'bal', 'amount'], '0.00')
                mob = get_val(row, ['contact_no', 'mobile', 'phone', 'contact', 'num'])
                mail = get_val(row, ['email', 'mail'])
                reg = get_val(row, ['reg', 'date', 'created'])

                if not user or user == 'N/A':
                    continue

                cursor.execute('''
                    INSERT INTO customers (subscriber_id, username, name, address, package, renewal_date, balance, mobile, email, reg_date, status, last_updated)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE 
                    subscriber_id=VALUES(subscriber_id), name=VALUES(name), address=VALUES(address), 
                    package=VALUES(package), renewal_date=VALUES(renewal_date), balance=VALUES(balance), 
                    mobile=VALUES(mobile), email=VALUES(email), status=VALUES(status), last_updated=VALUES(last_updated)
                ''', (sub_id, user, name, addr, pack, renew, bal, mob, mail, reg, upload_status, today_date))
                processed_count += 1

        return jsonify({"status": "success", "message": f"{processed_count} {upload_status} Customers process ho gaye!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- UPDATED API ENDPOINTS FOR FRONTEND ---

@app.route('/api/customers', methods=['GET'])
def get_customers_api():
    status_filter = request.args.get('status', None)
    try:
        with get_db_cursor() as cursor:
            if status_filter:
                cursor.execute("SELECT subscriber_id, username, name, package, renewal_date, balance, mobile, status FROM customers WHERE status = %s", (status_filter,))
            else:
                cursor.execute("SELECT subscriber_id, username, name, package, renewal_date, balance, mobile, status FROM customers")
            customers = cursor.fetchall()
        return jsonify({"status": "success", "customers": customers})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/complaints', methods=['GET'])
def get_complaints_api():
    try:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT * FROM complaints ORDER BY id DESC")
            complaints = cursor.fetchall()
        return jsonify({"status": "success", "complaints": complaints})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/create-complaint', methods=['POST'])
def create_complaint_api():
    data = request.json or request.form
    try:
        complaint_id = f"CMP-{int(datetime.now().timestamp())}"
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        area = detect_area_from_text(data.get('area'), data.get('address'), data.get('description'))
        
        with get_db_cursor() as cursor:
            cursor.execute('''
                INSERT INTO complaints (complaint_id, customer_name, username, mobile, area, category, type, priority, description, preferred_contact, additional_info, status, created_at, employee_name)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (
                complaint_id, data.get('customer_name'), data.get('username'), data.get('mobile'),
                area, data.get('category', 'General'), data.get('type', 'Other'), data.get('priority', 'Medium'),
                data.get('description', ''), data.get('preferred_contact', ''), data.get('additional_info', ''),
                'Pending', created_at, data.get('employee_name', 'Unassigned')
            ))
        return jsonify({"status": "success", "message": "Complaint created successfully!", "complaint_id": complaint_id})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/ont-details', methods=['GET'])
def get_ont_details_api():
    try:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT * FROM ont_details ORDER BY id DESC")
            ont_list = cursor.fetchall()
        return jsonify({"status": "success", "ont_details": ont_list})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)