# Fotos dos modelos no dashboard

Somente os cards de “Frota em Operação” recebem uma área de 110 px entre identificação e informações. Marca, família e ano vêm do cadastro existente, sem mudar CRLV, CNH, revisão ou veículos. A imagem é ilustrativa do modelo; não representa necessariamente a cor ou versão exata da viatura.

## Configuração

Contrate/obtenha a chave customer do IMAGIN.studio e configure o domínio autorizado da aplicação com o fornecedor. Na VPS, edite `/root/gestao-frotas/.env` e acrescente `IMAGIN_CUSTOMER_KEY=` com o valor recebido. Não envie a chave por chat nem faça commit do `.env`. `.env.example` contém somente um valor vazio.

Após atualizar o código, recrie o backend para carregar a variável e coletar o JavaScript:

```bash
docker compose build backend
docker compose run --rm --no-deps -T backend python manage.py check
docker compose up -d --no-deps backend
```

A variável é lida em `config/settings.py`. Sem chave, nenhum pedido é feito ao fornecedor e todos os cards mostram o SVG. O customer aparece na URL do CDN enviada ao navegador conforme o protocolo do serviço; não é uma credencial de autenticação dos usuários. Configure as restrições de domínio com o fornecedor.

## Normalização e cache

Edite `BRAND_ALIASES` e `MODEL_FAMILIES` em `apps/fleet/vehicle_images.py` para novas abreviações e famílias. São exemplos: GM/CHEV → chevrolet, ONIX 10MT LT2 → onix, COROLLA APREMIUMH → corolla e KING GS → king. Não alteramos os valores originais do cadastro.

`url_imagem_veiculo(marca, modelo, ano=None)` usa `urlencode`, angle=23, zoomtype=fullscreen e modelYear somente com ano válido. URLs são guardadas em cache LRU de até 2.048 combinações normalizadas por processo, incluindo a chave para permitir rotação. Nenhum pedido externo ocorre na renderização Django.

O navegador carrega imagens visíveis sob demanda, deduplica o pedido para veículos de mesmo modelo/ano e respeita o cache HTTP do CDN. Timeout de 5 segundos inclui leitura da resposta. Os bytes ficam somente no navegador, sem gravação de imagens no servidor. A documentação exige uso direto do CDN salvo acordo específico: https://docs.imagin.studio/guides/getting-images

## Fallback e diagnóstico

O SVG mantém a mesma altura em falta de marca/modelo/chave, falha HTTP, timeout, CORS, conteúdo diferente de imagem, falha de decodificação ou placeholder. Os cabeçalhos `x-imaginstudio-request-found` e `x-imaginstudio-request-resolved` precisam ser `true` para exibir a imagem. Se qualquer um for `false`, o resultado é tratado como placeholder; se estiverem ausentes, `unverified`. A detecção é conservadora: HTTP 200 sozinho não comprova uma foto real.

Fontes dos cabeçalhos: https://docs.imagin.studio/api-integration/manuals/cdn-return-header-behavior e https://docs.imagin.studio/faq/cors-headers

Sem modificar dados nem baixar imagens no servidor, teste os três modelos:

```bash
docker compose exec -T backend python manage.py check_vehicle_images --samples
```

Depois liste todos os veículos ativos da SEGOV exibidos nos cards que precisam de fallback:

```bash
docker compose exec -T backend python manage.py check_vehicle_images \
  --company 5257b218-6ffe-4e70-a979-86a44a2626d8
```

A saída lista UUID, placa, marca, modelo, ano e motivo, sem revelar chave ou URLs. O comando usa HEAD com timeout de 5s, uma vez por combinação durante sua execução; não altera veículos. Pode demorar até 5s por modelo distinto. Sem `--company` ou `--samples` ele não consulta o banco. HEAD valida disponibilidade e os cabeçalhos, não substitui a inspeção visual humana da correspondência exata do modelo/ano. O navegador também aplica os mesmos critérios às respostas GET.

Motivos: `missing_data` (corrigir cadastro), `missing_customer_key` (configurar chave), `placeholder` (modelo sem imagem confirmada), `unverified` (cabeçalhos ausentes), `invalid_content_type`, `network_error` ou `http_NNN`. Falhas locais do navegador, como conexão/CORS, podem diferir do diagnóstico feito pelo servidor; o elemento do card registra `data-image-state` para inspeção.

## Validação inicial

Corolla, Onix e BYD King tiveram normalização e construção de URL validadas por testes automatizados com chave fictícia. Não havia chave comercial no ambiente de desenvolvimento, por isso os três testes reais retornaram `missing_customer_key`, sem pedido ao CDN. Não é possível afirmar cobertura real nem identificar os fallbacks da frota da VPS antes de configurar a chave e executar os comandos acima.
