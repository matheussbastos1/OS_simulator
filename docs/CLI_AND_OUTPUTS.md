# DICIONÁRIO OFICIAL DA CLI E PADRÕES DE SAÍDA — OS SIMULATOR

> **Status:** Especificação Oficial Consolidada (Etapa 5 — Processos, Threads, Escalonamento e Concorrência)  
> **Objetivo:** Estabelecer o contrato formal da interface de linha de comando (CLI), respeitando rigorosamente a sintaxe oficial e documentando todos os parâmetros, aliases, tipos, unidades e padrões visuais das Etapas 1 a 5.

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

### 2.6. `io_status`
- **Sintaxe Oficial:** `io_status`
- **Exemplo:** `io_status`
- **Subsistema:** `io` (`IOManager`).
- **Finalidade:** Exibir métricas operacionais do subsistema de E/S, total de leituras/escritas, número de requisições pendentes, posição atual do cabeçote e total de trilhas percorridas.
- **Exemplo de Saída:**
  ```text
  ======================================================================
                       DIAGNÓSTICO DO SUBSISTEMA DE E/S
  ======================================================================
  Escalonador Ativo            : SSTFScheduler
  Posição Atual da Cabeça      : Trilha 53
  Dispositivo de Armazenamento : RAID5Controller
  Total de Operações de Leitura: 12
  Total de Operações de Escrita: 8
  Total de Requisições de E/S  : 20
  Total de Trilhas Percorridas : 208 trilhas
  Requisições Pendentes na Fila: 0
  ======================================================================
  ```

---

### 2.7. `io_scheduler`
- **Sintaxe Oficial:** `io_scheduler [--set <fcfs|sstf|scan|cscan>]`
- **Exemplos:**
  - `io_scheduler` (consulta o escalonador corrente e posição da cabeça)
  - `io_scheduler --set scan` (comuta dinamicamente para o algoritmo SCAN)
  - `io_scheduler cscan` (comuta utilizando sintaxe posicional)
- **Subsistema:** `io.scheduler`.
- **Saída de Sucesso:**
  ```text
  Escalonador de disco alterado com sucesso para: SCAN
  ```

---

### 2.8. `io_benchmark`
- **Sintaxe Oficial:** `io_benchmark [--algorithm <fcfs|sstf|scan|cscan>] [--queue <t1,t2,...>] [--head <pos>]`
- **Exemplos:**
  - `io_benchmark --algorithm sstf --queue 98,183,37,122,14 --head 53` (executa simulação isolada)
  - `io_benchmark --queue 98,183,37,122,14 --head 53` (benchmark comparativo de todos os 4 algoritmos)
- **Subsistema:** `io.scheduler`.
- **Exemplo de Saída Comparativa:**
  ```text
  ========================================================================================
                       BENCHMARK COMPARATIVO DE ESCALONAMENTO DE DISCO
  ========================================================================================
  Posição Inicial da Cabeça : Trilha 53
  Fila de Requisições       : [98, 183, 37, 122, 14] (5 requisições)
  ----------------------------------------------------------------------------------------
  Algoritmo  Ordem de Atendimento                   Deslocamento (Trilhas)    Média/Req
  ----------------------------------------------------------------------------------------
  FCFS       [98, 183, 37, 122, 14]                 469                       93.80
  SSTF       [37, 14, 98, 122, 183]                 208                       41.60
  SCAN       [98, 122, 183, 199, 37, 14]            331                       66.20
  C-SCAN     [98, 122, 183, 199, 0, 14, 37]         382                       76.40
  ========================================================================================
  Melhor Desempenho         : SSTF com 208 trilhas percorridas (média 41.60/req)
  ========================================================================================
  ```

---

### 2.9. `ssd_status`
- **Sintaxe Oficial:** `ssd_status [--mode <none|dynamic|static>]`
- **Exemplos:**
  - `ssd_status` (diagnóstico de ciclos e FTL)
  - `ssd_status --mode static` (altera a política de nivelamento para estática)
