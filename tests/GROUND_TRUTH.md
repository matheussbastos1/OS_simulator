# MATRIZ OFICIAL DE GROUND TRUTH E TESTES DETERMINÍSTICOS — OS SIMULATOR

> **Status:** Especificação Oficial Consolidada (Etapa 5 — Processos, Threads, Escalonamento e Concorrência)  
> **Objetivo:** Estabelecer a verdade fundamental (*ground truth*) e os critérios exatos de aceitação para os testes de integração e unitários das cinco etapas do simulador, preservando integralmente os exemplos oficiais e formalizando cenários determinísticos de validação.

---

## 1. CENÁRIOS DA ETAPA 1 — SISTEMA DE ARQUIVOS

### Cenário FS-001: Hierarquia de Diretórios e Resolução de Caminhos
- **Identificador:** `FS-001`
- **Etapa:** 1 (Sistema de Arquivos)
- **Preparação do Estado:** Sistema de arquivos recém-formatado com diretório raiz `/` montado.
- **Comandos Executados:**
  ```bash
  mkdir /sistema
  mkdir /sistema/logs
  create /sistema/logs/app.log
  ```
- **Entradas:** Caminhos absolutos fornecidos.
- **Resultado Esperado:**
  - A árvore de nós deve conter `/`, `/sistema` (DirectoryNode), `/sistema/logs` (DirectoryNode) e `/sistema/logs/app.log` (FileNode).
  - O pai de `app.log` deve apontar para `/sistema/logs`.
  - Cada nó deve possuir um i-node distinto atribuído.
- **Critério de Aprovação:** Resolução de caminhos `vfs.resolve("/sistema/logs/../logs/app.log")` retorna a mesma referência de objeto que `vfs.resolve("/sistema/logs/app.log")`.

---

### Cenário FS-002: Alocação Indexada, Métricas de Fragmentação e Sobrecarga
- **Identificador:** `FS-002`
- **Etapa:** 1 (Sistema de Arquivos)
- **Preparação do Estado:** Disco simulado com blocos de $4.096\text{ bytes}$ ($4\text{ KB}$).
- **Comandos Executados:**
  ```bash
  create /sistema/logs/app.log --size 10KB --strategy indexed
  write_file /sistema/logs/app.log "<conteudo_de_10240_bytes>"
  ```
- **Entradas:** Carga de dados de exatamente $10.240\text{ bytes}$ ($10\text{ KB}$).
- **Cálculos Esperados:**
  - Tamanho real dos dados (`data_space_used`): $10.240\text{ bytes}$.
  - Tamanho do bloco: $4.096\text{ bytes}$.
  - Blocos de dados necessários: $\lceil 10.240 / 4.096 \rceil = 3\text{ blocos}$ ($12.288\text{ bytes}$ alocados para dados).
  - Blocos de índice necessários: $1\text{ bloco}$ ($4.096\text{ bytes}$ de sobrecarga de metadados).
  - Ocupação física total no dispositivo: $(3 + 1) \times 4.096 = 16.384\text{ bytes}$.
  - **Fragmentação Interna:** $12.288 - 10.240 = 2.048\text{ bytes}$ (resíduo no 3º bloco de dados).
  - **Fragmentação Externa do Arquivo:** $0\text{ bytes}$ (a alocação indexada aproveita blocos livres dispersos por ponteiros; nenhuma fragmentação externa impede a alocação).
- **Critério de Aprovação:** O diagnóstico reporta exatamente `fragmentacao_interna == 2048` e `fragmentacao_externa == 0`.

---

### Cenário FS-003: Validação Comparativa de Estratégias de Alocação
- **Identificador:** `FS-003`
- **Etapa:** 1 (Sistema de Arquivos)
- **Preparação do Estado:** Três sistemas de arquivos idênticos com blocos livres e ocupados intercalados.
- **Comandos Executados:** Gravar um arquivo de 3 blocos em cada sistema configurado respectivamente com:
  1. Alocação Contígua (`--strategy contiguous`).
  2. Alocação Encadeada (`--strategy fat`).
  3. Alocação Indexada (`--strategy indexed`).
