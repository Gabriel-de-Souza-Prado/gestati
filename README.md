# GESTATI

Aplicação web para gestão de equipamentos de TI, ordens de serviço, estoque de componentes, transferências, empréstimos, baixas e relatórios.

## Instalação local no Windows

Requisitos: Python 3.14 e PostgreSQL 18 instalado e em execução. As bibliotecas Python serão instaladas pelo `requirements.txt`. Execute os comandos no PowerShell, um por vez.

Se o ambiente já estiver configurado, vá direto a **Iniciar novamente**.

### 1. Obter o código

Com Git instalado:

```powershell
git clone https://github.com/Gabriel-de-Souza-Prado/gestati.git
Set-Location gestati
```

Também é possível baixar e extrair o ZIP do repositório. Abra a pasta que contém `manage.py`. Repositórios privados exigem acesso autorizado para baixar o código.

### 2. Criar ambiente virtual e instalar dependências

Confirme que o comando `python` usa o Python 3.14. Se ele não estiver no PATH, use o caminho do seu executável Python.

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

Os próximos comandos usam o Python da `.venv` diretamente; não é necessário ativar scripts do PowerShell.

### 3. Preparar o PostgreSQL

Esta etapa é feita somente na primeira instalação. Se o banco e o usuário já existirem, utilize-os sem recriar ou apagar os dados.

Abra o cliente PostgreSQL como administrador do banco. Ajuste o caminho se sua instalação estiver em outro diretório:

```powershell
& 'C:\Program Files\PostgreSQL\18\bin\psql.exe' -X -h localhost -p 5432 -U postgres -d postgres -W
```

Digite a senha do usuário `postgres` quando solicitada. Dentro do `psql`, execute:

```sql
CREATE ROLE gestati_app WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
```

Defina uma senha para a conta da aplicação. O comando abaixo pede a senha duas vezes, sem incluí-la na instrução SQL:

```text
\password gestati_app
```

Crie o banco:

```sql
CREATE DATABASE gestati OWNER gestati_app ENCODING 'UTF8' TEMPLATE template0;
```

Saia do cliente:

```text
\q
```

Os parâmetros padrão da aplicação são: servidor `localhost`, porta `5432`, banco `gestati` e usuário `gestati_app`.

### 4. Configurar a conexão e criar as tabelas

De volta ao PowerShell, na pasta de `manage.py`:

```powershell
.\.venv\Scripts\python.exe configurar_ambiente.py
```

Informe a senha definida para `gestati_app`. O assistente verifica a conexão e cria `.gestati.local.json` com a configuração e uma chave própria do Django. Esse arquivo é local e não deve ser enviado ao GitHub. Uma configuração existente é preservada.

Para usar outra conexão, defina `GESTATI_DB_HOST`, `GESTATI_DB_PORT`, `GESTATI_DB_NAME` e `GESTATI_DB_USER` no ambiente antes de configurar e executar o sistema.

Depois:

```powershell
.\.venv\Scripts\python.exe manage.py check --database default
.\.venv\Scripts\python.exe manage.py migrate
```

As migrações incluídas no código criam ou atualizam as tabelas.

### 5. Criar o primeiro administrador

```powershell
.\.venv\Scripts\python.exe manage.py createsuperuser
```

Escolha o usuário e a senha de acesso ao GESTATI. Essa conta é diferente da conta `gestati_app` do PostgreSQL. Crie-a uma vez; usuários adicionais podem ser gerenciados pelo administrador no sistema.

### 6. Executar

```powershell
.\.venv\Scripts\python.exe manage.py runserver
```

Acesse [http://127.0.0.1:8000/](http://127.0.0.1:8000/) e entre com a conta criada. Para encerrar, pressione `Ctrl+C` no terminal.

`runserver` é o servidor de desenvolvimento local. A publicação em um servidor requer configuração de hospedagem própria.

## Iniciar novamente

Com PostgreSQL em execução, abra a pasta do projeto e execute:

```powershell
.\.venv\Scripts\python.exe manage.py runserver
```

Não é necessário recriar banco, ambiente virtual, configuração ou administrador a cada execução.

## Atualizar uma instalação existente

Pare o servidor com `Ctrl+C`. Se o projeto foi clonado com Git e não houver alterações locais pendentes:

```powershell
git pull --ff-only
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver
```

Se o Git informar divergência ou alterações locais, resolva-as antes de continuar. O repositório contém o código e as migrações; cada instalação mantém seu próprio banco, credenciais e usuários.
