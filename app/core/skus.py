"""Nomes amigáveis de SKUs comuns (lista parcial; desconhecidos mostram o Part Number)."""

FRIENDLY_SKU_NAMES: dict[str, str] = {
    "SPE_E3": "Microsoft 365 E3",
    "SPE_E5": "Microsoft 365 E5",
    "SPE_F1": "Microsoft 365 F3",
    "ENTERPRISEPACK": "Office 365 E3",
    "ENTERPRISEPREMIUM": "Office 365 E5",
    "STANDARDPACK": "Office 365 E1",
    "DESKLESSPACK": "Office 365 F3",
    "SPB": "Microsoft 365 Business Premium",
    "O365_BUSINESS_PREMIUM": "Microsoft 365 Business Standard",
    "O365_BUSINESS_ESSENTIALS": "Microsoft 365 Business Basic",
    "O365_BUSINESS": "Microsoft 365 Apps for business",
    "OFFICESUBSCRIPTION": "Microsoft 365 Apps for enterprise",
    "EXCHANGESTANDARD": "Exchange Online (Plano 1)",
    "EXCHANGEENTERPRISE": "Exchange Online (Plano 2)",
    "AAD_PREMIUM": "Microsoft Entra ID P1",
    "AAD_PREMIUM_P2": "Microsoft Entra ID P2",
    "EMS": "Enterprise Mobility + Security E3",
    "EMSPREMIUM": "Enterprise Mobility + Security E5",
    "DEVELOPERPACK_E5": "Microsoft 365 E5 Developer",
    "FLOW_FREE": "Power Automate Free",
    "POWER_BI_STANDARD": "Power BI (gratuito)",
    "POWER_BI_PRO": "Power BI Pro",
    "TEAMS_EXPLORATORY": "Teams Exploratory",
}


def friendly_sku_name(part_number: str) -> str:
    return FRIENDLY_SKU_NAMES.get(part_number, part_number)
