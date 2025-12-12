# -*- coding: utf-8 -*-
"""
物販管理ツール - Web版 (クラウド対応)
Flask + PostgreSQL/SQLite によるWebアプリケーション
Supabase対応版
"""

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
from werkzeug.utils import secure_filename
from datetime import datetime, date, timedelta
import os
import csv
import io

# PostgreSQL対応
DATABASE_URL = os.environ.get('DATABASE_URL')

if DATABASE_URL:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    USE_POSTGRES = True
    print("📦 PostgreSQL (Supabase) モードで起動")
else:
    import sqlite3
    USE_POSTGRES = False
    DATABASE = 'merchandise.db'
    print("📦 SQLite モードで起動（ローカル開発用）")

# アプリケーション設定
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'merchandise-manager-secret-key-2024')

UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024


def get_db():
    if USE_POSTGRES:
        return psycopg2.connect(DATABASE_URL)
    else:
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        return conn


def db_execute(conn, query, params=None):
    if not USE_POSTGRES:
        query = query.replace('%s', '?').replace("''", '""')
    if USE_POSTGRES:
        cur = conn.cursor()
        cur.execute(query, params or ())
        conn.commit()
        cur.close()
    else:
        conn.execute(query, params or ())
        conn.commit()


def db_fetchone(conn, query, params=None):
    if not USE_POSTGRES:
        query = query.replace('%s', '?').replace("''", '""')
    if USE_POSTGRES:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(query, params or ())
        result = cur.fetchone()
        cur.close()
        return dict(result) if result else None
    else:
        cur = conn.execute(query, params or ())
        row = cur.fetchone()
        return dict(row) if row else None


def db_fetchall(conn, query, params=None):
    if not USE_POSTGRES:
        query = query.replace('%s', '?').replace("''", '""')
    if USE_POSTGRES:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(query, params or ())
        results = cur.fetchall()
        cur.close()
        return [dict(r) for r in results]
    else:
        cur = conn.execute(query, params or ())
        return [dict(r) for r in cur.fetchall()]


def db_insert(conn, query, params=None):
    if not USE_POSTGRES:
        query = query.replace('%s', '?').replace("''", '""')
    if USE_POSTGRES:
        if 'RETURNING' not in query.upper():
            query = query.rstrip().rstrip(')') + ') RETURNING id'
        cur = conn.cursor()
        cur.execute(query, params or ())
        result = cur.fetchone()
        conn.commit()
        cur.close()
        return result[0] if result else None
    else:
        cur = conn.execute(query, params or ())
        conn.commit()
        return cur.lastrowid


