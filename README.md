# GESTATI

Aplicação web para gestão interna dos ativos de TI. PostgreSQL, usuário próprio, login/logout, início protegido, administração inicial de contas e cadastros de departamentos, fornecedores e categorias implementados. Catálogo de componentes e entradas de estoque também implementados. Ativos, perfis, garantia e composição inicial com consumo também implementados. OS, intervenções de instalação/retirada/retorno e PDF também implementados. Transferências, empréstimos, baixa/recuperação e relatórios também implementados. Revisão atual: erros, autenticação, busca de OS e aparência conforme REVISAO-ACESSO-APARENCIA.md.

## Executar no Windows

Para a demonstração online do TCC, ler [HOSPEDAGEM-RENDER.md](HOSPEDAGEM-RENDER.md). Configuração preparada/testada localmente; ainda não publicada. O uso local abaixo continua igual.

### Iniciar no dia a dia — ambiente já preparado

No terminal PowerShell do VS Code, executar:

```powershell
cd C:\Users\gabriel.prado\Desktop\gestati
.\.venv\Scripts\python.exe manage.py runserver
```

O comando usa o Python do ambiente virtual e inicia o servidor local. Quando aparecer `Starting development server at http://127.0.0.1:8000/`, abrir esse endereço no navegador. Manter o terminal aberto; `Ctrl+C` encerra o servidor. Para carregar alterações do backend, encerrar e executar o mesmo comando novamente. Configuração, migrações e administrador do ambiente atual já foram preparados; não repetir a sequência de instalação abaixo apenas para iniciar o sistema.

### Preparação inicial — referência para uma instalação nova

Abrir esta pasta no VS Code. Python 3.14.8, Django 5.2.18 e Psycopg 3.3.6 foram verificados. Ambiente e dependências já foram preparados na sessão atual; para uma instalação nova, seguir PREPARACAO-DO-AMBIENTE.md e instalar requirements.txt em uma `.venv`.

Banco e papel `gestati` / `gestati_app` foram criados e o usuário confirmou login no psql. Executar no PowerShell, um comando de cada vez:

```powershell
.\.venv\Scripts\python.exe configurar_ambiente.py
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py createsuperuser
.\.venv\Scripts\python.exe manage.py runserver
```

O primeiro comando solicita a senha local do PostgreSQL, confirma a conexão e grava `.gestati.local.json`. Esse arquivo guarda senha e chave do Django e está excluído do Git; não compartilhar seu conteúdo. Não é necessário instalar outra biblioteca para carregá-lo. Variáveis de ambiente GESTATI_SECRET_KEY e GESTATI_DB_PASSWORD podem fornecer os valores em outro ambiente; parâmetros de conexão têm variáveis GESTATI_DB_NAME/USER/HOST/PORT.