- **Resultado Esperado:**
  - *Contígua:* Localiza o primeiro ou menor intervalo contíguo livre.
  - *FAT:* Aloca blocos dispersos atualizando a tabela FAT encadeada.
  - *Indexada:* Aloca 1 bloco de índice e 3 blocos de dados dispersos.
- **Critério de Aprovação:** Sucesso na recuperação do conteúdo original nas 3 estratégias.

---

### Cenário FS-004: Atomicidade e Transacionalidade de Gravação (write_file)
- **Identificador:** `FS-004`
- **Etapa:** 1 (Sistema de Arquivos)
- **Preparação do Estado:** Disco simulado de 8 blocos com arquivo existente ocupando dados.
- **Comando Executado:**
  ```bash
  write_file /sistema/dados.log "<payload_que_excede_a_capacidade_do_disco>"
  ```
- **Resultado Esperado:**
  1. A operação falha levantando `DiskFullException`.
  2. O conteúdo anterior do arquivo permanece 100% intacto e legível via `read_file`.
  3. O i-node retém seus metadados (`file_size`, `allocated_blocks`, `index_block_id`) consistentes com o estado pré-falha.
  4. Nenhum bloco fica órfão ou duplamente alocado no dispositivo (`BlockDevicePort`).
  5. Válido e verificado para as três estratégias (`ContiguousAllocation`, `LinkedFATAllocation`, `IndexedAllocation`).
- **Critério de Aprovação:** Dados lidos após a falha de escrita coincidem perfeitamente com os dados originais e contadores de blocos livres do dispositivo são preservados.

---

## 2. CENÁRIOS DA ETAPA 2 — ENTRADA E SAÍDA E RAID

### Cenário IO-001: Escalonamento de Disco SSTF
- **Identificador:** `IO-001`
- **Etapa:** 2 (E/S e Escalonamento)
- **Preparação do Estado:** Disco rígido com 200 trilhas (0 a 199). Posição inicial do cabeçote: Trilha 53.
- **Entrada da Fila de Requisições:**
  ```text
  [98, 183, 37, 122, 14]
  ```
- **Cálculo Passo a Passo:**
  1. A partir de 53: distâncias para `[98: 45, 183: 130, 37: 16, 122: 69, 14: 39]`. Menor é 37 ($\Delta = 16$). Cabeçote vai para 37.
  2. A partir de 37: distâncias para `[98: 61, 183: 146, 122: 85, 14: 23]`. Menor é 14 ($\Delta = 23$). Cabeçote vai para 14.
  3. A partir de 14: distâncias para `[98: 84, 183: 169, 122: 108]`. Menor é 98 ($\Delta = 84$). Cabeçote vai para 98.
  4. A partir de 98: distâncias para `[183: 85, 122: 24]`. Menor é 122 ($\Delta = 24$). Cabeçote vai para 122.
  5. A partir de 122: resta 183 ($\Delta = 61$). Cabeçote vai para 183.
- **Cálculo da Movimentação Total:**
  $$16 + 23 + 84 + 24 + 61 = 208\text{ trilhas}$$
- **Critério de Aprovação:** Sequência exata de visitação `[53, 37, 14, 98, 122, 183]` e acumulador `total_head_movement == 208`.

---

### Cenário IO-002: Arranjo RAID 5, Paridade XOR e Reconstrução
- **Identificador:** `IO-002`
- **Etapa:** 2 (RAID e Tolerância a Falhas)
- **Preparação do Estado:** Arranjo RAID 5 com 3 discos físicos ($N = 3$), blocos de $4.096\text{ bytes}$.
- **Comando Executado:** Gravação de um arquivo de $8\text{ KB}$ ($8.192\text{ bytes}$ = 2 blocos de dados).
- **Mapeamento:**
  - Faixa 0: Disco 1 = Bloco $D_0$; Disco 2 = Bloco $D_1$; Disco 3 = Paridade $P = D_0 \oplus D_1$.
