import os
import threading
import queue
import sqlite3
import time
import uuid
from flask import Flask, render_template, request, redirect, url_for, jsonify, send_from_directory
from werkzeug.utils import secure_filename
import numpy as np
import soundfile as sf

# Import existing logic
from extractor import Extractor

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['AUDIO_FOLDER'] = 'audio'
app.config['DATA_FOLDER'] = 'data'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['AUDIO_FOLDER'], exist_ok=True)
os.makedirs(app.config['DATA_FOLDER'], exist_ok=True)

# Database setup
DB_PATH = os.path.join(app.config['DATA_FOLDER'], 'app.db')

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # stored_filename is the file on disk in uploads/
    # audio_filename is the file on disk in audio/
    c.execute('''CREATE TABLE IF NOT EXISTS jobs
                 (id TEXT PRIMARY KEY, filename TEXT, stored_filename TEXT, 
                  audio_filename TEXT, status TEXT, created_at REAL)''')
    conn.commit()
    conn.close()

init_db()

# Job Queue
job_queue = queue.Queue()

def process_audio_job():
    # Initialize Reader once
    print("Worker: Initializing Reader...")
    try:
        from reader_kokoro import Reader
        reader = Reader()
        print("Worker: Reader initialized.")
    except Exception as e:
        print(f"Worker: Failed to initialize reader: {e}")
        return

    while True:
        job_id = job_queue.get()
        if job_id is None:
            break
        
        print(f"Worker: Processing job {job_id}")
        
        # Get job details
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT stored_filename FROM jobs WHERE id=?", (job_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            job_queue.task_done()
            continue
            
        stored_filename = row[0]
        original_path = os.path.join(app.config['UPLOAD_FOLDER'], stored_filename)
        
        # Update status to processing
        c.execute("UPDATE jobs SET status='processing' WHERE id=?", (job_id,))
        conn.commit()
        
        try:
            # Extraction
            extractor = Extractor(original_path)
            title, abstract, sections = extractor.extract()
            
            if not title and not sections:
                # If it's a text file, extractor might return empty title but have sections
                # Extractor logic handles this now.
                pass

            # Audio Generation Logic
            full_audio_buffer = []
            
            def process_text_chunk(text_chunk):
                if not text_chunk or not text_chunk.strip():
                    return
                # Use the reader instance
                generator = reader.pipeline(text_chunk, voice='af_heart')
                for _, _, audio in generator:
                    full_audio_buffer.append(audio)

            # Title
            if title:
                process_text_chunk(f"Title: {title}.")
                full_audio_buffer.append(np.zeros(int(24000 * 0.5)))

            # Abstract
            if abstract:
                process_text_chunk("Abstract.")
                full_audio_buffer.append(np.zeros(int(24000 * 0.5)))
                process_text_chunk(abstract)
                full_audio_buffer.append(np.zeros(int(24000 * 0.5)))

            # Sections
            for section in sections:
                sec_title = section['section-title']
                sec_text = section['section-text']
                
                if sec_title:
                    process_text_chunk(f"Section: {sec_title}.")
                    full_audio_buffer.append(np.zeros(int(24000 * 0.5)))
                
                if sec_text:
                    process_text_chunk(sec_text)
                
                full_audio_buffer.append(np.zeros(int(24000 * 0.5)))

            if full_audio_buffer:
                combined_audio = np.concatenate(full_audio_buffer)
                output_filename = f"{job_id}.wav"
                output_path = os.path.join(app.config['AUDIO_FOLDER'], output_filename)
                sf.write(output_path, combined_audio, 24000)
                
                c.execute("UPDATE jobs SET status='completed', audio_filename=? WHERE id=?", 
                          (output_filename, job_id))
            else:
                print(f"Worker: No audio generated for job {job_id}")
                c.execute("UPDATE jobs SET status='failed' WHERE id=?", (job_id,))

        except Exception as e:
            print(f"Worker: Job {job_id} failed: {e}")
            import traceback
            traceback.print_exc()
            c.execute("UPDATE jobs SET status='failed' WHERE id=?", (job_id,))
        
        conn.commit()
        conn.close()
        job_queue.task_done()

# Start worker thread
worker_thread = threading.Thread(target=process_audio_job, daemon=True)
worker_thread.start()

@app.route('/')
def index():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM jobs ORDER BY created_at ASC")
    jobs = c.fetchall()
    conn.close()
    return render_template('index.html', jobs=jobs)

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return redirect(request.url)
    file = request.files['file']
    if file.filename == '':
        return redirect(request.url)
    
    if file:
        filename = secure_filename(file.filename)
        job_id = str(uuid.uuid4())
        stored_filename = f"{job_id}_{filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], stored_filename)
        file.save(file_path)
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO jobs (id, filename, stored_filename, status, created_at) VALUES (?, ?, ?, ?, ?)",
                  (job_id, filename, stored_filename, 'queued', time.time()))
        conn.commit()
        conn.close()
        
        job_queue.put(job_id)
        
        return redirect(url_for('index'))

@app.route('/status/<job_id>')
def job_status(job_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT status, audio_filename FROM jobs WHERE id=?", (job_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return jsonify({'status': row[0], 'audio_filename': row[1]})
    return jsonify({'status': 'unknown'}), 404

@app.route('/clear_history', methods=['POST'])
def clear_history():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Get all files to delete them from disk
    c.execute("SELECT stored_filename, audio_filename FROM jobs")
    files = c.fetchall()
    
    for stored_filename, audio_filename in files:
        if stored_filename:
            try:
                os.remove(os.path.join(app.config['UPLOAD_FOLDER'], stored_filename))
            except OSError:
                pass
        if audio_filename:
            try:
                os.remove(os.path.join(app.config['AUDIO_FOLDER'], audio_filename))
            except OSError:
                pass

    # Clear the database
    c.execute("DELETE FROM jobs")
    conn.commit()
    conn.close()
    
    return redirect(url_for('index'))

@app.route('/uploads/<path:filename>')
def download_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/audio/<path:filename>')
def download_audio(filename):
    return send_from_directory(app.config['AUDIO_FOLDER'], filename)

if __name__ == '__main__':
    # Note: debug=True reloads the server, which might restart the worker thread.
    # For production, use a proper WSGI server and separate worker process.
    # For this demo, it's fine, but existing jobs in queue might be lost on reload.
    # The DB state persists though.
    app.run(host='0.0.0.0', debug=True, port=5000, use_reloader=False) 
