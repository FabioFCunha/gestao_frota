# Empresas e interface completa no piloto

Esta versão usa `config.driver_settings` e o banco separado do piloto. O modo
institucional (`config.settings`) mantém o comportamento anterior. Não aplicar
esta branch à instalação de produção nem ao SIED.

## Fluxo de uso

1. O proprietário (superusuário) entra em `/api/driver/management/` e cadastra,
   no mesmo formulário, a empresa, nome/e-mail do gestor, login e senha.
2. O gestor entra em `/` e usa a interface completa da frota: veículos, motoristas,
   manutenção, contratos, multas, vistorias e ordens de saída. O painel exibe sua
   empresa, sem exigir setores ADM/Lei Seca.
3. Em Motoristas, cadastrar pela CNH em PDF e conferir antes de salvar.
   Em Veículos, cadastrar pelo CRLV e conferir antes de salvar. A alternativa
   manual existente continua disponível.
4. Em **Acessos e motoristas**, criar o login e selecionar o motorista já
   cadastrado pela CNH. Autorizar os veículos que poderá usar no aplicativo.
   Também é possível criar acessos de gestores, desativar/reativar usuários e
   redefinir senhas. Gestores não recebem acesso ao Django admin.
5. Veículos cadastrados pela interface entram automaticamente na lista de
   autorizações do aplicativo. Motoristas usam `/api/driver/app/`; gestores
   acompanham os BDTs em `/api/driver/panel/`.

O proprietário não precisa cadastrar a frota de cada cliente. Seu painel mostra
empresas e acessos; a operação fica com os gestores. Billing permanece fora desta entrega.

## Isolamento e migração

`RecordOwner` associa os registros UUID do domínio à empresa. O escopo do pedido
filtra as consultas quando o SQL é compilado, inclusive QuerySets declarados nas
classes de API/formulários. Há verificações de gravação, chaves estrangeiras,
vínculos genéricos de documentos, agregações e joins em catálogos compartilhados.
Senhas nunca são registradas na auditoria. Downloads de PDFs passam pela API
com autenticação; gestores não acessam arquivos diretamente em `/media/`.

Marcas/modelos e catálogos previamente sem proprietário continuam compartilhados.
Catálogos compartilhados são protegidos contra alteração por empresas; novos
status/tipos privados são associados à empresa. Comandos offline sem escopo
continuam sendo operações da plataforma. Consultas SQL diretas estão bloqueadas
no contexto da empresa. Novos endpoints devem manter os managers e validar
vínculos; não usar SQL direto nem remover o escopo para atender pedidos de clientes.

A migração `0003` parte apenas dos vínculos explícitos de CompanyVehicle e Member
já existentes. Associa seus históricos, documentos e registros dependentes.
Registros privados sem vínculo ficam visíveis somente ao proprietário. A migração
interrompe em caso de vínculos conflitantes entre empresas, sem escolher um dono
arbitrariamente. Corrigir os vínculos antes de repetir. Os vínculos novos têm a
mesma proteção contra transferência silenciosa.

As restrições históricas de unicidade de CPF/CNH, matrícula, placa, chassi,
RENAVAM e número de contrato continuam globais. Cadastros duplicados entre
empresas ainda exigem revisão de esquema antes de oferecer essa possibilidade.
A entrega é para homologação, não uma certificação de prontidão comercial.

## Atualização compartilhada

As empresas usam a mesma instalação e código. Publicar uma atualização no piloto
atualiza o backend para todas; ao abrir ou atualizar a página, cada gestor recebe
a nova interface. A PWA busca recursos pela rede e usa cache apenas como fallback
offline. Uma tela já aberta não se substitui instantaneamente; concluir/sincronizar
operações pendentes antes de recarregar. Os dados e permissões permanecem separados.

## Aplicar na VPS do piloto

Revisar os checks PostgreSQL e navegador da PR antes de publicar. Não há acesso SSH
nesta sessão: estes comandos são executados pelo operador da VPS.

```sh
cd /root/transfrota-pwa-piloto
git status --short
git fetch origin
git diff --name-only HEAD..origin/codex/empresas-interface-completa-20261020 -- deploy/pwa/
```

O último comando deve ficar sem saída. Os ajustes locais de rede e HTTPS em
`deploy/pwa/compose.yaml` e `deploy/pwa/nginx.conf` são mantidos; não usar
`git reset --hard`, `git clean` ou restaurar esses arquivos. Se houver alterações
locais nos arquivos de aplicação também modificados pela branch, conciliar antes.

```sh
git merge --ff-only origin/codex/empresas-interface-completa-20261020
bash scripts/update-company-pilot.sh
```

O script salva a configuração e a imagem anterior, constrói e valida o Django.
Pausa brevemente o web do piloto para impedir gravações durante o dump PostgreSQL
e a migração de vínculos. O banco continua ligado. Se o dump ou a migração falhar,
reinicia o contêiner antigo; na atualização, recria somente web e espera sua saúde.
Recarrega o proxy interno para resolver o novo IP do web.
O `sied_proxy` e a produção não são recriados. Em falha de migração, o script para
antes da troca do web; não continuar manualmente sem resolver a causa.

Backup: `/root/transfrota-backups/companies-<data-hora>/`. Para rollback de código,
usar a imagem etiquetada `transfrota-company-rollback:companies-<data-hora>` em um
override temporário de compose (sem `build`), recriar somente web e recarregar o
proxy interno. As novas tabelas são compatíveis com o código anterior; não restaurar
o banco nem apagar tabelas automaticamente. Um restore de banco exige parada e
conferência das alterações feitas depois do backup.

Após publicar, testar com dois gestores em sessões separadas: listas, tentativa
de abrir UUID da outra empresa, CNH/CRLV, autorização de veículo, login de motorista,
abertura/fechamento de BDT e retorno ao painel da frota.

## Verificações desta entrega

Os testes de empresa cobrem UI, APIs, QuerySets lazy/cache, joins de catálogos,
contagens, gravações, formulários, PDFs, redefinição de senha e migração de vínculos.
O workflow executa esses testes com PostgreSQL 16 e o fluxo PWA/empresa em Chromium.

Localmente: 41 testes de backend/empresa passaram (2 de navegador pendentes);
83 testes de regressão de CNH/CRLV/OS passaram (3 ignorados); 4 testes JS passaram.
Django check e verificação de migrações passaram.

Foi usado SQLite com uma função determinística REGEXP_REPLACE apenas
no executor de testes, para compatibilidade com a migração antiga de CPF/CNH.
Esse executor não modifica configurações da aplicação. A suíte antiga completa
apresenta duas falhas preexistentes em `apps.ui.test_dashboard_licensing_cards`,
reproduzidas também no commit base `3b13bfa`; não são falhas novas de isolamento.
O download local do Chromium não terminou corretamente; os dois testes de navegador
são executados no workflow com PostgreSQL e Chromium. Consultar o resultado da CI na PR.

As correções feitas só na VPS de produção (incluindo foto da CNH e ajustes locais
de extração/OS) não são importadas automaticamente desta instalação. Reconciliar
esses diffs antes de substituir a produção. A correção conhecida que impede
interpretar “LEIA O QR CODE E BAIXE” como chassi foi incluída e tem teste de regressão.