- **Injeção de Falha:**
  - Marcar `physical_disks[1].failed = True` (falha total do Disco 2).
- **Operação de Reconstrução:**
  - Leitura de $D_1$: O controlador lê $D_0$ do Disco 1 e $P$ do Disco 3, reconstruindo $D_1 = D_0 \oplus P$.
- **Critério de Aprovação:** $D_{1,\text{reconstruído}} == D_1$ idêntico byte a byte.

---

## 3. CENÁRIOS DA ETAPA 3 — SEGURANÇA E PROTEÇÃO

### Cenário SEC-001: Autenticação Criptográfica com PBKDF2 e Salt
- **Identificador:** `SEC-001`
- **Etapa:** 3 (Segurança e Controle de Acesso)
- **Preparação do Estado:** Usuário `carlos` cadastrado com salt aleatório de 16 bytes e hash derivado com 600.000 iterações no grupo `devs`.
- **Comando Executado:**
  ```bash
  login --user carlos
  # Senha fornecida via prompt
  ```
- **Resultado Esperado:** O serviço calcula PBKDF2 com 600.000 iterações e o salt registrado, compara via `hmac.compare_digest` e inicializa a sessão ativa como `carlos`.
- **Critério de Aprovação:** `context.username == "carlos"` e evento gravado no `AuditLog`.

---

### Cenário SEC-002: Fiscalização de ACL e Negação de Acesso com Auditoria
- **Identificador:** `SEC-002`
- **Etapa:** 3 (Segurança e Controle de Acesso)
- **Preparação do Estado:**
  - Arquivo: `/sistema/config.sys`
  - Proprietário: `root`, Grupo: `admin`, Permissões: `750` (`rwxr-x---`)
  - Usuário ativo: `carlos` (Grupo: `devs`)
- **Comando Executado:**
  ```bash
  read_file /sistema/config.sys
  ```
- **Avaliação de Permissões:**
  1. `carlos != root` $\implies$ não aplica permissões de proprietário.
  2. `devs != admin` $\implies$ não aplica permissões de grupo.
  3. Aplica permissões de "outros": `---` ($000$ binário $\implies$ sem leitura).
- **Resultado Esperado:** Operação bloqueada com `PermissionDeniedException` e evento `ACCESS_DENIED` gravado no `AuditLog`.
- **Critério de Aprovação:** Leitura bloqueada e evento registrado.

---

### Cenário SEC-003: Integridade, HMAC e Detecção de Adulteração
- **Identificador:** `SEC-003`
- **Etapa:** 3 (Segurança e Proteção)
- **Preparação do Estado:** Arquivo gravado com checksum SHA-256 e assinatura HMAC do Kernel.
- **Injeção de Anomalia:** Alterar 1 byte no bloco físico correspondente.
- **Comando Executado:**
  ```bash
  antivirus_scan /
  ```
- **Resultado Esperado:** Detecção de violação de integridade pelo recálculo de hash e assinatura, gerando alerta no relatório.
- **Critério de Aprovação:** Detecção precisa do arquivo e bloco adulterado.

---

## 4. CENÁRIOS DA ETAPA 4 — GERENCIAMENTO DE MEMÓRIA

### Cenário MEM-001: Alocação Contígua na Área Reservada e Fragmentação Externa
- **Identificador:** `MEM-001`
- **Etapa:** 4 (Gerenciamento de Memória)
- **Preparação do Estado:** Área Reservada Total: $4.096\text{ KB}$ ($4\text{ MB}$); Núcleo Base: $1.024\text{ KB}$ ($0 - 1023\text{ KB}$).
- **Comandos Executados:**
  ```bash
  create_process --name "Kernel_DiskDriver" --size 512KB --type critical
  create_process --name "Kernel_NetDriver" --size 1024KB --type critical
  create_process --name "Kernel_CryptoEngine" --size 512KB --type critical
  terminate_process --name "Kernel_NetDriver"
  memory_status --reserved
  ```
