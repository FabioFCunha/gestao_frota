# Fotos de modelos — Wikimedia Commons

A integração anterior com IMAGIN foi substituída por um catálogo local de fotografias do Wikimedia Commons. Não há chave, assinatura nem busca externa durante a renderização do painel. A variável IMAGIN_CUSTOMER_KEY não é mais usada e pode ser removida do `.env`.

## Catálogo inicial e créditos

Os modelos Corolla, Onix e King têm fotos reais revisadas. São fotografias ilustrativas: ano, cor, versão e mercado podem diferir da viatura. A foto usada para King é do BYD Destroyer 05, denominação chinesa do modelo, com essa identificação explícita na página de créditos.

`apps/fleet/data/vehicle_images.json` guarda o nome original, autor, página de origem, licença, link da licença e informação sobre redimensionamento. As miniaturas foram geradas pelo próprio Commons, sem recorte ou remoção de fundo. Créditos resumidos aparecem em cada card; o link “Créditos das fotos” abre todas as atribuições e licenças.

As imagens ficam em `static/ui/vehicle_models/` e são servidas pela própria aplicação. Não dependem de links externos de terceiros no dia a dia. O browser usa lazy loading, cache HTTP e deduplicação, com timeout de 5s e validação de content-type para o arquivo local. Falhas e modelos não catalogados mantêm o SVG discreto sem quebrar os cards.

## Adicionar novos modelos

1. Localize uma foto no Wikimedia Commons e confira modelo/carroceria/geração e licença na página do arquivo.
2. Use foto com licença compatível com uso comercial: CC0, CC BY 4.0, CC BY-SA 3.0 ou CC BY-SA 4.0. Não importe uma imagem só por aparecer na busca.
3. Baixe uma miniatura apropriada para os cards em `static/ui/vehicle_models/` e adicione entrada `marca/familia` ao JSON com todos os créditos.
4. Preserve o crédito, o link da licença e a identificação de alterações; para adaptações de CC BY-SA, observe as condições da licença correspondente.
5. Atualize o backend/collectstatic. O catálogo é carregado uma vez por processo.

Abreviações de CRLV continuam em `BRAND_ALIASES` e `MODEL_FAMILIES` de `apps/fleet/vehicle_images.py`. O cadastro original não é alterado. Por ora as imagens são por família, sem garantir correspondência ao ano; uma família ainda não revisada recebe fallback. Não há busca automática pelo primeiro resultado da internet.

## Verificar na VPS

```bash
docker compose exec -T backend python manage.py check_vehicle_images --samples
docker compose exec -T backend python manage.py check_vehicle_images \
  --company 5257b218-6ffe-4e70-a979-86a44a2626d8
```

Os comandos consultam somente o catálogo e arquivos locais, sem rede e sem modificar dados. O relatório da empresa usa os mesmos veículos ativos com placa atual do dashboard. Motivos: `missing_data`, `missing_catalog` ou `missing_file`. Informe a lista de modelos sem catálogo para ampliar a seleção revisada.

## Atualização

Faça fetch/merge da branch de integração, build e recrie o backend. O comando de inicialização existente coleta os estáticos. Recarregue os proxies após recriar o container para renovar a resolução do endereço do backend.

Referências: https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia e páginas de cada arquivo registradas no JSON.
