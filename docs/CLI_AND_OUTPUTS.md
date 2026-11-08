# DICIONÁRIO OFICIAL DA CLI E PADRÕES DE SAÍDA — OS SIMULATOR

> **Status:** Especificação Oficial Consolidada (Fase 0.1)  
> **Objetivo:** Estabelecer o contrato formal da interface de linha de comando (CLI), respeitando rigorosamente a sintaxe oficial fornecida pelo professor e documentando parâmetros, tipos, unidades e padrões visuais.

---

## 1. DIRETRIZES GERAIS DA CLI

1. **Prompt Interativo Padrão:**  
   `[usuario@ubuntu-simulator:caminho_atual]$ ` (para usuários comuns).  
   `[root@ubuntu-simulator:caminho_atual]# ` (para o superusuário root).
2. **Compatibilidade Oficial e Aliases:** A sintaxe estabelecida pelo professor é a **interface oficial obrigatória**. Formas alternativas e simplificadas são aceitas exclusivamente como *aliases* documentados, sem substituir a sintaxe primordial.
3. **Unidades de Memória e Tamanho:** Os parâmetros aceitam especificações com sufixos de grandeza case-insensitive (`KB`, `MB`, `B`), convertidos internamente em bytes ($1\text{ KB} = 1.024\text{ bytes}$, $1\text{ MB} = 1.048.576\text{ bytes}$).
4. **Linguagem das Mensagens:** Saídas visuais, títulos, diagnósticos e erros são exibidos em língua portuguesa, preservando termos técnicos consolidados de SO (ex.: *i-node*, *frame*, *page fault*, *cluster*, *swap*, *wear leveling*, *ACL*).

---

## 2. CATÁLOGO OFICIAL DE COMANDOS DA CLI

### 2.1. `mkdir`
- **Sintaxe Oficial:** `mkdir <caminho_diretorio>`
- **Parâmetros Obrigatórios:** `<caminho_diretorio>` (caminho absoluto ou relativo).
- **Parâmetros Opcionais:** `-p` (criação recursiva de diretórios pais).
- **Pré-condições:** Diretório pai existente com permissão de escrita (`w`) e execução (`x`).
- **Subsistema:** `filesystem` (VFS).
- **Saída de Sucesso:** Confirmação da criação do diretório e i-node atribuído.

---

### 2.2. `create`
- **Sintaxe Oficial:** `create <caminho_arquivo> [--size <tamanho>] [--strategy <contiguous|fat|indexed>]`
- **Exemplo do Professor:** `create /sistema/logs/app.log --size 10KB`
- **Parâmetros Obrigatórios:** `<caminho_arquivo>`.
- **Parâmetros Opcionais:**
  - `--size <tamanho>`: Reserva inicial de espaço (ex.: `10KB`, `4096B`). Se omitido, cria arquivo vazio (0 bytes).
  - `--strategy <estrategia>`: Estratégia de alocação (`contiguous`, `fat`, `indexed`; padrão: `indexed`).
- **Pré-condições:** Diretório pai existente com permissão `w`. Espaço em disco suficiente se `--size` informado.
- **Subsistema:** `filesystem` via `BlockDevicePort`.
- **Saída de Sucesso:** Mensagem indicando criação, i-node e blocos alocados se `--size` foi especificado.

---

### 2.3. `write_file`
- **Sintaxe Oficial:** `write_file <caminho_arquivo> "<conteudo>"`
- **Exemplo do Professor:** `write_file /sistema/logs/app.log "Novo Registro"`
- **Parâmetros Obrigatórios:** `<caminho_arquivo>`, `"<conteudo>"`.
- **Parâmetros Opcionais:** `--append` (anexar ao fim ao invés de truncar).
- **Pré-condições:** Permissão de escrita (`w`) no arquivo ou diretório pai.
- **Subsistema:** Integração `AuthorizationPort` $\to$ `filesystem` $\to$ `BlockDevicePort`.
- **Saída de Sucesso:** Relatório com bytes gravados, blocos alocados e cálculo de fragmentação interna.

---

### 2.4. `read_file`
- **Sintaxe Oficial:** `read_file <caminho_arquivo>`
- **Exemplo do Professor:** `read_file /sistema/logs/app.log`
- **Parâmetros Obrigatórios:** `<caminho_arquivo>`.
- **Parâmetros Opcionais:** `--hex` (exibe dump binário/hexadecimal dos blocos).
- **Pré-condições:** Arquivo existente e permissão de leitura (`r`).
- **Subsistema:** `AuthorizationPort` $\to$ `filesystem` $\to$ `BlockDevicePort`.
- **Saída de Sucesso:** Exibição do conteúdo do arquivo na tela.

---

### 2.5. `fs_status`
- **Sintaxe Oficial:** `fs_status [--details]`
- **Exemplo do Professor:** `fs_status --details`
- **Parâmetros Opcionais:** `--details` (exibe mapa detalhado de blocos e tabela de i-nodes). *Alias aceito:* `--detailed`.
- **Subsistema:** `filesystem`.
- **Saída de Sucesso:** Relatório com blocos totais, ocupados, livres, i-nodes e métricas de fragmentação.