- **Cálculo da Fragmentação Externa:**
  - Espaço livre total: $1.024\text{ KB} + 1.024\text{ KB} = 2.048\text{ KB}$.
  - Maior bloco livre contíguo: $1.024\text{ KB}$.
  - Uma nova solicitação contígua de $1.536\text{ KB}$ falha por fragmentação externa!
- **Critério de Aprovação:** `memory_status --reserved` reporta $2.048\text{ KB}$ livres totais e maior bloco livre de $1.024\text{ KB}$.

---

### Cenário MEM-002: Desfragmentação Deslizante (`memory_compact --reserved`)
- **Identificador:** `MEM-002`
- **Etapa:** 4 (Gerenciamento de Memória)
- **Preparação do Estado:** Estado resultante imediatamente após `MEM-001`.
- **Comando Executado:**
  ```bash
  memory_compact --reserved
  ```
- **Operação:** Desloca `Kernel_CryptoEngine` para $[1536 - 2047\text{ KB}]$, consolidando um bloco contíguo livre de $2.048\text{ KB}$ na faixa $[2048 - 4095\text{ KB}]$.
- **Critério de Aprovação:** Maior bloco livre contíguo passa a ser $2.048\text{ KB}$ e fragmentação externa reduz-se a $0\text{ KB}$.

---

### Cenário MEM-003: Memória Virtual, Paginação e Fragmentação Interna
- **Identificador:** `MEM-003`
- **Etapa:** 4 (Gerenciamento de Memória)
- **Preparação do Estado:** Área Dinâmica com páginas/molduras de $4.096\text{ bytes}$ ($4\text{ KB}$).
- **Comando Executado:**
  ```bash
  create_process --name "App_Navegador" --size 10KB --type normal
  ```
- **Cálculos:**
  - Tamanho: $10\text{ KB} = 10.240\text{ bytes}$.
  - Páginas lógicas: $\lceil 10.240 / 4.096 \rceil = 3$ (Páginas 0, 1 e 2).
  - Página 0 e 1: $4.096\text{ bytes}$ ocupados cada.
  - Página 2: $2.048\text{ bytes}$ ocupados.
  - **Fragmentação Interna:** $4.096 - 2.048 = 2.048\text{ bytes}$.
- **Critério de Aprovação:** A `PageTable` contém 3 entradas e a fragmentação interna total é $2.048\text{ bytes}$.

---

### Cenário MEM-004A: Tradução de Endereço Virtual — Exemplo Oficial do Professor
- **Identificador:** `MEM-004A`
- **Etapa:** 4 (Gerenciamento de Memória)
- **Origem:** Exemplo acadêmico original do professor.
- **Preparação do Estado:** Processo `App_Navegador` com Página Lógica 1 mapeada na Moldura Física 12 (`frame_id = 12`). Tamanho da página: $4.096\text{ bytes}$ ($4\text{ KB}$).
- **Comando Executado:**
  ```bash
  translate_address --process App_Navegador --page 1
  ```
- **Cálculo Esperado:**
  - Moldura Física associada: $f = 12$.
  - Endereço Base da Moldura: $12 \times 4.096 = 49.152$.
  - Intervalo Físico da Moldura: $[49.152 - 53.247\text{ bytes}]$.
- **Critério de Aprovação:** O comando retorna com sucesso a Moldura Física 12 e o endereço base físico $49.152$.

---

### Cenário MEM-004B: Tradução de Endereço Lógico com Deslocamento Numérico
- **Identificador:** `MEM-004B`
- **Etapa:** 4 (Gerenciamento de Memória)
- **Origem:** Cenário complementar de cálculo aritmético da MMU.
- **Preparação do Estado:** Processo `App_Navegador` com Página Lógica 1 mapeada na Moldura Física 5 (`frame_id = 5`).
- **Comando Executado:**
  ```bash
  translate_address --pid <PID> --address 4100
  ```
