// Infraestrutura mínima do Portal de Provisionamento M365.
// Escopo: assinatura (cria o Resource Group e os recursos dentro dele).
targetScope = 'subscription'

@description('Ambiente de implantação.')
@allowed(['lab', 'production'])
param environment string = 'lab'

@description('Região do Azure.')
param location string = 'brazilsouth'

@description('Prefixo dos recursos (3 a 10 letras minúsculas/números).')
@minLength(3)
@maxLength(10)
param prefix string = 'm365up'

@description('SKU do App Service Plan. F1 é gratuito (lab); B1 ou superior para produção.')
@allowed(['F1', 'B1', 'B2', 'S1', 'P0v3', 'P1v3'])
param appServiceSku string = 'F1'

@description('Domínio padrão para novos usuários (ex.: contoso.com).')
param m365DefaultDomain string = ''

@description('Usage Location padrão (ISO 3166 alpha-2).')
param usageLocation string = 'BR'

@description('Fuso horário das admissões (IANA).')
param timezone string = 'America/Sao_Paulo'

@description('Limite diário de ingestão do Log Analytics em GB (controle de custo).')
param logDailyCapGb int = 1

@description('Client ID do App Registration do portal (Sprint 2). Vazio = login não configurado.')
param entraClientId string = ''

@description('Tags adicionais.')
param tags object = {}

var envShort = environment == 'production' ? 'prd' : 'lab'
var allTags = union({ projeto: 'm365-user-provisioning-portal', ambiente: environment }, tags)

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${prefix}-${environment}'
  location: location
  tags: allTags
}

module resources 'modules/resources.bicep' = {
  name: 'resources-${prefix}-${environment}'
  scope: rg
  params: {
    location: location
    prefix: prefix
    environment: environment
    envShort: envShort
    appServiceSku: appServiceSku
    m365DefaultDomain: m365DefaultDomain
    usageLocation: usageLocation
    timezone: timezone
    logDailyCapGb: logDailyCapGb
    entraClientId: entraClientId
    tags: allTags
  }
}

output resourceGroupName string = rg.name
output webAppName string = resources.outputs.webAppName
output webAppUrl string = resources.outputs.webAppUrl
output managedIdentityName string = resources.outputs.managedIdentityName
output managedIdentityClientId string = resources.outputs.managedIdentityClientId
output managedIdentityPrincipalId string = resources.outputs.managedIdentityPrincipalId
output storageAccountName string = resources.outputs.storageAccountName
output tableEndpoint string = resources.outputs.tableEndpoint
output authEnabled bool = resources.outputs.authEnabled
