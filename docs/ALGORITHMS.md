# ESPECIFICAÇÃO DE ALGORITMOS E CONTRATOS LÓGICOS — OS SIMULATOR

> **Status:** Especificação Oficial Consolidada (Etapa 5 — Processos, Threads, Escalonamento e Concorrência)  
> **Objetivo:** Estabelecer a especificação matemática, formal e algorítmica de todas as operações computacionais do simulador em suas cinco etapas acadêmicas, incorporando portas, adaptadores, origens de páginas, padrões de segurança modernos e simulação discreta de CPU, E/S, sincronização e métricas.

---

## 1. SUBSISTEMA DE SISTEMA DE ARQUIVOS (ETAPA 1)

### 1.1. Alocação Contígua
- **Objetivo:** Alocar um conjunto de blocos fisicamente adjacentes para armazenar um arquivo.
- **Entradas:** `file_size: int` (bytes), `block_size: int` (padrão: 4.096 bytes), `block_device: BlockDevicePort`.
- **Saídas:** `allocated_block_ids: List[int]` ou exceção de espaço contíguo insuficiente.
- **Passo a Passo:**
  1. Calcular o número de blocos de dados necessários: $N = \lceil \text{file\_size} / \text{block\_size} \rceil$.
  2. Consultar o mapa de blocos livres do `BlockDevicePort`.
  3. Localizar o primeiro intervalo contíguo de tamanho $\ge N$ (*First-Fit*) ou o menor intervalo $\ge N$ (*Best-Fit*).
  4. Se nenhum intervalo contíguo satisfizer $N$, lançar `DiskFragmentationException` (fragmentação externa impedindo alocação).
  5. Reservar os $N$ blocos contíguos e associá-los ao `Inode`.
- **Complexidade:** $O(M)$ onde $M$ é o total de blocos do dispositivo.

---

### 1.2. Alocação Encadeada (FAT — File Allocation Table)
- **Objetivo:** Alocar blocos arbitrários não adjacentes interligados por ponteiros em uma tabela centralizada.
- **Passo a Passo:**
  1. Calcular $N = \lceil \text{file\_size} / \text{block\_size} \rceil$.
  2. Coletar os primeiros $N$ blocos livres disponíveis no dispositivo de blocos.
  3. Atualizar a tabela FAT: para $i$ de $0$ a $N-2$, `fat_table[blocks[i]] = blocks[i+1]`.
  4. Definir o último bloco como fim de arquivo: `fat_table[blocks[N-1]] = EOF` (`-1`).
  5. Gravar o ID do primeiro bloco (`blocks[0]`) no `Inode`.
- **Complexidade:** Alocação $O(N)$; leitura aleatória do k-ésimo bloco requer travessia encadeada $O(k)$.

---

### 1.3. Alocação Indexada (i-node com Bloco de Índices Dedicado)
- **Objetivo:** Manter todos os ponteiros de blocos de um arquivo centralizados em um bloco físico de índices dedicado.
- **Entradas:** `file_size: int`, `block_size: int`, `block_device: BlockDevicePort`.
- **Saídas:** `index_block_id: int`, `allocated_data_blocks: List[int]`.
- **Passo a Passo:**
  1. Calcular o total de blocos de dados necessários: $N = \lceil \text{file\_size} / \text{block\_size} \rceil$.
  2. Alocar 1 bloco físico exclusivo para armazenar os índices de blocos (`index_block_id = block_device.allocate_block()`).
  3. Alocar $N$ blocos físicos de dados em quaisquer posições livres disponíveis.
  4. Gravar a lista de $N$ IDs de dados no conteúdo do bloco de índices.
  5. Registrar o `index_block_id` e a lista de blocos no `Inode`.
- **Complexidade:** Acesso aleatório a qualquer bloco lógico em $O(1)$ diretamente via índice.

---

### 1.4. Métricas Formais de Fragmentação e Ocupação de Armazenamento
Para evitar divergências na interpretação acadêmica e técnica:
1. **Espaço Ocupado pelos Dados ($E_{\text{dados}}$):**
   $$E_{\text{dados}} = \text{file\_size} \quad (\text{bytes reais da carga útil})$$
2. **Sobrecarga de Metadados e Indexação ($S_{\text{meta}}$):**
   $$S_{\text{meta}} = (\text{qtd\_blocos\_indice} \times \text{block\_size}) + \text{tamanho da entrada na tabela de i-nodes}$$