- **Subsistema:** `io.ssd` (`SSDDevice`).
- **Exemplo de Saída:**
  ```text
  ======================================================================
                  DIAGNÓSTICO DE WEAR LEVELING DO SSD
  ======================================================================
  Política Ativa               : DYNAMIC
  Capacidade Lógica (LBAs)     : 16 blocos
  Capacidade Física Total (PBAs: 20 blocos (Overprovisioning: 4)
  Total de Ciclos de Escrita   : 25 escritas
  Desgaste Mínimo / Máximo     : 1 / 2 ciclos
  Desgaste Médio               : 1.25 ciclos/bloco
  Desvio Padrão do Desgaste    : 0.43 (menor = melhor distribuição)
  ----------------------------------------------------------------------
  Mapa de Ciclos de Escrita por Bloco Físico (PBA):
  [00: 1] [01: 2] [02: 1] [03: 1] [04: 1] [05: 2] [06: 1] [07: 1]
  [08: 1] [09: 2] [10: 1] [11: 1] [12: 1] [13: 2] [14: 1] [15: 1]
  [16: 1] [17: 2] [18: 1] [19: 1]
  ======================================================================
  ```

---

### 2.10. `raid_status`
- **Sintaxe Oficial:** `raid_status`
- **Exemplo:** `raid_status`
- **Subsistema:** `storage.raid` (`RAIDController`).
- **Exemplo de Saída:**
  ```text
  ======================================================================
                       DIAGNÓSTICO DO ARRANJO RAID 5
  ======================================================================
  Nível RAID                   : RAID 5
  Estado do Arranjo            : OPTIMAL
  Total de Discos Membros      : 4 discos
  Discos Operacionais (Online) : 4 discos
  Discos Falhos (Offline)      : 0 discos
  Capacidade de Cada Disco     : 8 blocos (32 KB)
  Capacidade Útil Total (LBA)  : 24 blocos (96 KB)
  ----------------------------------------------------------------------
  Discos Físicos do Arranjo:
    Disco 00: ONLINE [OK] | Leituras: 5 | Escritas: 3
    Disco 01: ONLINE [OK] | Leituras: 4 | Escritas: 3
    Disco 02: ONLINE [OK] | Leituras: 6 | Escritas: 3
    Disco 03: ONLINE [OK] | Leituras: 5 | Escritas: 3
  ======================================================================
  ```

---

### 2.11. `raid_fail`
- **Sintaxe Oficial:** `raid_fail --disk <id_disco>`
- **Exemplo:** `raid_fail --disk 1` (ou posicional: `raid_fail 1`)
- **Subsistema:** `storage.raid`.
- **Efeito:** Marca o disco especificado como offline e altera o estado do arranjo para `DEGRADED` (ou `FAILED` se a tolerância for excedida).
- **Exemplo de Saída:**
  ```text
  [RAID] Falha física injetada com sucesso no Disco #01.
  Estado atual do arranjo: DEGRADED
  ```

---

### 2.12. `raid_rebuild`
- **Sintaxe Oficial:** `raid_rebuild --disk <id_disco>`
- **Exemplo:** `raid_rebuild --disk 1` (ou posicional: `raid_rebuild 1`)
- **Subsistema:** `storage.raid`.
- **Efeito:** Reconstrói integralmente os dados do disco substituído através do cálculo XOR dos discos sobreviventes e restaura o arranjo para `OPTIMAL`.
- **Exemplo de Saída:**
  ```text
  [RAID] Reconstrução dos dados do Disco #01 concluída com sucesso.
  Estado atual do arranjo: OPTIMAL
  ```

---

### 2.13. `raid_init`
- **Sintaxe Oficial:** `raid_init --level <0|1|4|5> [--disks <n>] [--capacity <tam>]`
- **Exemplo:** `raid_init --level 1 --disks 2 --capacity 8`
- **Subsistema:** `storage.raid` (`RAIDFactory`).
- **Efeito:** Inicializa um novo arranjo RAID e reconecta o `IOBlockDeviceAdapter` e o `FileSystemService`.
- **Exemplo de Saída:**
  ```text
  Arranjo RAID 1 inicializado com sucesso (2 discos, capacidade útil: 8 blocos).
  ```

---

### 2.14. Comandos de Segurança e Proteção (Etapa 3)

