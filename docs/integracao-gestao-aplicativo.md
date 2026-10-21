# Gestão central e aplicativo operacional

O sistema principal é a única origem de usuários, senhas, empresas, motoristas,
veículos, autorizações e BDTs. O host do piloto é uma entrada operacional para o
mesmo backend. Não é uma segunda administração e não usa uma cópia dos usuários.

## Fluxo

- Proprietário: sistema principal, `/empresas/`, para cadastrar empresa e primeiro
  gestor. O login do gestor é seu e-mail; não há campo separado de username.
- Gestor: sistema principal, `/`, com a interface completa já existente. Em
  `/usuarios/`, cadastrar/editar acessos, selecionar o motorista registrado pela
  CNH e marcar os veículos autorizados. O gestor só vê usuários da própria empresa;
  não pode atribuir privilégios da plataforma nem editar perfis globais.
- Motorista: host operacional, `/api/driver/app/`. Entrar com o mesmo e-mail e senha
  do cadastro principal. No primeiro acesso, trocar a senha inicial em uma tela
  operacional sem o menu desktop. O aplicativo continua com BDT, destinos, KM,
  checklist e fotos.
- Inativação e redefinição de senha em Usuários revogam os tokens antigos. As
  autorizações atualizam a lista de veículos e as próximas aberturas de BDT; viagens
  já iniciadas mantêm seu histórico e não são apagadas.
- Sessões web são separadas por host; não há compartilhamento de cookies de
  domínio amplo nem transferência de senha entre domínios. É a mesma credencial,
  com login em cada superfície, sem promessa de SSO automático.

No host do aplicativo, `/` leva ao app; páginas de gestão levam ao domínio
principal. POSTs de gestão são recusados, sem encaminhar o corpo para outro host.
Gestores não recebem tokens operacionais nem usam o bootstrap no host do app.
A API de acompanhamento do gestor permanece disponível no backend principal,
com sessão e escopo de empresa. O desktop usa `/gestao/bdts/`.

## Ativação no backend principal

Esta entrega é opt-in: `config.company_settings`. `config.settings` mantém a
instalação institucional e `config.driver_settings` mantém o piloto independente
anterior, para permitir uma transição revisada. Não basta atualizar somente o
repositório do piloto para integrar os dados.

As correções de CNH/foto, CRLV e OS da VPS foram reconciliadas na branch de
integração, incluindo a migração fleet/0048 já aplicada na produção. Antes de
publicar, conferir novas alterações locais; não usar reset ou clean.
Confirmar também um superusuário ativo para administrar empresas antes de ativar
o limite por empresa. Usuários institucionais sem Member não ganham uma empresa
por inferência de e-mail/grupo/setor.

No serviço `backend` do sistema principal, manter as credenciais e os volumes
atuais e configurar, após confirmar o domínio de gestão:

```text
DJANGO_SETTINGS_MODULE=config.company_settings
MANAGEMENT_ORIGIN=https://DOMINIO-DA-GESTAO
DRIVER_APP_ORIGIN=https://piloto.transfrota.digital
```

`MANAGEMENT_ORIGIN` é o domínio existente do desktop, não um domínio novo
presumido. Se for usar transfrota.net, confirmar registro, DNS e certificado antes.
Origens devem ser HTTPS, distintas e sem caminhos. O módulo inclui explicitamente
os dois hosts nas listas de Host/CSRF, sem configurar cookies compartilhados.
A configuração do PostgreSQL continua sendo a do **banco principal de frota**.
Nunca trocar esse banco pelo `transfrota_pwa` do piloto.

Fazer dump e guardar a imagem/configuração anterior. Com gravações suspensas,
construir a nova imagem já reconciliada, executar `check`, `makemigrations --check
--dry-run` e `migrate` com o novo settings. As migrações de driverops já são as da
branch anterior; a migração fleet/0048 cria a foto apenas onde ainda não existe.

### Instalação com registros ADM e Lei Seca no mesmo banco

Não usar `--adopt-all-unowned` neste caso. O inventário de 21/10/2026 encontrou
87 veículos ADM (19 ativos e 68 inativos), 26 motoristas ADM, dos quais dois também
possuem BDTs da Lei Seca. Esses dois somam 29 BDTs ADM e 27 BDTs Lei Seca.
O cadastro de motorista é mantido; a propriedade dos BDTs segue a origem e os
vínculos do veículo. Os registros fora do conjunto adotado permanecem no banco,
visíveis à administração da plataforma, sem associação automática à empresa.

Simular o conjunto ADM sem criar empresa permanente nem alterar cadastros:

```sh
python manage.py adopt_legacy_sector --sector adm
```

O comando valida o grafo inteiro (incluindo documentos, fotos, OS e históricos).
Referência a veículo/motorista externo, documento compartilhado com cadastro
externo ou BDT de origem incompatível aborta a transação para revisão. Um BDT
sem veículo só é incluído quando origem e motorista correspondem ao setor.
Cadastros sem setor não são incluídos por suposição. O relatório separa veículos
ativos e inativos; os vínculos do aplicativo preservam a situação de cada um.

Após revisar a simulação e cadastrar explicitamente a empresa:

```sh
python manage.py adopt_legacy_sector --sector adm --company UUID-DA-EMPRESA
python manage.py adopt_legacy_sector --sector adm --company UUID-DA-EMPRESA --apply
```

