import os
from flask import Flask, render_template, redirect, url_for, g
from flask_login import LoginManager, current_user
from config import Config
from models import init_db, close_db, get_db, User, get_school_settings
from utils.helpers import format_currency

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize database
    with app.app_context():
        init_db(app)

    # Database teardown
    app.teardown_appcontext(close_db)

    # Initialize Flask-Login
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = "Please sign in to access this page."
    login_manager.login_message_category = "warning"

    @login_manager.user_loader
    def load_user(user_id):
        return User.get_by_id(int(user_id))

    # Context processors for global template variables
    @app.context_processor
    def inject_global_data():
        settings = get_school_settings()
        return {
            'school_settings': settings,
            'format_currency': lambda amt: format_currency(amt, settings.get('currency_symbol', '$'))
        }

    # Register blueprints
    from auth import auth_bp
    from routes.admin import admin_bp
    from routes.student import student_bp
    from routes.teacher import teacher_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(teacher_bp)

    @app.route('/')
    def index():
        if current_user.is_authenticated:
            if current_user.role == 'admin':
                return redirect(url_for('admin.dashboard'))
            elif current_user.role == 'student':
                return redirect(url_for('student.dashboard'))
            elif current_user.role == 'teacher':
                return redirect(url_for('teacher.dashboard'))

        # Check if first-run setup is required
        db = get_db()
        admin_count = db.execute("SELECT COUNT(*) as cnt FROM users WHERE role = 'admin';").fetchone()['cnt']
        if admin_count == 0:
            return redirect(url_for('auth.setup'))
        return redirect(url_for('auth.login'))

    # Custom Error Handlers
    @app.errorhandler(403)
    def forbidden_error(e):
        return render_template('errors/403.html', settings=get_school_settings()), 403

    @app.errorhandler(404)
    def not_found_error(e):
        return render_template('errors/404.html', settings=get_school_settings()), 404

    @app.errorhandler(500)
    def internal_error(e):
        return render_template('errors/500.html', settings=get_school_settings()), 500

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5000, debug=True)
