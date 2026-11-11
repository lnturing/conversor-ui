# Conversor .ui → .py (PyQt6)

Site para alunos: envie um arquivo `.ui` do Qt Designer e baixe o `.py` compatível com PyQt6.

```
public/            front-end (estático)
  index.html       estrutura da página
  css/style.css    aparência (tema escuro/claro)
  js/script.js     upload (até 10 arquivos), envio à API, lista de resultados, download .py/.zip
  images/          logo e ícones
  docs/tutorial.pdf  PDF aberto pelo botão "Saiba mais"
api/
  convert.py       back-end Python (Flask) com o conversor próprio: POST /api/convert (recebe o .ui, devolve o .py executável)
requirements.txt   dependências Python (só o Flask)
vercel.json        configuração da hospedagem
```

## Rodar localmente
```
pip install -r requirements.txt
python api/convert.py
```
Abra http://127.0.0.1:5000 — o Flask serve o site e a API juntos.

## Publicar na Vercel
```
npm i -g vercel
vercel
```

## Contrato da API
`POST /api/convert` — corpo: conteúdo bruto do `.ui`; cabeçalho `X-Filename` com o nome original.
Sucesso: `200` com o `.py` (`Content-Disposition: attachment`). Erro: `4xx/5xx` com `{"error": "..."}`.