Vincular o gestor existente explicitamente por Member, sem substituir sua senha
ou criar uma conta duplicada. A ativação dos hosts ocorre depois dessas etapas.
Importações offline posteriores de BDT não deduzem a empresa somente pelo
motorista compartilhado: exigem veículo vinculado e origem compatível.

Os vínculos CompanyVehicle/Member existentes são respeitados. Para uma instalação
legada sem vínculos, o proprietário pode criar a empresa e primeiro gestor; os
registros privados antigos não ficam visíveis a uma empresa por adivinhação.
Somente se TODOS os registros sem proprietário forem da mesma empresa, usar o
comando abaixo primeiro em simulação. Ele valida o grafo e desfaz a transação:

```sh
python manage.py adopt_legacy_company --company UUID-DA-EMPRESA --adopt-all-unowned
```

Após revisão, repetir com `--apply`. Registros já pertencentes a outras empresas
não são transferidos. Uma referência conflitante interrompe a transação. O comando
não copia usuários, senhas, imagens ou dados do banco isolado do piloto. Vínculos
entre contas principais já existentes e empresas precisam ser associados
explicitamente pelo proprietário (Member), sem criar contas duplicadas.

## Fazer o host do piloto usar o backend principal

Incluídos:

- `deploy/integrated/nginx.app.conf`: encaminha os pedidos ao `frota_backend:8000`,
  preservando Host e HTTPS. Recursos estáticos usam o volume da frota principal.
- `deploy/integrated/pilot-proxy.override.yaml`: conecta o proxy já publicado à
  rede principal e substitui o arquivo nginx/volume estático. Configurações locais
  da rede pública, domínio e certificado devem ser mantidas.

No checkout do piloto, depois que o backend principal estiver ativo e validado,
revisar a composição sem criar contêineres:

```sh
docker compose --env-file deploy/pwa/.env \
  -f deploy/pwa/compose.yaml \
  -f deploy/integrated/pilot-proxy.override.yaml config
```

Conferir que o proxy continua na rede pública usada pelo `sied_proxy` e também
na rede `gestao-frotas_default`; que o volume estático é o principal; e que seu
nome/porta continuam os já publicados. Os nomes podem ser configurados por
`MAIN_FLEET_NETWORK`, `MAIN_FLEET_STATIC_VOLUME` e `PUBLIC_PROXY_NETWORK`. Não recriar o SIED.

Guardar dump/imagem do piloto. Trocar somente seu proxy, com `--no-deps`, usando
OS DOIS arquivos compose acima. Isso mantém a identidade de rede que o proxy
externo já usa; testar `nginx -t` e recarregar o `sied_proxy` somente se o IP do
proxy interno tiver mudado. Após validar o login do motorista e o BDT no banco
principal, parar os serviços isolados `web` e `database` do piloto, preservando
seus volumes para conferência/rollback. Não executar `down -v`.

As contas e viagens criadas SOMENTE no banco piloto permanecem nesse banco.
Inventariar e decidir seu destino antes da mudança; esta entrega não as mistura
automaticamente com dados reais. Cadastrar a conta de motorista no sistema
principal antes de testar o host operacional integrado.

## Validação e limites

Testes cobrem cadastro na área Usuários, login por e-mail, troca obrigatória de
senha, mesma credencial na API operacional, autorizações, revogação de token,
separação entre empresas/hosts, bloqueio de POST de gestão no app e adoção legada
em simulação. O teste Chromium cria a conta no desktop e entra com ela no host
operacional. A CI usa PostgreSQL real; não considerar uma atualização de VPS feita
somente por ter publicado esta branch no Git.

As restrições históricas de unicidade global de CPF/CNH, matrícula, placa, chassi,
RENAVAM e contratos continuam exigindo revisão antes de duplicar identidades entre
clientes. As duas falhas preexistentes de template em
`apps.ui.test_dashboard_licensing_cards` continuam documentadas na PR anterior.
Pagamentos seguem fora do escopo.

## Sugestões de endereço no aplicativo

Os campos de destinos sugerem locais ao digitar pelo menos quatro caracteres,
com pausa de 700 ms entre digitação e consulta, resultados brasileiros, cache e
limite de 30 consultas por minuto por usuário. A escolha guarda latitude/longitude
no trecho; Maps e Waze passam a usar esse ponto. Um destino digitado manualmente
continua aceito, inclusive por versões antigas do app. Sugestões não confirmam
número de porta: o motorista deve conferir o local antes de iniciar.

A busca autenticada `/api/driver/addresses/` envia apenas o texto ao geocodificador,
sem conta, empresa, motorista ou posição atual. Sugestões não são armazenadas no
service worker. A atribuição OpenStreetMap/Photon fica junto ao campo.

`DRIVER_GEOCODER_URL` configura um endpoint compatível com Photon; por padrão usa
`https://photon.komoot.io/api/`, demonstração pública sem chave para uso moderado.
Ela não oferece garantia de disponibilidade; para maior volume comercial, usar
instância dedicada ou contratar serviço compatível, em vez de presumir cota
ilimitada. Não usar o Nominatim público para autocomplete. Se a busca falhar,
o app permite informar o endereço completo manualmente.

Publicar a migração driverops/0004 junto do backend principal. Ela acrescenta
coordenadas opcionais aos trechos existentes, sem reescrever BDTs históricos.
O cache da PWA passa à versão 2 para incluir o módulo de sugestões.
