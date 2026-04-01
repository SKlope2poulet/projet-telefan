from flask import Flask, render_template, request, redirect, session, url_for
from flask_bcrypt import Bcrypt
import pymysql
import plotly.express as px
import plotly.graph_objects as go
from functools import wraps

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

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def get_sidebar_context():
    """Retourne les variables nécessaires à la sidebar (resources + filtres actifs)."""
    db = get_db()
    try:
        with db.cursor() as cursor:
            cursor.execute("SELECT ResourceID, ResourceName FROM tblresource WHERE ResourceID > 0 ORDER BY ResourceID;")
            resources = cursor.fetchall()
    except Exception:
        resources = []
    finally:
        db.close()
    return {
        'resources': resources,
        'date_debut': request.args.get('date_debut', ''),
        'date_fin':   request.args.get('date_fin', ''),
        'selected_resources': request.args.getlist('resource_id'),
    }

@app.route("/", methods=["GET", "POST"])
def login():
    if "user" in session:
        return redirect(url_for('production'))
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
                return redirect(url_for('production'))
            else:
                return render_template("login.html", error="Identifiants incorrects")
        finally:
            db.close()
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for('login'))


# ─────────────────────────────────────────────
#  PRODUCTION
# ─────────────────────────────────────────────
@app.route("/production")
@login_required
def production():
    db = get_db()
    try:
        # ── Filtres sidebar ───────────────────────────────────────────────
        date_debut  = request.args.get('date_debut', '')
        date_fin    = request.args.get('date_fin', '')
        resource_ids = request.args.getlist('resource_id')

        def date_filter(col_start='Start', col_end='End', table_alias=''):
            prefix = table_alias + '.' if table_alias else ''
            parts = []
            if date_debut:
                parts.append(f"{prefix}{col_start} >= %(date_debut)s")
            if date_fin:
                parts.append(f"{prefix}{col_end} <= %(date_fin)s")
            return (' AND ' + ' AND '.join(parts)) if parts else ''

        def resource_filter(col='ResourceID', table_alias=''):
            prefix = table_alias + '.' if table_alias else ''
            if resource_ids:
                ids = ','.join(str(int(r)) for r in resource_ids if r.isdigit())
                return f" AND {prefix}{col} IN ({ids})" if ids else ''
            return ''

        params = {'date_debut': date_debut, 'date_fin': date_fin}

        with db.cursor() as cursor:
            # ── Ressources disponibles (pour sidebar) ─────────────────────
            cursor.execute("SELECT ResourceID, ResourceName FROM tblresource WHERE ResourceID > 0 ORDER BY ResourceID;")
            resources = cursor.fetchall()

            # ── TRG : temps_utile / temps_ouverture ────────────────────────
            # On filtre les durées aberrantes (< 1s ou > 1h) pour exclure les
            # dates parasites qui fausseraient le span MIN/MAX.
            cursor.execute("""
                SELECT
                    SUM(TIMESTAMPDIFF(SECOND, Start, End))        AS temps_utile,
                    TIMESTAMPDIFF(SECOND, MIN(Start), MAX(End))   AS temps_ouverture
                FROM tblfinstep
                WHERE Start IS NOT NULL AND End IS NOT NULL
                  AND TIMESTAMPDIFF(SECOND, Start, End) BETWEEN 1 AND 3600
            """ + date_filter() + resource_filter(table_alias=''), params)
            temps_data = cursor.fetchone()

            cursor.execute("SELECT COUNT(ID) AS nb_pieces FROM tblpartsreport WHERE ResourceID > 0" + resource_filter(), params)
            pieces_data = cursor.fetchone()

            temps_utile = temps_data['temps_utile'] or 0
            temps_ouv   = temps_data['temps_ouverture'] or 1
            nb_pieces   = pieces_data['nb_pieces'] or 0

            trg = min((temps_utile / temps_ouv * 100) if temps_ouv > 0 else 0, 100)
            capa_inutilisee = max(0, 100 - trg)

            # jauge TRG
            couleur_trg = "#22c55e" if trg >= 70 else ("#fde047" if trg >= 65 else "#ef4444")
            fig_trg = go.Figure(go.Indicator(
                mode="gauge+number",
                value=min(round(trg, 1), 100),
                title={'text': "TRG (%)"},
                gauge={
                    'axis': {'range': [0, 100]},
                    'bar': {'color': couleur_trg},
                    'steps': [
                        {'range': [0, 65],  'color': "#fca5a5"},
                        {'range': [65, 70], 'color': "#fde047"},
                        {'range': [70, 100],'color': "#86efac"},
                    ],
                    'threshold': {'line': {'color': "#F59E0B", 'width': 4}, 'thickness': 0.75, 'value': 70}
                }
            ))
            fig_trg.update_layout(height=250, margin=dict(l=20, r=20, t=30, b=20), paper_bgcolor='white')
            graph_trg = fig_trg.to_html(full_html=False)

            # jauge Capacité inutilisée
            couleur_capa = "#22c55e" if capa_inutilisee < 35 else ("#fde047" if capa_inutilisee < 45 else "#ef4444")
            fig_capa = go.Figure(go.Indicator(
                mode="gauge+number",
                value=round(capa_inutilisee, 1),
                title={'text': "Capacité inutilisée (%)"},
                gauge={
                    'axis': {'range': [0, 100]},
                    'bar': {'color': couleur_capa},
                    'steps': [
                        {'range': [0, 35],  'color': "#86efac"},
                        {'range': [35, 45], 'color': "#fde047"},
                        {'range': [45, 100],'color': "#fca5a5"},
                    ],
                    'threshold': {'line': {'color': "#F59E0B", 'width': 4}, 'thickness': 0.75, 'value': 35}
                }
            ))
            fig_capa.update_layout(height=250, margin=dict(l=20, r=20, t=30, b=20), paper_bgcolor='white')
            graph_capa = fig_capa.to_html(full_html=False)

            # ── Productivité par poste ─────────────────────────────────────
            cursor.execute("""
                SELECT
                    f.ResourceID,
                    r.ResourceName,
                    COUNT(*)                                          AS nb_pieces,
                    SUM(TIMESTAMPDIFF(SECOND, f.Start, f.End))       AS temps_poste,
                    AVG(TIMESTAMPDIFF(SECOND, f.Start, f.End))       AS cycle_reel_poste
                FROM tblfinstep f
                LEFT JOIN tblresource r ON f.ResourceID = r.ResourceID
                WHERE f.Start IS NOT NULL AND f.End IS NOT NULL AND f.ResourceID > 0
                  AND TIMESTAMPDIFF(SECOND, f.Start, f.End) BETWEEN 1 AND 3600
            """ + date_filter(table_alias='f') + resource_filter(table_alias='f') + """
                GROUP BY f.ResourceID, r.ResourceName
                ORDER BY f.ResourceID;
            """, params)
            poste_data = cursor.fetchall()

            postes, productivites, couleurs_postes = [], [], []
            for row in poste_data:
                label = row['ResourceName'] or f"Poste {row['ResourceID']}"
                if row['temps_poste'] and row['temps_poste'] > 0:
                    prod = (row['nb_pieces'] * row['cycle_reel_poste'] / row['temps_poste']) * 100
                else:
                    prod = 0
                postes.append(label)
                productivites.append(round(prod, 1))
                couleurs_postes.append("#22c55e" if prod >= 80 else ("#fde047" if prod >= 70 else "#ef4444"))

            fig_prod = go.Figure(go.Bar(
                x=postes, y=productivites,
                marker_color=couleurs_postes,
                text=[f"{v:.1f}%" for v in productivites],
                textposition='outside'
            ))
            fig_prod.add_hline(y=80, line_dash="dash", line_color="#F59E0B", annotation_text="Objectif 80%")
            fig_prod.add_hline(y=70, line_dash="dot",  line_color="#ef4444", annotation_text="Seuil alerte 70%")
            fig_prod.update_layout(
                height=280, margin=dict(l=20, r=20, t=20, b=60),
                yaxis_title="Productivité (%)", xaxis_title="",
                paper_bgcolor='white', plot_bgcolor='white',
                yaxis=dict(range=[0, 120])
            )
            graph_prod = fig_prod.to_html(full_html=False)

            # ── Durée moyenne du cycle de production ──────────────────────
            cursor.execute("""
                SELECT
                    AVG(TIMESTAMPDIFF(SECOND, Start, End)) AS cycle_reel_s,
                    MIN(TIMESTAMPDIFF(SECOND, Start, End)) AS cycle_min_s,
                    MAX(TIMESTAMPDIFF(SECOND, Start, End)) AS cycle_max_s
                FROM tblfinstep
                WHERE Start IS NOT NULL AND End IS NOT NULL
                  AND TIMESTAMPDIFF(SECOND, Start, End) BETWEEN 1 AND 3600
            """ + date_filter() + resource_filter() + ";", params)
            cycle_data = cursor.fetchone()
            cycle_reel_s = cycle_data['cycle_reel_s'] or 0
            cycle_min_s  = cycle_data['cycle_min_s']  or 0
            cycle_max_s  = cycle_data['cycle_max_s']  or 0

            # WorkingTime dans tblresourceoperation est en ms mais les valeurs
            # présentes sont trop petites pour servir de référence fiable.
            # On utilise la moyenne globale comme référence de base.
            theo_s = cycle_reel_s if cycle_reel_s > 0 else 1
            ecart_cycle = 100.0  # pas d'écart (référence = moyenne réelle)

            # graphique durée de cycle par poste (moy / min / max)
            cursor.execute("""
                SELECT
                    r.ResourceName AS poste,
                    AVG(TIMESTAMPDIFF(SECOND, f.Start, f.End)) AS cycle_moy,
                    MIN(TIMESTAMPDIFF(SECOND, f.Start, f.End)) AS cycle_min,
                    MAX(TIMESTAMPDIFF(SECOND, f.Start, f.End)) AS cycle_max
                FROM tblfinstep f
                LEFT JOIN tblresource r ON f.ResourceID = r.ResourceID
                WHERE f.Start IS NOT NULL AND f.End IS NOT NULL
                  AND TIMESTAMPDIFF(SECOND, f.Start, f.End) BETWEEN 1 AND 3600
                  AND f.ResourceID > 0
            """ + date_filter(table_alias='f') + resource_filter(table_alias='f') + """
                GROUP BY f.ResourceID, r.ResourceName
                ORDER BY f.ResourceID;
            """, params)
            cycle_postes = cursor.fetchall()

            if cycle_postes:
                c_postes = [r['poste'] or 'N/A' for r in cycle_postes]
                c_moy    = [round(r['cycle_moy'] or 0, 1) for r in cycle_postes]
                c_min    = [round(r['cycle_min'] or 0, 1) for r in cycle_postes]
                c_max    = [round(r['cycle_max'] or 0, 1) for r in cycle_postes]

                fig_cycle = go.Figure()
                fig_cycle.add_trace(go.Bar(name='Cycle moyen (s)', x=c_postes, y=c_moy,
                                           marker_color='#1355B8', text=[f"{v}s" for v in c_moy], textposition='outside'))
                fig_cycle.add_trace(go.Scatter(name='Min (s)', x=c_postes, y=c_min,
                                               mode='markers', marker=dict(color='#22c55e', size=8, symbol='triangle-up')))
                fig_cycle.add_trace(go.Scatter(name='Max (s)', x=c_postes, y=c_max,
                                               mode='markers', marker=dict(color='#ef4444', size=8, symbol='triangle-down')))
                fig_cycle.update_layout(
                    height=260, margin=dict(l=20, r=20, t=10, b=60),
                    paper_bgcolor='white', plot_bgcolor='white',
                    yaxis_title='Durée (s)',
                    legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1)
                )
                graph_cycle = fig_cycle.to_html(full_html=False)
            else:
                graph_cycle = "<p style='color:#94a3b8;text-align:center;padding:40px'>Pas de données disponibles</p>"

            # ── Temps d'attente moyen entre opérations ────────────────────
            cursor.execute("""
                SELECT AVG(wait_s) AS avg_wait_s
                FROM (
                    SELECT TIMESTAMPDIFF(SECOND,
                        LAG(End) OVER (PARTITION BY ONo ORDER BY StepNo),
                        Start
                    ) AS wait_s
                    FROM tblfinstep
                    WHERE Start IS NOT NULL AND End IS NOT NULL AND ONo > 0
                      AND TIMESTAMPDIFF(SECOND, Start, End) BETWEEN 1 AND 3600
                ) t
                WHERE wait_s > 0 AND wait_s < 600;
            """)
            wait_data = cursor.fetchone()
            avg_wait_s = round(wait_data['avg_wait_s'] or 0, 1)

            # ── Suivi des OF ───────────────────────────────────────────────
            cursor.execute("""
                SELECT ONo, PlannedStart, PlannedEnd, Start, End, State
                FROM tblfinorder
                ORDER BY PlannedStart DESC
                LIMIT 15;
            """)
            ordres_raw = cursor.fetchall()
            ordres = []
            for o in ordres_raw:
                status = "En cours"
                retard = False
                if o['State'] == 100:
                    status = "Terminé"
                elif o['State'] == 0:
                    status = "Planifié"

                if o['Start'] and o['PlannedStart']:
                    diff = (o['Start'] - o['PlannedStart']).total_seconds()
                    if diff > 60:
                        retard = True
                        status = "En retard" if o['State'] != 100 else status

                ordres.append({
                    'OrderID': o['ONo'],
                    'PlannedStart': o['PlannedStart'],
                    'PlannedEnd':   o['PlannedEnd'],
                    'Start':        o['Start'],
                    'End':          o['End'],
                    'Status':       status,
                    'retard':       retard,
                })

    except Exception as e:
        import traceback; traceback.print_exc()
        err = f"<p style='color:red;padding:20px'>Erreur DB : {e}</p>"
        graph_trg = graph_capa = graph_prod = graph_cycle = err
        trg = capa_inutilisee = cycle_reel_s = cycle_min_s = cycle_max_s = avg_wait_s = 0
        ordres = []
        resources = []
    finally:
        db.close()

    return render_template("production.html",
                           graph_trg=graph_trg,
                           graph_capa=graph_capa,
                           graph_prod=graph_prod,
                           graph_cycle=graph_cycle,
                           cycle_reel_s=round(cycle_reel_s, 1),
                           cycle_min_s=round(cycle_min_s, 1),
                           cycle_max_s=round(cycle_max_s, 1),
                           avg_wait_s=avg_wait_s,
                           ordres=ordres,
                           trg=round(trg, 1),
                           capa_inutilisee=round(capa_inutilisee, 1),
                           resources=resources,
                           date_debut=request.args.get('date_debut',''),
                           date_fin=request.args.get('date_fin',''),
                           selected_resources=request.args.getlist('resource_id'))