3. **Ocupação Física Total no Disco ($O_{\text{total}}$):**
   $$O_{\text{total}} = (N_{\text{dados}} + N_{\text{indice}}) \times \text{block\_size}$$
4. **Fragmentação Interna ($FI$):**
   $$FI = (N_{\text{dados}} \times \text{block\_size}) - \text{file\_size}$$
   *Exemplo oficial:* Para um arquivo de 10 KB ($10.240\text{ bytes}$) com blocos de 4 KB ($4.096\text{ bytes}$):
   $$N_{\text{dados}} = \lceil 10.240 / 4.096 \rceil = 3\text{ blocos}$$
   $$\text{Espaço alocado para dados} = 3 \times 4.096 = 12.288\text{ bytes}$$
   $$FI = 12.288 - 10.240 = 2.048\text{ bytes}$$
5. **Fragmentação Externa ($FE$):**
   - *Métrica Geral do Disco:* Soma dos bytes livres espalhados em blocos isolados que não conseguem atender a uma solicitação contígua de tamanho $K$:
     $$FE_{\text{disco}} = \sum \text{bytes de todos os blocos livres} \quad (\text{quando nenhum segmento contíguo} \ge K)$$
   - *Métrica do Arquivo na Alocação Indexada:* Reportada oficialmente como **$0\text{ bytes}$**, pois a alocação indexada tem a propriedade fundamental de interligar blocos livres dispersos por meio de ponteiros, sem exigir adjacência física. Portanto, a fragmentação externa não impede a alocação de arquivos indexados.

---

### 1.5. Algoritmo Transacional de Gravação e Redimensionamento (`write_data`)
Para garantir integridade contra falhas de espaço em disco e evitar perda de dados:
1. **Planejamento Prévio:** Calcula o número de blocos necessários ($N_{\text{novo}}$) em relação aos blocos atuais ($N_{\text{atual}}$).
2. **Reutilização e Expansão Delta ($\Delta = N_{\text{novo}} - N_{\text{atual}}$):**
   - Se $N_{\text{novo}} == N_{\text{atual}}$: Sobrescreve os blocos existentes em vigor sem alocação ou liberação.
   - Se $N_{\text{novo}} < N_{\text{atual}}$ (Encolhimento): Mantém os primeiros $N_{\text{novo}}$ blocos e devolve apenas os blocos excedentes ao dispositivo.
   - Se $N_{\text{novo}} > N_{\text{atual}}$ (Crescimento):
     - **FAT e Indexada:** Valida se `device.get_free_count() >= \Delta`. Se insuficiente, lança `DiskFullException` imediatamente sem alterar os blocos existentes. Aloca apenas $\Delta$ blocos novos e conecta à estrutura existente.
     - **Contígua:** Avalia se os blocos subsequentes estão livres para expansão in-place; se não, busca novo intervalo contíguo de tamanho $N_{\text{novo}}$ no espaço livre restante. Caso precise desalocar o espaço antigo para consolidar um segmento, realiza backup em memória do payload original e efetua rollback estrito se a alocação for frustrada por fragmentação ou espaço.
3. **Rollback em Caso de Falha:** Qualquer exceção durante escrita restaura o estado anterior de ponteiros, i-node e blocos no dispositivo físico, assegurando que o arquivo nunca permaneça truncado ou corrompido.

---

## 2. SUBSISTEMA DE ENTRADA E SAÍDA (I/O) E ARMAZENAMENTO (ETAPA 2)

### 2.1. Escalonamento Mecânico de Disco (HDD)
Os algoritmos de escalonamento atuam sobre a fila de `IORequest` para minimizar a métrica de *Seek Time* (deslocamento de trilhas).
- **FCFS (First-Come, First-Served):**
  Atendimento sequencial por ordem de chegada na fila:
  $$\text{Deslocamento Total} = \sum_{i=1}^{m} |\text{track}_i - \text{track}_{i-1}|$$
- **SSTF (Shortest Seek Time First):**
  Seleciona guloso a requisição com menor distância absoluta da posição corrente do cabeçote:
  $$R^* = \arg\min_{R \in \text{Fila}} |\text{track}(R) - \text{cabeçote\_atual}|$$
  *Critério de Desempate Determinístico (Ground Truth):* Em caso de empate na distância, atende primeiro a requisição com menor número de trilha; persistindo o empate, segue a ordem original de chegada.
  *Cenário Homologado IO-001:* Cabeçote inicial em 53, fila `[98, 183, 37, 122, 14]`.
  Sequência de atendimento: $53 \to 37 \to 14 \to 98 \to 122 \to 183$.
  Deslocamentos parciais: $|37-53|=16$, $|14-37|=23$, $|98-14|=84$, $|122-98|=24$, $|183-122|=61$.
  Deslocamento total acumulado: $16 + 23 + 84 + 24 + 61 = 208\text{ trilhas}$.
