# GESTATI no Render — demonstração do TCC

Atualizado em 12/11/2026: conta Render criada por Gabriel usando GitHub e painel conferido. Repositório privado existente identificado: [Gabriel-de-Souza-Prado/gestati](https://github.com/Gabriel-de-Souza-Prado/gestati). Código preparado e verificado localmente; **ainda não publicado no Render**. Autenticação Git concluída e confirmada por fetch; histórico remoto integrado preservando os arquivos locais. Versão atual enviada à main no commit444f409, com histórico anterior preservado. Publicação no Render ainda pendente.

## Decisões recebidas de Gabriel

- A primeira publicação será para demonstrar o TCC com dados fictícios.
- Gabriel já tinha GitHub e agora confirmou a criação da conta Render usando esse GitHub; o painel autenticado foi conferido.
- O Render foi recomendado pelo professor. A preparação abaixo atende a esse caminho; não transforma a demonstração em implantação municipal/piloto com dados reais.
- O banco local e as contas existentes devem permanecer separados da demonstração. Nenhum banco/dump real será enviado automaticamente.

## Avaliação e limites consultados em12/11/2026

Render suporta Django e PostgreSQL, permite publicar por repositório Git e fornece uma URL do serviço. É compatível com o monólito/MTV atual; não exige converter a aplicação em site estático ou reescrever seus módulos.

O Blueprint preparado usa planos Free para aplicação e banco. É uma configuração de demonstração, não uma contratação paga. Conferir a seleção e as condições exibidas no painel antes de criar os recursos:

- O serviço web gratuito pausa após15 minutos sem tráfego e pode levar aproximadamente um minuto para iniciar no acesso seguinte.
- O PostgreSQL gratuito tem1GB e expira30 dias após a criação. Após expirar fica inacessível sem upgrade; existe período adicional de14 dias para upgrade antes da exclusão dos dados pelo provedor. Isso não significa que o banco seja gratuito permanentemente.
- O plano gratuito não oferece terminal remoto nem backups gerenciados de PostgreSQL. Por isso a primeira conta terá inicialização própria e os dados devem ser exclusivamente fictícios.
- O sistema de arquivos do serviço é efêmero. Estado operacional fica no PostgreSQL; PDFs atuais são gerados a partir dos registros, sem depender de arquivos salvos nesse disco.

Se a demonstração precisar permanecer disponível além dessas condições, avaliar o banco/plano antes da expiração. Nenhum plano pago, outro provedor ou gasto foi escolhido nesta etapa. Não usar preços antigos dos planos legados como orçamento atual.

Fontes oficiais:

- [Django no Render](https://render.com/docs/deploy-django).
- [Limites do gratuito](https://render.com/docs/free).
- [Planos e preços — conferir ao contratar](https://render.com/pricing).
- [Referência do Blueprint](https://render.com/docs/blueprint-spec).
- [Versão de Python](https://render.com/docs/python-version).
- [Configuração do WhiteNoise](https://whitenoise.readthedocs.io/en/stable/django.html).
- [Orientações de implantação do Django](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/).

## O que já foi preparado na pasta

| Arquivo | Função |
|---|---|
| config/settings_production.py | Configuração da hospedagem: DEBUG=False, PostgreSQL por DATABASE_URL, domínio explícito, HTTPS/cookies seguros e estáticos WhiteNoise. Exige os segredos do ambiente; não usa a chave/banco local como fallback da hospedagem. |
| render.yaml | Serviço web e PostgreSQL Free, mesma região Oregon, banco acessível somente na rede interna, chave gerada pelo provedor e campos privados para a primeira conta. Atualizações automáticas por commit desativadas nesta proposta. |
| build.sh | Instala dependências da hospedagem e executa collectstatic. Seleciona configuração de produção e exige as variáveis antes de executar. |
| start.sh | Aplica migrações no banco configurado da demonstração, inicializa a primeira conta quando autorizado e inicia Gunicorn WSGI no PORT informado pelo Render. Um worker e duas threads como configuração inicial. |
| .python-version | Fixa Python3.14.10, conferido no ambiente local e documentado como suportado pelo Render na consulta atual. |
| requirements.txt / requirements.in | Dependências comuns registradas; acrescentados dj-database-url3.1.2 e WhiteNoise6.12.0. |
| requirements-render.txt | Inclui as comuns e Gunicorn27.0.0 para Linux. O Windows continua usando runserver. |
| contas/management/commands/inicializar_admin.py | Primeira conta sem terminal remoto, sem senha no código e sem redefinir contas existentes. |
| /health/ | Consulta mínima de disponibilidade da aplicação/banco, sem autenticação, sem dados de negócio/segredos, sem cache; indisponibilidade retorna503. |

Não executar os scripts de hospedagem no dia a dia local. O comando de desenvolvimento continua .\.venv\Scripts\python.exe manage.py runserver. As novas bibliotecas comuns foram instaladas na.venv existente, sem reinstalar Python/Django/PostgreSQL. Gunicorn foi fixado para o servidor Linux; não foi executado no Windows.

Git local inicializado na branch main, sem commit. O remoto origin aponta para o repositório privado existente de Gabriel; nenhum arquivo foi enviado pelo agente. A main remota tem o commit inicial e ainda não inclui as mudanças recentes. Comparação com ZIP baixado pela sessão GitHub: 235 arquivos candidatos da aplicação/guia, sendo19 novos e59 alterados após normalizar quebras de linha; os demais já existem iguais. O arquivo baixado não contém.gestati.local.json nem arquivos.env. Credenciais locais,.venv, estáticos coletados e exports de banco ficam fora do versionamento pelas regras do.gitignore. Não anexar/copiar.gestati.local.json ao GitHub ou Render.

## Autenticação Git concluída —12/11/2026

Gabriel concluiu o login pelo executável Git do runtime do Codex. Fetch autenticado confirmado; main local passou a acompanhar o histórico inicial remoto com reset --mixed, preservando todos os arquivos de trabalho. Não usar reset --hard nem force push. O Git do runtime ainda não está no PATH do PowerShell do usuário. Integrações GitHub/Render não estão instaladas; autenticação Git é independente delas.

Envio realizado: commit444f409,78 arquivos, sem segredos/banco/evidências/referências. Regras remotas anteriores de.gitignore/.gitattributes preservadas, acrescentando guia hospedagem e LF de scripts.61 templates compilados após limpeza de espaços em branco;311 testes completos continuam sendo da preparação anterior.

Próximo: Gabriel confirmar Install na aba GitHub Installing Render, preparada com Only select repositories e somente Gabriel-de-Souza-Prado/gestati selecionado. Isso concede ao app Render leitura de código/metadados e as permissões de integração listadas pelo GitHub nesse repositório. A confirmação ainda não foi feita pelo agente. O painel Render inicialmente listou apenas outro vínculo GitHub; não selecionar aquele projeto. Depois da instalação, voltar à seleção Blueprint e conectar gestati/main/render.yaml. Credenciais da primeira conta devem ser preenchidas pessoalmente no painel, sem envio pelo chat.

## Etapas seguintes, após conta e repositório

1. Após autenticar o Git, buscar o histórico do repositório existente e integrar a pasta sem sobrescrever os arquivos locais. Não forçar push nem substituir o commit inicial remoto por um histórico independente.
2. Revisar o diff e a identidade do commit; enviar os arquivos atuais para a main preservando histórico e visibilidade privada. Publicar código/dependências/migrações/templates/estáticos/scripts e documentação pertinente; não enviar configuração local, banco, exportações ou ambiente virtual. Referências acadêmicas e evidências não precisam integrar o envio.
3. No Render, criar um Blueprint ligado ao repositório com render.yaml. Conferir serviço/banco Free e a expiração antes de aplicar. Render usa o repositório ligado ao Blueprint; não há URL de repositório alheio fixa no arquivo.
4. No painel privado, definir GESTATI_ADMIN_USERNAME e GESTATI_ADMIN_PASSWORD para a primeira conta. São credenciais novas da demonstração, diferentes da conta local. A senha deve atender aos validadores do Django. Não colocá-la no YAML, em mensagem ou comando versionado.
5. Aguardar banco, build e início do serviço. Migrações vão para o banco novo apontado pelo próprio Blueprint, nunca para localhost5432 do usuário. Nenhum conjunto demonstrativo é inserido automaticamente.
6. Abrir a URL HTTPS fornecida pelo Render, entrar com a primeira conta e definir a senha pessoal exigida pelo fluxo existente. Essa conta técnica inicial serve para preparar contas da demonstração.
7. Após confirmar o primeiro acesso, retirar GESTATI_ADMIN_PASSWORD do ambiente do serviço. A inicialização é idempotente: banco com qualquer usuário não tem contas/senhas/permissões alteradas e não exige repetir a senha de bootstrap nos próximos inícios. Não usar esse mecanismo para redefinição administrativa.
8. Conferir login, permissões, temas/estáticos, PDFs, estoque/configuração e operações com dados fictícios. Somente depois considerar a publicação demonstrativa concluída. A verificação real do Gunicorn no Linux será nessa implantação, pois o teste local usou o mesmo aplicativo WSGI com o Python do Windows.

Atualizações futuras são manuais nesta configuração. Start executa migrações; revisar migrações e preservação/backup antes de atualizações com dados relevantes. Produção municipal real continua etapa distinta, com definição própria de acesso, responsabilidades e restauração.

## Verificações realizadas nesta preparação

- 311 testes completos aprovados no PostgreSQL isolado127.0.0.1:55432, com diretório de dados conferido antes de testar.12 novos casos de configuração/health/inicialização, incluindo concorrência da primeira conta e preservação de contas existentes.
- Blueprint validado contra o esquema oficial https://render.com/schema/render.yaml.json; planos gratuitos/banco interno conferidos. Scripts com LF, com proteção contra executar comandos de hospedagem sem variáveis/configuração adequadas.
- collectstatic com configuração de produção:144 arquivos coletados e432 processados. Login e oito recursos com nomes hash foram servidos pelo aplicativo WSGI/WhiteNoise com DEBUG=False no teste local.
- Health consultou somente a instância isolada; redirecionamento HTTPS conferido. Conta fictícia inicial autenticou sem diferença de caixa e recebeu troca obrigatória; repetição não alterou senha/conta.
- pip check sem conflitos. Nenhum model/migração novo, nenhuma leitura/exibição de credencial local e nenhuma operação sobre o banco real.
- check --deploy não apontou erro impeditivo, mas registrou **security.W005 e security.W021**: política HSTS não se estende a subdomínios e não solicita preload. São escolhas explícitas desta demonstração com domínio ainda não publicado; HSTS de uma hora/HTTPS/cookies seguros estão configurados. Não alegar que esse comando passou sem avisos nem ocultar os avisos. Reavaliar política de domínio/HSTS em hospedagem definitiva.

O teste Windows/WSGI e a validação do Blueprint não substituem build/HTTP/Gunicorn no Render. A conta Render está criada; aplicação/banco hospedados, custos e URL ainda não foram confirmados. A comparação de models/migrações também terminou sem mudanças. A instância PostgreSQL isolada permanece encerrada; não pressupor portas de QA disponíveis na próxima retomada. Esta conferência de conta/repositório não alterou o código nem reexecutou a suíte de311 testes da preparação anterior.
