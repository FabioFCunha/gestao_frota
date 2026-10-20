# Transfrota Motorista — homologação

Esta branch inicia o aplicativo nativo Android/iOS e um módulo Django separado.
Não instalar diretamente sobre a VPS: há alterações locais de CNH, CRLV, OS e manutenção
que não estão na main usada como base. Reconcilie o código da VPS em outra branch antes
de integrar. Não executar git reset, git clean ou substituir arquivos em produção.

## Fluxo implementado

1. Administrador da plataforma cadastra empresa, usuário/motorista e veículo atribuído.
2. Motorista entra e abre BDT com destinos ordenados; OS existente é opcional.
3. Confirma KM inicial e vistoria; inicia o primeiro trecho e autoriza localização.
4. Abre Google Maps ou Waze para o destino do trecho ativo.
5. Ao chegar, informa KM final, vistoria, observações e conclui o trecho.
6. O GPS para durante a espera. O próximo trecho exige novo início e confirmação do KM.
7. O retorno é um destino adicional. Inclua-o antes de concluir o último trecho.
8. Concluir o último trecho encerra o BDT; encerramento antecipado exige justificativa e nenhum trecho ativo.
9. BDT não fecha a OS automaticamente. Horários são registrados pelo servidor.
10. Gestor consulta BDTs, vistorias, fotos, auditoria e últimas posições no painel.

O BDT nativo usa tabelas driverops; não altera os BDTs importados do Hórus.
Não há migração de cadastros institucionais para empresas nesta entrega.
Os vínculos com Vehicle/Driver/OS são explícitos e preservam o legado.

## Configurar ambiente isolado

Use cópia do repositório e **banco PostgreSQL de homologação**, sem credenciais de produção.
As migrações antigas usam funções específicas de PostgreSQL; SQLite não é suportado para os testes.

```sh
export DJANGO_SETTINGS_MODULE=config.driver_settings
# Configure DJANGO_SECRET_KEY, DJANGO_ALLOWED_HOSTS e variáveis POSTGRES_* para homologação.
python manage.py check
python manage.py migrate
python manage.py test apps.driverops --verbosity 2
python manage.py runserver
```

Em Docker, passe DJANGO_SETTINGS_MODULE=config.driver_settings somente ao serviço
de homologação. O settings padrão e as URLs atuais de produção permanecem inalterados.
Exponha o ambiente por HTTPS; o celular recusa API HTTP.
Revise o resultado de manage.py check --deploy com configurações próprias do ambiente.

No /admin/ da homologação, um **superusuário da plataforma**:
- cria Company;
- cria usuário comum sem privilégios de staff e Driver;
- cria Member com empresa, usuário, motorista e role driver;
- cria CompanyVehicle com empresa, veículo, identificação/placa e motoristas autorizados;
- cria Member role manager para o gestor (sem necessidade de Driver).

Um usuário pertence a uma empresa nesta versão. Um veículo e um motorista pertencem
a um único vínculo de empresa. Mudar a empresa de cadastros com histórico é bloqueado no admin.
Não atribua grupos institucionais como Operacional aos usuários novos.
Usuários vinculados ao módulo não podem acessar telas/APIs antigas sem escopo de empresa.
Superusuários continuam sendo administradores globais: não entregue esse perfil aos clientes.
A aplicação legada **ainda não é um SaaS completo**; o isolamento vale para este módulo e
o bloqueio de acesso ao legado. Cadastros comerciais completos e planos/cobrança são trabalhos posteriores.

Gestor entra pelo portal com:
`/entrar/?next=/api/driver/panel/`.
Painel: `/api/driver/panel/`. API: `/api/driver/`.
Senha obrigatória deve ser atualizada em `/minha-senha/` antes do login no app.

## Executar o app

```sh
cd mobile/driver
cp .env.example .env
# Ajuste EXPO_PUBLIC_API_URL para sua URL HTTPS de homologação.
npm install
npx expo install --check
npm run typecheck
npx expo run:android
# macOS com Xcode:
npx expo run:ios
```

A base é Expo SDK 55 / React Native 0.83.10. Localização em segundo plano exige
build nativo de desenvolvimento; Expo Go não é a validação deste recurso.
Alternativa com conta Expo e credenciais próprias: EAS build, perfil development ou preview.
Identificadores de pacote são sugestões; registrar contas, assinatura e publicação nas lojas
ainda depende da empresa proprietária. Não há APK ou IPA assinado nesta branch.

Dependências vêm das versões compatíveis publicadas no repositório oficial Expo SDK55.
O primeiro npm install deve gerar um package-lock para ser revisado e versionado antes do release.

