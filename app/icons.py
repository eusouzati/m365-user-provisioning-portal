"""Ícones SVG (desenho próprio, traço de 1,75 px, grade 24×24) — sem dependências externas.

Usados nos templates com ``{{ icone("inicio") }}``. São decorativos (aria-hidden): o texto
ao lado é que descreve a ação.
"""

from __future__ import annotations

from markupsafe import Markup, escape

ICONES: dict[str, str] = {
    "inicio": '<path d="M3.5 10.5 12 3.5l8.5 7"/><path d="M5.5 9v11h5v-6h3v6h5V9"/>',
    "solicitacoes": '<rect x="5" y="3" width="14" height="18" rx="2.5"/>'
    '<path d="M9 8h6M9 12h6M9 16h3.5"/>',
    "aprovacoes": '<circle cx="12" cy="12" r="8.5"/><path d="m8.5 12.3 2.4 2.4 4.6-5"/>',
    "equipe": '<circle cx="9" cy="8.5" r="3.3"/><path d="M3 19.5c0-3.4 2.7-5.6 6-5.6s6 2.2 6 5.6"/>'
    '<circle cx="16.8" cy="9.3" r="2.4"/><path d="M16.2 14c2.8.2 4.8 2.2 4.8 5.5"/>',
    "admin": '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/>'
    '<circle cx="9" cy="17" r="2"/>',
    "menu": '<path d="M4 6.5h16M4 12h16M4 17.5h16"/>',
    "sol": '<circle cx="12" cy="12" r="3.8"/><path d="M12 2.5v2M12 19.5v2M5.3 5.3l1.4 1.4'
    'M17.3 17.3l1.4 1.4M2.5 12h2M19.5 12h2M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/>',
    "lua": '<path d="M19.5 14.5A7.8 7.8 0 0 1 9.5 4.5a7.8 7.8 0 1 0 10 10Z"/>',
    "auto": '<circle cx="12" cy="12" r="8.5"/><path d="M12 3.5a8.5 8.5 0 0 1 0 17Z" '
    'fill="currentColor" stroke="none"/>',
    "sair": '<path d="M10 4H6.5A2.5 2.5 0 0 0 4 6.5v11A2.5 2.5 0 0 0 6.5 20H10"/>'
    '<path d="m15 8 4 4-4 4M19 12H9.5"/>',
    "recolher": '<rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/><path d="M9 4.5v15"/>'
    '<path d="m15.5 10-2 2 2 2"/>',
    "usuario_novo": '<circle cx="10" cy="8" r="3.8"/><path d="M3.5 20c0-3.8 2.9-6.2 6.5-6.2 1.1 0 '
    '2.2.2 3.1.7"/><path d="M18 14.5v6M15 17.5h6"/>',
    "usuario_sair": '<circle cx="10" cy="8" r="3.8"/><path d="M3.5 20c0-3.8 2.9-6.2 6.5-6.2 1.1 0 '
    '2.2.2 3.1.7"/><path d="M15 17.5h6"/>',
    "seta": '<path d="M5 12h14M13.5 6.5 19 12l-5.5 5.5"/>',
    "escudo": '<path d="M12 3.5 5 6.2v5.3c0 4.2 2.9 7.6 7 9 4.1-1.4 7-4.8 7-9V6.2Z"/>',
}


def icone(nome: str, classe: str = "") -> Markup:
    corpo = ICONES[nome]  # KeyError em nome errado: falha nos testes, não em produção
    cls = escape(f"icone {classe}".strip())
    # corpo vem da constante ICONES acima (nunca de entrada do usuário); a classe é escapada
    return Markup(  # noqa: S704
        f'<svg class="{cls}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">{corpo}</svg>'
    )