def init_db():
    conn = get_db()
    if USE_POSTGRES:
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS merchandise (
                id SERIAL PRIMARY KEY,
                purchase_date TEXT, photo_path TEXT, product_name TEXT NOT NULL,
                store_name TEXT, purchase_price REAL DEFAULT 0, payment_method TEXT,
                is_listed INTEGER DEFAULT 0, listing_date TEXT, sold_date TEXT,
                listing_price REAL DEFAULT 0, expected_shipping REAL DEFAULT 0, expected_commission REAL DEFAULT 0,
                sale_price REAL DEFAULT 0, shipping_cost REAL DEFAULT 0,
                sales_platform TEXT, commission REAL DEFAULT 0, is_shipped INTEGER DEFAULT 0,
                memo TEXT, customer_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # 既存テーブルにカラムがなければ追加
        try:
            cur.execute('ALTER TABLE merchandise ADD COLUMN IF NOT EXISTS listing_price REAL DEFAULT 0')
            cur.execute('ALTER TABLE merchandise ADD COLUMN IF NOT EXISTS expected_shipping REAL DEFAULT 0')
            cur.execute('ALTER TABLE merchandise ADD COLUMN IF NOT EXISTS expected_commission REAL DEFAULT 0')
            conn.commit()
        except:
            pass
        cur.execute('''
            CREATE TABLE IF NOT EXISTS customers (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL, email TEXT, phone TEXT, address TEXT, memo TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        cur.close()
    else:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS merchandise (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                purchase_date TEXT, photo_path TEXT, product_name TEXT NOT NULL,
                store_name TEXT, purchase_price REAL DEFAULT 0, payment_method TEXT,
                is_listed INTEGER DEFAULT 0, listing_date TEXT, sold_date TEXT,
                listing_price REAL DEFAULT 0, expected_shipping REAL DEFAULT 0, expected_commission REAL DEFAULT 0,
                sale_price REAL DEFAULT 0, shipping_cost REAL DEFAULT 0,
                sales_platform TEXT, commission REAL DEFAULT 0, is_shipped INTEGER DEFAULT 0,
                memo TEXT, customer_id INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL, email TEXT, phone TEXT, address TEXT, memo TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
    conn.close()


# ランク設定
RANK_THRESHOLDS = {'platinum': 100000, 'gold': 50000, 'silver': 10000, 'bronze': 0}
RANK_COLORS = {'platinum': '#E5E4E2', 'gold': '#FFD700', 'silver': '#C0C0C0', 'bronze': '#CD7F32'}
RANK_NAMES = {'platinum': 'プラチナ', 'gold': 'ゴールド', 'silver': 'シルバー', 'bronze': 'ブロンズ'}


def get_customer_rank(total):
    if total >= RANK_THRESHOLDS['platinum']: return 'platinum'
    if total >= RANK_THRESHOLDS['gold']: return 'gold'
    if total >= RANK_THRESHOLDS['silver']: return 'silver'
    return 'bronze'


def get_customer_stats(conn, customer_id):
    result = db_fetchone(conn, '''
        SELECT COUNT(*) as purchase_count, COALESCE(SUM(sale_price), 0) as total_purchase
        FROM merchandise WHERE customer_id = %s AND sold_date IS NOT NULL AND sold_date != ''
    ''', (customer_id,))
    total = (result['total_purchase'] if result else 0) or 0
    count = (result['purchase_count'] if result else 0) or 0
    rank = get_customer_rank(total)
    return {'purchase_count': count, 'total_purchase': total, 'rank': rank,
            'rank_name': RANK_NAMES[rank], 'rank_color': RANK_COLORS[rank]}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def calculate_profit(item):
    return (item['sale_price'] or 0) - (item['purchase_price'] or 0) - (item['shipping_cost'] or 0) - (item['commission'] or 0)


def calculate_profit_rate(item):
    profit = calculate_profit(item)
    purchase = item['purchase_price'] or 0
    return (profit / purchase * 100) if purchase > 0 else 0


def calculate_expected_profit(item):
    """想定利益を計算（出品価格ベース）"""
    listing_price = item.get('listing_price') or 0
    purchase_price = item.get('purchase_price') or 0
    expected_shipping = item.get('expected_shipping') or 0
    expected_commission = item.get('expected_commission') or 0
    return listing_price - purchase_price - expected_shipping - expected_commission


def calculate_expected_profit_rate(item):
    """想定利益率を計算"""
    profit = calculate_expected_profit(item)
    purchase = item.get('purchase_price') or 0
    return (profit / purchase * 100) if purchase > 0 else 0


with app.app_context():
    init_db()
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)


@app.route('/')
def index():
    conn = get_db()
    filter_type = request.args.get('filter', 'all')
    search = request.args.get('search', '')
    
    query = 'SELECT * FROM merchandise'
    params = []
    conditions = []
    
    if search:
        conditions.append("(product_name LIKE %s OR store_name LIKE %s OR sales_platform LIKE %s)")
        params.extend([f'%{search}%', f'%{search}%', f'%{search}%'])
    
    today = date.today()
    if filter_type == 'today':
        conditions.append('purchase_date = %s')
        params.append(today.strftime('%Y-%m-%d'))
    elif filter_type == 'yesterday':
        conditions.append('purchase_date = %s')
        params.append((today - timedelta(days=1)).strftime('%Y-%m-%d'))
    elif filter_type == 'this_week':
        conditions.append('purchase_date >= %s')
        params.append((today - timedelta(days=today.weekday())).strftime('%Y-%m-%d'))
    elif filter_type == 'this_month':
        conditions.append('purchase_date >= %s')
        params.append(today.replace(day=1).strftime('%Y-%m-%d'))
    elif filter_type == 'not_listed':
        conditions.append('is_listed = 0')
    elif filter_type == 'listed':
        conditions.append("is_listed = 1 AND (sold_date IS NULL OR sold_date = '')")
    elif filter_type == 'sold':
        conditions.append("sold_date IS NOT NULL AND sold_date != ''")
    
    if conditions:
        query += ' WHERE ' + ' AND '.join(conditions)
    query += ' ORDER BY id DESC'
    
    items = db_fetchall(conn, query, tuple(params) if params else None)
    
    stats = {
        'total': db_fetchone(conn, 'SELECT COUNT(*) as cnt FROM merchandise')['cnt'],
        'listed': db_fetchone(conn, 'SELECT COUNT(*) as cnt FROM merchandise WHERE is_listed = 1')['cnt'],
        'sold': db_fetchone(conn, "SELECT COUNT(*) as cnt FROM merchandise WHERE sold_date IS NOT NULL AND sold_date != ''")['cnt'],
        'total_profit': db_fetchone(conn, "SELECT COALESCE(SUM(sale_price - purchase_price - shipping_cost - commission), 0) as profit FROM merchandise WHERE sold_date IS NOT NULL AND sold_date != ''")['profit']
    }
    conn.close()
    
    return render_template('index.html', items=items, stats=stats, filter_type=filter_type,
                          search=search, calculate_profit=calculate_profit, calculate_profit_rate=calculate_profit_rate,
                          calculate_expected_profit=calculate_expected_profit, calculate_expected_profit_rate=calculate_expected_profit_rate)


@app.route('/add', methods=['GET', 'POST'])
def add_item():
    if request.method == 'POST':
        photo_path = None
        if 'photo' in request.files:
            file = request.files['photo']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}")
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                photo_path = filepath
        
        conn = get_db()
        db_insert(conn, '''
            INSERT INTO merchandise (purchase_date, photo_path, product_name, store_name,
                purchase_price, payment_method, is_listed, listing_date, sold_date,
                listing_price, expected_shipping, expected_commission,
                sale_price, shipping_cost, sales_platform, commission, is_shipped, memo, customer_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (
            request.form.get('purchase_date') or None, photo_path,
            request.form.get('product_name'), request.form.get('store_name') or None,
            float(request.form.get('purchase_price') or 0), request.form.get('payment_method') or None,
            1 if request.form.get('is_listed') else 0, request.form.get('listing_date') or None,
            request.form.get('sold_date') or None,
            float(request.form.get('listing_price') or 0),
            float(request.form.get('expected_shipping') or 0),
            float(request.form.get('expected_commission') or 0),
            float(request.form.get('sale_price') or 0),
            float(request.form.get('shipping_cost') or 0), request.form.get('sales_platform') or None,
            float(request.form.get('commission') or 0), 1 if request.form.get('is_shipped') else 0,
            request.form.get('memo') or None,
            int(request.form.get('customer_id')) if request.form.get('customer_id') else None
        ))
        conn.close()
        flash('商品を登録しました', 'success')
        return redirect(url_for('index'))
    
    return render_template('form.html', item=None, action='add')


@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit_item(id):
    conn = get_db()
    if request.method == 'POST':
        photo_path = request.form.get('existing_photo')
        if 'photo' in request.files:
            file = request.files['photo']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}")
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                photo_path = filepath
        
        db_execute(conn, '''
            UPDATE merchandise SET purchase_date=%s, photo_path=%s, product_name=%s, store_name=%s,
                purchase_price=%s, payment_method=%s, is_listed=%s, listing_date=%s, sold_date=%s,
                listing_price=%s, expected_shipping=%s, expected_commission=%s,
                sale_price=%s, shipping_cost=%s, sales_platform=%s, commission=%s, is_shipped=%s,
                memo=%s, customer_id=%s, updated_at=CURRENT_TIMESTAMP WHERE id=%s
        ''', (
            request.form.get('purchase_date') or None, photo_path,
            request.form.get('product_name'), request.form.get('store_name') or None,
            float(request.form.get('purchase_price') or 0), request.form.get('payment_method') or None,
            1 if request.form.get('is_listed') else 0, request.form.get('listing_date') or None,
            request.form.get('sold_date') or None,
            float(request.form.get('listing_price') or 0),
            float(request.form.get('expected_shipping') or 0),
            float(request.form.get('expected_commission') or 0),
            float(request.form.get('sale_price') or 0),
            float(request.form.get('shipping_cost') or 0), request.form.get('sales_platform') or None,
            float(request.form.get('commission') or 0), 1 if request.form.get('is_shipped') else 0,
            request.form.get('memo') or None,
            int(request.form.get('customer_id')) if request.form.get('customer_id') else None, id
        ))
        conn.close()
        flash('商品を更新しました', 'success')
        return redirect(url_for('index'))
    
    item = db_fetchone(conn, 'SELECT * FROM merchandise WHERE id = %s', (id,))
    conn.close()
    if not item:
        flash('商品が見つかりません', 'error')
        return redirect(url_for('index'))
    return render_template('form.html', item=item, action='edit')


@app.route('/delete/<int:id>', methods=['POST'])
def delete_item(id):
    conn = get_db()
    db_execute(conn, 'DELETE FROM merchandise WHERE id = %s', (id,))
    conn.close()
    flash('商品を削除しました', 'success')
    return redirect(url_for('index'))


@app.route('/view/<int:id>')
def view_item(id):
    conn = get_db()
    item = db_fetchone(conn, 'SELECT * FROM merchandise WHERE id = %s', (id,))
    conn.close()
    if not item:
        flash('商品が見つかりません', 'error')
        return redirect(url_for('index'))
    return render_template('view.html', item=item, calculate_profit=calculate_profit, calculate_profit_rate=calculate_profit_rate)


@app.route('/export')
def export_csv():
    conn = get_db()
    items = db_fetchall(conn, 'SELECT * FROM merchandise ORDER BY id DESC')
    conn.close()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['管理No', '仕入日', '商品名', '店舗名', '仕入額', '出品済', '出品日', '売却日',
                     '売上金', '送料', '販売先', '手数料', '利益', '利益率', '発送済', 'メモ'])
    for item in items:
        profit = calculate_profit(item)
        writer.writerow([item['id'], item['purchase_date'] or '', item['product_name'],
            item['store_name'] or '', item['purchase_price'], '✓' if item['is_listed'] else '',
            item['listing_date'] or '', item['sold_date'] or '', item['sale_price'],
            item['shipping_cost'], item['sales_platform'] or '', item['commission'],
            f'{profit:.0f}', f'{calculate_profit_rate(item):.1f}%', '✓' if item['is_shipped'] else '',
            item['memo'] or ''])
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode('utf-8-sig')), mimetype='text/csv',
                     as_attachment=True, download_name=f'売上データ_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv')