- **SCAN (Elevador):**
  O braço move-se em um sentido (padrão: crescente `UP`) atendendo todas as requisições no caminho até atingir a borda do disco (`max_track = 199`). Ao atingir o limite, inverte a direção (`DOWN`) e atende as requisições pendentes no sentido oposto.
- **C-SCAN (Circular SCAN):**
  Semelhante ao SCAN, mas atende requisições apenas no sentido crescente. Ao atingir a borda final (`max_track`), executa um salto direto de retorno para o início oposto (`min_track = 0`) sem atender requisições durante o percurso de retorno, proporcionando tempo de espera mais uniforme.

---

### 2.2. Simulação de SSD e Wear Leveling
A camada Flash Translation Layer (FTL) desacopla o endereço lógico (LBA) do bloco físico (PBA).
- **Modo NONE:** Mapeamento direto (LBA $i 	o$ PBA $i$). Causa concentração prematura de desgaste em blocos de escrita intensa.
- **Modo DYNAMIC (Wear Leveling Dinâmico):**
  Ao gravar em um LBA, o bloco físico atual é invalidado (`is_valid = False`, `is_free = True`), e um novo bloco físico livre com o **menor contador de ciclos de escrita** (`write_count`) é selecionado.
- **Modo STATIC (Wear Leveling Estático):**
  Além da política dinâmica, se $(\max(\text{write\_count}) - \min(\text{write\_count})) > \text{static\_threshold}$, o controlador identifica dados frios (pouco modificados que residem em blocos de baixo desgaste) e move-os para blocos mais desgastados, liberando os blocos mais conservados para novas escritas dinâmicas.
- **Métricas Estatísticas:**
  $$\text{Média} = \frac{1}{N} \sum_{i=0}^{N-1} w_i, \quad \sigma = \sqrt{\frac{1}{N} \sum_{i=0}^{N-1} (w_i - \text{Média})^2}$$
  O desvio padrão ($\sigma$) mede formalmente a uniformidade da distribuição do desgaste entre as células de memória flash.

---

### 2.3. Controladores RAID e Reconstrução XOR
- **RAID 0 (Striping):**
  Distribui dados entre $N$ discos sem redundância. LBA $i$ mapeia para Disco $d = i \pmod N$, Bloco $b = \lfloor i / N \rfloor$. Eficiência $= 100\%$. Falha de 1 disco inutiliza o arranjo.
- **RAID 1 (Mirroring):**
  Grava réplicas idênticas em $N$ discos ($N \ge 2$). Eficiência $= 1/N$. Sobrevive à falha de até $N-1$ discos.
- **RAID 4 (Dedicated Parity):**
  Striping em $N-1$ discos de dados e paridade dedicada no disco $N-1$.
- **RAID 5 (Distributed Parity):**
  Striping com rotação de paridade esquerda-simétrica entre faixas (*stripes*). Para a faixa $s = \lfloor i / (N-1) \rfloor$, o disco de paridade é $p = (N - 1) - (s \pmod N)$. Os dados da faixa ocupam os demais $N-1$ discos. Eficiência $= (N-1)/N$.
- **Cálculo da Paridade XOR:**
  Para cada byte $j$ do bloco (0 a $4095$):
  $$P[j] = D_0[j] \oplus D_1[j] \oplus \dots \oplus D_{N-2}[j]$$
- **Reconstrução On-The-Fly e Rebuild:**
  Com 1 disco offline em RAID 5 (estado `DEGRADED`), leituras no disco falho reconstroem os dados em tempo real:
  $$D_{\text{falho}}[j] = P[j] \oplus \bigoplus_{m \neq \text{falho}} D_m[j]$$
  O comando `rebuild_disk` restaura fisicamente os dados de todos os blocos do disco participante e restabelece o status `OPTIMAL`.

---

## 3. SUBSISTEMA DE SEGURANÇA E PROTEÇÃO (ETAPA 3)

