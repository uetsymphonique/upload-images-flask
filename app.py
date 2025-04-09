from flask import Flask, request, redirect, render_template, url_for, flash
import mysql.connector
from google.cloud import storage
from google.api_core.exceptions import NotFound
import os
import uuid
from contextlib import contextmanager
import configparser

app = Flask(__name__)

# Load configuration from config.ini
config = configparser.ConfigParser()
config_path = '/var/www/upload-images-flask/config.ini'  # Absolute path to config.ini
config.read(config_path)

# Set Flask secret key from config.ini
app.secret_key = config['app']['secret_key']

# Database connection
db = mysql.connector.connect(
    host=config['database']['host'],
    user=config['database']['user'],
    password=config['database']['password'],
    database=config['database']['database']
)

# Google Cloud Storage
storage_client = storage.Client()
bucket = storage_client.bucket(config['storage']['bucket'])

# Context manager for database cursor
@contextmanager
def get_cursor():
    cursor = db.cursor()
    try:
        yield cursor
    finally:
        cursor.close()

# Home page: List all images (Read)
@app.route('/')
def index():
    with get_cursor() as cursor:
        cursor.execute("SELECT id, filename, title, upload_time FROM images")
        images = cursor.fetchall()
    image_data = []
    for img in images:
        blob = bucket.blob(img[1])
        image_data.append({
            'id': img[0],
            'filename': img[1],
            'title': img[2] if img[2] else img[1],  # Use filename as fallback if title is NULL
            'upload_time': img[3],
            'url': blob.public_url
        })
    return render_template('index.html', images=image_data)

# Upload handler: Add a new image (Create)
@app.route('/upload', methods=['POST'])
def upload_image():
    image = request.files['image']
    title = request.form.get('title', image.filename)  # Use filename as default title if none provided
    if not image or not image.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
        flash("Invalid image file!", "danger")
        return redirect(url_for('index'))
    unique_filename = f"{uuid.uuid4().hex}_{image.filename}"
    blob = bucket.blob(unique_filename)
    try:
        blob.upload_from_file(image)
        with get_cursor() as cursor:
            cursor.execute("INSERT INTO images (filename, title) VALUES (%s, %s)", (unique_filename, title))
            db.commit()
        flash("Image uploaded successfully!", "success")
    except Exception as e:
        flash(f"Error uploading image: {str(e)}", "danger")
        db.rollback()
    return redirect(url_for('index'))

# Update page: Edit an image’s title (Update)
@app.route('/update/<int:id>', methods=['GET', 'POST'])
def update_image(id):
    with get_cursor() as cursor:
        if request.method == 'POST':
            new_title = request.form['title']
            if not new_title:
                flash("Title cannot be empty!", "danger")
                return redirect(url_for('update_image', id=id))
            cursor.execute("UPDATE images SET title = %s WHERE id = %s", (new_title, id))
            db.commit()
            flash("Image title updated successfully!", "success")
            return redirect(url_for('index'))
        cursor.execute("SELECT id, filename, title FROM images WHERE id = %s", (id,))
        image = cursor.fetchone()
    if image:
        return render_template('update.html', image=image)
    else:
        flash("Image not found!", "danger")
        return redirect(url_for('index'))

# Delete an image (Delete)
@app.route('/delete/<int:id>')
def delete_image(id):
    with get_cursor() as cursor:
        cursor.execute("SELECT filename FROM images WHERE id = %s", (id,))
        result = cursor.fetchone()
        if result:
            filename = result[0]
            blob = bucket.blob(filename)
            try:
                blob.delete()
                flash(f"Image '{filename}' deleted from storage.", "success")
            except NotFound:
                flash(f"Image '{filename}' not found in storage.", "warning")
            cursor.execute("DELETE FROM images WHERE id = %s", (id,))
            db.commit()
            flash("Image removed from database.", "success")
        else:
            flash("Image not found in database.", "danger")
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80)