@app.route('/api/stats')
def api_stats():
    conn = get_db()
    stats = {
        'total': db_fetchone(conn, 'SELECT COUNT(*) as cnt FROM merchandise')['cnt'],
        'listed': db_fetchone(conn, 'SELECT COUNT(*) as cnt FROM merchandise WHERE is_listed = 1')['cnt'],
        'sold': db_fetchone(conn, "SELECT COUNT(*) as cnt FROM merchandise WHERE sold_date IS NOT NULL AND sold_date != ''")['cnt'],
        'total_profit': db_fetchone(conn, "SELECT COALESCE(SUM(sale_price - purchase_price - shipping_cost - commission), 0) as profit FROM merchandise WHERE sold_date IS NOT NULL AND sold_date != ''")['profit']
    }
    conn.close()
    return jsonify(stats)


# 顧客管理
@app.route('/customers')
def customers_list():
    conn = get_db()
    rank_filter = request.args.get('rank', 'all')
    search = request.args.get('search', '')
    
    customers = db_fetchall(conn, 'SELECT * FROM customers ORDER BY id DESC')
    customers_with_stats = []
    for c in customers:
        stats = get_customer_stats(conn, c['id'])
        c_dict = dict(c)
        c_dict.update(stats)
        if rank_filter != 'all' and stats['rank'] != rank_filter:
            continue
        if search and search.lower() not in c['name'].lower():
            continue
        customers_with_stats.append(c_dict)
    
    rank_counts = {'platinum': 0, 'gold': 0, 'silver': 0, 'bronze': 0}
    for c in customers_with_stats:
        rank_counts[c['rank']] += 1
    conn.close()
    
    return render_template('customers.html', customers=customers_with_stats, rank_filter=rank_filter,
                          search=search, rank_counts=rank_counts, rank_names=RANK_NAMES,
                          rank_colors=RANK_COLORS, rank_thresholds=RANK_THRESHOLDS)


