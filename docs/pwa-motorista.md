# Teste do motorista pela PWA

PWA incluída na mesma branch de homologação e na mesma API do app nativo.
A interface web é servida pelo próprio Django, com JavaScript modular e CSS locais.
Não exige build Node nem dependências Expo para abrir pelo navegador.
O app Android pode continuar usando a API depois da validação das regras.

## Endereço e instalação

Após subir **a homologação**, usando config.driver_settings e banco separado:
- motorista: /api/driver/app/
- gestor: /api/driver/panel/

O motorista entra com a conta vinculada à empresa. O cadastro inicial é descrito
em docs/app-motorista.md. Não usar superusuário nem grupos institucionais para motoristas.
Abra o endereço HTTPS pelo Chrome no Android e escolha Instalar aplicativo ou
Adicionar à tela inicial. No iPhone: Safari, Compartilhar, Adicionar à Tela de Início.
O botão Instalar aparece somente quando o navegador disponibilizar essa opção.

Manifest, ícones PNG 192/512 e service worker ficam em /api/driver/app/.
O service worker controla apenas esse caminho; não controla o painel, as APIs
ou o restante do sistema. Não há token Bearer no navegador: usa sessão Django e CSRF.
Todas as mutações precisam de sessão válida e proteção CSRF, inclusive fotos e GPS.

## Roteiro de teste

1. Selecionar veículo e OS opcional; digitar ida e retorno, um endereço por linha.
2. Abrir BDT, preencher vistoria e confirmar KM inicial.
3. Iniciar trecho, autorizar localização e abrir Maps/Waze se desejado.
4. Voltar à PWA, informar KM final, vistoria e concluir trecho.
5. Iniciar o próximo trecho somente quando for sair.
6. Encerrar o último destino e conferir histórico e painel do gestor.
7. Testar foto de saída/chegada antes de concluir cada trecho.
8. Testar conexão interrompida e o botão Sincronizar sem repetir manualmente a operação.

As fotos são opcionais, até 5 MB, JPEG/PNG, e precisam de conexão.
O último destino encerra o BDT: cadastre o retorno antes de concluir a última chegada.
A OS não é fechada automaticamente.

## Localização e offline

A PWA não oferece GPS contínuo em segundo plano. A coleta é interrompida
explicitamente quando a página fica oculta; pode ser retomada ao retornar se já
autorizada durante esta sessão. Abrir Maps/Waze, trocar de app ou bloquear a tela
produz lacunas no percurso. A tela avisa isso; não usar esse piloto como rastreador.

Posições e comandos são persistidos em IndexedDB, associados ao motorista.
Repetir uma operação utiliza o mesmo UUID e corpo, evitando duplicação após perder
a resposta. Abertura, início e chegada só são confirmados após resposta do servidor.
Fotos não têm fila offline. Não apagar dados do navegador com operações pendentes.

O cache armazena somente a estrutura genérica e recursos da PWA: não armazena
respostas da API, fotos, histórico ou dados pessoais. Após reabrir offline, a
estrutura pode carregar, mas é preciso conexão para recuperar sessão e BDT.
Uma conta diferente não pode enviar a fila de outro motorista.
A sincronização exige página aberta, sessão válida e rede; não depende de
Background Sync e não promete execução quando o navegador estiver fechado.

## Antes de testar na VPS

Não fazer checkout sobre /root/gestao-frotas com alterações locais.
Preservar/reconciliar CNH, CRLV, OS e manutenção primeiro. Criar outro checkout e
banco de homologação. Configurar host, HTTPS, CSRF_TRUSTED_ORIGINS e settings
de homologação. Não alterar o proxy compartilhado com SIED sem revisar a configuração.
Nenhum endereço público de homologação é criado automaticamente por esta branch.

## Verificação

CI: testes Django de sessão/CSRF/manifest/cache, regras JS no Node e fluxo completo
em Chromium com Playwright (BDT com ida e retorno). Teste de navegador automatizado
não substitui instalação e permissões em celular físico.