### 3.1. Autenticação e Derivação de Chaves (PBKDF2-HMAC-SHA256)
- **Padrão Oficial:** PBKDF2-HMAC-SHA256 alinhado às recomendações do *OWASP Password Storage Cheat Sheet*.
- **Parâmetros:**
  - Salt individual aleatório: 16 bytes (`secrets.token_bytes(16)`).
  - Número de iterações de referência: **600.000 iterações** (armazenado nos metadados de cada credencial para permitir evolução futura de custo computacional).
  - Testes de desempenho no ambiente devem validar tempo de derivação adequado (~100-300 ms).
- **Verificação:** Comparação em tempo constante via `hmac.compare_digest(hash_calculado, hash_armazenado)` para imunidade a ataques de temporização (*timing attacks*).

---

### 3.2. Criptografia em Repouso (AES-256-GCM)
- **Padrão Oficial:** AES-256 no modo GCM (Galois/Counter Mode — AEAD).
- **Parâmetros e Estrutura:**
  - Nonce exclusivo: **12 bytes (96 bits)** gerado criptograficamente para cada gravação. Nunca reutilizar nonces com a mesma chave.
  - Tag de autenticação: **16 bytes (128 bits)** gerada automaticamente para validar integridade e autenticidade.
  - Formato no bloco simulado: `[12 bytes Nonce] + [16 bytes Tag] + [Ciphertext]`.
- **Separação de Chaves:** A chave utilizada para cifrar o arquivo **não** é o hash da senha de login do usuário. A chave de arquivo é derivada via HKDF/PBKDF2 com rótulo de contexto explícito (`info="file-encryption"`), isolando as funções de autenticação e confidencialidade.
- **Tratamento de Falhas:** Se o conteúdo cifrado for alterado ou corrompido, o GCM falha na verificação da tag e lança `InvalidTagException`, abortando a leitura e registrando alerta no `AuditLog`.
- **Dependência Autorizada:** Biblioteca `cryptography` autorizada para a Etapa 3.

---

### 3.3. Integridade e Antivírus Simulado
- **Detecção de Corrupção Acidental vs. Adulteração Maliciosa:**
  - *Corrupção Acidental:* Detectada por divergência entre o SHA-256 recalculado e o hash registrado no i-node.
  - *Adulteração Maliciosa:* Para prevenir que um invasor altere simultaneamente o bloco de dados e o hash de referência nos metadados, o Kernel mantém uma chave raiz protegida que assina os hashes via HMAC (`IntegrityRecord.hmac_signature`). Qualquer modificação não assinada pelo Kernel é detectada.
- **Antivírus Simulado (`antivirus_scan`):**
  - Percorre os blocos e compara padrões de bytes contra uma base de assinaturas simuladas (ex.: assinatura EICAR simulada). Emite relatório de arquivos íntegros, infectados e suspeitos.

---

## 4. SUBSISTEMA DE GERENCIAMENTO DE MEMÓRIA REAL E VIRTUAL (ETAPA 4)

### 4.1. Área Reservada Contígua e Compactação Deslizante (`memory_compact`)
- **Alocação:** First-Fit / Best-Fit sobre a lista ligada de `MemorySegment`.
- **Diagnóstico de Fragmentação Externa:**
  $$FE_{\text{mem}} = \text{Espaço Livre Total} - \text{Tamanho do Maior Segmento Livre Contíguo}$$
- **Algoritmo `memory_compact`:**
  1. Identificar segmentos alocados (`status == ALLOCATED`).
  2. Deslocar os segmentos contiguamente para a base da memória (após o Núcleo Base).
  3. Atualizar `start_address` e `end_address` de cada processo crítico/driver.
  4. Consolidar os buracos livres em um único segmento livre contíguo no topo da área reservada.

---

### 4.2. Paginação, MMU e Origens Válidas no Page Fault
- **Tradução:** $p = \lfloor \text{virtual\_address} / 4096 \rfloor$, $d = \text{virtual\_address} \pmod{4096}$.
- **Tratamento de Falta de Página (`present == False`):**
  1. Identificar a moldura livre. Se a RAM dinâmica estiver saturada, invocar substituição (LRU ou Segunda Chance).
  2. **Tratamento da Página Vítima:**
     - Se `dirty == False`: A página está limpa. Se possuir origem recuperável (`PROCESS_IMAGE`), é descartada da moldura sem gravação no Swap.
     - Se `dirty == True`: A página foi modificada. Deve ser obrigatoriamente gravada no Swap simulado via `BlockDevicePort`.
  3. **Carregamento da Página Requerida Conforme sua Origem Válida:**
     - *Origem `ZERO_FILL_ON_DEMAND`:* A moldura física é preenchida diretamente com zeros na RAM (`bytearray(4096)`). **Nenhuma leitura de Swap ou disco é acionada!**
     - *Origem `PROCESS_IMAGE`:* A página de código/dados é carregada do binário executável simulado.
     - *Origem `SWAP_STORAGE`:* A página já residiu na RAM e foi salva no Swap; é executado `swap_in` lendo o bloco de swap e liberando o slot correspondente.
  4. Atualizar `PageTableEntry`: `frame_id = frame`, `present = True`, `dirty = False`, `referenced = True`.