---

### 2.6. `login`
- **Sintaxe Oficial:** `login --user <username>`
- **Exemplo do Professor:** `login --user carlos`
- **Parâmetros Obrigatórios:** `--user <username>`. *Alias aceito:* `login <username>`.
- **Parâmetros Opcionais:** `--password <senha>` (se omitido, solicita senha via prompt oculto no terminal).
- **Pré-condições:** Usuário cadastrado no simulador.
- **Subsistema:** `security.auth`.
- **Saída de Sucesso:** Sessão atualizada para o usuário e evento no `AuditLog`.

---

### 2.7. `chmod`
- **Sintaxe Oficial:** `chmod <mascara_octal> <caminho>`
- **Exemplo:** `chmod 750 /sistema/config.sys`
- **Parâmetros Obrigatórios:** `<mascara_octal>` (3 dígitos octais de `000` a `777`), `<caminho>`.
- **Pré-condições:** Usuário solicitante deve ser o proprietário ou `root`.
- **Subsistema:** `security.acl`.
- **Saída de Sucesso:** Atualização da ACL do i-node.

---

### 2.8. `encrypt_file`
- **Sintaxe Oficial:** `encrypt_file <caminho_arquivo> --key "<chave>"`
- **Exemplo do Professor:** `encrypt_file /home/carlos/segredo.txt --key "MinhaChave123"`
- **Parâmetros Obrigatórios:** `<caminho_arquivo>`, `--key "<chave>"`.
- **Pré-condições:** Arquivo existente, usuário com permissão de escrita/proprietário.
- **Subsistema:** `security.crypto` (AES-256-GCM com nonce de 12 bytes e tag de 16 bytes).
- **Saída de Sucesso:** Cifragem da carga útil nos blocos e atualização da flag `is_encrypted` no i-node.

---

### 2.9. `antivirus_scan`
- **Sintaxe Oficial:** `antivirus_scan [<caminho_base>]`
- **Exemplo do Professor:** `antivirus_scan /`
- **Parâmetros Opcionais:** `<caminho_base>` (padrão: `/`).
- **Subsistema:** `security.integrity`.
- **Saída de Sucesso:** Relatório de varredura de integridade (SHA-256 com verificação de assinatura HMAC do Kernel) e detecção de padrões maliciosos simulados.

---

### 2.10. `create_process`
- **Sintaxe Oficial:** `create_process --name "<nome>" --size <tamanho> --type <critical|normal>`
- **Exemplos do Professor:**
  - `create_process --name "Kernel_DiskDriver" --size 512KB --type critical`
  - `create_process --name "App_Navegador" --size 10KB --type normal`
- **Parâmetros Obrigatórios:**
  - `--name "<nome>"`: Nome identificador do processo ou driver.
  - `--size <tamanho>`: Tamanho de memória solicitado (ex.: `512KB`, `10KB`).
  - `--type <critical|normal>`:
    - `critical`: Processo de núcleo/driver alocado contiguamente na **Área Reservada**.
    - `normal`: Processo de usuário alocado dinamicamente na **Área Paginada**.
- **Parâmetros Opcionais (Aliases):** Sintaxe posicional `create_process <nome> <tamanho_kb> [--reserved]`.
- **Pré-condições:** Se `--type critical`, exige privilégio de `root`/Kernel Mode.
- **Subsistema:** `process` $\to$ `memory`.
- **Saída de Sucesso:** PCB criado, PID retornado e confirmação da alocação de memória.

---

### 2.11. `terminate_process`
- **Sintaxe Oficial:** `terminate_process --name "<nome>"`
- **Exemplo do Professor:** `terminate_process --name "Kernel_NetDriver"`
- **Parâmetros Obrigatórios:** `--name "<nome>"`.
- **Parâmetros Alternativos (Alias):** `terminate_process --pid <PID>` ou posicional `terminate_process <PID>`.
- **Pré-condições:** O processo deve estar ativo (`READY` ou `RUNNING`).
- **Subsistema:** `process` $\to$ `memory`.
- **Saída de Sucesso:** Liberação dos segmentos de memória contígua ou molduras/slots de swap e transição para `TERMINATED`.

---

### 2.12. `memory_status`
- **Sintaxe Oficial:** `memory_status [--reserved]`
- **Exemplo do Professor:** `memory_status --reserved`
- **Parâmetros Opcionais:** `--reserved` (filtra o diagnóstico para a Área Reservada Contígua). Se omitido, exibe relatório completo de Área Reservada, Área Dinâmica Paginada e Swap.
- **Subsistema:** `memory`.
- **Saída de Sucesso:** Mapa visual dos segmentos, blocos livres, fragmentação externa e molduras.

---

### 2.13. `memory_compact`
- **Sintaxe Oficial:** `memory_compact [--reserved]`
- **Exemplo do Professor:** `memory_compact --reserved`
- **Parâmetros Opcionais:** `--reserved` (compacta a Área Reservada Contígua).
- **Pré-condições:** Privilégio de `root` / Kernel Mode.
- **Subsistema:** `memory`.
- **Saída de Sucesso:** Reorganização deslizante de segmentos, unificação de buracos livres e fragmentação externa zerada.