#### 2.14.1. `login`
- **Sintaxe Oficial:** `login --user <nome> [--password <senha>]`
- **Exemplo do Professor:** `login --user carlos`
- **Subsistema:** `security.auth` (`AuthenticationService`).
- **Comportamento:** Calcula PBKDF2-HMAC-SHA256 com 600.000 iterações e salt de 16 bytes. Inicializa o contexto de execução ativo com o anel correspondente (`MODO_USUARIO` ou `MODO_KERNEL`). Registra evento no `AuditLog`.
- **Exemplo de Saída:**
  ```text
  Autenticado com sucesso.
  Usuário: 'carlos' | Grupo: 'devs' | Modo: MODO_USUARIO
  ```

#### 2.14.2. `logout`
- **Sintaxe Oficial:** `logout`
- **Subsistema:** `security.auth`.
- **Comportamento:** Encerra a sessão ativa e redefine o contexto para o usuário não privilegiado `nobody`.

#### 2.14.3. `whoami`
- **Sintaxe Oficial:** `whoami`
- **Subsistema:** `security`.
- **Comportamento:** Exibe o usuário autenticado, UID, grupos associados, anel de privilégio e diretório de trabalho corrente.

#### 2.14.4. `groups`
- **Sintaxe Oficial:** `groups [<usuario>]`
- **Subsistema:** `security.user`.
- **Comportamento:** Exibe a lista de grupos do usuário informado ou do usuário ativo da sessão.

#### 2.14.5. `useradd`
- **Sintaxe Oficial:** `useradd <nome> [--group <grupo_primario>] [--groups <suplementares>] [--password <senha>]`
- **Subsistema:** `security.user` (`UserManager`).
- **Pré-condições:** Privilégio administrativo (`root` / `MODO_KERNEL`).

#### 2.14.6. `userdel`
- **Sintaxe Oficial:** `userdel <nome>`
- **Subsistema:** `security.user` (`UserManager`).
- **Pré-condições:** Privilégio administrativo. Bloqueia terminantemente a remoção do superusuário `root`.

#### 2.14.7. `usermod`
- **Sintaxe Oficial:** `usermod <nome> [--group <grp>] [--append-groups <g1,g2>] [--password <senha>]`
- **Subsistema:** `security.user` (`UserManager`).
- **Pré-condições:** Privilégio administrativo.

#### 2.14.8. `groupadd` e `groupdel`
- **Sintaxe Oficial:** `groupadd <nome>` / `groupdel <nome>`
- **Subsistema:** `security.user` (`UserManager`).
- **Pré-condições:** Privilégio administrativo. `groupdel` impede a remoção de grupos essenciais do sistema (`root`, `admin`, `users`) ou que sejam grupos primários de usuários ativos.

#### 2.14.9. `chmod`
- **Sintaxe Oficial:** `chmod <modo_octal|simbolico> <caminho>`
- **Exemplo do Professor:** `chmod 750 /sistema/config.sys`
- **Subsistema:** `security.acl` (`SecurityManager`).
- **Pré-condições:** Usuário deve ser proprietário do recurso ou `root`.

#### 2.14.10. `chown` e `chgrp`
- **Sintaxe Oficial:** `chown <dono>[:<grupo>] <caminho>` / `chgrp <grupo> <caminho>`
- **Subsistema:** `security.acl` (`SecurityManager`).
- **Pré-condições:** `chown` exige `root` para alterar proprietário.

#### 2.14.11. `security_status`
- **Sintaxe Oficial:** `security_status`
- **Subsistema:** `security`.
- **Comportamento:** Exibe relatório consolidado com usuário ativo, grupos, anel de privilégio, estatísticas de usuários, grupos, baseline e eventos de auditoria.

#### 2.14.12. `encrypt_file` e `decrypt_file`
- **Sintaxe Oficial:** `encrypt_file <caminho> [--key <chave>]` / `decrypt_file <caminho> [--key <chave>]`
- **Exemplo do Professor:** `encrypt_file /home/carlos/segredo.txt`
- **Subsistema:** `security.crypto`.
- **Comportamento:** Aplica cifra autêntica AES-256-GCM com nonce de 12 bytes e tag de 16 bytes. Os blocos físicos passam a armazenar apenas texto cifrado, validando a tag AEAD na leitura.

#### 2.14.13. `antivirus_scan` e `integrity_check`
- **Sintaxe Oficial:** `antivirus_scan [<caminho>]` / `integrity_check [--register] <caminho>`
- **Exemplo do Professor:** `antivirus_scan /`
- **Subsistema:** `security.integrity`.
- **Comportamento:** Varredura recursiva de diretórios com verificação de hashes SHA-256 de blocos contra o catálogo oficial assinado por HMAC do Kernel, detectando blocos adulterados e assinaturas maliciosas simuladas.