# ─────────────────────────────────────────────
#  QUALITE
# ─────────────────────────────────────────────
@app.route("/qualite")
@login_required
def qualite():
    db = get_db()
    try:
        with db.cursor() as cursor:
            # ── Taux NC global ────────────────────────────────────────────
            cursor.execute("""
                SELECT
                    COUNT(*)                                              AS total,
                    SUM(CASE WHEN ErrorID != 0 THEN 1 ELSE 0 END)        AS nc_count
                FROM tblpartsreport
                WHERE ResourceID > 0;
            """)
            nc_data = cursor.fetchone()
            total_pieces = nc_data['total'] or 0
            nc_count     = nc_data['nc_count'] or 0
            nc_rate      = (nc_count / total_pieces * 100) if total_pieces > 0 else 0

            # évolution NC par jour
            cursor.execute("""
                SELECT
                    DATE(TimeStamp)                                       AS jour,
                    COUNT(*)                                              AS total,
                    SUM(CASE WHEN ErrorID != 0 THEN 1 ELSE 0 END)        AS nc
                FROM tblpartsreport
                WHERE ResourceID > 0
                GROUP BY DATE(TimeStamp)
                ORDER BY jour;
            """)
            nc_timeline = cursor.fetchall()

            if nc_timeline:
                jours  = [str(r['jour']) for r in nc_timeline]
                nc_vals = [r['nc'] for r in nc_timeline]
                fig_nc = go.Figure()
                fig_nc.add_trace(go.Scatter(
                    x=jours, y=nc_vals, mode='lines+markers',
                    name='Pièces NC', line=dict(color='#ef4444', width=2),
                    fill='tozeroy', fillcolor='rgba(239,68,68,0.1)'
                ))
                fig_nc.add_hline(y=0, line_dash="solid", line_color="#22c55e", annotation_text="Objectif : 0 NC")
                fig_nc.update_layout(
                    height=220, margin=dict(l=20, r=20, t=10, b=40),
                    paper_bgcolor='white', plot_bgcolor='white',
                    xaxis_title="Date", yaxis_title="Nb NC"
                )
                graph_nc = fig_nc.to_html(full_html=False)
            else:
                graph_nc = "<p style='color:#94a3b8;text-align:center;padding:40px'>Pas de données</p>"

            # ── Taux fiabilité IA (Resource 3 = caméra IA) ────────────────
            # VP = IA détecte NC (ErrorID!=0 à poste 3) ET humain confirme NC (ErrorID!=0 à poste 6)
            # Approximation : on compare les taux NC des deux postes
            cursor.execute("""
                SELECT
                    SUM(CASE WHEN ResourceID=3 AND ErrorID!=0 THEN 1 ELSE 0 END) AS ia_nc,
                    SUM(CASE WHEN ResourceID=3 AND ErrorID=0  THEN 1 ELSE 0 END) AS ia_ok,
                    SUM(CASE WHEN ResourceID=6 AND ErrorID!=0 THEN 1 ELSE 0 END) AS hum_nc,
                    SUM(CASE WHEN ResourceID=6 AND ErrorID=0  THEN 1 ELSE 0 END) AS hum_ok,
                    COUNT(CASE WHEN ResourceID=3 THEN 1 END)                     AS total_ia,
                    COUNT(CASE WHEN ResourceID=6 THEN 1 END)                     AS total_hum
                FROM tblpartsreport;
            """)
            ia_row  = cursor.fetchone()
            ia_nc   = ia_row['ia_nc']  or 0
            ia_ok   = ia_row['ia_ok']  or 0
            hum_nc  = ia_row['hum_nc'] or 0
            hum_ok  = ia_row['hum_ok'] or 0

            # Matrice de confusion simplifiée
            VP = min(ia_nc, hum_nc)
            VN = min(ia_ok, hum_ok)
            FP = max(ia_nc - hum_nc, 0)
            FN = max(hum_nc - ia_nc, 0)
            total_ia_pred = VP + VN + FP + FN
            ia_fiabilite  = ((VP + VN) / total_ia_pred * 100) if total_ia_pred > 0 else 0

            couleur_ia = "#22c55e" if ia_fiabilite >= 80 else ("#fde047" if ia_fiabilite >= 70 else "#ef4444")
            fig_ia = go.Figure(go.Indicator(
                mode="gauge+number",
                value=round(ia_fiabilite, 1),
                title={'text': "Fiabilité IA (%)"},
                gauge={
                    'axis': {'range': [0, 100]},
                    'bar': {'color': couleur_ia},
                    'steps': [
                        {'range': [0, 79.9], 'color': "#fca5a5"},
                        {'range': [79.9, 90],'color': "#fde047"},
                        {'range': [90, 100], 'color': "#86efac"},
                    ],
                    'threshold': {'line': {'color': "#F59E0B", 'width': 4}, 'thickness': 0.75, 'value': 79.9}
                }
            ))
            fig_ia.update_layout(height=250, margin=dict(l=20, r=20, t=30, b=20), paper_bgcolor='white')
            graph_ia = fig_ia.to_html(full_html=False)

            # ── Plan d'action – Pareto erreurs ────────────────────────────
            cursor.execute("""
                SELECT
                    e.ErrorNo,
                    e.ErrorDesc,
                    COUNT(mr.ID)              AS nb_occurrences,
                    MAX(s.Rating)             AS rating,
                    COUNT(mr.ID) * MAX(COALESCE(s.Rating, 1)) AS score
                FROM tblmainterror e
                LEFT JOIN tblmachinereport mr ON (mr.ErrorL0=1 OR mr.ErrorL1=1 OR mr.ErrorL2=1)
                LEFT JOIN tblmaintsolutions s  ON s.ErrorNo = e.ErrorNo
                GROUP BY e.ErrorNo, e.ErrorDesc
                HAVING nb_occurrences > 0
                ORDER BY score DESC
                LIMIT 20;
            """)
            pareto_raw = cursor.fetchall()

            # top 20% selon la règle de Pareto
            pareto_top = pareto_raw[:max(1, len(pareto_raw) // 5)] if pareto_raw else []

            if pareto_raw:
                p_labels = [f"E{r['ErrorNo']}" for r in pareto_raw[:10]]
                p_counts = [r['nb_occurrences'] for r in pareto_raw[:10]]
                total_p  = sum(p_counts) or 1
                cumul    = []
                c = 0
                for v in p_counts:
                    c += v / total_p * 100
                    cumul.append(round(c, 1))

                fig_pareto = go.Figure()
                fig_pareto.add_trace(go.Bar(x=p_labels, y=p_counts, name='Occurrences',
                                            marker_color='#1355B8', yaxis='y'))
                fig_pareto.add_trace(go.Scatter(x=p_labels, y=cumul, name='Cumulé %',
                                                mode='lines+markers', line=dict(color='#F59E0B'),
                                                yaxis='y2'))
                fig_pareto.add_hline(y=80, line_dash="dash", line_color="#ef4444",
                                     annotation_text="80%", yref='y2')
                fig_pareto.update_layout(
                    height=260, margin=dict(l=20, r=50, t=10, b=40),
                    paper_bgcolor='white', plot_bgcolor='white',
                    yaxis=dict(title='Occurrences'),
                    yaxis2=dict(title='Cumulé %', overlaying='y', side='right',
                                range=[0, 110], showgrid=False),
                    legend=dict(orientation='h', y=1.1)
                )
                graph_pareto = fig_pareto.to_html(full_html=False)
            else:
                graph_pareto = "<p style='color:#94a3b8;text-align:center;padding:40px'>Pas de données</p>"

            # solutions pour le plan d'action
            cursor.execute("""
                SELECT
                    e.ErrorNo,
                    e.ErrorDesc,
                    s.CauseDesc,
                    s.SolutionDesc,
                    s.Rating,
                    s.ModuleType AS machine
                FROM tblmainterror e
                JOIN tblmaintsolutions s ON s.ErrorNo = e.ErrorNo
                ORDER BY s.Rating DESC
                LIMIT 15;
            """)
            plan_action = cursor.fetchall()

    except Exception as e:
        import traceback; traceback.print_exc()
        err = f"<p style='color:red;padding:20px'>Erreur DB : {e}</p>"
        graph_nc = graph_ia = graph_pareto = err
        nc_count = total_pieces = nc_rate = ia_fiabilite = 0
        VP = VN = FP = FN = 0
        pareto_top = plan_action = []
    finally:
        db.close()

    return render_template("qualite.html",
                           graph_nc=graph_nc,
                           graph_ia=graph_ia,
                           graph_pareto=graph_pareto,
                           nc_count=nc_count,
                           total_pieces=total_pieces,
                           nc_rate=round(nc_rate, 2),
                           ia_fiabilite=round(ia_fiabilite, 1),
                           VP=VP, VN=VN, FP=FP, FN=FN,
                           pareto_top=pareto_top,
                           plan_action=plan_action,
                           **get_sidebar_context())


# ─────────────────────────────────────────────
#  STOCK
# ─────────────────────────────────────────────
@app.route("/stock")
@login_required
def stock():
    db = get_db()
    try:
        with db.cursor() as cursor:
            # ── Stock via tblfinorder (tblbufferpos vide après simulation) ──
            # WIP  = OF démarrés, non terminés
            # PF   = OF terminés (State=100)
            # MP   = OF planifiés, non démarrés

            cursor.execute("""
                SELECT
                    SUM(CASE WHEN Start IS NOT NULL AND (End IS NULL OR State < 100) THEN 1 ELSE 0 END) AS wip_count,
                    SUM(CASE WHEN State = 100 THEN 1 ELSE 0 END)                                        AS pf_count,
                    SUM(CASE WHEN Start IS NULL THEN 1 ELSE 0 END)                                      AS mp_count,
                    COUNT(*)                                                                             AS total
                FROM tblfinorder;
            """)
            ord_row   = cursor.fetchone() or {}
            wip_count = ord_row.get('wip_count') or 0
            pf_count  = ord_row.get('pf_count')  or 0
            mp_count  = ord_row.get('mp_count')  or 0
            total_ord = ord_row.get('total')      or 1

            wip_pct = round(wip_count / total_ord * 100, 1)
            pf_pct  = round(pf_count  / total_ord * 100, 1)
            mp_pct  = round(mp_count  / total_ord * 100, 1)

            # ── Jauge WIP ─────────────────────────────────────────────────
            couleur_wip = "#22c55e" if wip_pct <= 20 else ("#fde047" if wip_pct <= 30 else "#ef4444")
            fig_wip = go.Figure(go.Indicator(
                mode="gauge+number+delta",
                value=wip_count,
                title={'text': "OF en cours (WIP)"},
                delta={'reference': total_ord, 'valueformat': '.0f'},
                gauge={
                    'axis': {'range': [0, total_ord]},
                    'bar': {'color': couleur_wip},
                    'steps': [
                        {'range': [0, total_ord * 0.2], 'color': "#86efac"},
                        {'range': [total_ord * 0.2, total_ord * 0.3], 'color': "#fde047"},
                        {'range': [total_ord * 0.3, total_ord], 'color': "#fca5a5"},
                    ],
                }
            ))
            fig_wip.update_layout(height=250, margin=dict(l=20, r=20, t=30, b=20), paper_bgcolor='white')
            graph_wip = fig_wip.to_html(full_html=False)

            # ── Évolution PF cumulés par jour (OF terminés) ────────────────
            cursor.execute("""
                SELECT DATE(End) AS jour, COUNT(*) AS qty
                FROM tblfinorder
                WHERE State = 100 AND End IS NOT NULL
                GROUP BY DATE(End)
                ORDER BY jour;
            """)
            pf_timeline = cursor.fetchall()

            if pf_timeline:
                pf_jours = [str(r['jour']) for r in pf_timeline]
                pf_vals  = [r['qty'] for r in pf_timeline]
                # cumul
                cumul_pf = []
                c = 0
                for v in pf_vals:
                    c += v
                    cumul_pf.append(c)
                fig_pf = go.Figure()
                fig_pf.add_trace(go.Bar(x=pf_jours, y=pf_vals, name='Terminés/jour',
                                        marker_color='#22c55e'))
                fig_pf.add_trace(go.Scatter(x=pf_jours, y=cumul_pf, name='Cumulé PF',
                                            mode='lines+markers', line=dict(color='#0A3A82', width=2),
                                            yaxis='y2'))
                fig_pf.update_layout(
                    height=250, margin=dict(l=20, r=20, t=10, b=40),
                    paper_bgcolor='white', plot_bgcolor='white',
                    yaxis=dict(title='OF/jour'),
                    yaxis2=dict(title='Cumulé', overlaying='y', side='right', showgrid=False),
                    legend=dict(orientation='h', y=1.1)
                )
                graph_pf = fig_pf.to_html(full_html=False)
            else:
                graph_pf = "<p style='color:#94a3b8;text-align:center;padding:40px'>Pas de données</p>"

            # ── Répartition des OF par état (bar chart) ───────────────────
            fig_mp = go.Figure(go.Bar(
                x=['Planifiés (MP)', 'En cours (WIP)', 'Terminés (PF)'],
                y=[mp_count, wip_count, pf_count],
                marker_color=['#1355B8', '#F59E0B', '#22c55e'],
                text=[f"{mp_count} ({mp_pct}%)", f"{wip_count} ({wip_pct}%)", f"{pf_count} ({pf_pct}%)"],
                textposition='outside'
            ))
            fig_mp.update_layout(
                height=260, margin=dict(l=20, r=20, t=20, b=40),
                paper_bgcolor='white', plot_bgcolor='white',
                yaxis_title="Nombre d'OF", showlegend=False,
                yaxis=dict(range=[0, total_ord * 1.2])
            )
            graph_mp = fig_mp.to_html(full_html=False)

    except Exception as e:
        import traceback; traceback.print_exc()
        err = f"<p style='color:red;padding:20px'>Erreur DB : {e}</p>"
        graph_wip = graph_mp = graph_pf = err
        wip_count = mp_count = pf_count = 0
        wip_pct = mp_pct = pf_pct = 0
    finally:
        db.close()

    return render_template("stock.html",
                           graph_wip=graph_wip,
                           graph_mp=graph_mp,
                           graph_pf=graph_pf,
                           wip_count=wip_count, wip_pct=wip_pct,
                           mp_count=mp_count,   mp_pct=mp_pct,
                           pf_count=pf_count,   pf_pct=pf_pct,
                           **get_sidebar_context())


# ─────────────────────────────────────────────
#  MAINTENANCE
# ─────────────────────────────────────────────
@app.route("/maintenance")
@login_required
def maintenance():
    db = get_db()
    try:
        with db.cursor() as cursor:
            # ── Nombre de pannes par machine et niveau ────────────────────
            cursor.execute("""
                SELECT
                    r.ResourceName,
                    mr.ResourceID,
                    SUM(CASE WHEN mr.ErrorL0=1 THEN 1 ELSE 0 END) AS l0,
                    SUM(CASE WHEN mr.ErrorL1=1 THEN 1 ELSE 0 END) AS l1,
                    SUM(CASE WHEN mr.ErrorL2=1 THEN 1 ELSE 0 END) AS l2
                FROM tblmachinereport mr
                JOIN tblresource r ON mr.ResourceID = r.ResourceID
                WHERE mr.ResourceID > 0
                GROUP BY mr.ResourceID, r.ResourceName
                ORDER BY (SUM(mr.ErrorL0) + SUM(mr.ErrorL1) + SUM(mr.ErrorL2)) DESC;
            """)
            pannes_data = cursor.fetchall()

            if pannes_data:
                machines = [r['ResourceName'] for r in pannes_data]
                fig_pannes = go.Figure()
                fig_pannes.add_trace(go.Bar(name='Niveau 0', x=machines,
                                            y=[r['l0'] for r in pannes_data], marker_color='#fde047'))
                fig_pannes.add_trace(go.Bar(name='Niveau 1', x=machines,
                                            y=[r['l1'] for r in pannes_data], marker_color='#f97316'))
                fig_pannes.add_trace(go.Bar(name='Niveau 2', x=machines,
                                            y=[r['l2'] for r in pannes_data], marker_color='#ef4444'))
                fig_pannes.update_layout(
                    barmode='stack', height=280,
                    margin=dict(l=20, r=20, t=10, b=60),
                    paper_bgcolor='white', plot_bgcolor='white',
                    legend=dict(orientation='h', y=1.05)
                )
                graph_pannes = fig_pannes.to_html(full_html=False)
            else:
                graph_pannes = "<p style='color:#94a3b8;text-align:center;padding:40px'>Pas de données</p>"

            # ── MTBF ──────────────────────────────────────────────────────
            cursor.execute("""
                SELECT AVG(TIMESTAMPDIFF(MINUTE, prev_ts, TimeStamp)) AS mtbf_min
                FROM (
                    SELECT
                        TimeStamp,
                        (ErrorL0=1 OR ErrorL1=1 OR ErrorL2=1)                     AS in_error,
                        LAG((ErrorL0=1 OR ErrorL1=1 OR ErrorL2=1))
                            OVER (PARTITION BY ResourceID ORDER BY TimeStamp)       AS prev_error,
                        LAG(TimeStamp)
                            OVER (PARTITION BY ResourceID ORDER BY TimeStamp)       AS prev_ts
                    FROM tblmachinereport
                    WHERE ResourceID > 0
                ) t
                WHERE in_error = 1 AND prev_error = 0;
            """)
            mtbf_row = cursor.fetchone()
            mtbf_min = round(mtbf_row['mtbf_min'] or 0, 1)

            # MTBF par machine (pour sparkline)
            cursor.execute("""
                SELECT ResourceID, AVG(TIMESTAMPDIFF(MINUTE, prev_ts, TimeStamp)) AS mtbf_min
                FROM (
                    SELECT ResourceID, TimeStamp,
                        (ErrorL0=1 OR ErrorL1=1 OR ErrorL2=1) AS in_error,
                        LAG((ErrorL0=1 OR ErrorL1=1 OR ErrorL2=1))
                            OVER (PARTITION BY ResourceID ORDER BY TimeStamp) AS prev_error,
                        LAG(TimeStamp)
                            OVER (PARTITION BY ResourceID ORDER BY TimeStamp) AS prev_ts
                    FROM tblmachinereport WHERE ResourceID > 0
                ) t
                WHERE in_error = 1 AND prev_error = 0
                GROUP BY ResourceID;
            """)
            mtbf_by_res = cursor.fetchall()

            # ── MTTR ──────────────────────────────────────────────────────
            cursor.execute("""
                SELECT AVG(TIMESTAMPDIFF(MINUTE, prev_ts, TimeStamp)) AS mttr_min
                FROM (
                    SELECT
                        TimeStamp,
                        (ErrorL0=1 OR ErrorL1=1 OR ErrorL2=1)                     AS in_error,
                        LAG((ErrorL0=1 OR ErrorL1=1 OR ErrorL2=1))
                            OVER (PARTITION BY ResourceID ORDER BY TimeStamp)       AS prev_error,
                        LAG(TimeStamp)
                            OVER (PARTITION BY ResourceID ORDER BY TimeStamp)       AS prev_ts
                    FROM tblmachinereport
                    WHERE ResourceID > 0
                ) t
                WHERE in_error = 0 AND prev_error = 1;
            """)
            mttr_row = cursor.fetchone()
            mttr_min = round(mttr_row['mttr_min'] or 0, 1)

            # graphique MTTR vs objectif
            fig_mttr = go.Figure()
            fig_mttr.add_trace(go.Bar(
                x=['MTTR réel', 'Objectif'],
                y=[mttr_min, 5],
                marker_color=['#ef4444' if mttr_min > 15 else ('#fde047' if mttr_min > 5 else '#22c55e'), '#F59E0B'],
                text=[f"{mttr_min:.1f} min", "5 min"],
                textposition='outside'
            ))
            fig_mttr.add_hline(y=15, line_dash="dash", line_color="#ef4444", annotation_text="Seuil alerte 15 min")
            fig_mttr.update_layout(
                height=250, margin=dict(l=20, r=20, t=10, b=20),
                paper_bgcolor='white', plot_bgcolor='white',
                showlegend=False, yaxis_title="Minutes"
            )
            graph_mttr = fig_mttr.to_html(full_html=False)

    except Exception as e:
        import traceback; traceback.print_exc()
        err = f"<p style='color:red;padding:20px'>Erreur DB : {e}</p>"
        graph_pannes = graph_mttr = err
        mtbf_min = mttr_min = 0
        pannes_data = mtbf_by_res = []
    finally:
        db.close()

    # couleurs jauge MTBF
    couleur_mtbf = "#22c55e" if mtbf_min >= 60 else ("#fde047" if mtbf_min >= 30 else "#ef4444")

    return render_template("maintenance.html",
                           graph_pannes=graph_pannes,
                           graph_mttr=graph_mttr,
                           mtbf_min=mtbf_min,
                           mttr_min=mttr_min,
                           couleur_mtbf=couleur_mtbf,
                           pannes_data=pannes_data,
                           mtbf_by_res=mtbf_by_res,
                           **get_sidebar_context())


# ─────────────────────────────────────────────
#  ALERTES
# ─────────────────────────────────────────────
@app.route("/alertes")
@login_required
def alertes():
    db = get_db()
    alertes_list = []

    try:
        with db.cursor() as cursor:
            # TRG
            cursor.execute("""
                SELECT
                    (COUNT(pr.ID) * AVG(TIMESTAMPDIFF(SECOND, f.Start, f.End)))
                    / NULLIF(TIMESTAMPDIFF(SECOND, MIN(f.Start), MAX(f.End)), 0) * 100 AS trg
                FROM tblfinstep f, tblpartsreport pr
                WHERE f.Start IS NOT NULL AND f.End IS NOT NULL;
            """)
            trg_val = round((cursor.fetchone() or {}).get('trg') or 0, 1)
            alertes_list.append({
                'domaine': 'Production', 'kpi': 'TRG (Taux de rendement global)',
                'valeur': f"{trg_val} %", 'seuil': '< 65 %',
                'alerte': trg_val < 65,
                'critique': trg_val < 50,
            })

            # Capacité inutilisée
            cursor.execute("""
                SELECT
                    TIMESTAMPDIFF(SECOND, MIN(Start), MAX(End)) AS ouv,
                    AVG(WorkingTime)/1000 AS theo
                FROM tblfinstep, tblresourceoperation
                WHERE Start IS NOT NULL AND WorkingTime > 0;
            """)
            row_c = cursor.fetchone() or {}
            ouv  = row_c.get('ouv') or 1
            theo = row_c.get('theo') or 1
            cursor.execute("SELECT COUNT(ID) AS n FROM tblpartsreport;")
            n_p = (cursor.fetchone() or {}).get('n') or 0
            capa_inu = round(max(0, 100 - (n_p / (ouv / theo)) * 100), 1) if ouv > 0 else 0
            alertes_list.append({
                'domaine': 'Production', 'kpi': 'Capacité de production inutilisée',
                'valeur': f"{capa_inu} %", 'seuil': '> 45 %',
                'alerte': capa_inu > 45,
                'critique': capa_inu > 60,
            })

            # Cycle moyen
            cursor.execute("""
                SELECT AVG(TIMESTAMPDIFF(SECOND, Start, End)) AS cr,
                       (SELECT AVG(WorkingTime)/1000 FROM tblresourceoperation WHERE WorkingTime>0) AS ct
                FROM tblfinstep
                WHERE Start IS NOT NULL AND End IS NOT NULL
                  AND TIMESTAMPDIFF(SECOND, Start, End) BETWEEN 1 AND 3600;
            """)
            cyc = cursor.fetchone() or {}
            cr = cyc.get('cr') or 0
            ct = cyc.get('ct') or 1
            ecart_cyc = round(cr / ct * 100, 1) if ct > 0 else 100
            alertes_list.append({
                'domaine': 'Production', 'kpi': 'Durée moyenne cycle (écart vs théorique)',
                'valeur': f"{ecart_cyc} %", 'seuil': '> 115 % ou < 85 %',
                'alerte': ecart_cyc > 115 or ecart_cyc < 85,
                'critique': ecart_cyc > 130 or ecart_cyc < 70,
            })

            # Temps d'attente
            cursor.execute("""
                SELECT AVG(wait_s) AS aw FROM (
                    SELECT TIMESTAMPDIFF(SECOND,
                        LAG(End) OVER (PARTITION BY ONo ORDER BY StepNo), Start) AS wait_s
                    FROM tblfinstep WHERE Start IS NOT NULL AND End IS NOT NULL AND ONo > 0
                ) t WHERE wait_s BETWEEN 0 AND 600;
            """)
            aw_val = round((cursor.fetchone() or {}).get('aw') or 0, 1)
            alertes_list.append({
                'domaine': 'Production', 'kpi': "Temps d'attente moyen entre opérations",
                'valeur': f"{aw_val} s", 'seuil': '> 10 s',
                'alerte': aw_val > 10,
                'critique': aw_val > 20,
            })

            # NC rate
            cursor.execute("""
                SELECT COUNT(*) AS t, SUM(CASE WHEN ErrorID!=0 THEN 1 ELSE 0 END) AS nc
                FROM tblpartsreport WHERE ResourceID > 0;
            """)
            nc_r = cursor.fetchone() or {}
            nc_rate_val = round((nc_r.get('nc') or 0) / (nc_r.get('t') or 1) * 100, 2)
            alertes_list.append({
                'domaine': 'Qualité', 'kpi': 'Taux de produit NC',
                'valeur': f"{nc_rate_val} %", 'seuil': '> 0 %',
                'alerte': nc_rate_val > 0,
                'critique': nc_rate_val > 5,
            })

            # IA fiabilité
            cursor.execute("""
                SELECT
                    SUM(CASE WHEN ResourceID=3 AND ErrorID!=0 THEN 1 ELSE 0 END) AS ia_nc,
                    SUM(CASE WHEN ResourceID=3 AND ErrorID=0  THEN 1 ELSE 0 END) AS ia_ok,
                    SUM(CASE WHEN ResourceID=6 AND ErrorID!=0 THEN 1 ELSE 0 END) AS hum_nc,
                    SUM(CASE WHEN ResourceID=6 AND ErrorID=0  THEN 1 ELSE 0 END) AS hum_ok
                FROM tblpartsreport;
            """)
            ia_r = cursor.fetchone() or {}
            ia_nc_v  = ia_r.get('ia_nc')  or 0
            ia_ok_v  = ia_r.get('ia_ok')  or 0
            hum_nc_v = ia_r.get('hum_nc') or 0
            hum_ok_v = ia_r.get('hum_ok') or 0
            VP = min(ia_nc_v, hum_nc_v)
            VN = min(ia_ok_v, hum_ok_v)
            FP = max(ia_nc_v - hum_nc_v, 0)
            FN = max(hum_nc_v - ia_nc_v, 0)
            tot_ia = VP + VN + FP + FN
            ia_fib = round((VP + VN) / tot_ia * 100, 1) if tot_ia > 0 else 0
            alertes_list.append({
                'domaine': 'Qualité', 'kpi': "Fiabilité de l'IA",
                'valeur': f"{ia_fib} %", 'seuil': '< 79.9 %',
                'alerte': ia_fib < 79.9,
                'critique': ia_fib < 70,
            })

            # WIP
            cursor.execute("""
                SELECT COUNT(b.PNo) AS wip FROM tblbufferpos b JOIN tblparts p ON b.PNo=p.PNo
                WHERE p.Type=2 AND b.PNo>0;
            """)
            wip_v = (cursor.fetchone() or {}).get('wip') or 0
            cursor.execute("SELECT COUNT(*) AS t FROM tblbufferpos WHERE PNo>0;")
            buf_t = (cursor.fetchone() or {}).get('t') or 1
            wip_p = round(wip_v / buf_t * 100, 1)
            alertes_list.append({
                'domaine': 'Stock', 'kpi': 'Niveau des en-cours (WIP)',
                'valeur': f"{wip_p} %", 'seuil': '> 30 %',
                'alerte': wip_p > 30,
                'critique': wip_p > 40,
            })

            # Stock MP
            cursor.execute("""
                SELECT COUNT(b.PNo) AS mp FROM tblbufferpos b JOIN tblparts p ON b.PNo=p.PNo
                WHERE p.Type=1 AND b.PNo>0;
            """)
            mp_v = (cursor.fetchone() or {}).get('mp') or 0
            mp_p = round(mp_v / buf_t * 100, 1)
            alertes_list.append({
                'domaine': 'Stock', 'kpi': 'Évolution stock MP',
                'valeur': f"{mp_p} %", 'seuil': '< 70 %',
                'alerte': mp_p < 70,
                'critique': mp_p < 50,
            })

            # Stock PF
            cursor.execute("""
                SELECT COUNT(b.PNo) AS pf FROM tblbufferpos b JOIN tblparts p ON b.PNo=p.PNo
                WHERE p.Type=3 AND b.PNo>0;
            """)
            pf_v = (cursor.fetchone() or {}).get('pf') or 0
            pf_p = round(pf_v / buf_t * 100, 1)
            alertes_list.append({
                'domaine': 'Stock', 'kpi': 'Évolution stock PF',
                'valeur': f"{pf_p} %", 'seuil': '< 60 %',
                'alerte': pf_p < 60,
                'critique': pf_p < 40,
            })

            # MTBF
            cursor.execute("""
                SELECT AVG(TIMESTAMPDIFF(MINUTE, prev_ts, TimeStamp)) AS mtbf FROM (
                    SELECT TimeStamp,
                        (ErrorL0=1 OR ErrorL1=1 OR ErrorL2=1) AS in_error,
                        LAG((ErrorL0=1 OR ErrorL1=1 OR ErrorL2=1))
                            OVER (PARTITION BY ResourceID ORDER BY TimeStamp) AS prev_error,
                        LAG(TimeStamp) OVER (PARTITION BY ResourceID ORDER BY TimeStamp) AS prev_ts
                    FROM tblmachinereport WHERE ResourceID > 0
                ) t WHERE in_error=1 AND prev_error=0;
            """)
            mtbf_v = round((cursor.fetchone() or {}).get('mtbf') or 0, 1)
            alertes_list.append({
                'domaine': 'Maintenance', 'kpi': 'MTBF (Temps moyen entre pannes)',
                'valeur': f"{mtbf_v} min", 'seuil': '< 30 min',
                'alerte': mtbf_v < 30,
                'critique': mtbf_v < 10,
            })

            # MTTR
            cursor.execute("""
                SELECT AVG(TIMESTAMPDIFF(MINUTE, prev_ts, TimeStamp)) AS mttr FROM (
                    SELECT TimeStamp,
                        (ErrorL0=1 OR ErrorL1=1 OR ErrorL2=1) AS in_error,
                        LAG((ErrorL0=1 OR ErrorL1=1 OR ErrorL2=1))
                            OVER (PARTITION BY ResourceID ORDER BY TimeStamp) AS prev_error,
                        LAG(TimeStamp) OVER (PARTITION BY ResourceID ORDER BY TimeStamp) AS prev_ts
                    FROM tblmachinereport WHERE ResourceID > 0
                ) t WHERE in_error=0 AND prev_error=1;
            """)
            mttr_v = round((cursor.fetchone() or {}).get('mttr') or 0, 1)
            alertes_list.append({
                'domaine': 'Maintenance', 'kpi': 'MTTR (Temps moyen de réparation)',
                'valeur': f"{mttr_v} min", 'seuil': '> 15 min',
                'alerte': mttr_v > 15,
                'critique': mttr_v > 30,
            })

    except Exception as e:
        import traceback; traceback.print_exc()
        alertes_list = [{'domaine': 'Erreur', 'kpi': str(e), 'valeur': '-',
                         'seuil': '-', 'alerte': True, 'critique': True}]
    finally:
        db.close()

    nb_alertes   = sum(1 for a in alertes_list if a['alerte'])
    nb_critiques = sum(1 for a in alertes_list if a['critique'])

    return render_template("alertes.html",
                           alertes_list=alertes_list,
                           nb_alertes=nb_alertes,
                           nb_critiques=nb_critiques,
                           **get_sidebar_context())


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