@app.route('/customers/add', methods=['GET', 'POST'])
def add_customer():
    if request.method == 'POST':
        conn = get_db()
        db_insert(conn, '''
            INSERT INTO customers (name, email, phone, address, memo)
            VALUES (%s, %s, %s, %s, %s)
        ''', (request.form.get('name'), request.form.get('email') or None,
              request.form.get('phone') or None, request.form.get('address') or None,
              request.form.get('memo') or None))
        conn.close()
        flash('顧客を登録しました', 'success')
        return redirect(url_for('customers_list'))
    return render_template('customer_form.html', customer=None, action='add')


@app.route('/customers/edit/<int:id>', methods=['GET', 'POST'])
def edit_customer(id):
    conn = get_db()
    if request.method == 'POST':
        db_execute(conn, '''
            UPDATE customers SET name=%s, email=%s, phone=%s, address=%s, memo=%s,
                updated_at=CURRENT_TIMESTAMP WHERE id=%s
        ''', (request.form.get('name'), request.form.get('email') or None,
              request.form.get('phone') or None, request.form.get('address') or None,
              request.form.get('memo') or None, id))
        conn.close()
        flash('顧客情報を更新しました', 'success')
        return redirect(url_for('customers_list'))
    
    customer = db_fetchone(conn, 'SELECT * FROM customers WHERE id = %s', (id,))
    conn.close()
    if not customer:
        flash('顧客が見つかりません', 'error')
        return redirect(url_for('customers_list'))
    return render_template('customer_form.html', customer=customer, action='edit')