---

### 4.3. Algoritmos de Substituição de Páginas
- **LRU (Least Recently Used):** Elege a moldura cuja página possui o menor timestamp de último acesso (`last_access`).
- **Segunda Chance (Clock):** Percorre circularmente as molduras:
  - Se `referenced == False`: Vítima selecionada.
  - Se `referenced == True`: Concede segunda chance (`referenced = False`), avança ponteiro e continua.

---

## 5. SUBSISTEMA DE PROCESSOS, ESCALONAMENTO, CONCORRÊNCIA E EXECUÇÃO DISCRETA (ETAPA 5)

### 5.1. Máquina de Estados de 5 Estados e Sincronização de Processo Pai
- **Estados Válidos (`ProcessState`):** `NEW`, `READY`, `RUNNING`, `BLOCKED`, `TERMINATED` (o valor legado `WAITING` é normalizado para `BLOCKED` via `ProcessState.normalize`).
- **Transições Permitidas (`ProcessStateMachine.VALID_TRANSITIONS`):**
  - `NEW` $\to$ `{READY, TERMINATED}`
  - `READY` $\to$ `{RUNNING, TERMINATED}`
  - `RUNNING` $\to$ `{READY, BLOCKED, TERMINATED}`
  - `BLOCKED` $\to$ `{READY, TERMINATED}`
  - `TERMINATED` $\to$ $\emptyset$
  - Auto-transições (`src == dst`) e transições fora do mapa lançam `InvalidStateTransitionException` (subclasse de `InvalidProcessStateException`).
- **Sincronização Agregada (`ProcessManager.sync_process_state`):** Quando um processo possui threads filhas, seu estado derivado segue a precedência:
  1. `TERMINATED` se **todas** as threads estão `TERMINATED`;
  2. `RUNNING` se **alguma** thread está `RUNNING`;
  3. `READY` se **alguma** thread está `READY`;
  4. `BLOCKED` se **alguma** thread está `BLOCKED`;
  5. `NEW` caso contrário.

---

### 5.2. Escalonamento Multinível por Prioridade + Round-Robin (`PriorityRoundRobinScheduler`)
- **Interpretação de Prioridade:** Prioridade é um inteiro $\ge 1$, onde **`1` é a prioridade mais alta** e inteiros maiores representam prioridades menores (filas `1..5` pré-inicializadas, com expansão dinâmica para qualquer inteiro $\ge 1$). Dentro de cada nível, threads `READY` são mantidas em fila FIFO (`collections.deque`) sem duplicação de TID.
- **Preempção Cruzada entre Prioridades:** Ao enfileirar uma thread `READY` via `enqueue_ready(thread, timestamp_ms)`, se existir uma thread em execução (`running`) com `running.priority > thread.priority` (ou seja, a nova thread tem prioridade estritamente maior):
  1. `preempt_current` transiciona `running` de `RUNNING` $\to$ `READY`;
  2. Zera `running.quantum_used_ms = 0`;
  3. Insere `running` no final da fila FIFO de seu respectivo nível de prioridade;
  4. Incrementa `preemptions_total += 1` e limpa `running_tid = None`.
  5. Threads de prioridade igual ou menor não preemptam a thread corrente.
- **Contabilização de Quantum (Round-Robin):**
  - `quantum_ms >= 1` (padrão: `4` ms). A cada tick de 1 ms de CPU, `tick_quantum(1)` incrementa `running.quantum_used_ms += 1`.
  - Se `quantum_used_ms >= quantum_ms` ao fim do tick (e a thread permanecer `RUNNING`), `on_quantum_expired` transiciona `RUNNING` $\to$ `READY`, zera `quantum_used_ms = 0`, recoloca a thread na cauda da fila FIFO de sua prioridade e incrementa `quantum_expirations_total += 1`.
  - `quantum_used_ms` também é zerado em qualquer transição de saída de `RUNNING` (expiração de quantum, preempção, bloqueio ou encerramento).
