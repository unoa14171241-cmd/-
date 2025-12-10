# -*- coding: utf-8 -*-
"""
物販管理ツール - Web版 (クラウド対応)
Flask + SQLite によるWebアプリケーション
"""

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
from werkzeug.utils import secure_filename
from datetime import datetime, date, timedelta
import sqlite3
import os
import csv
import io

# アプリケーション設定
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'merchandise-manager-secret-key-2024')

# ファイルアップロード設定
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

# データベースパス
DATABASE = os.environ.get('DATABASE_PATH', 'merchandise.db')


def get_db():
    """データベース接続を取得"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """データベース初期化"""
    conn = get_db()
    # 商品テーブル
    conn.execute('''
        CREATE TABLE IF NOT EXISTS merchandise (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            purchase_date TEXT,
            photo_path TEXT,
            product_name TEXT NOT NULL,
            store_name TEXT,
            purchase_price REAL DEFAULT 0,
            payment_method TEXT,
            is_listed INTEGER DEFAULT 0,
            listing_date TEXT,
            sold_date TEXT,
            sale_price REAL DEFAULT 0,
            shipping_cost REAL DEFAULT 0,
            sales_platform TEXT,
            commission REAL DEFAULT 0,
            is_shipped INTEGER DEFAULT 0,
            memo TEXT,
            customer_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # 顧客テーブル
    conn.execute('''
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT,
            phone TEXT,
            address TEXT,
            memo TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()


# ランク設定（購入金額の閾値）
RANK_THRESHOLDS = {
    'platinum': 100000,  # プラチナ: 10万円以上
    'gold': 50000,       # ゴールド: 5万円以上
    'silver': 10000,     # シルバー: 1万円以上
    'bronze': 0          # ブロンズ: 0円以上
}

RANK_COLORS = {
    'platinum': '#E5E4E2',
    'gold': '#FFD700',
    'silver': '#C0C0C0',
    'bronze': '#CD7F32'
}

RANK_NAMES = {
    'platinum': 'プラチナ',
    'gold': 'ゴールド',
    'silver': 'シルバー',
    'bronze': 'ブロンズ'
}


def get_customer_rank(total_purchase):
    """購入金額からランクを判定"""
    if total_purchase >= RANK_THRESHOLDS['platinum']:
        return 'platinum'
    elif total_purchase >= RANK_THRESHOLDS['gold']:
        return 'gold'
    elif total_purchase >= RANK_THRESHOLDS['silver']:
        return 'silver'
    else:
        return 'bronze'


def get_customer_stats(conn, customer_id):
    """顧客の統計情報を取得"""
    result = conn.execute('''
        SELECT 
            COUNT(*) as purchase_count,
            COALESCE(SUM(sale_price), 0) as total_purchase
        FROM merchandise 
        WHERE customer_id = ? AND sold_date IS NOT NULL AND sold_date != ""
    ''', (customer_id,)).fetchone()
    
    total_purchase = result['total_purchase'] or 0
    return {
        'purchase_count': result['purchase_count'] or 0,
        'total_purchase': total_purchase,
        'rank': get_customer_rank(total_purchase),
        'rank_name': RANK_NAMES[get_customer_rank(total_purchase)],
        'rank_color': RANK_COLORS[get_customer_rank(total_purchase)]
    }


def allowed_file(filename):
    """許可されたファイル形式かチェック"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def calculate_profit(item):
    """利益を計算"""
    sale_price = item['sale_price'] or 0
    purchase_price = item['purchase_price'] or 0
    shipping_cost = item['shipping_cost'] or 0
    commission = item['commission'] or 0
    return sale_price - purchase_price - shipping_cost - commission


def calculate_profit_rate(item):
    """利益率を計算"""
    profit = calculate_profit(item)
    purchase_price = item['purchase_price'] or 0
    if purchase_price > 0:
        return (profit / purchase_price) * 100
    return 0


# アプリ起動時にDB初期化とアップロードフォルダ作成
with app.app_context():
    init_db()
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)


