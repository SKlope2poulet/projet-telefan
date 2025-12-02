from flask import Flask, render_template, request, redirect, session
from flask_bcrypt import Bcrypt
import pymysql
import plotly.express as px

app = Flask(__name__, template_folder="templates", static_folder="static")
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

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT * FROM users WHERE username=%s", (username,))
        user = cursor.fetchone()

        if user and bcrypt.check_password_hash(user["password_hash"], password):
            session["user"] = username
            return redirect("/home")

    return render_template("login.html")

@app.route("/home")
def home():
    if "user" not in session:
        return redirect("/")

    db = get_db()
    cursor = db.cursor()

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


@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect("/")

    db = get_db()
    cursor = db.cursor()
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

app.run(host="0.0.0.0", port=5000)