## GPS, conexão e bateria

- Coleta somente após início confirmado do trecho. Pára na chegada confirmada.
- Google Maps/Waze navegam externamente; o app mantém a tarefa nativa de localização.
- A troca do destino no navegador acontece ao tocar em Navegar no próximo trecho:
  não controlamos uma sessão de navegação que permaneceu aberta em outro aplicativo.
- Posições ficam em SQLite no dispositivo e são enviadas em lotes de até 200.
  O token fica no SecureStore; não colocar token em URL ou logs.
- Operações de abertura/início/chegada têm UUID e corpo persistidos antes do envio.
  Após perda da resposta, Sincronizar repete a mesma operação sem duplicar registros.
- **Operação inteiramente offline ainda não é permitida**: início/chegada só aparecem
  confirmados depois da aceitação pelo servidor. A fila recupera falhas de envio/resposta.
  Não iniciar outro trecho enquanto houver operação pendente.
- Sessões expiram em 7 dias. É possível entrar novamente com o mesmo usuário mantendo a fila.
  Troca de usuário e saída são bloqueadas quando há BDT ativo ou dados a sincronizar.
- Permissões e otimização de bateria podem interromper GPS, especialmente ao encerrar
  o app no sistema. Não prometer rastreamento contínuo nessas condições.
- Datas do celular precisam estar automáticas. Posições fora do intervalo do trecho
  ficam em quarentena local, contabilizadas no app, e não entram no mapa.
- Painel mostra idade da medição, recebimento e precisão; últimas 1.000 posições por BDT.
  Segmentos diferentes não são ligados por uma linha artificial.
- KM oficial vem do painel informado pelo motorista; não é calculado pelo GPS.
- Fotos exigem conexão nesta versão. Só informar Foto salva após resposta do servidor.
  JPEG é reprocessado sem metadados EXIF e servido por endpoint autenticado.
- O dispositivo mantém a fila no armazenamento privado do app. Definir política de retenção,
  limpeza e eventual criptografia adicional antes de distribuir em escala.
- Não há busca/geocodificação interna: endereços completos são enviados ao navegador.
  Gestor usa tiles públicos OpenStreetMap com atribuição. Contratar/operar infraestrutura
  adequada antes de volume comercial e respeitar a política do provedor.

## API e integridade

POST login retorna Bearer opaco com hash no banco, expiração e associação à empresa.
POST logout revoga a sessão. bootstrap lista apenas veículos atribuídos e BDT ativo.
POST trips cria BDT; POST trips/{id}/{start|finish|append|close}/ controla transições.
Todas essas mutações exigem Idempotency-Key UUID.
GET trips, trips/{id}, trips/{id}/tracking e photos/{id} respeitam empresa e autoria.
Gestores podem consultar a empresa, sem operar viagens em nome de motoristas.
POST trips/{id}/legs/{id}/locations recebe posições com UUID, data ISO com fuso,
latitude, longitude e accuracy; responde accepted e rejected.
POST trips/{id}/legs/{id}/photos recebe multipart image e moment departure/arrival.

Locks no motorista, BDT e veículo serializam as transições; constraints impedem
duplicidade de BDT ativo e de trecho ativo. Um retry não duplica a quilometragem.
Eventos preservam autor, horário e dados da ação. Não há edição/destruição via app.
A vistoria exige oito itens; problema exige observação. Fotos são opcionais.

## Critérios antes de liberar

O workflow Driver app checks executa checks/migrações/testes Django em PostgreSQL,
compatibilidade Expo, TypeScript e export do bundle Android.
Isso não substitui build nativo nem validação em aparelho real.

Homologar com duas empresas e pelo menos dois motoristas:
- isolamento de histórico, veículos, fotos e painel;
- dois logins tentando usar a mesma viatura, KM regressivo e destino fora de ordem;
- ida, espera, retorno, último destino e cancelamento justificado;
- perda de resposta de chegada e repetição após reinício do app;
- rede desligada durante percurso, posterior sincronização e pontos fora de horário;
- Maps/Waze abertos, tela bloqueada, economia de bateria e encerramento forçado;
- vencimento de sessão e reautenticação sem misturar dados entre usuários;
- fotos, permissões recusadas e retomada explícita de GPS.

Antes de produção: reconciliar alterações locais da VPS, backup e restauração ensaiada,
limitação de login compartilhada entre workers/instâncias (o throttle de homologação
usa cache local), limites no proxy, monitoramento, retenção e política de localização,
assinatura dos apps, revisão de dependências/lockfile e teste em Android/iOS.