@app.route('/')
def index():
    """メインページ - 商品一覧"""
    conn = get_db()
    
    # フィルター処理
    filter_type = request.args.get('filter', 'all')
    search = request.args.get('search', '')
    
    query = 'SELECT * FROM merchandise'
    params = []
    conditions = []
    
    # 検索条件
    if search:
        conditions.append('(product_name LIKE ? OR store_name LIKE ? OR sales_platform LIKE ?)')
        params.extend([f'%{search}%', f'%{search}%', f'%{search}%'])
    
    # フィルター条件
    today = date.today()
    if filter_type == 'today':
        conditions.append('purchase_date = ?')
        params.append(today.strftime('%Y-%m-%d'))
    elif filter_type == 'yesterday':
        yesterday = today - timedelta(days=1)
        conditions.append('purchase_date = ?')
        params.append(yesterday.strftime('%Y-%m-%d'))
    elif filter_type == 'this_week':
        week_start = today - timedelta(days=today.weekday())
        conditions.append('purchase_date >= ?')
        params.append(week_start.strftime('%Y-%m-%d'))
    elif filter_type == 'this_month':
        month_start = today.replace(day=1)
        conditions.append('purchase_date >= ?')
        params.append(month_start.strftime('%Y-%m-%d'))
    elif filter_type == 'not_listed':
        conditions.append('is_listed = 0')
    elif filter_type == 'listed':
        conditions.append('is_listed = 1 AND (sold_date IS NULL OR sold_date = "")')
    elif filter_type == 'sold':
        conditions.append('sold_date IS NOT NULL AND sold_date != ""')
    
    if conditions:
        query += ' WHERE ' + ' AND '.join(conditions)
    
    query += ' ORDER BY id DESC'
    
    items = conn.execute(query, params).fetchall()
    
    # 統計情報
    stats = {
        'total': conn.execute('SELECT COUNT(*) FROM merchandise').fetchone()[0],
        'listed': conn.execute('SELECT COUNT(*) FROM merchandise WHERE is_listed = 1').fetchone()[0],
        'sold': conn.execute('SELECT COUNT(*) FROM merchandise WHERE sold_date IS NOT NULL AND sold_date != ""').fetchone()[0],
        'total_profit': conn.execute('''
            SELECT COALESCE(SUM(sale_price - purchase_price - shipping_cost - commission), 0)
            FROM merchandise WHERE sold_date IS NOT NULL AND sold_date != ""
        ''').fetchone()[0]
    }
    
    conn.close()
    
    return render_template('index.html', 
                          items=items, 
                          stats=stats, 
                          filter_type=filter_type,
                          search=search,
                          calculate_profit=calculate_profit,
                          calculate_profit_rate=calculate_profit_rate)


@app.route('/add', methods=['GET', 'POST'])
def add_item():
    """商品追加"""
    if request.method == 'POST':
        # 写真アップロード処理
        photo_path = None
        if 'photo' in request.files:
            file = request.files['photo']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}")
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                photo_path = filepath
        
        conn = get_db()
        conn.execute('''
            INSERT INTO merchandise (
                purchase_date, photo_path, product_name, store_name,
                purchase_price, payment_method, is_listed, listing_date,
                sold_date, sale_price, shipping_cost, sales_platform,
                commission, is_shipped, memo, customer_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            request.form.get('purchase_date') or None,
            photo_path,
            request.form.get('product_name'),
            request.form.get('store_name') or None,
            float(request.form.get('purchase_price') or 0),
            request.form.get('payment_method') or None,
            1 if request.form.get('is_listed') else 0,
            request.form.get('listing_date') or None,
            request.form.get('sold_date') or None,
            float(request.form.get('sale_price') or 0),
            float(request.form.get('shipping_cost') or 0),
            request.form.get('sales_platform') or None,
            float(request.form.get('commission') or 0),
            1 if request.form.get('is_shipped') else 0,
            request.form.get('memo') or None,
            int(request.form.get('customer_id')) if request.form.get('customer_id') else None
        ))
        conn.commit()
        conn.close()
        
        flash('商品を登録しました', 'success')
        return redirect(url_for('index'))
    
    conn = get_db()
    customers = conn.execute('SELECT id, name FROM customers ORDER BY name').fetchall()
    conn.close()
    return render_template('form.html', item=None, action='add', customers=customers)


@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit_item(id):
    """商品編集"""
    conn = get_db()
    
    if request.method == 'POST':
        # 写真アップロード処理
        photo_path = request.form.get('existing_photo')
        if 'photo' in request.files:
            file = request.files['photo']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}")
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                photo_path = filepath
        
        conn.execute('''
            UPDATE merchandise SET
                purchase_date = ?, photo_path = ?, product_name = ?, store_name = ?,
                purchase_price = ?, payment_method = ?, is_listed = ?, listing_date = ?,
                sold_date = ?, sale_price = ?, shipping_cost = ?, sales_platform = ?,
                commission = ?, is_shipped = ?, memo = ?, customer_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (
            request.form.get('purchase_date') or None,
            photo_path,
            request.form.get('product_name'),
            request.form.get('store_name') or None,
            float(request.form.get('purchase_price') or 0),
            request.form.get('payment_method') or None,
            1 if request.form.get('is_listed') else 0,
            request.form.get('listing_date') or None,
            request.form.get('sold_date') or None,
            float(request.form.get('sale_price') or 0),
            float(request.form.get('shipping_cost') or 0),
            request.form.get('sales_platform') or None,
            float(request.form.get('commission') or 0),
            1 if request.form.get('is_shipped') else 0,
            request.form.get('memo') or None,
            int(request.form.get('customer_id')) if request.form.get('customer_id') else None,
            id
        ))
        conn.commit()
        conn.close()
        
        flash('商品を更新しました', 'success')
        return redirect(url_for('index'))
    
    item = conn.execute('SELECT * FROM merchandise WHERE id = ?', (id,)).fetchone()
    conn.close()
    
    if not item:
        flash('商品が見つかりません', 'error')
        return redirect(url_for('index'))
    
    return render_template('form.html', item=item, action='edit')


