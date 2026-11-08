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

### 2.14. `login`
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
