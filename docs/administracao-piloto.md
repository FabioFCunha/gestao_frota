# Administração simples do piloto

Endereço: /api/driver/management/ (na homologação HTTPS).
Superusuários podem abrir mesmo sem vínculo com empresa e são encaminhados
para esta tela ao abrir a PWA. Gestores acessam somente sua empresa.

1. Selecionar empresa existente ou cadastrar uma nova (somente administrador da plataforma).
2. Se necessário, usar Vincular meu usuário como gestor desta empresa. O botão
   não transfere um vínculo existente entre empresas.
3. Cadastrar pessoa: nome, login, perfil, senha confirmada e veículos autorizados.
   Motorista cria automaticamente User, Driver e Member; gestor cria User e Member.
4. Cadastrar veículo por placa e KM. O cadastro cria Vehicle, placa, quilometragem
   e vínculo com a empresa em uma única transação.
5. Abrir o veículo na lista para atualizar os motoristas autorizados.
6. Testar o aplicativo com a conta comum de motorista, preferencialmente em janela
   anônima, mantendo o administrador na sessão principal.

Como administrador da plataforma, também é possível selecionar um Driver ou
Vehicle já cadastrado e ainda sem vínculo. Não é necessário duplicar os registros
feitos anteriormente pelo Django admin. Para veículo existente, preencher apenas
a identificação do aplicativo e os motoristas; deixar placa e KM do veículo novo vazios.
Para gestor, deixar veículos e motorista existente vazios.

Permissões: cadastros de pessoas nunca recebem is_staff/is_superuser.
Gestores não conseguem consultar cadastros globais não vinculados nem administrar
outra empresa. As senhas passam pelos validadores Django, não aparecem nas listas,
não são gravadas na auditoria e não são reapresentadas ao ocorrer erro de formulário.
A auditoria registra empresa, autor e cadastros/vínculos alterados.

Não há migrações novas. Alterações cadastrais avançadas, desativação e manutenção
de dados históricos permanecem no Django admin da plataforma nesta versão.

## Atualizar a VPS preservando a publicação feita manualmente

A rede do piloto e o encaminhamento HTTPS foram configurados localmente em
deploy/pwa/compose.yaml e deploy/pwa/nginx.conf. Preserve esses arquivos ao atualizar:

```sh
cd /root/transfrota-pwa-piloto
git status --short
git fetch origin
git diff --name-only HEAD..origin/codex/app-motorista-bdt-20261020 -- deploy/pwa/
```

Se o último comando não listar arquivos, o avanço pode ser aplicado com
git merge --ff-only origin/codex/app-motorista-bdt-20261020.
Se listar arquivos ou houver conflito, não sobrescrever as configurações locais.
Não executar git reset --hard nem git clean.

Depois:
```sh
docker compose --env-file deploy/pwa/.env -f deploy/pwa/compose.yaml up -d --build web
docker compose --env-file deploy/pwa/.env -f deploy/pwa/compose.yaml exec web python manage.py check
```

A recriação do web pode mudar seu IP. Para atualizar a resolução do proxy
interno, valide e recarregue apenas o proxy do piloto:
```sh
docker compose --env-file deploy/pwa/.env -f deploy/pwa/compose.yaml exec proxy nginx -t
docker compose --env-file deploy/pwa/.env -f deploy/pwa/compose.yaml exec proxy nginx -s reload
```

Não é necessário recriar sied_proxy para esta mudança.