@app.route('/delete/<int:id>', methods=['POST'])
def delete_item(id):
    """商品削除"""
    conn = get_db()
    conn.execute('DELETE FROM merchandise WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    
    flash('商品を削除しました', 'success')
    return redirect(url_for('index'))


@app.route('/view/<int:id>')
def view_item(id):
    """商品詳細表示"""
    conn = get_db()
    item = conn.execute('SELECT * FROM merchandise WHERE id = ?', (id,)).fetchone()
    conn.close()
    
    if not item:
        flash('商品が見つかりません', 'error')
        return redirect(url_for('index'))
    
    return render_template('view.html', 
                          item=item,
                          calculate_profit=calculate_profit,
                          calculate_profit_rate=calculate_profit_rate)


@app.route('/export')
def export_csv():
    """CSV出力"""
    conn = get_db()
    items = conn.execute('SELECT * FROM merchandise ORDER BY id DESC').fetchall()
    conn.close()
    
    # CSVデータ作成
    output = io.StringIO()
    writer = csv.writer(output)
    
    # ヘッダー
    headers = [
        '管理No', '仕入日', '商品名', '店舗名', '仕入額',
        '出品済', '出品日', '売却日', '売上金', '送料',
        '販売先', '手数料', '利益', '利益率', '発送済', 'メモ'
    ]
    writer.writerow(headers)
    
    # データ行
    for item in items:
        profit = calculate_profit(item)
        profit_rate = calculate_profit_rate(item)
        writer.writerow([
            item['id'],
            item['purchase_date'] or '',
            item['product_name'],
            item['store_name'] or '',
            item['purchase_price'],
            '✓' if item['is_listed'] else '',
            item['listing_date'] or '',
            item['sold_date'] or '',
            item['sale_price'],
            item['shipping_cost'],
            item['sales_platform'] or '',
            item['commission'],
            f'{profit:.0f}',
            f'{profit_rate:.1f}%',
            '✓' if item['is_shipped'] else '',
            item['memo'] or ''
        ])
    
    # レスポンス作成
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8-sig')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'売上データ_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    )


@app.route('/api/stats')
def api_stats():
    """統計情報API"""
    conn = get_db()
    stats = {
        'total': conn.execute('SELECT COUNT(*) FROM merchandise').fetchone()[0],
        'listed': conn.execute('SELECT COUNT(*) FROM merchandise WHERE is_listed = 1').fetchone()[0],
        'sold': conn.execute('SELECT COUNT(*) FROM merchandise WHERE sold_date IS NOT NULL AND sold_date != ""').fetchone()[0],
        'total_purchase': conn.execute('SELECT COALESCE(SUM(purchase_price), 0) FROM merchandise').fetchone()[0],
        'total_sales': conn.execute('SELECT COALESCE(SUM(sale_price), 0) FROM merchandise WHERE sold_date IS NOT NULL').fetchone()[0],
        'total_profit': conn.execute('''
            SELECT COALESCE(SUM(sale_price - purchase_price - shipping_cost - commission), 0)
            FROM merchandise WHERE sold_date IS NOT NULL AND sold_date != ""
        ''').fetchone()[0]
    }
    conn.close()
    return jsonify(stats)


# ============================================
# 顧客管理
# ============================================

