import os
import json # Importar json
from datetime import datetime
from typing import Optional, Tuple, Dict



import dotenv
from flask import (Flask, flash, redirect, render_template, request,
                   send_from_directory, url_for)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

# Importar el procesador y la categoría
from processor import OrthoPhotoProcessor, ProcessorError, NutrientCategory, all_nutrients_info

dotenv.load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'default_secret_key_change_me')

# --- Configuración (igual que antes) ---
UPLOAD_FOLDER = 'uploads'
PROCESSED_FOLDER = 'processed_images'
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'tiff', 'tif'}
MAX_CONTENT_LENGTH = 10240 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['PROCESSED_FOLDER'] = PROCESSED_FOLDER
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///photos.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
db = SQLAlchemy(app)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['PROCESSED_FOLDER'], exist_ok=True)


# --- Modelo de Base de Datos (Añadir campo nutrient_assessment) ---
class Photo(db.Model):
    """Modelo de base de datos para almacenar información de las fotos."""
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False, unique=True)
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    file_path = db.Column(db.String(300), nullable=False)
    is_processed = db.Column(db.Boolean, default=False)
    processing_date = db.Column(db.DateTime, nullable=True)
    vi_image = db.Column(db.String(255), nullable=True)
    gli_image = db.Column(db.String(255), nullable=True)
    vari_image = db.Column(db.String(255), nullable=True)
    # Campo para guardar el resultado del análisis como JSON string
    nutrient_assessment = db.Column(db.Text, nullable=True) # Usar db.JSON si el backend lo soporta

    def __repr__(self) -> str:
        return f'<Photo {self.filename}>'

    # Propiedad para obtener la evaluación parseada (si se almacena como texto)
    @property
    def assessment_data(self) -> Optional[Dict]:
        if self.nutrient_assessment:
            try:
                return json.loads(self.nutrient_assessment)
            except json.JSONDecodeError:
                app.logger.error(f"Error decodificando JSON de assessment para foto ID {self.id}")
                return None
        return None


def allowed_file(filename: str) -> bool:
    """
    Valida si el archivo tiene una extensión permitida.

    Args:
        filename: El nombre del archivo a verificar.

    Returns:
        True si la extensión es válida, False en caso contrario.
    """
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# --- Rutas de la Aplicación ---
@app.route('/')
def home():
    """Muestra la página principal con la lista de fotos subidas."""
    try:
        photos = Photo.query.order_by(Photo.upload_date.desc()).all()
    except Exception as e:
        app.logger.error(f"Error al consultar fotos: {e}")
        flash("Error al cargar la lista de fotos.", "error")
        photos = []
    # Pasar la configuración del tamaño máximo a la plantilla
    return render_template('index.html', photos=photos, config=app.config)

@app.route('/upload', methods=['POST'])
def upload_file():
    """Gestiona la subida de nuevos archivos de imagen."""
    if 'file' not in request.files:
        flash('No se seleccionó ningún archivo.', 'warning')
        return redirect(url_for('home'))

    file = request.files['file']

    if file.filename == '':
        flash('Nombre de archivo vacío.', 'warning')
        return redirect(url_for('home'))

    if not file or not allowed_file(file.filename):
        flash(f'Formato no permitido. Se permiten: {", ".join(ALLOWED_EXTENSIONS)}', 'warning')
        return redirect(url_for('home'))

    try:
        # Verificar tamaño máximo antes de guardar
        # Nota: Werkzeug > 2.1 maneja esto mejor, pero una verificación explícita es segura
        if request.content_length and request.content_length > app.config['MAX_CONTENT_LENGTH']:
             # Lanzar la excepción correcta que Flask capturará
             raise RequestEntityTooLarge()

        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        if os.path.exists(file_path):
             flash(f'Ya existe un archivo llamado {filename}. Por favor, renómbrelo o elimine el existente.', 'error')
             return redirect(url_for('home'))

        file.save(file_path)

        new_photo = Photo(filename=filename, file_path=file_path)
        db.session.add(new_photo)
        db.session.commit()

        flash(f'Archivo "{filename}" subido correctamente.', 'success')

    except RequestEntityTooLarge:
        flash(f'El archivo es demasiado grande. El límite es {app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)} MB.', 'error')
        return redirect(url_for('home')) # Redirigir en caso de error de tamaño
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error al subir archivo '{getattr(file, 'filename', 'N/A')}': {e}")
        flash(f'Error al subir el archivo: {str(e)}', 'error')

    return redirect(url_for('home'))