- **Regra de Contagem de Troca de Contexto (`context_switches_total`):**
  - Ao despachar `next_thread` em `dispatch_next` (ou despacho imediato de syscall), `dispatches_total += 1`.
  - `context_switches_total` é incrementado **somente se** `last_dispatched_tid is not None and next_thread.tid != last_dispatched_tid`.
  - Arranque a frio (`last_dispatched_tid is None`) e re-despacho consecutivo da mesma thread (`T1 -> T1`, mesmo após expiração de quantum ou bloqueio/desbloqueio sem thread intermediária) **não** incrementam `context_switches_total`. `on_current_suspended()` preserva `last_dispatched_tid`.

---

### 5.3. Modelo Temporal Discreto, Desempate de Eventos e Avanço Ocioso
- **Relógio Lógico (`LogicalClock`):** Opera estritamente em milissegundos inteiros não negativos (`now_ms: int >= 0`), sem uso de relógio de parede ou `time.sleep`.
- **Chave Determinística de Ordenação (`SimulationEvent.sort_key`):** Todos os eventos na fila de prioridade `EventManager` (min-heap) são ordenados pela tupla `(timestamp_ms, priority, seq)`, onde `seq` é um contador monotônico crescente (`1, 2, ...`).
- **Tabela Oficial de Prioridades de Eventos Simultâneos (`EVENT_PRIORITY_MAP`):**
  1. `PROCESS_TERMINATED`: `0` (maior prioridade no mesmo `timestamp_ms`)
  2. `IO_COMPLETION`: `1`
  3. `MUTEX_WAKEUP`: `2`
  4. `SLEEP_WAKEUP`: `2`
  5. `PROCESS_ARRIVAL`: `3`
  6. `THREAD_ARRIVAL`: `3`
  7. `QUANTUM_EXPIRE`: `4`
  8. `SYSCALL_REQUEST`: `5`
  9. `DISPATCH_RESCHEDULE`: `6`
- **Avanço Ocioso (*Idle Fast-Forward*):** Quando não há thread `RUNNING` nem threads `READY` nas filas, `ExecutionEngine._advance_single_tick_or_idle` consulta `next_ev = event_manager.peek_next()`:
  - Se `next_ev is None`, invoca `_check_no_progress(now_ms)` (verifica deadlock ou estagnação) e encerra o avanço.
  - Se `next_ev` existe, calcula `jump_to = min(next_ev.timestamp_ms, cap_ms)` (ou `next_ev.timestamp_ms` se sem limite), registra fatia ociosa `[now_ms, jump_to]` via `metrics_collector.record_idle_slice`, avança `clock.advance_to(jump_to)` e drena eventos se `clock.now_ms >= next_ev.timestamp_ms`.
- **Ordem Exata de Execução de um Tick (`_advance_single_tick_or_idle`):**
  1. Drenar eventos com `timestamp_ms <= now_ms`.
  2. Se `running is None`, despachar próxima thread `READY` (ou executar avanço ocioso).
  3. Avaliar syscalls pendentes pré-tick (`check_due_syscalls`, cobrindo `trigger_cpu_ms == 0`). Se a thread deixar de estar `RUNNING`, encerrar o tick.
  4. Se `running.remaining_burst_ms <= 0`, concluir thread (`_complete_running_thread`) e drenar eventos em `now_ms`.
  5. Se o processo for `NORMAL` e nenhuma syscall explícita de memória executou no pré-tick, executar acesso automático de memória paginada (`_access_process_memory_tick`) com timestamp `float(now_ms)`.
  6. Consumir 1 ms de CPU (`cpu_consumed_ms += 1`), incrementar `tick_quantum(1)`, registrar fatia Gantt `[now_ms, now_ms + 1]` e avançar o relógio (`clock.advance_by(1)` para `after_ms`).
  7. Avaliar syscalls pós-tick para o novo `cpu_consumed_ms`.
  8. Se `RUNNING` e `remaining_burst_ms <= 0`, concluir thread em `after_ms`.
  9. Drenar eventos devidos em `after_ms` **antes** da checagem de expiração de quantum.
  10. Se a thread ainda estiver `RUNNING` e `quantum_used_ms >= quantum_ms`, expirar quantum (`on_quantum_expired`) em `after_ms`.