#### 2.14.14. `audit_log`
- **Sintaxe Oficial:** `audit_log [--user <u_id>] [--type <evento>] [--limit <n>]`
- **Subsistema:** `security.audit` (`AuditLog`).
- **Comportamento:** Exibe a trilha de auditoria inviolável de acessos concedidos, acessos negados, autenticações e operações privilegiadas.

---

### 2.15. `create_process`
- **Sintaxe Oficial:** `create_process --name "<nome>" --size <tamanho> --type <critical|normal> [--priority <int>] [--burst <ms>] [--arrival <ms>] [--io-profile <none|fixed|periodic|random>] [--io-every <ms>] [--io-duration <ms>] [--seed <int>] [--pages <p0,p1,...>] [--no-admit]`
- **Exemplos:**
  - `create_process --name "Kernel_DiskDriver" --size 512KB --type critical`
  - `create_process --name "App_Navegador" --size 10KB --type normal`
  - `create_process --name "AppStage5" --size 8KB --type normal --priority 2 --burst 6 --arrival 1 --io-profile periodic --io-every 2 --io-duration 3 --pages 0,1:w`
- **Parâmetros Obrigatórios:**
  - `--name "<nome>"` (`-n`): Nome identificador do processo ou driver.
  - `--size <tamanho>` (`-s`): Tamanho de memória solicitado (ex.: `512KB`, `10KB`).
  - `--type <critical|normal>` (`-t`, ou `--reserved` / `-r` para `critical`):
    - `critical`: Processo de núcleo/driver alocado contiguamente na **Área Reservada**.
    - `normal`: Processo de usuário alocado dinamicamente na **Área Paginada**.
- **Parâmetros Opcionais da Etapa 5 (Retrocompatíveis):**
  - `--priority <int>`: Prioridade (`>= 1`, sendo `1` a maior; padrão `3`).
  - `--burst <ms>`: Burst total de CPU em ms (`>= 0`; se `> 0`, cria thread `"main"`).
  - `--arrival <ms>`: Tempo lógico de chegada em ms (se `> clock.now_ms`, inicia em `NEW` e agenda `PROCESS_ARRIVAL`).
  - `--io-profile <none|fixed|periodic|random>`, `--io-every <ms>`, `--io-duration <ms>`, `--seed <int>`: Perfil automático de E/S.
  - `--pages <p0,p1,...>`: Padrão de acesso a páginas virtuais por tick (suporta sufixo `:w`/`w` para escrita, ex.: `0,1,0:w`).
  - `--no-admit`: Mantém processo em `NEW` até invocação manual de `process_admit`.
- **Parâmetros Alternativos (Aliases):** Sintaxe posicional `create_process <nome> <tamanho> [critical|normal]`.
- **Pré-condições:** Se `--type critical`, exige privilégio de `root`/Kernel Mode. Em falha de memória (`OutOfMemoryException` / `MemoryFragmentationException`), executa rollback integral do PCB e threads.
- **Subsistema:** `process` $\to$ `memory` ($\to$ `ExecutionEngine` quando flags da Etapa 5 são informadas).
- **Saída de Sucesso:** PCB criado, PID retornado, confirmação da alocação de memória e resumo de prioridade/burst/chegada/perfil de E/S quando aplicável.

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

### 2.16. Comandos de Processos, Threads, Escalonamento, Syscalls, Concorrência e Métricas (Etapa 5)

#### 2.16.1. `ps` / `process_status`
- **Sintaxe:** `ps [--all]` ou `process_status [--all]` (`-a` como alias de `--all`).
- **Comportamento:** Lista processos ativos (ou todos, incluindo `TERMINATED`, com `--all`) e suas respectivas threads, exibindo PID, Nome, Tipo, Estado, Prioridade, consumo de CPU (`cpu_consumed_ms/burst`), motivo de bloqueio (`block_reason(blocked_on)`) e mutexes retidos.