@app.route('/view/original/<int:photo_id>')
def view_original_image(photo_id: int):
    """Muestra la imagen original subida."""
    photo = db.session.get(Photo, photo_id)
    if not photo:
        flash("Foto no encontrada.", "error")
        return redirect(url_for('home')), 404
    # Asegurarse que el archivo existe antes de enviarlo
    if not os.path.exists(photo.file_path):
        flash(f"Archivo original '{photo.filename}' no encontrado en el servidor.", "error")
        return redirect(url_for('home')), 404
    return send_from_directory(app.config['UPLOAD_FOLDER'], photo.filename)

@app.route('/view/processed/<filename>')
def view_processed_image(filename: str):
    """Muestra una imagen procesada específica por su nombre de archivo."""
    safe_filename = secure_filename(filename)
    if safe_filename != filename:
        flash("Nombre de archivo inválido.", "error")
        return redirect(url_for('home')), 400
    file_path = os.path.join(app.config['PROCESSED_FOLDER'], safe_filename)
    if not os.path.exists(file_path):
        flash(f"Archivo procesado '{safe_filename}' no encontrado.", "error")
        return redirect(url_for('home')), 404
    return send_from_directory(app.config['PROCESSED_FOLDER'], safe_filename)

@app.route('/delete/<int:photo_id>', methods=['POST'])
def delete_image(photo_id: int):
    """Elimina una imagen y sus archivos procesados asociados."""
    photo = db.session.get(Photo, photo_id)
    if not photo:
        flash("Foto no encontrada.", "error")
        return redirect(url_for('home')), 404

    original_filename = photo.filename
    files_to_delete = []
    if photo.file_path and os.path.exists(photo.file_path): # Solo añadir si existe
        files_to_delete.append(photo.file_path)

    # Añadir rutas completas de archivos procesados si existen
    processed_filenames = [photo.vi_image, photo.gli_image, photo.vari_image]
    for proc_filename in processed_filenames:
        if proc_filename:
            proc_path = os.path.join(app.config['PROCESSED_FOLDER'], proc_filename)
            if os.path.exists(proc_path):
                files_to_delete.append(proc_path)

    try:
        deleted_files_count = 0
        for file_path in files_to_delete:
            try:
                os.remove(file_path)
                deleted_files_count += 1
            except OSError as e:
                app.logger.warning(f"No se pudo eliminar el archivo {file_path}: {e}")

        db.session.delete(photo)
        db.session.commit()
        flash(f'Archivo "{original_filename}" y sus derivados ({deleted_files_count-1} procesados) eliminados correctamente.', 'success')

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error al eliminar foto ID {photo_id}: {e}")
        flash(f'Error al eliminar el archivo: {str(e)}', 'error')

    return redirect(url_for('home'))


@app.route('/download/<int:photo_id>')
def download_image(photo_id: int):
    """Permite descargar la imagen original."""
    photo = db.session.get(Photo, photo_id)
    if not photo:
        flash("Foto no encontrada.", "error")
        return redirect(url_for('home')), 404
    try:
        # Verificar existencia antes de intentar enviar
        if not os.path.exists(photo.file_path):
             raise FileNotFoundError
        return send_from_directory(
            app.config['UPLOAD_FOLDER'],
            photo.filename,
            as_attachment=True
        )
    except FileNotFoundError:
         flash(f'Archivo original "{photo.filename}" no encontrado en el servidor.', 'error')
         return redirect(url_for('home')), 404