`migrate` aplica as migrações já existentes às tabelas do banco. `createsuperuser` cria uma conta administrativa do GESTATI, diferente da conta gestati_app do PostgreSQL. `runserver` inicia o servidor local. Acessar [GESTATI local](http://127.0.0.1:8000/) e entrar com o usuário criado. Administração em `/admin/`. Encerrar servidor com Ctrl+C. Este servidor é para desenvolvimento; hospedagem ainda não foi preparada.

## Estrutura

| Caminho | Finalidade |
|---|---|
| manage.py | Comandos do Django. |
| config/ | Configurações, URLs e entradas do servidor. |
| contas/ | Usuário da TI e configuração de administração. |
| contas/migrations/ | Evolução do banco; a primeira migração define o usuário customizado. |
| core/ | Página inicial e testes básicos da barreira de acesso. |
| cadastros/ | Models, forms, validadores, serviços, views/URLs e testes de departamentos/fornecedores/categorias. |
| ativos/ | Cadastro/consulta/edição, perfis e composição inicial com serviços integrados. |
| estoque/ | Catálogo, movimentos, serviços transacionais e consultas de saldo. |
| ordens/ | OS, registros de serviços/peças, conclusão/devolução, filtros e PDF. |
| templates/ | Páginas HTML, incluindo login. |
| static/ | CSS local inicial. |
| requirements.in / requirements.txt | Dependências diretas e versões exatas verificadas. |

Arquitetura em [ARQUITETURA.md](ARQUITETURA.md): monólito modular/MTV com serviços de departamentos, fornecedores e categorias já implementados. Serviços de catálogo/entradas e de cadastro/composição/consumo inicial também implementados; intervenções por OS também implementadas conforme ORDENS-DE-SERVICO.md.

Após a instalação inicial já concluída, para iniciar o sistema basta executar o comando runserver na pasta do projeto. Não é necessário recriar configuração, banco ou administrador. Aplicar novas migrações quando forem adicionadas ao projeto.

## Verificações

Após configurar a conexão local:

```powershell
.\.venv\Scripts\python.exe manage.py check --database default
.\.venv\Scripts\python.exe manage.py test core
```

`test core` usa SimpleTestCase e não cria banco. A suíte core + contas + cadastros + estoque + ativos + ordens + movimentacoes + baixas + relatorios já possui 284 testes, incluindo tabelas, proteção de exclusão e concorrência; foi executada pelo agente em outra instância PostgreSQL temporária, encerrada após uso. gestati_app não possui CREATEDB: para executar a suíte completa pelo servidor habitual, preparar um banco separado chamado test_gestati, de propriedade de gestati_app, pelo administrador, e usar `manage.py test core contas cadastros estoque ativos ordens movimentacoes baixas relatorios --keepdb`. Nunca apontar a suíte ao banco real do aplicativo ou reaproveitar banco de origem desconhecida. Não é necessário preparar testes novamente apenas para usar a tela.

## Departamentos

A migração cadastros.0001_initial já foi aplicada nesta instalação. No menu Departamentos ou no cartão da página inicial, é possível listar/pesquisar, cadastrar, editar, inativar/ativar e excluir registros sem vínculo. Nome é obrigatório; sigla opcional. Nome/sigla são comparados sem diferenças de caixa, acentos ou espaços extras; o nome apresentado preserva os acentos.

Exemplo para validar: cadastrar Recursos Humanos com sigla RH e tentar criar outro departamento chamado RH. O sistema informa o cadastro existente. Sem sigla ou outra indicação correspondente, não adivinha equivalência de nomes diferentes.

Vínculos com equipamentos/históricos impedirão exclusão; inativação preserva os dados. Identificadores internos de nome/sigla acompanham o cadastro e não são vínculos históricos de utilização. Nos próximos módulos, referências a Departamento devem usar PROTECT e alterações de identificação devem passar pelos serviços.

As imagens em evidencias/ foram capturadas com dados fictícios em uma instância isolada; nenhum desses dados foi inserido no banco do usuário. Migração real foi conferida com zero departamentos logo após aplicar. Para visualizar, atualizar a página com o servidor em execução ou iniciar runserver.

## Continuidade

Consultar AGENTS.md, CONTEXTO-DO-PROJETO.md, REQUISITOS-REVISADOS.md, MODELO-DE-DADOS.md e PLANO-DE-DESENVOLVIMENTO.md. A interface inicial não representa módulos já concluídos.

## Fornecedores

Migração cadastros.0002_fornecedor já aplicada nesta instalação. Menu Fornecedores ou cartão da página inicial: listar/pesquisar por nome/CNPJ, filtrar situação, criar, editar, inativar/reativar e excluir sem vínculo. Nome obrigatório; CNPJ, telefone e e-mail opcionais. E-mail preenchido é validado. CNPJ aceita máscara padrão ou 14 caracteres, numérico/alfanumérico; dígitos verificadores são conferidos localmente. Não consulta existência/situação fiscal.

CNPJ informado não pode repetir, mesmo em fornecedor inativo. Vários cadastros sem CNPJ são permitidos; nomes iguais mostram aviso para conferir o CNPJ, permitindo empresas distintas. Contatos opcionais e essa política de nomes são escolhas iniciais de implementação, ajustáveis com feedback. Nenhum fabricante foi incluído. Referências futuras de ativos/entradas usarão PROTECT; inativar preserva informações.

Não há dependências novas. Com o servidor em execução, atualizar a página; se necessário, iniciar com `.\.venv\Scripts\python.exe manage.py runserver`. Testar nome sem contatos, busca, edição e inativação/reativação. A migração já foi executada pelo agente; não repetir configuração/banco/administrador. Screenshots em evidencias/fornecedores-desktop.png e fornecedores-mobile.png usam somente dados fictícios no ambiente separado; banco do usuário tinha zero fornecedores logo após migrar.

## Categorias de equipamentos

Migração cadastros.0003_categoriaativo aplicada nesta instalação. Menu Categorias ou cartão na página inicial: listar/buscar, filtrar situação, criar/editar, inativar/reativar e excluir sem vínculos. Nome obrigatório; comparação normalizada impede repetição por caixa/acentos/espaços, inclusive entre inativas. Não infere sinônimos entre nomes diferentes.

Quando não há categorias, o botão Adicionar categorias iniciais cria Computador, Notebook, Monitor, Nobreak e Switch. É opcional; não é executado pela migração. Pode repetir sem duplicar ou reativar registros existentes. Use Nova categoria para incluir outras, como Impressora. Configuração pertinente a cada tipo e composição instalada ainda serão implementadas com ativos.

Não há dependências novas. Com o servidor aberto, atualizar a página; se parado, iniciar com o runserver habitual. Migração já aplicada pelo agente, sem dados fictícios no banco do usuário (zero categorias logo após aplicar). Captura da instância isolada em evidencias/categorias-desktop.jpg. Próximo incremento: componentes e entradas de estoque.

## Componentes e entradas de estoque

Migração estoque.0001_initial aplicada nesta instalação, sem dados de demonstração. Atualizar a página ou iniciar o runserver habitual; acessar Componentes. Sem dependências novas.

1. Novo componente: nome/especificação, tipo, mínimo e descrição. Para RAM informar capacidade por unidade em GB; SSD/HDD aceitam GB/TB. Fonte, placa-mãe, processador e outro componente não usam capacidade GB/TB.
2. Registrar entrada: componente ativo, quantidade inteira positiva, origem, data até hoje e fornecedor opcional. Estoque já existente/outro recebimento exigem observação de origem. Uma compra de 50 fontes gera um movimento de 50 unidades.
3. Consultar: saldo, mínimo/alerta, situação e histórico com filtros de período/origem. Fornecedor da entrada documenta o recebimento, sem identificar cada unidade física.

Criar especificação no catálogo não acrescenta peças ao saldo. Repetir a mesma confirmação não soma novamente. Para novo recebimento, abrir novo formulário. Registros com movimentações não podem ser excluídos; inativação preserva saldo/histórico. Depois de movimentar, tipo/capacidade/unidade não podem ser reinterpretados pelo serviço: outra especificação exige outro cadastro. Nome, descrição e mínimo continuam editáveis.

Consumo de montagem inicial já implementado com ativos, conforme seção abaixo. Intervenções por OS, retorno de peças e reaproveitamento automático na baixa ainda futuros. Não usar outro recebimento para substituir a futura operação de recuperação de um ativo. Correção/estorno e valores/custos permanecem pendentes. Detalhes em ESTOQUE.md; capturas em evidencias/componentes-desktop.jpg e estoque-entrada-desktop.jpg usam só ambiente isolado.

## Preparação de ativos — registro histórico, superado pela entrega abaixo

A próxima etapa foi iniciada com funções puras em ativos/composicao.py: agrupam componente/quantidade preservando origem e calculam RAM total. O cadastro de ativos, persistência e consumo integrado ainda não estão disponíveis. Seis testes novos passaram com os dois core, sem banco (`manage.py test core ativos`). Nenhuma instalação/migração nova nesta preparação. Perguntas sobre DTI, configurações e dados de equipamentos antigos foram enviadas ao usuário; detalhes em ATIVOS.md.

## Ativos e composição

Migrações cadastros.0004, ativos.0001 e estoque.0002_aplicacao_componentes já aplicadas. Sem novas dependências. Atualizar/reiniciar o runserver e acessar Ativos.

Conferir o perfil nas Categorias. Computador/Notebook exigem placa-mãe, processador, RAM, fonte/alimentação e SSD ou HDD. Genérico aceita extras campo/valor, como um Projetor com Luminosidade. No catálogo, cadastrar as especificações necessárias mesmo que não existam peças soltas em estoque; o formulário do ativo permite abrir esse cadastro em outra aba e atualizar as opções sem perder o preenchimento.

DTI manual aceita letras/números/hífens e preserva zeros; patrimônio opcional/único e série opcional/repetível. Modelo conhecido deve ser preenchido; PC genérico pode ficar sem modelo. Compra/garantia desconhecidas podem ficar sem informação. Garantia tem Não informada, Sem garantia ou Com garantia informada, com datas/duração quando aplicável.

Cada peça indica se já veio no equipamento ou será usada do estoque da TI. Só a segunda origem consome saldo; a confirmação salva ativo, composição e movimentos juntos. Falha de saldo reverte o conjunto, e reenvio não consome outra vez. Página do ativo mostra configuração e RAM total calculada. Edição de dados gerais mantém as peças; transferências e alterações por OS são próximos módulos.

111 testes completos passaram em PostgreSQL isolado e telas foram conferidas em desktop/celular. Nenhum exemplo fictício entrou no banco real; estoque existente preservado. ATIVOS.md e CONTEXTO-DO-PROJETO.md registram o estado atual, substituindo a preparação histórica descrita acima.

## Ordens de serviço e peças

Implementadas em /ordens/ e pela ficha do ativo. Abertura com aviso de garantia, uma OS não encerrada por ativo, serviços com/sem peças, instalação/retirada/retorno integrado ao estoque, conclusão separada da coleta, devolução por outro nome e encerramento para baixa sem efetivar baixa. Consulta reúne antigas e atuais com filtros por identificadores, período de abertura e técnico participante. Imprimir PDF funciona em qualquer etapa.

Migrações ativos.0002/0003, estoque.0003 e ordens.0001 já aplicadas nesta instalação. ReportLab 4.5.1 instalado na .venv, com dependências fixadas em requirements.txt. Para outra instalação: `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` e migrate; nesta pasta basta reiniciar runserver. Nada de recriar banco, administrador ou configuração. Guia completo, testes e limites em ORDENS-DE-SERVICO.md; custos, cancelamento, reabertura e estornos ainda não implementados.

## Revisão de Ativos — 0.23

Implementado: busca única por modelo/nome na rede e identificadores; formulário sem nome livre/Genérico; PC/notebook com grupos de peças, SSD/HDD múltiplos e nome na rede; demais com básicos/Observações. Especificações podem ser criadas no próprio cadastro sem entrada física. Em Componentes, Estoque mostra acompanhados e Catálogo mostra todos; saldo zero controlado continua visível.

Na ficha do ativo, Alterar configuração permite troca/upgrade físico ou corrigir inclusão errada sem OS. Justificativa e prévia de configuração/movimentos/saldos antes de confirmar; consumo incorreto compensado preservando original. Ler REVISAO-ATIVOS.md para limites de OS ativa e intervenções posteriores. 165 testes completos aprovados. Migrações ativos.0004/estoque.0004 já aplicadas nesta pasta, sem dependências novas ou perda dos dados do usuário. Reiniciar runserver para carregar a revisão. Bootstrap ainda não aplicado.

## Sistema operacional, transferências e empréstimos — 0.24

Sistema operacional voltou ao cadastro/edição de PC/notebook com valores antigos preservados. Menu Movimentações e ficha do ativo permitem transferir, emprestar e devolver. Transferência altera vínculo e gera PDF; empréstimo mantém vínculo e destino temporário separado, com devolução por nome/técnico. Transferir equipamento emprestado o torna definitivo e encerra empréstimo automaticamente, sem devolução fictícia. OS/peças bloqueadas durante empréstimo; OS aberta deve encerrar antes de movimentar. Guia MOVIMENTACOES.md.

188 testes aprovados e revisão de navegador/PDF concluída. Movimentacoes.0001 já aplicada nesta pasta, sem dependência nova; dados reais existentes preservados. Reiniciar runserver, sem recriar banco/admin/configuração. Próximo incremento: baixa/recuperação e documento próprio.

## Baixa/recuperação — 0.25

Menu Baixas ou ficha do ativo: registrar motivo, selecionar quantidades úteis, conferir efeitos e confirmar. Baixa direta sem OS ou após OS encerrada para baixa; nenhuma OS pode estar aberta. Empréstimo aberto encerra automaticamente com referência à baixa, sem devolução manual anterior. Entradas de reaproveitamento e composição são confirmadas juntas, sem fornecedor fictício nem duplicação. PDF reimprimível e histórico preservado. Guia BAIXAS.md.

216 testes completos aprovados e revisão desktop/celular/PDF concluída. Quatro migrações já aplicadas nesta pasta, dados reais preservados; nenhuma dependência nova. Reiniciar runserver, sem recriar banco/admin/configuração. Próximo: consolidação/demonstração e relatórios prioritários.

## Relatórios e consolidação — 0.27

Menu Relatórios: seis consultas/PDFs de ativos, OS, estoque, transferências, empréstimos e baixas. Filtros próprios, exportação de todo o resultado filtrado e links para fichas. Página inicial com atalhos para coleta/peça/empréstimos/estoque baixo/Sem reparo. RELATORIOS.md explica datas/colunas e limites; ROTEIRO-DE-VALIDACAO.md organiza a validação humana e a demonstração acadêmica.

233 testes completos passaram em PostgreSQL isolado; navegador desktop/celular e PDFs revisados. Teste legado de RAM atualizado sem reintroduzir destaque removido. Sem novas bibliotecas ou migrações; dados reais preservados e nenhum exemplo inserido. Reiniciar runserver e acessar Relatórios. Próximo: validação humana orientada pelo roteiro e alinhamento do TCC, sem confundir com piloto/implantação já realizados.

## Revisão funcional atual — 0.28

Ver REVISAO-OS.md para edição de serviços/peças durante trabalho técnico, prévia/compensações, capacidade/unidade/somas mantidas e grandes resumos de RAM retirados. Departamento atual inativo identificado; catálogo/estoque esclarecidos. 254 testes completos e navegador desktop/PDF conferidos. Migrações ordens.0002 e ativos.0006 já aplicadas com dados reais preservados; nenhuma dependência nova. Reiniciar o runserver habitual e validar com o login existente. Próximo: continuar os relatos de uso e correções de backend; interface ampla depois.

## Início e navegação — 0.29

Primeira proposta visual entregue em FRONTEND.md: nove módulos por famílias, pendências compactas, descrições curtas, menus superiores e conta. Desktop sem rolagem nas dimensões verificadas1280×720 e1366×768; móvel empilhado e legível. G SVG experimental. CSS/JS próprios, Bootstrap ainda não incorporado; sua retirada do TCC ainda depende da avaliação do usuário. 254 testes novamente aprovados e QA desktop/móvel, sem nova dependência/migração. Atualizar a página com runserver em execução; Ctrl+F5 caso o navegador mantenha CSS antigo.

## Cadastro de usuários e próxima revisão — discussão0.30

Com a conta administrativa, menu da conta → Administração → Usuários da TI permite criar/editar contas pela interface Django já existente. O primeiro administrador foi criado por createsuperuser; a conta gestati_app do PostgreSQL é distinta. Tela própria de Usuários e troca obrigatória ainda não existem. Gabriel confirmou senha temporária definida pelo administrador + troca no primeiro acesso para o próximo incremento. USUARIOS.md registra contrato/estado; FRONTEND.md contém sugestões para o login. Nenhuma conta/senha/permissão/código foi alterada nesta discussão.

## Login e Usuários entregues —0.31 (atual)

Login renovado, gestão de contas e troca obrigatória no primeiro acesso implementados conforme USUARIOS.md. Como administrador, abrir menu da conta→Usuários→Novo usuário; demais técnicos não gerenciam contas. Definir senha temporária e confirmação; técnico troca ao entrar. Edição, inativação/reativação e redefinição disponíveis, sem exclusão de autoria. Administrador GESTATI não recebe privilégios técnicos; superusuário inicial preservado/protegido. Admin Django de Usuários agora somente leitura.

277 testes completos e QA desktop/móvel/HTTP concluídos. Migração contas.0002 já aplicada preservando contas/hashes/permissões/dados reais; nenhuma dependência nova. Reiniciar runserver e atualizar Ctrl+F5, sem recriar configuração/banco/administrador. Notas antigas que dizem que a tela própria/troca inicial não existem foram superadas por esta entrega.

## Ajuste visual0.32

Login com degradê branco→verde claro uniforme e cabeçalho integrado; mostrar/ocultar senha por olho/olho riscado em todos os formulários próprios. Atualizar Ctrl+F5 para carregar CSS/JS. Check+2 testes core e revisão desktop/móvel concluídos; sem migração/dependência/regra nova.277 testes completos referem-se à entrega0.31. FRONTEND.md.

## Ativos e padrões de interface —0.33

Revisão entregue em REVISAO-EQUIPAMENTOS.md. Identificação interna (DTI), garantia somente datas condicionais,10 ativos/página/números/filtros, remoção imediata de linhas e botões Cancelar/Voltar padronizados. Somente PC/notebook oferecem configuração de componentes; nome/SO editáveis na configuração por Salvar dados sem movimentar estoque.284 testes e QA desktop/móvel; nenhuma dependência/migração nova ou dado real alterado. Reiniciar runserver e atualizar Ctrl+F5 para carregar código/templates/CSS/JS.

## Revisão atual0.34

Movimentações/Baixas e padrões compartilhados revisados; ler REVISAO-MOVIMENTACOES.md.285 testes aprovados em PostgreSQL isolado, QA desktop/móvel e PDFs conferidos. Recursos estáticos versionados automaticamente, ações uniformes, remoção sem caixa duplicada, buscas/navegação contextual, seleção pelo nome e documentos sem instruções institucionais. Sem novas dependências/migrações. Reiniciar runserver e recarregar a página para carregar a nova tag. Não recriar configuração/banco/administrador.

## Revisão atual0.35

OS/Componentes revisados conforme REVISAO-OS-ESTOQUE.md.287 testes/57 templates e QA desktop-móvel/PDF aprovados. Seleção pelo nome, painéis/etapa alinhados, cores de resultado e números simples nos PDFs. Componentes somente estoque; cadastro rápido em Ativos preservado, entrada ativa acompanhamento. Observações das entradas opcionais em todas origens. Sem migração/dependência nova. Reiniciar runserver/recarregar, sem recriar configuração/banco/admin.

## Revisão atual0.36

Grupos preservados e Voltar ao início nas telas principais de todos os módulos, nome Estoque de componentes e textos de cadastros/relatório ajustados. REVISAO-CADASTROS.md.58 templates/check/3 testes CNPJ/QA desktop-móvel aprovados; suíte287 da entrega0.35. Sem migração/dependência/regra de negócio alterada.

## Revisão atual0.37 — acesso, erros e aparência

Menu da conta→Configurações→Aparência permite Claro/Escuro, salvo neste navegador. Nome de usuário no login não diferencia caixa; senha continua diferenciando. Erros de campo aparecem abaixo do controle e gerais no final. Busca OS inclui departamento histórico/nome e sigla atuais.299 testes completos no PostgreSQL isolado,61 templates/check/makemigrations e QA desktop/móvel aprovados; sem migração/dependência/escrita real. Reiniciar runserver/recarregar para carregar backend/forms novos; não recriar configuração/admin/banco. Detalhes e limites em REVISAO-ACESSO-APARENCIA.md. Outras paletas continuam proposta em resposta à pergunta de Gabriel.

## Demonstração no Render —0.38

[HOSPEDAGEM-RENDER.md](HOSPEDAGEM-RENDER.md) registra a demonstração TCC com dados fictícios, limites do Free e passos seguintes. settings_production,render.yaml,build.sh/start.sh,estáticos WhiteNoise,Gunicorn Linux,health e primeira conta preparados/testados localmente;311 testes completos/Blueprint/WSGI aprovados. Sem migração nova ou envio do banco real. Conta Render criada e repositório privado existente Gabriel-de-Souza-Prado/gestati conferido; Git autenticado e versão atual enviada à main com histórico preservado. Demonstração publicada em https://gestati-demo.onrender.com/: login HTTPS e health com banco verificados. Primeiro acesso/troca de senha de Gabriel e validação autenticada remota continuam pendentes. Não usar runserver como comando de produção nem enviar.gestati.local.json. O desenvolvimento local continua usando o comando da seção inicial.


## Experimento de interface —0.39

Esta branch `design/inicio-azul-grafite` contém uma proposta de início com azul/grafite, módulos em listas, pendências laterais e marca GESTATI no rodapé. A paleta é compartilhada com o login e as telas internas; Claro/Escuro continuam disponíveis em Configurações. Para avaliar, iniciar o app local com o comando habitual e atualizar a página. Sem dependência/migração nova. A main e o site do Render mantêm o layout anterior até uma decisão de publicação. Check,3 testes core,61 templates, comparação de links/perfis e QA desktop/móvel em prévia sem banco concluídos; não houve nova execução da suíte completa.