#### 2.16.2. `process_admit`
- **Sintaxe:** `process_admit --process <nome|pid>` (aliases `-p`, `--pid` ou argumento posicional `<nome|pid>`).
- **Comportamento:** Admite um processo no estado `NEW` para `READY` (e enfileira suas threads prontas no escalonador) ou agenda `PROCESS_ARRIVAL` caso `arrival_time_ms > clock.now_ms`.

#### 2.16.3. `thread_create`
- **Sintaxe:** `thread_create --process <nome|pid> --name <tname> [--priority <int>] [--burst <ms>] [--arrival <ms>] [--io-profile <none|fixed|periodic|random>] [--io-every <ms>] [--io-duration <ms>] [--seed <int>] [--pages <p0,p1,...>]`
- **Aliases:** `-p` / `--pid` para `--process`, `-n` para `--name` (aceita também `<proc> <tname>` posicionais).
- **Pré-condições:** Processo pai existente e não encerrado (proibido em `Nucleo_Base` PID 0).

#### 2.16.4. `thread_status`
- **Sintaxe:** `thread_status [--process <nome|pid>] [--active]` (aliases `-p`, `--pid` ou posicional `<nome|pid>`).
- **Comportamento:** Exibe tabela detalhada das threads simuladas (TID, PID, Nome, Estado, Prioridade, CPU consumida/burst, quantum usado e bloqueios/mutexes).

#### 2.16.5. `sched_config`
- **Sintaxe:** `sched_config [--algorithm <priority_rr>] [--quantum <ms>] [--seed <int>]`
- **Aliases:** `--alg` / `-a` para `--algorithm`, `-q` para `--quantum`, `-s` para `--seed`.
- **Comportamento:** Sem argumentos, exibe a configuração corrente (`priority_rr`, quantum padrão `4 ms`, seed padrão `42`, overhead). Com parâmetros, valida e atualiza dinamicamente o `quantum_ms` (`>= 1`) e/ou `default_seed`.

#### 2.16.6. `sched_status`
- **Sintaxe:** `sched_status`
- **Comportamento:** Exibe o relógio lógico atual, a thread `RUNNING`, todas as filas `READY` agrupadas por nível de prioridade, entidades `BLOCKED` com tempo previsto de desbloqueio, contadores de despachos/trocas de contexto/preempções/expirações e eventos pendentes.

#### 2.16.7. `sched_step`
- **Sintaxe:** `sched_step [--ms <int>]` (alias `-m` ou posicional `<int>`, padrão `1`).
- **Comportamento:** Avança o `ExecutionEngine` em até `ms` milissegundos lógicos (`>= 0`), respeitando rigorosamente o limite `start_ms + ms`, tratando eventos discretos, syscalls e paginação.

#### 2.16.8. `sched_run`
- **Sintaxe:** `sched_run [--max-ms <int>] [--until-process <nome|pid>] [--until-event <tipo_evento>]`
- **Comportamento:** Executa o loop discreto até concluir todas as pendências (`COMPLETED`), atingir `--max-ms` (`MAX_MS_REACHED`), encerrar `--until-process` (`TARGET_PROCESS_TERMINATED`) ou drenar `--until-event` (`TARGET_EVENT_REACHED`). Captura `DeadlockDetectedException` e `SimulationStallException` retornando diagnóstico estruturado.

#### 2.16.9. `process_syscall`
- **Sintaxe:** `process_syscall --process <nome|pid> --type <io_read|io_write|fs_read|fs_write|sleep|yield|mutex_lock|mutex_unlock|memory_load|memory_write|exit> [--thread <tname|tid>] [--at-cpu <ms>] [--duration <ms>] [--block <id>] [--path <p>] [--data <txt>] [--mutex <name>] [--page <n>] [--write] [--now]`
- **Aliases:** `-p` / `--pid` para `--process`, `-t` / `--tid` para `--thread`.
- **Comportamento:** Agenda um `WorkloadStep` para `cpu_consumed_ms == trigger_cpu_ms` (via `--at-cpu`, padrão `cpu_consumed_ms` atual) ou executa imediatamente (`--now`, mutuamente exclusivo com `--at-cpu`).

