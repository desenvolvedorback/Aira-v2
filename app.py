from flask import Flask, request, jsonify, send_from_directory, render_template_string, session, redirect, url_for
import requests, time, logging, re, os, sqlite3, csv, io
from bs4 import BeautifulSoup
from googlesearch import search
from functools import wraps

# ----------------- CONFIGURAÇÃO ---------------------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "troque_esta_chave")
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # 2 MB

ADMIN_CREDENCIAIS = {
    "admin": "1234",
    "Davi": "oi"
}

def validar_login(usuario, senha):
    return ADMIN_CREDENCIAIS.get(usuario) == senha

UA_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36"}

DB = "logs.db"

# ----------------- BANCO DE DADOS --------------------------------------

def init_db():
    with sqlite3.connect(DB) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts DATETIME DEFAULT CURRENT_TIMESTAMP,
                pergunta TEXT,
                resposta TEXT
            )
        """)
init_db()

def grava_log(pergunta, resposta):
    if not resposta or any(palavra in resposta.lower() for palavra in [
        "não achei", "erro", "falha", "client error", "forbidden", "como posso te ajudar?"
    ]):
        print("Resposta não salva, pois não é útil ou está incompleta.")
        return

    with sqlite3.connect(DB) as con:
        con.execute("INSERT INTO log (pergunta, resposta) VALUES (?, ?)", (pergunta, resposta))

def buscar_resposta_semelhante(pergunta):
    with sqlite3.connect(DB) as con:
        cursor = con.execute("SELECT pergunta, resposta FROM log ORDER BY id DESC")
        for p_salva, resposta in cursor.fetchall():
            if pergunta.strip().lower() == p_salva.strip().lower():
                return resposta
            if pergunta.lower() in p_salva.lower() or p_salva.lower() in pergunta.lower():
                return resposta
    return None

# ----------------- UTILIDADES ------------------------------------------

def resposta_automatica(p):
    p = p.lower().strip()
    cortesias = {
        "oi": "Oi! Como posso te ajudar?",
        "olá": "Oi! Como posso te ajudar?",
        "tudo bem": "Tudo ótimo por aqui! E com você?",
        "bom dia": "Bom dia! Que hoje seja um dia abençoado.",
        "boa noite": "Boa noite! Que você tenha um descanso top!",
        "obrigado": "De nada! Qualquer coisa, tô por aqui.",
        "obrigada": "De nada! Qualquer coisa, tô por aqui.",
        "valeu": "Tamo junto!",
    }
    for k, resp in cortesias.items():
        if k == p or k in p:
            return resp
    return None

def resumir(texto, n=2):
    frases = re.split(r'(?<=[.!?]) +', texto)
    return " ".join(frases[:n]).strip()

def extrair_resumo(link):
    try:
        r = requests.get(link, headers=UA_HEADERS, timeout=6)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        parags = [p.get_text(" ", strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) >= 20]
        return resumir(" ".join(parags[:8]))
    except Exception as e:
        logging.warning("Falha ao acessar %s: %s", link, e)
        return None

def obter_links(q, mx=3):
    vistos, links = set(), []
    for url in search(q, num_results=20, lang="pt"):
        if any(bad in url for bad in ("google.", "pinterest.")) or url.startswith("/"):
            continue
        if url in vistos:
            continue
        vistos.add(url)
        links.append(url)
        if len(links) == mx:
            break
    return links

# ----------------- DECORADOR DE LOGIN ----------------------------------

def login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if session.get("auth"):
            return f(*a, **kw)
        return redirect(url_for("login"))
    return wrapper

# ----------------- HTML EMBUTIDO ---------------------------------------

LOGIN_HTML = """ ... """  # Mantém igual ao original
ADMIN_HTML = """ ... """  # Mantém igual ao original

# ----------------- ROTAS PÚBLICAS --------------------------------------

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/perguntar", methods=["POST"])
def perguntar():
    pergunta = request.get_json().get("pergunta", "").strip()

    # Verifica se é resposta automática (cortesia)
    auto = resposta_automatica(pergunta)
    if auto:
        grava_log(pergunta, auto)
        return jsonify({"resposta": auto})

    # Busca se a pergunta já foi feita antes
    resposta_existente = buscar_resposta_semelhante(pergunta)
    if resposta_existente:
        return jsonify({"resposta": f"(Resposta recuperada do banco)<br><br>{resposta_existente}"})

    # Caso não tenha no banco, faz a pesquisa
    links = obter_links(pergunta)
    respostas = [r for r in (extrair_resumo(l) for l in links) if r]

    if respostas:
        resp = f"Pesquisei e encontrei isso sobre <b>{pergunta}</b>:<br><br>{respostas[0]}"
    else:
        resp = ("Procurei bastante, mas não achei uma resposta clara. "
                "Quer tentar reformular a pergunta?")

    if links:
        fontes = "<br>".join(f'<a href="{x}" target="_blank">{x}</a>' for x in links)
        resp += f"<br><br><b>Fontes:</b><br>{fontes}"

    grava_log(pergunta, resp)
    return jsonify({"resposta": resp})

@app.route("/avaliar", methods=["POST"])
def avaliar():
    logging.info("Feedback: %s", request.get_json())
    return jsonify({"status": "Valeu pelo feedback!"})

# ----------------- ROTAS ADMIN -----------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form.get("user")
        p = request.form.get("pass")
        if validar_login(u, p):
            session["auth"] = True
            return redirect("/admin")
        return "Credenciais inválidas", 403
    with open("login.html", "r", encoding="utf-8") as f:
        html = f.read()
    return render_template_string(html)

@app.route("/logout")
def logout():
    session.clear()
    return "Saiu!"

@app.route("/admin")
@login_required
def admin():
    with sqlite3.connect(DB) as con:
        rows = con.execute("SELECT * FROM log ORDER BY id DESC LIMIT 100").fetchall()
        with open("admin.html", "r", encoding="utf-8") as f:
            html = f.read()
        return render_template_string(html, rows=rows)

@app.route("/download")
@login_required
def download():
    with sqlite3.connect(DB) as con:
        rows = con.execute("SELECT * FROM log").fetchall()
        buf = io.StringIO()
        csv.writer(buf).writerows(rows)
        return buf.getvalue(), 200, {
            "Content-Type": "text/csv",
            "Content-Disposition": "attachment; filename=log.csv"
        }

@app.route("/limpar")
@login_required
def limpar():
    with sqlite3.connect(DB) as con:
        con.execute("DELETE FROM log")
    return redirect("/admin")

# ----------------- EXECUÇÃO --------------------------------------------

if __name__ == "__main__":
    app.run(debug=True)