- **Cálculo da MMU:**
  - Página lógica: $p = \lfloor 4100 / 4096 \rfloor = 1$.
  - Deslocamento: $d = 4100 \pmod{4096} = 4$.
  - Endereço físico: $(5 \times 4.096) + 4 = 20.480 + 4 = 20.484$.
- **Critério de Aprovação:** Retorna com exatidão o endereço físico $20.484$.

---

### Cenário MEM-005: Ciclo Determinístico de Page Fault, LRU e Swap
- **Identificador:** `MEM-005`
- **Etapa:** 4 (Gerenciamento de Memória)
- **Preparação do Estado:**
  - Memória física restrita a 2 molduras dinâmicas (Moldura 0 e Moldura 1) para teste de reposição.
  - Processo `App_Navegador` em execução.
  - Moldura 0: hospeda Página 0 (`last_access = 100.0`, `dirty = False`, `page_origin = PROCESS_IMAGE`).
  - Moldura 1: hospeda Página 1 (`last_access = 200.0`, `dirty = False`, `page_origin = PROCESS_IMAGE`).
- **Fase A — Falta de Página com Origem Zero-Fill e Descarte de Página Limpa:**
  - Comando: `execute_step --process App_Navegador --instruction "LOAD_DATA Página 2"`
  - Página 2 está com `present == False` e `page_origin = ZERO_FILL_ON_DEMAND` (heap virgem).
  - MMU emite `PageFaultException`.
  - A RAM está cheia. LRU compara idades: Página 0 ($t=100$) é mais antiga que Página 1 ($t=200$). Vítima: Página 0.
  - **Comportamento da Vítima:** Como Página 0 tem `dirty == False`, é descartada da moldura **sem gravação no Swap**.
  - **Comportamento da Requerida:** Como Página 2 tem origem `ZERO_FILL_ON_DEMAND`, a Moldura 0 é preenchida diretamente com zeros na RAM (**sem leitura de Swap!**).
  - Entrada de Página 2: `present = True`, `frame_id = 0`, `dirty = False`, `referenced = True`.
- **Fase B — Modificação e Swap-Out Obrigatório de Página Modificada:**
  - Comando: `execute_step --process App_Navegador --instruction "WRITE_DATA Página 2"`
  - Página 2 tem seu bit alterado para `dirty = True` e timestamp atualizado para $t=300$.
  - Comando seguinte: `execute_step --process App_Navegador --instruction "LOAD_DATA Página 0"`
  - Página 0 gera Page Fault. LRU compara: Moldura 1 (Página 1, $t=200$) vs Moldura 0 (Página 2, $t=300$). Vítima eleita: Página 1 ($t=200$, limpa $\implies$ descartada).
  - Página 0 é recarregada em Moldura 1.
  - Em seguida, comando acessa Página 3 ($t=400$, virgem).
  - Vítima eleita agora: Página 2 (Moldura 0, com `dirty == True`).
  - **Comportamento da Vítima Modificada:** Página 2 é **obrigatoriamente descarregada no Swap simulado** (Slot de Swap 0). A entrada de Página 2 passa a `present = False`, `frame_id = None`, `page_origin = SWAP_STORAGE`, `swap_slot_id = 0`.
- **Fase C — Swap-In Determinístico de Página Previamente Gravada:**
  - Comando: `execute_step --process App_Navegador --instruction "LOAD_DATA Página 2"`
  - Página 2 gera Page Fault. Origem identificada: `SWAP_STORAGE` no slot 0.
  - Uma moldura é liberada e os dados da Página 2 são **lidos deterministicamente do Swap simulado via `BlockDevicePort`**, restaurando o conteúdo original modificado e liberando o slot 0.
- **Critério de Aprovação:** O ciclo valida de forma 100% determinística o descarte sem I/O de páginas limpas, a inicialização sem Swap de páginas virgens, a gravação de páginas sujas no Swap e a recuperação posterior via `swap_in`.

