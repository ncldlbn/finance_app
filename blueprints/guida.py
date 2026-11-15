"""Pagina Guida: la logica del programma e come usarlo. Contenuto statico (nessun dato dell'utente)."""
from flask import Blueprint, render_template

guida_bp = Blueprint('guida', __name__)


@guida_bp.route('/guida')
def index():
    return render_template('guida.html')