---

### 5.4. Syscalls por Tempo de CPU e Política `RANDOM` Determinística (`SyscallDispatcher`)
- **Gatilho por Tempo de CPU:** Todo `WorkloadStep` e perfil `IOProfile` é avaliado exclusivamente contra `thread.cpu_consumed_ms` (nunca contra o relógio global `now_ms`).
- **Validação de Limites:**
  - Para syscalls bloqueantes (`IO_READ`, `IO_WRITE`, `FS_READ`, `FS_WRITE`, `SLEEP_WAIT` com `duration_ms > 0`, e `MUTEX_LOCK`): exige $0 \le \text{trigger\_cpu\_ms} < \text{cpu\_burst\_ms}$ quando $\text{cpu\_burst\_ms} > 0$.
  - Para syscalls não bloqueantes: aceita $0 \le \text{trigger\_cpu\_ms} \le \text{cpu\_burst\_ms}$.
  - Para threads com `cpu_burst_ms == 0`, somente `trigger_cpu_ms == 0` é válido.
- **Modos de `IOProfile`:**
  - `NONE`: apenas `WorkloadStep` explícitos.
  - `FIXED`: inclui `profile.fixed_steps`.
  - `PERIODIC`: dispara enquanto $0 < \text{cpu\_consumed\_ms} < \text{cpu\_burst\_ms}$ sempre que $\text{cpu\_consumed\_ms} \bmod \text{interval\_cpu\_ms} == 0$.
  - `RANDOM` determinístico por thread:
    - Instancia gerador isolado `random.Random(seed + pid * 1009 + tid)` (jamais altera o estado global do módulo `random`).
    - Avaliado uma única vez por valor de `cpu_consumed_ms` múltiplo de `interval_cpu_ms` (padrão `1`) enquanto $0 < \text{cpu\_consumed\_ms} < \text{cpu\_burst\_ms}$.
    - Limitado por `max_random_events` (padrão `3`).
    - Dispara quando `rng.random() < io_probability` (padrão `0.25`), sorteando `duration_ms = rng.randint(min_duration_ms, max_duration_ms)` e `block_id = rng.randint(0, capacity - 1)` (para `IO_READ`/`IO_WRITE`).
- **Integração com E/S, VFS e ACL:**
  - `IO_READ` / `IO_WRITE` invocam `IOManager.dispatch_read` / `IOManager.dispatch_write` (ou `BlockDevicePort` como fallback). Quando `IO_WRITE` possui `data=None`, o payload existente do bloco é lido diretamente do backend sem alterar os contadores de leitura do `IOManager`, preservando dados gravados pelo VFS.
  - `FS_READ` / `FS_WRITE` invocam `FileSystemService` utilizando o `ExecutionContext` ativo e respeitando integralmente ACLs e auditoria.
  - Syscalls bloqueantes com `duration_ms > 0` transicionam `RUNNING` $\to$ `BLOCKED`, registram `BlockRecord` em `BlockRegistry` e agendam `IO_COMPLETION` (ou `SLEEP_WAKEUP` para `SLEEP_WAIT`) em `now_ms + duration_ms`.

---

### 5.5. Sincronização por Mutex, Filas FIFO, Wait-For Graph e Estagnação
- **Aquisição (`acquire`) e Fila FIFO:** Se o mutex está livre (`locked == False`), a thread adquire a posse imediata (`owner_tid`, `owner_pid`, `held_mutexes`). Se já está travado por outra thread, `contention_count += 1`, o `tid` entra no fim de `wait_queue` (FIFO), a thread transiciona para `BLOCKED` (`BlockReason.MUTEX_WAIT`, `blocked_on=mutex.name`) e `detect_deadlocks()` é executado imediatamente. Se a própria dona tentar readquirir (`owner_tid == thread.tid`), lança `DeadlockDetectedException` (*self-deadlock*).
- **Liberação e *Handoff* Imediato (`release` / `release_all_for_thread`):** Apenas a thread dona pode liberar (`MutexOwnershipException` caso contrário). Ao liberar (ou ao encerrar uma thread via `terminate_process` / término natural), o primeiro candidato não-`TERMINATED` da fila FIFO `wait_queue` recebe a posse imediata do mutex e transiciona `BLOCKED` $\to$ `READY`. Se a fila estiver vazia (ou contiver apenas encerradas), o mutex volta a `locked = False`.
- **Detecção de Deadlock por Grafo Wait-For (`detect_deadlocks`):**
  - Constrói arestas direcionadas `waiting_tid -> owner_tid` para todas as threads esperando em mutexes travados.
  - Detecta ciclos elementares por busca em profundidade canônica (estilo Johnson, iniciando pelo menor TID de cada ciclo para deduplicação determinística), auto-deadlocks e esperas cujo dono já esteja `TERMINATED` (`[TERMINATED]`).