@app.route('/process/<int:photo_id>', methods=['POST'])
def process_image(photo_id: int):
    """Inicia el procesamiento y evaluación de una imagen."""
    photo = db.session.get(Photo, photo_id)
    # ... (verificaciones de foto y archivo original) ...

    try:
        # Crear instancia del procesador
        processor = OrthoPhotoProcessor(
            image_path=photo.file_path,
            processed_folder=app.config['PROCESSED_FOLDER']
        )

        # --- CORRECCIÓN AQUÍ ---
        # En lugar de guardar individualmente accediendo a atributos inexistentes...
        # Llama al método que guarda todos los índices calculados
        base_filename = os.path.splitext(photo.filename)[0]
        saved_image_files = processor.save_all_processed_images(photo.id, base_filename)
        # 'saved_image_files' será un dict como: {'VI': 'vi_3_base.png', 'GLI': 'gli_3_base.png', ...}

        # Evaluación Nutricional (esto probablemente ya usa los índices calculados internamente)
        assessment_result = processor.assess_potential_nutrient_status()
        assessment_json = json.dumps(assessment_result, ensure_ascii=False)

        # Actualizar el objeto photo usando el diccionario de archivos guardados
        photo.is_processed = True
        photo.processing_date = datetime.utcnow()
        # Usar .get() para evitar errores si un índice no se calculó/guardó
        photo.vi_image = saved_image_files.get('VI')
        photo.gli_image = saved_image_files.get('GLI')
        photo.vari_image = saved_image_files.get('VARI')
        # Si añades soporte multiespectral, harías lo mismo para NDVI, etc.
        # photo.ndvi_image = saved_image_files.get('NDVI')
        photo.nutrient_assessment = assessment_json
        db.session.commit()

        flash(f'Imagen "{photo.filename}" procesada y evaluada correctamente.', 'success')
        return redirect(url_for('show_processing_results', photo_id=photo.id))

    except ProcessorError as e:
        db.session.rollback()
        app.logger.error(f"Error de procesamiento para foto ID {photo_id}: {e}")
        flash(f'Error al procesar la imagen: {str(e)}', 'error')
    except Exception as e:
        db.session.rollback()
        # Loggear el traceback completo para depuración
        app.logger.error(f"Error inesperado procesando foto ID {photo_id}:", exc_info=True)
        flash(f'Error inesperado durante el procesamiento.', 'error') # Mensaje genérico

    return redirect(url_for('home'))


@app.route('/results/<int:photo_id>')
def show_processing_results(photo_id: int):
    """Muestra los resultados del procesamiento y la evaluación."""
    photo = db.session.get(Photo, photo_id)
    if not photo:
        flash("Foto no encontrada.", "error")
        return redirect(url_for('home')), 404

    if not photo.is_processed:
        flash(f'La imagen "{photo.filename}" aún no ha sido procesada.', 'warning')
        return redirect(url_for('home'))

    # Obtener URLs de imágenes procesadas (igual que antes)
    image_urls = {}
    expected_files = {'vi': photo.vi_image, 'gli': photo.gli_image, 'vari': photo.vari_image}
    processed_files_exist = True
    for key, filename in expected_files.items():
        if filename:
             file_path = os.path.join(app.config['PROCESSED_FOLDER'], filename)
             if os.path.exists(file_path):
                 image_urls[key] = url_for('view_processed_image', filename=filename)
             else:
                 app.logger.warning(f"Archivo procesado {filename} para foto ID {photo_id} no encontrado.")
                 image_urls[key] = None
                 processed_files_exist = False
        else:
             image_urls[key] = None # No se esperaba archivo

    if not processed_files_exist:
         flash('Algunos archivos de imagen procesados no se encontraron. Puede ser necesario reprocesar.', 'warning')

    # Obtener datos de la evaluación desde la propiedad del modelo
    assessment = photo.assessment_data or {}
    if not isinstance(assessment, dict):
        assessment = {}   # Fallback si no es un diccionario

    # Pasar toda la información necesaria a la plantilla
    return render_template(
        'processing_results.html',
        photo=photo,
        image_urls=image_urls,
        assessment=assessment, # Pasar el diccionario de evaluación parseado
        NutrientCategory=NutrientCategory,
        all_nutrients_info=all_nutrients_info # Pasar la info general de nutrientes
    )

# --- Inicialización y Ejecución (igual que antes) ---
def create_database(app_instance):
    """Crea las tablas de la base de datos si no existen."""
    with app_instance.app_context():
        print("Creando tablas de la base de datos (si no existen)...")
        db.create_all()
        print("Tablas verificadas/creadas.")

@app.errorhandler(413)
@app.errorhandler(RequestEntityTooLarge)
def handle_request_entity_too_large(e):
    """Manejador de error para archivos demasiado grandes."""
    flash(f'El archivo es demasiado grande. El límite es {app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)} MB.', 'error')
    return redirect(request.referrer or url_for('home'))


if __name__ == '__main__':
    create_database(app)
    app.run(debug=True, host='0.0.0.0')