#### 2.16.10. `mutex_create`, `mutex_lock`, `mutex_unlock`, `mutex_status` e `mutex_demo`
- **`mutex_create [--name] <nome>`** (`-n`): Cria mutex nomeado no estado `LIVRE`.
- **`mutex_lock --mutex <nome> --process <nome|pid> [--thread <tname|tid>]`** (`-m`/`--name`, `-p`/`--pid`, `-t`/`--tid`): Tenta adquirir mutex imediatamente; em contenção, bloqueia a thread em fila FIFO e executa detecção de deadlock.
- **`mutex_unlock --mutex <nome> --process <nome|pid> [--thread <tname|tid>]`**: Libera o mutex e transfere a posse imediatamente (*handoff* FIFO) para a próxima thread aguardando, se houver.
- **`mutex_status`**: Exibe donos, filas FIFO de espera, contadores e eventuais ciclos de deadlock.
- **`mutex_demo [--scenario buffer_video] [--quantum <ms>]`** (`-q`, padrão `2`): Executa o cenário produtor/consumidor `Buffer_Video` no processo `Player_Video` com threads `T1` e `T2`, comprovando seções críticas disjuntas.

#### 2.16.11. `deadlock_check`
- **Sintaxe:** `deadlock_check`
- **Comportamento:** Executa varredura do Grafo Wait-For (`detect_deadlocks`) e verificação de estagnação (`check_no_progress`), classificando o estado como `SAUDÁVEL`, `DEADLOCK DETECTADO` ou `ESTAGNAÇÃO DETECTADA (No-Progress)`.

#### 2.16.12. `memory_frames`
- **Sintaxe:** `memory_frames`
- **Comportamento:** Exibe a tabela sincronizada ao vivo das molduras físicas da RAM dinâmica (`MemoryManager.physical_memory.frames` + `PageTableEntry`), indicando estado (`OCUPADA`/`LIVRE`), PID, página lógica, último evento (`HIT`/`PAGE_FAULT`/`N/A`), timestamp do último acesso, bits `Dirty` e `Ref` e algoritmo de substituição ativo.

#### 2.16.13. `sim_metrics`, `sim_timeline` e `sim_reset`
- **`sim_metrics`**: Exibe o relatório consolidado de métricas globais (tempo total, CPU ocupada/ociosa, utilização %, trocas de contexto, despachos/preempções, syscalls, bloqueios E/S e mutex, page hits/faults, `WT` médio, `TAT` médio, vazão) e detalhamento por processo/thread (`CPU`, `WT`, `BLK`, `TAT`, `RT`).
- **`sim_timeline [--limit <n>] [--gantt]`** (`-l`, `-g`): Exibe a linha do tempo cronológica de eventos (opcionalmente limitada às últimas `n` entradas) e, com `--gantt`, anexa o Diagrama de Gantt contíguo da CPU (incluindo intervalos `IDLE`).
- **`sim_reset`**: Reinicia o relógio lógico para `0 ms`, limpa filas do escalonador, eventos, mutexes, histórico de syscalls/métricas e processos/memória de usuário, preservando `Nucleo_Base` (PID 0) e o quantum configurado.

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
Fragmentação Externa (Geral) : 0 bytes (maior contíguo: 986 blocos)
======================================================================

[MAPA DE OCUPAÇÃO DOS BLOCOS]
[00:I] [01:D] [02:D] [03:D] [04:.] [05:.] [06:.] [07:.]
Legenda: . = Livre, D = Dados, I = Índice, X = Danificado
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

### 3.4. Cenário de Segurança 3.1 — Autenticação e Fiscalização de ACL
```text
login --user carlos
Senha: **********
Autenticado com sucesso.
Usuário: 'carlos' | Grupo: 'devs' | Modo: MODO_USUARIO

read_file /sistema/config.sys

[SISTEMA DE SEGURANÇA - VERIFICAÇÃO DE ACL]
Objeto      : /sistema/config.sys
Proprietário: root (Grupo: admin)
Permissões  : rwxr-x--- (750)
Ação Pedida : LEITURA por 'carlos' (Grupo: devs)

[NEGADO]: O usuário 'carlos' não possui permissão de leitura no objeto '/sistema/config.sys'.
Tentativa não autorizada registrada nos logs do sistema.
```

