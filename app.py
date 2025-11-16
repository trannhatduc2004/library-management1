from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///library.db')
if app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgres://'):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    borrows = db.relationship('Borrow', backref='user', lazy=True)

class Book(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    author = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50))
    total_copies = db.Column(db.Integer, default=1)
    available_copies = db.Column(db.Integer, default=1)
    borrows = db.relationship('Borrow', backref='book', lazy=True)

class Borrow(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    book_id = db.Column(db.Integer, db.ForeignKey('book.id'), nullable=False)
    borrow_date = db.Column(db.DateTime, default=datetime.utcnow)
    due_date = db.Column(db.DateTime, nullable=False)
    return_date = db.Column(db.DateTime)
    status = db.Column(db.String(20), default='borrowed')  # borrowed, returned

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Routes
@app.route('/')
def index():
    books = Book.query.all()
    return render_template('index.html', books=books)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Tên đăng nhập hoặc mật khẩu không đúng', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if User.query.filter_by(username=username).first():
            flash('Tên đăng nhập đã tồn tại', 'danger')
            return redirect(url_for('register'))
        
        user = User(username=username, password=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()
        flash('Đăng ký thành công! Vui lòng đăng nhập', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.is_admin:
        total_books = Book.query.count()
        total_users = User.query.count()
        active_borrows = Borrow.query.filter_by(status='borrowed').count()
        overdue = Borrow.query.filter(
            Borrow.status == 'borrowed',
            Borrow.due_date < datetime.utcnow()
        ).count()
        
        stats = {
            'total_books': total_books,
            'total_users': total_users,
            'active_borrows': active_borrows,
            'overdue': overdue
        }
        return render_template('admin_dashboard.html', stats=stats)
    else:
        borrows = Borrow.query.filter_by(user_id=current_user.id).order_by(Borrow.borrow_date.desc()).all()
        return render_template('user_dashboard.html', borrows=borrows)

@app.route('/books')
def books():
    search = request.args.get('search', '')
    category = request.args.get('category', '')
    
    query = Book.query
    if search:
        query = query.filter(
            db.or_(
                Book.title.ilike(f'%{search}%'),
                Book.author.ilike(f'%{search}%')
            )
        )
    if category:
        query = query.filter_by(category=category)
    
    books = query.all()
    categories = db.session.query(Book.category).distinct().all()
    return render_template('books.html', books=books, categories=[c[0] for c in categories])

@app.route('/books/add', methods=['GET', 'POST'])
@login_required
def add_book():
    if not current_user.is_admin:
        flash('Chỉ admin mới có quyền thêm sách', 'danger')
        return redirect(url_for('books'))
    
    if request.method == 'POST':
        book = Book(
            title=request.form.get('title'),
            author=request.form.get('author'),
            category=request.form.get('category'),
            total_copies=int(request.form.get('copies', 1)),
            available_copies=int(request.form.get('copies', 1))
        )
        db.session.add(book)
        db.session.commit()
        flash('Thêm sách thành công', 'success')
        return redirect(url_for('books'))
    return render_template('add_book.html')

@app.route('/books/<int:book_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_book(book_id):
    if not current_user.is_admin:
        flash('Chỉ admin mới có quyền sửa sách', 'danger')
        return redirect(url_for('books'))
    
    book = Book.query.get_or_404(book_id)
    if request.method == 'POST':
        book.title = request.form.get('title')
        book.author = request.form.get('author')
        book.category = request.form.get('category')
        new_copies = int(request.form.get('copies'))
        diff = new_copies - book.total_copies
        book.total_copies = new_copies
        book.available_copies += diff
        db.session.commit()
        flash('Cập nhật sách thành công', 'success')
        return redirect(url_for('books'))
    return render_template('edit_book.html', book=book)

@app.route('/books/<int:book_id>/delete', methods=['POST'])
@login_required
def delete_book(book_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    book = Book.query.get_or_404(book_id)
    db.session.delete(book)
    db.session.commit()
    flash('Xóa sách thành công', 'success')
    return redirect(url_for('books'))

@app.route('/borrow/<int:book_id>', methods=['POST'])
@login_required
def borrow_book(book_id):
    book = Book.query.get_or_404(book_id)
    
    if book.available_copies <= 0:
        flash('Sách đã hết', 'warning')
        return redirect(url_for('books'))
    
    # Check if user already borrowed this book
    existing = Borrow.query.filter_by(
        user_id=current_user.id,
        book_id=book_id,
        status='borrowed'
    ).first()
    
    if existing:
        flash('Bạn đã mượn sách này rồi', 'warning')
        return redirect(url_for('books'))
    
    borrow = Borrow(
        user_id=current_user.id,
        book_id=book_id,
        due_date=datetime.utcnow() + timedelta(days=14)
    )
    book.available_copies -= 1
    db.session.add(borrow)
    db.session.commit()
    flash('Mượn sách thành công', 'success')
    return redirect(url_for('dashboard'))

@app.route('/return/<int:borrow_id>', methods=['POST'])
@login_required
def return_book(borrow_id):
    borrow = Borrow.query.get_or_404(borrow_id)
    
    if borrow.user_id != current_user.id and not current_user.is_admin:
        flash('Không có quyền', 'danger')
        return redirect(url_for('dashboard'))
    
    borrow.status = 'returned'
    borrow.return_date = datetime.utcnow()
    borrow.book.available_copies += 1
    db.session.commit()
    flash('Trả sách thành công', 'success')
    return redirect(url_for('dashboard'))

@app.route('/api/stats')
@login_required
def api_stats():
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    # Most borrowed books
    most_borrowed = db.session.query(
        Book.title,
        db.func.count(Borrow.id).label('count')
    ).join(Borrow).group_by(Book.id).order_by(db.desc('count')).limit(5).all()
    
    # Most active users
    active_users = db.session.query(
        User.username,
        db.func.count(Borrow.id).label('count')
    ).join(Borrow).group_by(User.id).order_by(db.desc('count')).limit(5).all()
    
    return jsonify({
        'most_borrowed': [{'title': b[0], 'count': b[1]} for b in most_borrowed],
        'active_users': [{'username': u[0], 'count': u[1]} for u in active_users]
    })

@app.cli.command()
def init_db():
    """Initialize database with sample data"""
    db.create_all()
    
    # Create admin user
    if not User.query.filter_by(username='admin').first():
        admin = User(
            username='admin',
            password=generate_password_hash('admin123'),
            is_admin=True
        )
        db.session.add(admin)
    
    # Create sample books
    if Book.query.count() == 0:
        books = [
            Book(title='Đắc Nhân Tâm', author='Dale Carnegie', category='Kỹ năng sống', total_copies=5, available_copies=5),
            Book(title='Sapiens', author='Yuval Noah Harari', category='Lịch sử', total_copies=3, available_copies=3),
            Book(title='Nhà Giả Kim', author='Paulo Coelho', category='Văn học', total_copies=4, available_copies=4),
            Book(title='Tuổi Trẻ Đáng Giá Bao Nhiêu', author='Rosie Nguyễn', category='Kỹ năng sống', total_copies=3, available_copies=3),
        ]
        db.session.add_all(books)
    
    db.session.commit()
    print('Database initialized!')

def init_database():
    """Initialize database with tables and sample data"""
    with app.app_context():
        try:
            # Create all tables
            db.create_all()
            print('✅ Tables created')
            
            # Create admin user if not exists
            if not User.query.filter_by(username='admin').first():
                admin = User(
                    username='admin',
                    password=generate_password_hash('admin123'),
                    is_admin=True
                )
                db.session.add(admin)
                db.session.commit()
                print('✅ Admin user created')
            
            # Create sample books if not exists
            if Book.query.count() == 0:
                books = [
                    Book(title='Đắc Nhân Tâm', author='Dale Carnegie', category='Kỹ năng sống', total_copies=5, available_copies=5),
                    Book(title='Sapiens', author='Yuval Noah Harari', category='Lịch sử', total_copies=3, available_copies=3),
                    Book(title='Nhà Giả Kim', author='Paulo Coelho', category='Văn học', total_copies=4, available_copies=4),
                    Book(title='Tuổi Trẻ Đáng Giá Bao Nhiêu', author='Rosie Nguyễn', category='Kỹ năng sống', total_copies=3, available_copies=3),
                ]
                db.session.add_all(books)
                db.session.commit()
                print('✅ Sample books added')
                
            print('✅ Database initialization complete!')
        except Exception as e:
            print(f'⚠️ Database initialization error: {e}')
            # Don't raise error, app can still start

# Initialize database on import (production)
init_database()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))