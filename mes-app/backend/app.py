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
    
# Nouvelle fonction pour déterminer la plage de dates du dataset
def get_full_date_range(cursor):
    cursor.execute("""
        SELECT 
            MIN(Start) AS min_date,
            MAX(End) AS max_date
        FROM tblfinstep
        WHERE Start IS NOT NULL AND End IS NOT NULL;
    """)
    date_range = cursor.fetchone()
    
    min_date = date_range['min_date']
    max_date = date_range['max_date']

    if min_date and max_date:
        # Formatter les dates en YYYY-MM-DD pour les inputs HTML
        return min_date.strftime('%Y-%m-%d'), max_date.strftime('%Y-%m-%d')
    return None, None

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

@app.route("/home", methods=["GET"]) # Méthode GET pour le filtre
def home():
    if "user" not in session:
        return redirect("/")

    db = get_db()
    cursor = db.cursor()
    
    # 1. Détermination de la plage temporelle pour le filtre
    full_min_date, full_max_date = get_full_date_range(cursor)
    
    # 2. Récupération des dates de filtre
    start_date = request.args.get("start_date") or full_min_date
    end_date = request.args.get("end_date") or full_max_date

    # --- SQL filtering setup ---
    date_filter = ""
    date_filter_finstep = ""
    if start_date and end_date:
        # Filtre sur les champs TimeStamp (tblmachinereport, tblpartsreport)
        date_filter = f"AND TimeStamp >= '{start_date} 00:00:00' AND TimeStamp <= '{end_date} 23:59:59'"
        # Filtre sur les champs Start/End (tblfinstep)
        date_filter_finstep = f"AND t1.Start >= '{start_date} 00:00:00' AND t1.End <= '{end_date} 23:59:59'"
    
    # Initialisation des valeurs par défaut pour éviter le crash en cas d'erreur critique
    kpi_values = {f"kpi_{i}": 0.0 for i in range(1, 11)}
    kpi_notes = {
        "kpi_1": "", "kpi_2": "", "kpi_3": "Selon formule du PDF", "kpi_4": "Écart cycle réel / cycle théorique",
        "kpi_5": "", "kpi_6": "", "kpi_7": "", "kpi_8": "", "kpi_9": "", "kpi_10": "Taux de bonne détection",
    }
    error_note = None
    kpi_diagnostics = {}

    try:
        # --- 0. Récupération des métriques de base ---
        
        # Temps d'ouverture et cycle réel moyen (APPLIQUÉ LE FILTRE DE TEMPS)
        cursor.execute(f"""
            SELECT
                IFNULL(TIMESTAMPDIFF(SECOND, MIN(Start), MAX(End)), 0) AS temps_ouverture,
                IFNULL(AVG(TIMESTAMPDIFF(SECOND, Start, End)), 0.0) AS cycle_reel_moyen
            FROM tblfinstep
            WHERE End IS NOT NULL AND Start IS NOT NULL {date_filter_finstep.replace('t1.', '')};
        """)
        time_data = cursor.fetchone()
        temps_ouverture = float(time_data['temps_ouverture'])
        cycle_reel_moyen = float(time_data['cycle_reel_moyen'])
        kpi_diagnostics['Temps d\'ouverture (tblfinstep, filtré)'] = f"{temps_ouverture:.2f} sec"
        kpi_diagnostics['Cycle réel moyen (tblfinstep, filtré)'] = f"{cycle_reel_moyen:.2f} sec"

        # Temps de cycle théorique moyen (NON FILTRÉ)
        cursor.execute("SELECT IFNULL(AVG(WorkingTime / 1000.0), 1.0) AS avg_working_time FROM tblresourceoperation;")
        avg_time_data = cursor.fetchone()
        avg_working_time = float(avg_time_data['avg_working_time']) 
        if avg_working_time == 0: avg_working_time = 1.0 
        kpi_diagnostics['Temps théorique moyen (tblresourceoperation)'] = f"{avg_working_time:.2f} sec"
        
        # Nombre total de pièces produites (APPLIQUÉ LE FILTRE DE TEMPS)
        cursor.execute(f"SELECT COUNT(ID) AS nb_pieces FROM tblpartsreport WHERE TimeStamp IS NOT NULL {date_filter};")
        nb_pieces_data = cursor.fetchone()
        nb_pieces_produites = int(nb_pieces_data['nb_pieces'] or 0)
        kpi_diagnostics['Nb total de pièces (tblpartsreport, filtré)'] = nb_pieces_produites
        
        # Diviseurs sécurisés
        temps_ouverture_div = temps_ouverture if temps_ouverture != 0 else 1.0
        cycle_reel_moyen_div = cycle_reel_moyen if cycle_reel_moyen != 0 else 1.0
        
        # --- 1. Calculs des KPI basés sur le temps (KPI 1, 2, 3, 4) ---
        
        # KPI 1: Capacité de production inutilisée (%)
        capacite_theorique = temps_ouverture / avg_working_time 
        capacite_utilisee = nb_pieces_produites / (capacite_theorique if capacite_theorique != 0 else 1.0)
        kpi_values['kpi_1'] = max(0.0, min(100.0, 100.0 - (capacite_utilisee * 100.0)))
        
        # KPI 2: Taux de rendement global (TRG)
        kpi_values['kpi_2'] = (nb_pieces_produites * cycle_reel_moyen) / temps_ouverture_div

        # KPI 3: Productivité par poste
        prod_pieces_per_sec = nb_pieces_produites / temps_ouverture_div
        kpi_values['kpi_3'] = prod_pieces_per_sec / cycle_reel_moyen_div
        
        # KPI 4: Durée moyenne du cycle (Écart)
        kpi_values['kpi_4'] = (cycle_reel_moyen / avg_working_time) * 100.0
        
        # --- 2. KPI 5: Nombre de pannes machines (APPLIQUÉ LE FILTRE DE TEMPS) ---
        cursor.execute(f"""
            SELECT COUNT(*) AS nb_pannes
            FROM tblmachinereport
            WHERE (ErrorL0 = TRUE OR ErrorL1 = TRUE OR ErrorL2 = TRUE)
            AND TimeStamp IS NOT NULL {date_filter};
        """)
        kpi_values['kpi_5'] = int(cursor.fetchone()['nb_pannes'] or 0)
        kpi_diagnostics['Nb Pannes (tblmachinereport, filtré)'] = kpi_values['kpi_5']

        # --- 3. KPI 6, 7, 8: Stock (WIP, MP, PF) (NON FILTRÉ) ---
        cursor.execute("""
            SELECT
              IFNULL(SUM(CASE WHEN t2.Type = 1 THEN 1 ELSE 0 END), 0) AS stock_mp,
              IFNULL(SUM(CASE WHEN t2.Type = 2 THEN 1 ELSE 0 END), 0) AS stock_wip,
              IFNULL(SUM(CASE WHEN t2.Type = 3 THEN 1 ELSE 0 END), 0) AS stock_pf
            FROM tblbufferpos AS t1
            JOIN tblparts AS t2 ON t1.PNo = t2.PNo;
        """)
        stock_data = cursor.fetchone() or {}
        kpi_values['kpi_7'] = int(stock_data.get("stock_mp") or 0) 
        kpi_values['kpi_6'] = int(stock_data.get("stock_wip") or 0) 
        kpi_values['kpi_8'] = int(stock_data.get("stock_pf") or 0) 
        kpi_diagnostics['Stock MP (tblparts.Type=1)'] = kpi_values['kpi_7']
        kpi_diagnostics['Stock WIP (tblparts.Type=2)'] = kpi_values['kpi_6']
        kpi_diagnostics['Stock PF (tblparts.Type=3)'] = kpi_values['kpi_8']


        # --- 4. KPI 9: Taux de produit NC (Non Conforme) (APPLIQUÉ LE FILTRE DE TEMPS) ---
        cursor.execute(f"""
            SELECT
              SUM(CASE WHEN ErrorID IS NOT NULL AND ErrorID <> 0 THEN 1 ELSE 0 END) AS nb_nc,
              COUNT(ID) AS nb_total
            FROM tblpartsreport
            WHERE TimeStamp IS NOT NULL {date_filter};
        """)
        nc_data = cursor.fetchone()
        nb_nc = int(nc_data.get("nb_nc") or 0)
        nb_total = int(nc_data.get("nb_total") or 0)
        kpi_diagnostics['Nb NC (tblpartsreport, filtré)'] = nb_nc
        kpi_diagnostics['Nb total pièces (tblpartsreport, filtré)'] = nb_total
        
        kpi_values['kpi_9'] = (nb_nc / nb_total) * 100.0 if nb_total > 0 else 0.0

        # --- 5. KPI 10: Fiabilité IA (APPLIQUÉ LE FILTRE DE TEMPS) ---
        cursor.execute(f"""
            SELECT
                IFNULL(SUM(CASE WHEN t1.ErrorRetVal <> 0 AND t2.ErrorID <> 0 THEN 1 ELSE 0 END), 0) AS VP,  
                IFNULL(SUM(CASE WHEN t1.ErrorRetVal = 0 AND t2.ErrorID = 0 THEN 1 ELSE 0 END), 0) AS VN,    
                IFNULL(SUM(CASE WHEN t1.ErrorRetVal <> 0 AND t2.ErrorID = 0 THEN 1 ELSE 0 END), 0) AS FP,    
                IFNULL(SUM(CASE WHEN t1.ErrorRetVal = 0 AND t2.ErrorID <> 0 THEN 1 ELSE 0 END), 0) AS FN     
            FROM tblfinstep AS t1
            JOIN tblpartsreport AS t2 ON t1.PNo = t2.PNo
            WHERE t1.End IS NOT NULL {date_filter_finstep}; 
        """)
        conf_data = cursor.fetchone() or {}
        
        VP = int(conf_data.get('VP') or 0)
        VN = int(conf_data.get('VN') or 0)
        FP = int(conf_data.get('FP') or 0)
        FN = int(conf_data.get('FN') or 0)
        
        kpi_diagnostics['Fiabilité IA (VP, filtré)'] = VP
        kpi_diagnostics['Fiabilité IA (VN, filtré)'] = VN
        kpi_diagnostics['Fiabilité IA (FP, filtré)'] = FP
        kpi_diagnostics['Fiabilité IA (FN, filtré)'] = FN

        total_samples = VP + VN + FP + FN
        kpi_values['kpi_10'] = (VP + VN) / total_samples if total_samples > 0 else 0.0

    except Exception as e:
        error_note = f"Erreur critique lors de la récupération des données : {e}. Les valeurs N/A sont affichées."
        print(error_note)
        for key in kpi_values:
            if isinstance(kpi_values[key], float):
                kpi_values[key] = "N/A"
        if not kpi_diagnostics:
             kpi_diagnostics = {"Statut de la base de données": "Échec de l'une des requêtes critiques"}

    # Formatage final des KPI pour l'affichage
    kpis = [
        {"name": "ΚΡΙ 1 - Capacité de production inutilisée", "value": f"{kpi_values['kpi_1']:.2f}" if isinstance(kpi_values['kpi_1'], float) else kpi_values['kpi_1'], "unit": "%", "note": kpi_notes['kpi_1']},
        {"name": "ΚΡΙ 2 - Taux de rendement global (TRG)", "value": f"{kpi_values['kpi_2']:.4f}" if isinstance(kpi_values['kpi_2'], float) else kpi_values['kpi_2'], "unit": "Ratio", "note": kpi_notes['kpi_2']},
        {"name": "ΚΡΙ 3 - Productivité par poste", "value": f"{kpi_values['kpi_3']:.4f}" if isinstance(kpi_values['kpi_3'], float) else kpi_values['kpi_3'], "unit": "", "note": kpi_notes['kpi_3']},
        {"name": "ΚΡΙ 4 - Écart de durée moyenne du cycle", "value": f"{kpi_values['kpi_4']:.2f}" if isinstance(kpi_values['kpi_4'], float) else kpi_values['kpi_4'], "unit": "%", "note": kpi_notes['kpi_4']},
        {"name": "ΚΡΙ 5 - Nombre de pannes machines", "value": kpi_values['kpi_5'], "unit": "pannes", "note": kpi_notes['kpi_5']},
        {"name": "ΚΡΙ 6 - Stock en cours (WIP)", "value": kpi_values['kpi_6'], "unit": "pièces", "note": kpi_notes['kpi_6']},
        {"name": "ΚΡΙ 7 - Stock matières premières", "value": kpi_values['kpi_7'], "unit": "pièces", "note": kpi_notes['kpi_7']},
        {"name": "ΚΡΙ 8 - Stock produits finis", "value": kpi_values['kpi_8'], "unit": "pièces", "note": kpi_notes['kpi_8']},
        {"name": "ΚΡΙ 9 - Taux de produit NC", "value": f"{kpi_values['kpi_9']:.2f}" if isinstance(kpi_values['kpi_9'], float) else kpi_values['kpi_9'], "unit": "%", "note": kpi_notes['kpi_9']},
        {"name": "ΚΡΙ 10 - Fiabilité IA", "value": f"{kpi_values['kpi_10']:.2f}" if isinstance(kpi_values['kpi_10'], float) else kpi_values['kpi_10'], "unit": "Taux", "note": kpi_notes['kpi_10']},
    ]
    
    return render_template("home.html", kpis=kpis, error_note=error_note, diagnostics=kpi_diagnostics, 
                           full_min_date=full_min_date, full_max_date=full_max_date, 
                           start_date=start_date, end_date=end_date)


@app.route("/dashboard")
def dashboard():
    # ... code inchangé ...
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