- **Detecção de Estagnação sem Progresso (`check_no_progress`):**
  - Quando `has_ready == False`, `has_running == False` e `has_pending_events == False`, mas existem threads ativas em estado `BLOCKED`:
    - Se houver ciclo no Wait-For Graph: classifica como `DEADLOCK` e o `ExecutionEngine` lança `DeadlockDetectedException` (registrando no `AuditLog`).
    - Caso contrário (ex.: thread bloqueada em E/S sem evento de conclusão pendente): classifica como `STALL` e lança `SimulationStallException`.

---

### 5.6. Integração com Memória Virtual Dinâmica (Etapa 4)
- A cada tick de CPU de um processo `NORMAL` (se não houve syscall explícita `MEMORY_LOAD`/`MEMORY_WRITE` no pré-tick), `_access_process_memory_tick` consulta `thread.memory_access_pattern` (ou `proc.memory_access_pattern`) via cursor cíclico por TID, ou utiliza `(thread.cpu_consumed_ms % total_pages, False)` como padrão.
- Invoca `MemoryManager.execute_instruction(proc, instruction, current_time=float(now_ms))`, preservando integralmente o tratamento de `PageFaultException` (origens `PROCESS_IMAGE`, `ZERO_FILL_ON_DEMAND`, `SWAP_STORAGE`), substituição `LRU` / `SECOND_CHANCE` e `SwapManager`.
- Cada acesso gera um `FrameAccessRecord` (`HIT` ou `PAGE_FAULT`) e atualiza `page_hits_total` / `page_faults_total`. O comando `memory_frames` reflete o estado ao vivo das molduras de `PhysicalMemory`.

---

### 5.7. Fórmulas de Métricas de Desempenho (`MetricsCollector`)
- **Por Thread e por Processo (excluindo `Nucleo_Base` PID 0 das agregações globais):**
  - $\text{CPU} = \text{cpu\_consumed\_ms}$
  - $\text{WT (Waiting Time)} = \text{total\_wait\_ms}$ (tempo acumulado no estado `READY`)
  - $\text{BLK (Blocked Time)} = \text{total\_blocked\_ms}$ (tempo acumulado no estado `BLOCKED`)
  - $\text{TAT (Turnaround Time)} = \text{finish\_time\_ms} - \text{arrival\_time\_ms}$ (para threads concluídas satisfaz exatamente $\text{TAT} = \text{CPU} + \text{WT} + \text{BLK}$; `None` enquanto não concluída)
  - $\text{RT (Response Time)} = \text{start\_time\_ms} - \text{arrival\_time\_ms}$ (`None` antes do primeiro despacho)
- **Métricas Globais (`compute_global_metrics`):**
  - $\text{cpu\_busy\_ms} = \max(\sum \text{cpu\_consumed\_ms}, \sum_{\neg \text{idle}} \text{duration\_ms})$
  - $\text{total\_simulation\_ms} = \max(\text{clock\_now\_ms}, \text{cpu\_busy\_ms} + \text{explicit\_idle})$
  - $\text{idle\_time\_ms} = \text{total\_simulation\_ms} - \text{cpu\_busy\_ms} \implies \text{cpu\_busy\_ms} + \text{idle\_time\_ms} = \text{total\_simulation\_ms}$
  - $\text{CPU\_utilization (\%)} = \begin{cases} \frac{\text{cpu\_busy\_ms}}{\text{total\_simulation\_ms}} \times 100.0 & \text{se } \text{total\_simulation\_ms} > 0 \\ 0.0 & \text{se } \text{total\_simulation\_ms} = 0 \end{cases}$
  - $\text{avg\_waiting\_time\_ms} = \frac{1}{N_{\text{proc}}} \sum \text{WT}_i$, $\quad \text{avg\_turnaround\_time\_ms} = \frac{1}{N_{\text{concl}}} \sum \text{TAT}_j$, $\quad \text{throughput\_per\_sec} = \frac{N_{\text{concl}}}{\text{total\_simulation\_ms} / 1000.0}$
