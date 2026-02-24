from flask import Flask, render_template, request, redirect, session, url_for
from flask_bcrypt import Bcrypt
import pymysql
import plotly.express as px
from functools import wraps # Nécessaire pour créer un décorateur propre

app = Flask(__name__, template_folder="templates", static_folder="static")
# Attention : En production, ne laissez JAMAIS cela en clair dans le code. Utilisez des variables d'environnement (os.environ.get)
app.secret_key = "secretvraimentsupersecret1234"
bcrypt = Bcrypt(app)

def get_db():
    return pymysql.connect(
        host="db",
        user="root",
        password="motdepasserootrobuste1234",
        database="mes4",
        cursorclass=pymysql.cursors.DictCursor
    )

# ---------------------------------------------------------
# DÉCORATEUR DE SÉCURITÉ : Centralise la vérification
# ---------------------------------------------------------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user" not in session:
            # Redirige proprement vers la fonction login, pas juste une URL codée en dur
            return redirect(url_for('login')) 
        return f(*args, **kwargs)
    return decorated_function

# ---------------------------------------------------------
# ROUTES
# ---------------------------------------------------------

@app.route("/", methods=["GET", "POST"])
def login():
    # Si l'utilisateur est DÉJÀ connecté, on l'envoie direct sur le dashboard
    if "user" in session:
        return redirect(url_for('home'))

    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        db = get_db()
        try:
            with db.cursor() as cursor:
                cursor.execute("SELECT * FROM users WHERE username=%s", (username,))
                user = cursor.fetchone()

            if user and bcrypt.check_password_hash(user["password_hash"], password):
                session["user"] = username
                return redirect(url_for('home'))
            else:
                # Il FAUT gérer le cas d'échec pour prévenir l'utilisateur
                return render_template("login.html", error="Identifiants ou mot de passe incorrects")
        finally:
            # CRUCIAL : La connexion doit être fermée, même si le code plante avant
            db.close()

    return render_template("login.html")

# C'est cette route qui manquait pour "tuer" la session
@app.route("/logout")
def logout():
    session.pop("user", None) # Supprime l'utilisateur de la session
    return redirect(url_for('login'))

@app.route("/home")
@login_required # Remplace vos 2 lignes de if/redirect
def home():
    db = get_db()
    try:
        with db.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS total FROM tblfinorder;")
            data = cursor.fetchall()

        valeurs = [row["total"] for row in data]
        labels = ["Ordres totaux"]

        fig = px.bar(
            x=labels,
            y=valeurs,
            title="Nombre total d'ordres (test)"
        )
        graph_html = fig.to_html(full_html=False)

        return render_template("home.html", graph=graph_html)
    finally:
        db.close() # Fermeture obligatoire

@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    try:
        with db.cursor() as cursor:
            cursor.execute("""
                SELECT YEAR(End) AS annee, COUNT(*) AS total
                FROM tblfinorder
                WHERE End IS NOT NULL
                GROUP BY YEAR(End)
                ORDER BY annee;
            """)
            data = cursor.fetchall()

        annees = [str(row["annee"]) for row in data]
        totaux = [row["total"] for row in data]

        fig = px.bar(
            x=annees,
            y=totaux,
            labels={"x": "Année", "y": "Nombre d'ordres"},
            title="Nombre d'ordres finis par année"
        )
        graph_html = fig.to_html(full_html=False)

        return render_template("dashboard.html", graph=graph_html)
    finally:
        db.close() # Fermeture obligatoire

# Bonne pratique d'exécution Python
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)