### 3.5. Cenário de Segurança 3.2 — Criptografia em Repouso e Varredura de Antivírus
```text
encrypt_file /home/carlos/segredo.txt
Arquivo '/home/carlos/segredo.txt' criptografado com sucesso.

Conteúdo gravado nos blocos físicos:
0x8F4A12B... (Encrypted Ciphertext)

antivirus_scan /

[MÓDULO DE SEGURANÇA - VARREDURA DE INTEGRIDADE]
Analisando arquivos em busca de assinaturas maliciosas e hashes corrompidos...

/home/carlos/segredo.txt : [OK - Criptografado e Íntegro]
/sistema/logs/app.log    : [ALERTA] Hash do bloco difere do registro oficial!

Resultado: Possível modificação direta não autorizada no bloco do disco.
```

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

### 3.6. Exemplos da Etapa 5 — Escalonamento, Concorrência, Molduras e Métricas

#### `sched_status` e `memory_frames`
```text
Relógio Lógico Atual : 3 ms
======================================================================
        FILAS DO ESCALONADOR DE CPU (PRIORIDADE + ROUND-ROBIN)        
======================================================================
Quantum configurado          : 4 ms
Overhead troca de contexto   : 0 ms
Thread em Execução (RUNNING) : TID 1 'main' (PID 100, Prio 2, Quantum 3/4 ms, Restante 3 ms)
----------------------------------------------------------------------
Filas de Prontos (1 = maior prioridade):
  Prioridade 1: [vazia]
  Prioridade 2: [vazia]
  Prioridade 3: [vazia]
  Prioridade 4: [vazia]
  Prioridade 5: [vazia]
----------------------------------------------------------------------
Despachos: 1 | Trocas de Contexto: 0 | Preempções: 0 | Expirações de Quantum: 0
======================================================================

======================================================================
            RESUMO SINCRONIZADO DAS MOLDURAS FÍSICAS (FRAMES)
======================================================================
Algoritmo de Substituição Ativo: LRU
------------------------------------------------------------------------------
Moldura  | Estado   | PID   | Página  | Evento      | Últ.Acesso | Dirty | Ref
------------------------------------------------------------------------------
0        | OCUPADA  | 100   | 0       | HIT         | 2.0        | Sim   | Sim
1        | OCUPADA  | 100   | 1       | PAGE_FAULT  | 1.0        | Não   | Sim
======================================================================
```

#### `mutex_demo --scenario buffer_video --quantum 2`
```text
======================================================================
           DEMONSTRAÇÃO DE CONCORRÊNCIA E MUTEX — BUFFER_VIDEO
======================================================================
Cenário              : Buffer_Video (Processo 'Player_Video', PID 100)
Quantum Configurado  : 2 ms
Exclusão Mútua       : SIM (seções críticas disjuntas, zero condição de corrida)
Mutex 'Buffer_Video' : locked=False | aquisições=2 | liberações=2 | contenções=1
...
======================================================================
```

#### `sim_metrics` e `sim_timeline --gantt`
```text
======================================================================
          RELATÓRIO DE MÉTRICAS DE EXECUÇÃO E ESCALONAMENTO
======================================================================
Tempo Total de Simulação  : 9 ms
Tempo de CPU Ocupada      : 6 ms
Tempo de CPU Ociosa (Idle): 3 ms
Utilização da CPU         : 66.67%
Trocas de Contexto        : 2
Despachos / Preempções    : 3 / 0
Syscalls Executadas       : 1
Bloqueios (E/S / Mutex)   : 1 / 0
Memória (Hits / Faults)   : 4 / 2
Processos Concluídos      : 2 / 2
Tempo Médio de Espera (WT): 0.00 ms
Turnaround Médio (TAT)    : 5.00 ms
Vazão (Throughput)        : 222.22 proc/s
----------------------------------------------------------------------
MÉTRICAS POR PROCESSO:
PID   | Processo        | Estado     | Prio | CPU    | WT     | BLK    | TAT    | RT     | Hits/Faults
--------------------------------------------------------------------------------------------
100   | P1              | TERMINATED | 2    | 4   ms | 0   ms | 3   ms | 7ms    | 0ms    | 3/1
  └─ TID 1   (main      ) [TERMINATED] CPU=4ms WT=0ms BLK=3ms TAT=7ms RT=0ms
101   | P2              | TERMINATED | 3    | 2   ms | 0   ms | 0   ms | 3ms    | 1ms    | 1/1
  └─ TID 2   (main      ) [TERMINATED] CPU=2ms WT=0ms BLK=0ms TAT=3ms RT=1ms
======================================================================
```
