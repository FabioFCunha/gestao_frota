# Importação e conferência de CNH

A leitura auxilia o preenchimento. Alterações de motorista, histórico e foto só são gravadas após a conferência humana. Não há promessa de OCR sem erros nem porcentagem de confiança inventada.

## Fluxo comercial

Em `config.company_settings`, a leitura em segundo plano e a confirmação explícita estão habilitadas. Enviar um PDF cria uma tarefa persistida no mesmo PostgreSQL e no volume de mídia. O processador (`cnh_worker`) extrai os campos e a foto em um subprocesso limitado a 100 segundos. O serviço tem limite de 1 CPU e 768 MB. A página de acompanhamento pode ser fechada e reaberta.

As situações são: na fila, lendo documento, pronto para conferir, conferência concluída e falha. O gestor acessa o acompanhamento pelo link na tela da CNH. Uma tarefa em execução interrompida há mais de 5 minutos é marcada com falha. É possível repetir até três tentativas por tarefa. Envios idênticos em andamento do mesmo usuário são reaproveitados; há limite de cinco tarefas em andamento por usuário.

A empresa, o usuário, as permissões e o setor são revalidados no processamento. A confirmação continua exigindo que o documento seja do próprio usuário e do motorista selecionado. O banco mantém a proteção de duplicidade e as transações de confirmação. A leitura fica vinculada ao ID e ao SHA-256 da versão original; uma versão substituída, um arquivo modificado, ausente ou arquivado não pode ser confirmado com os dados da leitura anterior. Envios pendentes anteriores a esta atualização devem ser reenviados. Não há associação automática por nome entre cadastros.

## Conferência

- PDF privado ao lado do formulário, com opção de abrir em outra aba.
- Cadastro atual, valor lido e valor a confirmar, incluindo indicação de dados preservados.
- Alertas para leitura incompleta, CPF inválido, registro fora do formato, categoria desconhecida e datas incoerentes. CNH vencida é um alerta, permitindo preservar o histórico documental.
- Na atualização por PDF, valores vazios não apagam os existentes. Na edição manual, a remoção explícita de campos complementares continua possível e auditada.
- CPF com dígitos verificadores inválidos e datas incoerentes são bloqueados na confirmação e na edição manual. Um CPF divergente continua bloqueado, mesmo com confirmação humana.
- Se os identificadores não puderem ser reconhecidos de forma suficiente, o gestor pode usar a edição/cadastro manual já existente, conferindo o documento. A importação não inventa os dados ausentes nem ignora as proteções de identidade.

O original é servido por uma rota autenticada e privada; não é necessário publicar o diretório de mídia. O criador e as permissões são verificados. A foto é preparada em segundo plano e reaproveitada na conferência, evitando repetir o OCR em cada acesso.

## Correção de CPF

Na tela de CNH há uma ação específica para quem possui `fleet.correct_driver_identity`. No modo empresa, o gestor recebe essa permissão e o operador/consulta/motorista não recebem. Superusuários continuam autorizados.

A correção exige novo PDF, CPF válido lido nesse documento, digitação repetida do CPF, nome correspondente, compatibilidade com nascimento e registro já cadastrados, confirmação explícita e justificativa. Uma divergência de nome ou de outros identificadores exige conferência pela administração. A operação bloqueia concorrência, mantém o mesmo motorista e seus vínculos, respeita a restrição global de CPF único e grava autor, data, documento, motivo, valor anterior e novo. Não altera auditorias históricas. O histórico aparece na própria tela da CNH.

## Publicação na VPS existente

O serviço adicional precisa ser publicado junto com o backend. O PostgreSQL, a mídia e o proxy existentes são mantidos.

```bash
cd /root/gestao-frotas

git fetch origin codex/gestao-central-app-operacional-20261020 &&
git merge --ff-only origin/codex/gestao-central-app-operacional-20261020 &&
docker compose build backend cnh_worker &&
docker compose run --rm --no-deps -T backend python manage.py migrate --noinput &&
docker compose run --rm --no-deps -T backend python manage.py check &&
docker compose up -d --no-deps backend cnh_worker &&
docker exec transfrota-pwa-piloto-proxy-1 sh -c 'nginx -t && nginx -s reload' &&
docker exec sied_proxy sh -c 'nginx -t && nginx -s reload' &&
docker compose ps backend cnh_worker
```

A migração `fleet.0049_cnh_import_safety` adiciona a fila e a permissão; não reprocessa nem modifica os motoristas existentes. O backend possui verificação de saúde; em instalações novas o worker aguarda o backend concluir as migrações e começar a escutar.

`CNH_BACKGROUND_IMPORTS=0` permite operar temporariamente com a leitura síncrona. Os envios já enfileirados continuam dependendo do worker. Nenhuma integração paga ou serviço externo de OCR foi introduzido.

## Acompanhamento e manutenção

```bash
docker compose logs --tail=60 cnh_worker
docker compose exec -T backend python manage.py cleanup_cnh_imports
```

A limpeza simula por padrão. `--apply` remove as cópias temporárias de tarefas concluídas/falhadas há mais de sete dias, mantendo os documentos, versões e auditorias. Depois da remoção da cópia temporária de uma falha, é necessário reenviar o PDF. A execução não é agendada automaticamente.

O painel mostra situação, responsável, tentativas e tempo. O worker registra ID da tarefa, situação, duração e tentativas; não registra texto do PDF ou CPF. A quantidade de alertas da leitura fica no registro documental privado. Dados documentais e valores anteriores continuam nas auditorias privadas da empresa. A permissão e o acesso são revalidados, inclusive após reinício do serviço.

## Verificação

Os testes incluem PDFs inválidos/protegidos/excessivos, identificadores, datas, preservação de campos, duplicidade, renovação, foto, confirmação repetida, fila, nova tentativa, processo interrompido, revogação de acesso, propriedade da empresa e correção administrativa com auditoria. PDFs reais fornecidos pelo usuário são usados apenas na validação local protegida, sem incorporá-los ao repositório.

```bash
python manage.py test apps.fleet.test_cnh apps.fleet.test_cnh_front apps.fleet.test_cnh_legacy apps.fleet.test_cnh_safety apps.fleet.test_pdf_import
python manage.py test apps.driverops
```

A qualidade deve continuar sendo verificada com novos modelos e digitalizações autorizadas. Novas versões devem passar por esses testes antes de entrar em produção.
