"""Gera docs/Documentacao-Portal-Provisionamento-M365.pdf a partir de documentacao.html.

Requisitos (somente para quem for regerar o PDF, não para rodar o portal):
    pip install playwright && playwright install chromium
    qpdf (apt install qpdf / choco install qpdf) — junta a capa ao corpo

Uso:
    python docs/pdf/gerar_pdf.py

Duas passagens: a primeira descobre em que página cada capítulo caiu (pelos links do
sumário); a segunda escreve esses números no sumário. A capa sai sem rodapé.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.async_api import async_playwright

AQUI = Path(__file__).resolve().parent
FONTE = AQUI / "documentacao.html"
SAIDA = AQUI.parent / "Documentacao-Portal-Provisionamento-M365.pdf"
QPDF = shutil.which("qpdf") or sys.exit("Instale o qpdf para gerar o PDF.")

RODAPE = """
<div style="width:100%;font-family:Helvetica,Arial,sans-serif;font-size:7.5pt;color:#6b7480;
            padding:0 17mm;display:flex;justify-content:space-between;">
  <span>Portal de Provisionamento de Usuários Microsoft 365 — Documentação</span>
  <span><span class="pageNumber"></span> / <span class="totalPages"></span></span>
</div>"""


async def imprimir(pagina, destino: Path, faixa: str, rodape: bool) -> None:
    extra = {"page_ranges": faixa} if faixa else {}
    await pagina.pdf(
        path=str(destino),
        **extra,
        format="A4",
        print_background=True,
        prefer_css_page_size=True,
        display_header_footer=rodape,
        header_template="<div></div>",
        footer_template=RODAPE if rodape else "<div></div>",
    )


def paginas_dos_destinos(pdf: Path) -> dict[str, int]:
    """Página de cada âncora (#id) do HTML, lida dos destinos nomeados do PDF (qpdf --json)."""
    dados = json.loads(
        subprocess.run(  # noqa: S603 — argumentos fixos, sem entrada do usuário
            [QPDF, "--json", str(pdf)], capture_output=True, text=True, check=True
        ).stdout
    )
    objetos = dados["qpdf"][1]
    indice = {p["object"]: i + 1 for i, p in enumerate(dados["pages"])}
    catalogo = next(
        v["value"]
        for v in objetos.values()
        if isinstance(v.get("value"), dict) and v["value"].get("/Type") == "/Catalog"
    )
    dests = catalogo.get("/Dests", {})
    if isinstance(dests, str):
        dests = objetos["obj:" + dests]["value"]
    return {nome.lstrip("/"): indice.get(alvo[0], 0) for nome, alvo in dests.items()}


async def principal() -> None:
    async with async_playwright() as p:
        navegador = await p.chromium.launch()
        pagina = await navegador.new_page()
        await pagina.goto(FONTE.as_uri())
        await pagina.wait_for_load_state("networkidle")
        await pagina.evaluate("document.fonts.ready")

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            # 1ª passagem: descobrir as páginas
            await imprimir(pagina, tmp / "rascunho.pdf", "", False)
            paginas = paginas_dos_destinos(tmp / "rascunho.pdf")
            alvos = await pagina.eval_on_selector_all(
                ".sumario .pg", "els => els.map(e => e.dataset.alvo)"
            )
            faltando = [a for a in alvos if not paginas.get(a)]
            if faltando:
                sys.exit(f"Sumário: página não encontrada para {faltando}")
            await pagina.evaluate(
                """(mapa) => { for (const [id, n] of Object.entries(mapa)) {
                     const el = document.querySelector(`.pg[data-alvo="${id}"]`);
                     if (el) el.textContent = n; } }""",
                {a: paginas[a] for a in alvos},
            )
            # 2ª passagem: capa sem rodapé + corpo com rodapé
            await imprimir(pagina, tmp / "capa.pdf", "1", False)
            await imprimir(pagina, tmp / "corpo.pdf", "2-", True)
            capa, corpo = str(tmp / "capa.pdf"), str(tmp / "corpo.pdf")
            subprocess.run(  # noqa: S603 — argumentos fixos, sem entrada do usuário
                [QPDF, capa, "--pages", capa, corpo, "--", str(SAIDA)], check=True
            )
        await navegador.close()
    print(f"PDF gerado: {SAIDA} ({SAIDA.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    asyncio.run(principal())
