"""
Back-end do conversor .ui -> .py (PyQt6), feito com Flask.

Endpoint: POST /api/convert
  - corpo da requisição: o conteúdo bruto do arquivo .ui
  - cabeçalho X-Filename: nome original do arquivo (codificado com encodeURIComponent)

Respostas:
  - 200: o arquivo .py gerado (Content-Disposition: attachment)
  - 4xx/5xx: JSON {"error": "mensagem"}

Rodar localmente (serve também o site da pasta public/):
  python api/convert.py     ->  http://127.0.0.1:5000
"""

import io
import os
import re
import xml.etree.ElementTree as ET
from urllib.parse import unquote

from flask import Flask, Response, jsonify, request, send_from_directory

MAX_BYTES = 1_000_000  # 1 MB — arquivos .ui reais costumam ter poucos KB
PUBLIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "public")

# static_folder só é usado ao rodar localmente; na Vercel a pasta public/ é servida pela CDN
app = Flask(__name__, static_folder=PUBLIC_DIR, static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = MAX_BYTES


def compile_ui(ui_bytes: bytes) -> str:
    """Converte o conteúdo de um .ui em código Python usando o uic do PyQt6."""
    from PyQt6 import uic  # importado aqui para o erro de ambiente aparecer na resposta

    saida = io.StringIO()
    uic.compileUi(io.BytesIO(ui_bytes), saida)
    return saida.getvalue()


def safe_basename(raw_name: str) -> str:
    """Gera um nome de arquivo seguro (sem caminho, sem caracteres estranhos)."""
    nome = unquote(raw_name or "").replace("\\", "/").split("/")[-1]
    nome = re.sub(r"\.ui$", "", nome, flags=re.IGNORECASE)
    nome = re.sub(r"[^A-Za-z0-9_-]", "_", nome).strip("_")
    return nome or "form"


def erro(status: int, mensagem: str):
    resposta = jsonify({"error": mensagem})
    resposta.status_code = status
    resposta.headers["Cache-Control"] = "no-store"
    return resposta


@app.errorhandler(413)
def arquivo_grande(_):
    return erro(413, "Arquivo muito grande (limite de 1 MB).")


@app.errorhandler(405)
def metodo_invalido(_):
    return erro(405, "Use o método POST para enviar um arquivo .ui.")


@app.post("/api/convert")
def convert():
    conteudo = request.get_data()  # corpo bruto; respeita MAX_CONTENT_LENGTH

    if not conteudo:
        return erro(400, "Nenhum arquivo foi enviado.")

    # validação: precisa ser um XML com raiz <ui>
    try:
        raiz = ET.fromstring(conteudo)
    except ET.ParseError:
        return erro(400, "O arquivo não é um XML válido. Exporte-o novamente pelo Qt Designer.")
    if raiz.tag != "ui":
        return erro(400, "Esse arquivo não parece um .ui do Qt Designer (raiz <ui> não encontrada).")

    # conversão
    try:
        codigo = compile_ui(conteudo)
    except ImportError:
        return erro(500, "O servidor está sem o PyQt6 instalado.")
    except Exception as e:  # erros do uic (widget desconhecido, propriedade inválida etc.)
        return erro(422, f"Não foi possível converter esse .ui: {e}")

    # devolve o .py para download
    nome = safe_basename(request.headers.get("X-Filename", "")) + ".py"
    return Response(
        codigo,
        mimetype="text/x-python",
        headers={
            "Content-Disposition": f'attachment; filename="{nome}"',
            "Cache-Control": "no-store",
        },
    )


@app.get("/api/convert")
def convert_get():
    return erro(405, "Use o método POST para enviar um arquivo .ui.")


@app.get("/")
def index():
    """Só para o uso local: na Vercel o index.html é servido direto da pasta public/."""
    return send_from_directory(PUBLIC_DIR, "index.html")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