---

## 5. CENÁRIOS DA ETAPA 5 — PROCESSOS, THREADS, ESCALONAMENTO E CONCORRÊNCIA

### Cenário PROC-001: Escalonamento por Prioridade, Preempção Cruzada e Round-Robin
- **Identificador:** `PROC-001`
- **Etapa:** 5 (Escalonamento de CPU)
- **Parte A — Preempção por Prioridade:**
  - `sched_config --quantum 4`
  - `LowOnly` (`priority=4, cpu_burst_ms=6, arrival_time_ms=0`) e `Urgent` (`priority=1, cpu_burst_ms=3, arrival_time_ms=2`).
  - **Resultado Esperado:** `LowOnly` executa `[0..2]`; em `t=2`, `Urgent` chega com prioridade `1 < 4`, preemptando `LowOnly` (`preemptions_total == 1`), executando `[2..5]`; `LowOnly` retoma com quantum zerado e conclui em `[5..9]`. Gantt: `[("LowOnly", 0, 2), ("Urgent", 2, 5), ("LowOnly", 5, 9)]`.
- **Parte B — Rotação Round-Robin (`quantum_ms=2`):**
  - Processos de mesma prioridade (`priority=2`): `A` (`burst=5`), `B` (`burst=4`), `C` (`burst=2`), todos em `arrival_time_ms=0`.
  - **Resultado Esperado:** Gantt exato `A[0..2], B[2..4], C[4..6], A[6..8], B[8..10], A[10..11]`, com `dispatches_total == 6`, `context_switches_total == 5`, `finish_time_ms` iguais a `11` (`A`), `10` (`B`) e `6` (`C`).
- **Critério de Aprovação:** Validado por `test_scenario_c_priority_scheduling_and_dynamic_preemption` e `test_scenario_d_round_robin_quantum_and_context_switches` em `tests/test_process_memory_integration.py`.

---

### Cenário PROC-002: Syscalls Acionadas por Tempo de CPU (`cpu_consumed_ms`), E/S e ACLs
- **Identificador:** `PROC-002`
- **Etapa:** 5 (Syscalls e E/S)
- **Preparação do Estado:** `Hog` (`priority=1, burst=6`) e `Worker` (`priority=3, burst=5`) com syscalls agendadas em `Worker`: `YIELD` em `trigger_cpu_ms=0`, `IO_READ` (`duration=4, block_id=12`) em `trigger_cpu_ms=2` e `FS_READ` (`duration=2, path="/dados.txt"`) em `trigger_cpu_ms=4`.
- **Resultado Esperado:**
  - Em `t=6` (`step(6)`), `Hog` conclui e `Worker.cpu_consumed_ms == 0`: `IO_READ` **não** disparou pelo relógio global.
  - Em `t=8` (`step(2)`), `Worker` consumiu 2 ms de CPU, disparou `YIELD@0` e `IO_READ@2`, transicionou `RUNNING -> BLOCKED (IO_WAIT)` e incrementou `io_manager.total_reads` em `+1`.
  - Após `run()`, `Worker` desbloqueia em `t=12`, bloqueia em `FS_READ@4` (`[14..16]`), conclui em `t=17` com `total_blocked_ms == 6` e `fs_step.result == "VFS_INTACTO"`. Acesso a arquivo restrito (`chmod 600`) por usuário sem permissão lança `PermissionDeniedException`.
- **Critério de Aprovação:** Validado por `test_scenario_e_cpu_triggered_syscalls_vs_global_clock_and_io_fs`.

---

### Cenário PROC-003: Exclusão Mútua em Contenção (`Buffer_Video`) e Limpeza no Encerramento
- **Identificador:** `PROC-003`
- **Etapa:** 5 (Concorrência e Mutexes)
- **Comandos Executados:**
  ```text
  mutex_demo --scenario buffer_video --quantum 2
  ```