@app.route('/customers')
def customers_list():
    """顧客一覧"""
    conn = get_db()
    
    # フィルター
    rank_filter = request.args.get('rank', 'all')
    search = request.args.get('search', '')
    
    customers = conn.execute('SELECT * FROM customers ORDER BY id DESC').fetchall()
    
    # 顧客に統計情報を追加
    customers_with_stats = []
    for customer in customers:
        stats = get_customer_stats(conn, customer['id'])
        customer_dict = dict(customer)
        customer_dict.update(stats)
        
        # フィルター適用
        if rank_filter != 'all' and stats['rank'] != rank_filter:
            continue
        if search and search.lower() not in customer['name'].lower():
            continue
            
        customers_with_stats.append(customer_dict)
    
    # ランク別集計
    rank_counts = {'platinum': 0, 'gold': 0, 'silver': 0, 'bronze': 0}
    for c in customers_with_stats:
        rank_counts[c['rank']] += 1
    
    conn.close()
    
    return render_template('customers.html',
                          customers=customers_with_stats,
                          rank_filter=rank_filter,
                          search=search,
                          rank_counts=rank_counts,
                          rank_names=RANK_NAMES,
                          rank_colors=RANK_COLORS,
                          rank_thresholds=RANK_THRESHOLDS)


@app.route('/customers/add', methods=['GET', 'POST'])
def add_customer():
    """顧客追加"""
    if request.method == 'POST':
        conn = get_db()
        conn.execute('''
            INSERT INTO customers (name, email, phone, address, memo)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            request.form.get('name'),
            request.form.get('email') or None,
            request.form.get('phone') or None,
            request.form.get('address') or None,
            request.form.get('memo') or None
        ))
        conn.commit()
        conn.close()
        
        flash('顧客を登録しました', 'success')
        return redirect(url_for('customers_list'))
    
    return render_template('customer_form.html', customer=None, action='add')


@app.route('/customers/edit/<int:id>', methods=['GET', 'POST'])
def edit_customer(id):
    """顧客編集"""
    conn = get_db()
    
    if request.method == 'POST':
        conn.execute('''
            UPDATE customers SET
                name = ?, email = ?, phone = ?, address = ?, memo = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (
            request.form.get('name'),
            request.form.get('email') or None,
            request.form.get('phone') or None,
            request.form.get('address') or None,
            request.form.get('memo') or None,
            id
        ))
        conn.commit()
        conn.close()
        
        flash('顧客情報を更新しました', 'success')
        return redirect(url_for('customers_list'))
    
    customer = conn.execute('SELECT * FROM customers WHERE id = ?', (id,)).fetchone()
    conn.close()
    
    if not customer:
        flash('顧客が見つかりません', 'error')
        return redirect(url_for('customers_list'))
    
    return render_template('customer_form.html', customer=customer, action='edit')


@app.route('/customers/view/<int:id>')
def view_customer(id):
    """顧客詳細"""
    conn = get_db()
    customer = conn.execute('SELECT * FROM customers WHERE id = ?', (id,)).fetchone()
    
    if not customer:
        flash('顧客が見つかりません', 'error')
        return redirect(url_for('customers_list'))
    
    # 顧客の購入履歴
    purchases = conn.execute('''
        SELECT * FROM merchandise 
        WHERE customer_id = ? AND sold_date IS NOT NULL AND sold_date != ""
        ORDER BY sold_date DESC
    ''', (id,)).fetchall()
    
    # 統計情報
    stats = get_customer_stats(conn, id)
    
    # 次のランクまでの金額
    current_rank = stats['rank']
    next_rank_info = None
    if current_rank == 'bronze':
        next_rank_info = {'rank': 'シルバー', 'needed': RANK_THRESHOLDS['silver'] - stats['total_purchase']}
    elif current_rank == 'silver':
        next_rank_info = {'rank': 'ゴールド', 'needed': RANK_THRESHOLDS['gold'] - stats['total_purchase']}
    elif current_rank == 'gold':
        next_rank_info = {'rank': 'プラチナ', 'needed': RANK_THRESHOLDS['platinum'] - stats['total_purchase']}
    
    conn.close()
    
    return render_template('customer_view.html',
                          customer=customer,
                          purchases=purchases,
                          stats=stats,
                          next_rank_info=next_rank_info,
                          rank_thresholds=RANK_THRESHOLDS,
                          calculate_profit=calculate_profit)


@app.route('/customers/delete/<int:id>', methods=['POST'])
def delete_customer(id):
    """顧客削除"""
    conn = get_db()
    # 関連する商品の顧客IDをクリア
    conn.execute('UPDATE merchandise SET customer_id = NULL WHERE customer_id = ?', (id,))
    conn.execute('DELETE FROM customers WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    
    flash('顧客を削除しました', 'success')
    return redirect(url_for('customers_list'))


@app.route('/api/customers')
def api_customers():
    """顧客一覧API（商品登録時の選択用）"""
    conn = get_db()
    customers = conn.execute('SELECT id, name FROM customers ORDER BY name').fetchall()
    conn.close()
    return jsonify([{'id': c['id'], 'name': c['name']} for c in customers])


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)