---

### 2.14. `translate_address`
- **Sintaxe Oficial:** `translate_address --process "<nome>" --page <numero_pagina>`
- **Exemplo do Professor:** `translate_address --process App_Navegador --page 1`
- **Parâmetros Obrigatórios:** `--process "<nome>"` (ou `--pid <PID>`), `--page <numero_pagina>`.
- **Parâmetros Alternativos (Alias por Endereço Lógico):** `translate_address --pid <PID> --address <endereco_logico>` (ex.: `translate_address 103 4100`).
- **Subsistema:** `memory.mmu`.
- **Saída de Sucesso:** Moldura física mapeada ($f$) e cálculo de endereço físico, ou sinalização de Page Fault se ausente.

---

### 2.15. `execute_step`
- **Sintaxe Oficial:** `execute_step --process "<nome>" --instruction "<instrucao>"`
- **Exemplo do Professor:** `execute_step --process App_Navegador --instruction "LOAD_DATA Página 2"`
- **Parâmetros Obrigatórios:** `--process "<nome>"` (ou `--pid <PID>`), `--instruction "<instrucao>"`.
- **Subsistema:** `process` $\to$ `memory` (MMU, Page Fault Handler, LRU/Clock, Swap).
- **Saída de Sucesso:** Execução do acesso, resolução de falta de página (se ausente) respeitando a origem válida, substituição de página se memória cheia e confirmação do acesso.

---

## 3. EXEMPLOS OFICIAIS DE FORMATAÇÃO DE SAÍDAS

### 3.1. Diagnóstico do Sistema de Arquivos (`fs_status --details`)
```text
======================================================================
                  DIAGNÓSTICO DO SISTEMA DE ARQUIVOS
======================================================================
Estratégia de Alocação Ativa : INDEXADA (i-node)
Tamanho do Bloco             : 4.096 bytes (4 KB)
Total de Blocos no Disco     : 1.024 blocos (4.096 KB)
Blocos de Dados Ocupados     : 32 blocos (131.072 bytes)
Blocos de Índice Ocupados    : 6 blocos (24.576 bytes)
Blocos Livres                : 986 blocos (4.038.656 bytes)
Total de i-nodes             : 128 (Ocupados: 6 | Livres: 122)
----------------------------------------------------------------------
Espaço Ocupado pelos Dados   : 124.928 bytes
Sobrecarga de Metadados      : 24.576 bytes
Fragmentação Interna Total   : 6.144 bytes
Fragmentação Externa (Geral) : 0 bytes (disco sem fragmentação restritiva)
======================================================================
```

### 3.2. Gravação de Arquivo (`write_file`)
```text
[write_file] Arquivo gravado com sucesso: /sistema/logs/app.log
Tamanho Real do Conteúdo   : 10.240 bytes (10,00 KB)
Blocos de Dados Alocados   : 3 blocos ([12, 13, 14])
Bloco de Índice Alocado    : Bloco 11
Capacidade Total de Dados  : 12.288 bytes (12,00 KB)
Fragmentação Interna       : 2.048 bytes
Fragmentação Externa       : 0 bytes (alocação indexada bem-sucedida)
```

### 3.3. Diagnóstico e Compactação da Área Reservada (`memory_status --reserved` e `memory_compact --reserved`)
```text
======================================================================
              DIAGNÓSTICO DA ÁREA DE MEMÓRIA RESERVADA
======================================================================
Capacidade Total Reservada  : 4.096 KB (4 MB)
Segmentos Atuais:
  [0000 - 1023 KB] : Nucleo_Base (1.024 KB) - OCUPADO
  [1024 - 1535 KB] : Kernel_DiskDriver (512 KB) - OCUPADO
  [1536 - 2559 KB] : [BURACO LIVRE] (1.024 KB) - LIVRE
  [2560 - 3071 KB] : Kernel_CryptoEngine (512 KB) - OCUPADO
  [3072 - 4095 KB] : [BURACO LIVRE] (1.024 KB) - LIVRE
----------------------------------------------------------------------
Espaço Livre Total          : 2.048 KB
Maior Bloco Livre Contíguo  : 1.024 KB
Fragmentação Externa        : 1.024 KB (impede alocação contígua de 1.536 KB!)
======================================================================

[Ação: memory_compact --reserved executado pelo usuário root]

======================================================================
        ÁREA DE MEMÓRIA RESERVADA APÓS COMPACTAÇÃO DESLIZANTE
======================================================================
Segmentos Reorganizados:
  [0000 - 1023 KB] : Nucleo_Base (1.024 KB) - OCUPADO
  [1024 - 1535 KB] : Kernel_DiskDriver (512 KB) - OCUPADO
  [1536 - 2047 KB] : Kernel_CryptoEngine (512 KB) - OCUPADO
  [2048 - 4095 KB] : [BLOCO LIVRE CONSOLIDADO] (2.048 KB) - LIVRE
----------------------------------------------------------------------
Fragmentação Externa        : 0 KB (Capacidade máxima contígua: 2.048 KB)
======================================================================
```