- **Preparação:** Processo `Player_Video` (`priority=2, size=8192`) com threads `T1` e `T2` (`burst=8 ms` cada), cada qual executando `MUTEX_LOCK("Buffer_Video")` em `cpu=1 ms` e `MUTEX_UNLOCK("Buffer_Video")` em `cpu=6 ms`.
- **Resultado Esperado:**
  - `critical_sections_disjoint == True` (nunca há dois donos simultâneos na seção crítica).
  - `mutex.locked == False`, `acquire_count == 2`, `release_count == 2`, `contention_count >= 1`.
  - `T1`, `T2` e `Player_Video` terminam em `TERMINATED` e todas as molduras de memória são liberadas.
- **Critério de Aprovação:** Validado por `test_scenario_h_buffer_video_mutex_contention_and_termination_cleanup` e `test_mutex_buffer_video_manual_lock_unlock_and_terminate_cleanup`.

---

### Cenário PROC-004: Detecção de Deadlock por Grafo Wait-For e Estagnação (*Stall*)
- **Identificador:** `PROC-004`
- **Etapa:** 5 (Deadlock e No-Progress)
- **Preparação do Estado:** `quantum_ms=1`, mutexes `M1` e `M2`, `ProcA` (`MUTEX_LOCK M1 @ cpu=0`, `MUTEX_LOCK M2 @ cpu=2`) e `ProcB` (`MUTEX_LOCK M2 @ cpu=0`, `MUTEX_LOCK M1 @ cpu=2`).
- **Resultado Esperado:**
  - `ProcA` adquire `M1` em `[0..1]`; `ProcB` adquire `M2` em `[1..2]`; `ProcA` bloqueia em `M2` em `[2..3]`; ao `ProcB` tentar `M1` em `[3..4]`, o Grafo Wait-For detecta o ciclo `ProcA -> M2 -> ProcB -> M1 -> ProcA` e lança `DeadlockDetectedException` sem loop infinito.
  - Em cenário separado com thread bloqueada em `IO_READ` cujo evento de conclusão foi cancelado, `deadlock_check` e `sched_run` detectam estagnação (`SimulationStallException`).
- **Critério de Aprovação:** Validado por `test_scenario_i_circular_deadlock_and_stall_detection_no_infinite_loop` e `test_deadlock_detection_and_stall_diagnostics_via_cli`.

---

### Cenário PROC-005: Execução Acoplada à Memória Virtual (LRU, Swap e Invariantes de Métricas)
- **Identificador:** `PROC-005`
- **Etapa:** 5 (Integração com Etapa 4 e Métricas)
- **Preparação do Estado:** `dynamic_frames=2`, `page_size=4096`, política `LRU`, processo `MemApp` (`16 KB` = 4 páginas, `cpu_burst_ms=7`) com padrão `[(0, False), (1, False), (0, True), (2, False), (3, False), (0, False), (0, False)]`.
- **Resultado Esperado:**
  - Após `step(6)`: `page_faults_total == 5` (`process_image=1`, `zero_fill=3`, `swap=1`), `swap_outs_total == 1`, `swap_ins_total == 1`, `evictions_clean == 2`, `evictions_dirty == 1`, e `memory_frames` reporta Moldura `0` (Página `3`, `PAGE_FAULT`) e Moldura `1` (Página `0`, `PAGE_FAULT`).
  - Após `step(1)`: `MemApp` conclui (`TERMINATED`), molduras ocupadas retornam a `0`, slots de swap usados retornam a `0`, `page_hits_total == 2`, `page_faults_total == 5`.
  - Invariantes globais e por processo: $\text{TAT} = \text{CPU} + \text{WT} + \text{BLK}$, $\text{cpu\_busy\_ms} + \text{idle\_time\_ms} = \text{total\_simulation\_ms}$, com `Nucleo_Base` (PID 0) excluído das estatísticas de processos de usuário.
- **Critério de Aprovação:** Validado por `test_scenario_g_real_stage4_ram_lru_second_chance_swap_and_frames_summary` e `test_scenario_j_metrics_mathematical_invariants`.