@app.route('/customers/view/<int:id>')
def view_customer(id):
    conn = get_db()
    customer = db_fetchone(conn, 'SELECT * FROM customers WHERE id = %s', (id,))
    if not customer:
        conn.close()
        flash('顧客が見つかりません', 'error')
        return redirect(url_for('customers_list'))
    
    purchases = db_fetchall(conn, '''
        SELECT * FROM merchandise WHERE customer_id = %s AND sold_date IS NOT NULL AND sold_date != ''
        ORDER BY sold_date DESC
    ''', (id,))
    stats = get_customer_stats(conn, id)
    
    next_rank_info = None
    if stats['rank'] == 'bronze':
        next_rank_info = {'rank': 'シルバー', 'needed': RANK_THRESHOLDS['silver'] - stats['total_purchase']}
    elif stats['rank'] == 'silver':
        next_rank_info = {'rank': 'ゴールド', 'needed': RANK_THRESHOLDS['gold'] - stats['total_purchase']}
    elif stats['rank'] == 'gold':
        next_rank_info = {'rank': 'プラチナ', 'needed': RANK_THRESHOLDS['platinum'] - stats['total_purchase']}
    conn.close()
    
    return render_template('customer_view.html', customer=customer, purchases=purchases,
                          stats=stats, next_rank_info=next_rank_info, rank_thresholds=RANK_THRESHOLDS,
                          calculate_profit=calculate_profit)


@app.route('/customers/delete/<int:id>', methods=['POST'])
def delete_customer(id):
    conn = get_db()
    db_execute(conn, 'UPDATE merchandise SET customer_id = NULL WHERE customer_id = %s', (id,))
    db_execute(conn, 'DELETE FROM customers WHERE id = %s', (id,))
    conn.close()
    flash('顧客を削除しました', 'success')
    return redirect(url_for('customers_list'))


@app.route('/api/customers')
def api_customers():
    conn = get_db()
    customers = db_fetchall(conn, 'SELECT id, name FROM customers ORDER BY name')
    conn.close()
    return jsonify([{'id': c['id'], 'name': c['name']} for c in customers])


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
