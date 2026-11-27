# CATÁLOGO DE ESTRUTURAS DE DADOS — OS SIMULATOR

> **Status:** Especificação Oficial Consolidada (Etapa 5 — Processos, Threads, Escalonamento e Concorrência)  
> **Objetivo:** Definir com rigor formal todas as entidades, classes, atributos tipados em Python, contratos de interface (Portas), adaptadores provisórios/definitivos e relacionamentos entre os subsistemas do simulador.

---

## 1. CONVENÇÕES E DIRETRIZES DE TIPAGEM

1. **Tipos Python Nativos e Dataclasses:** Todas as estruturas devem ser representadas utilizando tipos da biblioteca padrão do Python (`typing`, `dataclasses`, `enum`, `collections`).
2. **Isolamento de Recursos:** Nenhum atributo pode conter ponteiros para o sistema de arquivos ou memória do Windows (`HANDLE`, caminhos reais no disco C:, ponteiros C types).
3. **Imutabilidade e Encapsulamento:** Identificadores únicos (`id`), capacidades físicas e tamanhos de blocos são imutáveis após a instanciação.

---

## 2. PORTAS ABSTRATAS E CONTRATOS DE DESACOPLAMENTO (CORE)

### 2.1. `BlockDevicePort` (Contrato de Armazenamento em Bloco)
| Campo | Especificação |
|---|---|
| **Tipo** | Interface Abstrata / Protocol (`abc.ABC` ou `typing.Protocol`) |
| **Subsistema** | `core.ports` |
| **Métodos Obrigatórios** | • `read_block(block_id: int) -> bytearray` — Lê o conteúdo do bloco informado.<br>• `write_block(block_id: int, data: bytearray) -> None` — Grava dados no bloco.<br>• `allocate_block() -> int` — Reserva um bloco livre e retorna seu ID numérico.<br>• `allocate_blocks(count: int) -> List[int]` — Reserva múltiplos blocos livres.<br>• `allocate_specific_blocks(block_ids: List[int]) -> List[int]` — Reserva blocos específicos (utilizado para alocação contígua e expansão in-place).<br>• `free_block(block_id: int) -> None` — Libera o bloco para reutilização.<br>• `free_blocks(block_ids: List[int]) -> None` — Libera múltiplos blocos.<br>• `get_capacity() -> int` — Retorna a capacidade total em blocos.<br>• `get_free_count() -> int` — Retorna o número de blocos atualmente livres.<br>• `get_used_count() -> int` — Retorna o número de blocos ocupados.<br>• `is_available(block_id: int) -> bool` — Verifica se o bloco é operacional (não danificado).<br>• `is_block_free(block_id: int) -> bool` — Verifica se o bloco está livre para alocação. |
| **Implementações** | • `InMemoryBlockDevice` (Etapa 1 — Adaptador provisório em memória RAM).<br>• `IOBlockDeviceAdapter` (Etapa 2 — Adaptador integrado a `IOManager`, `DiskScheduler` e `RAIDArray`). |
| **Responsabilidades** | Prover uma abstração de acesso a blocos desacoplada das implementações físicas e eletromecânicas. |

---

### 2.2. `AuthorizationPort` (Contrato de Autorização e Segurança)
| Campo | Especificação |
|---|---|
| **Tipo** | Interface Abstrata / Protocol |
| **Subsistema** | `core.ports` |
| **Métodos Obrigatórios** | • `check_read(context: ExecutionContext, path: str) -> bool` — Valida leitura.<br>• `check_write(context: ExecutionContext, path: str) -> bool` — Valida escrita.<br>• `check_execute(context: ExecutionContext, path: str) -> bool` — Valida execução.<br>• `is_admin(context: ExecutionContext) -> bool` — Valida privilégios de superusuário/Kernel. |
| **Implementações** | • `BootstrapSecurityPolicy` (Etapas 1 e 2 — Autorização ampla sob usuário simulado root).<br>• `SecurityManager` (Etapa 3 — Validação estrita por ACL POSIX, anéis de privilégio e auditoria). |
| **Responsabilidades** | Proteger recursos do sistema permitindo funcionamento provisório sem antecipação de código de segurança complexo. |

---

### 2.3. `ExecutionContext` (Contexto de Sessão Ativa)
| Campo | Especificação |
|---|---|
| **Classe** | `ExecutionContext` |
| **Subsistema** | `core.context` |
| **Atributos** | • `user_id: int` — UID do usuário ativo (0 para root).<br>• `username: str` — Nome do usuário da sessão corrente (padrão inicial: `"root"`).<br>• `groups: List[str]` — Grupos do usuário (padrão inicial: `["root", "admin"]`).<br>• `privilege_mode: PrivilegeMode` — Enum (`KERNEL_MODE`, `USER_MODE`).<br>• `cwd: str` — Diretório de trabalho atual no VFS (padrão: `"/"`). |
| **Responsabilidades** | Rastrear o estado de identidade e contexto de privilégio de cada comando executado. |

---

## 3. SUBSISTEMA DE SISTEMA DE ARQUIVOS (FILESYSTEM)

### 3.1. `Node` (Nó da Árvore Hierárquica)
| Campo | Especificação |
|---|---|
| **Classe** | `Node` (e subclasses `DirectoryNode`, `FileNode`) |
| **Subsistema** | `filesystem` |
| **Atributos** | • `name: str` — Nome do arquivo ou diretório.<br>• `node_type: NodeType` — Enum (`DIRECTORY`, `FILE`).<br>• `parent: Optional[DirectoryNode]` — Referência ao diretório pai (`None` na raiz `/`).<br>• `children: Dict[str, Node]` — Dicionário `nome -> Node` (vazio para arquivos).<br>• `inode_id: int` — Identificador do `Inode` associado.<br>• `created_at: float` — Timestamp simulado de criação.<br>• `modified_at: float` — Timestamp simulado de modificação. |
| **Responsabilidades** | Manter a topologia em árvore do VFS, permitindo travessia por caminhos absolutos e relativos, adição e remoção de nós filhos. |
| **Relacionamentos** | Referencia `Inode` por ID; associação 1:N com nós filhos em `DirectoryNode`. |

---

### 3.2. `Inode` (Estrutura de Metadados e Mapeamento de Blocos)
| Campo | Especificação |
|---|---|
| **Classe** | `Inode` |
| **Subsistema** | `filesystem` |
| **Atributos** | • `inode_id: int` — Identificador numérico único do i-node na tabela.<br>• `file_size: int` — Tamanho real do conteúdo em bytes.<br>• `permissions: str` — Máscara de permissões POSIX (ex.: `"755"`, `"750"`, `"644"`).<br>• `owner: str` — Nome do usuário proprietário.<br>• `group: str` — Nome do grupo associado.<br>• `allocated_blocks: List[int]` — Lista de IDs numéricos de blocos de dados (`block_id`).<br>• `allocation_strategy: AllocationStrategy` — Enum (`CONTIGUOUS`, `LINKED_FAT`, `INDEXED`).<br>• `index_block_id: Optional[int]` — ID do bloco de índice dedicado (quando alocação indexada).<br>• `is_encrypted: bool` — Flag indicando se o conteúdo dos blocos está cifrado.<br>• `integrity_hash: Optional[str]` — Checksum SHA-256 de referência do arquivo. |
| **Responsabilidades** | Centralizar metadados POSIX e rastrear os IDs de blocos alocados na camada de armazenamento via `BlockDevicePort`. |
| **Relacionamentos** | Mantido na tabela de i-nodes de `FileSystem`; referencia blocos gerenciados por `BlockDevicePort`. |

---

### 3.3. Métricas de Armazenamento no `FileSystem`
Para garantir transparência entre dados e sobrecarga estrutural:
1. **Espaço Ocupado pelos Dados (`data_space_used`):** Soma dos tamanhos reais (`file_size`) de todos os arquivos.
2. **Sobrecarga de Metadados (`metadata_overhead`):** Espaço consumido por blocos de índice dedicados ($\text{qtd\_blocos\_indice} \times 4096\text{ bytes}$) somado à tabela de metadados de i-nodes.
3. **Ocupação Física Total (`total_physical_used`):** Total de blocos de dados alocados mais blocos de índice multiplicados por $4.096\text{ bytes}$.
4. **Fragmentação Interna:** Calculada por arquivo como $(\text{blocos\_dados} \times 4096) - \text{file\_size}$.
5. **Fragmentação Externa:** Métricas separadas:
   - *Geral do Disco:* Total de bytes livres dispersos em blocos não contíguos que impedem alocações contíguas de tamanho $K$.
   - *Por Arquivo na Alocação Indexada:* Reportada oficialmente como $0\text{ bytes}$ (pois a alocação indexada aproveita blocos livres dispersos sem exigir contiguidade física).

---

## 4. SUBSISTEMA DE ENTRADA E SAÍDA (I/O) E ARMAZENAMENTO

### 4.1. `DiskBlock` (Propriedade Exclusiva da Camada de Storage)
| Campo | Especificação |
|---|---|
| **Classe** | `DiskBlock` |
| **Subsistema** | `io` (Camada de Armazenamento) |
| **Atributos** | • `block_id: int` — Endereço Lógico do Bloco (LBA).<br>• `capacity: int` — Capacidade fixa do bloco (padrão: `4096` bytes).<br>• `used_space: int` — Bytes efetivamente ocupados pela carga útil gravada.<br>• `data: bytearray` — Array de bytes em memória simulando o setor de armazenamento físico.<br>• `owner_inode: Optional[int]` — ID do i-node proprietário (`None` se livre).<br>• `block_status: BlockStatus` — Enum (`FREE`, `ALLOCATED`, `BAD`, `PARITY`).<br>• `checksum: str` — Hash SHA-256 do conteúdo do bloco.<br>• `next_block_id: Optional[int]` — Ponteiro para encadeamento em alocação FAT. |
| **Responsabilidades** | Manter os dados binários isolados na memória do Python. **Pertence unicamente à infraestrutura de armazenamento**. |

---

### 4.2. `PhysicalDisk` e `RAIDController`
| Campo | Especificação |
|---|---|
| **Classes** | `PhysicalDisk`, `RAIDController` (`RAID0Controller`, `RAID1Controller`, `RAID4Controller`, `RAID5Controller`, `RAIDFactory`) |
| **Subsistema** | `storage` |
| **Atributos de PhysicalDisk** | • `disk_id: int` — Identificador numérico do disco físico.<br>• `capacity_blocks: int` — Quantidade de blocos mantidos na unidade.<br>• `block_size: int` — Tamanho em bytes de cada bloco (padrão: 4096).<br>• `sectors_per_track: int` — Geometria de setores/blocos por trilha (padrão: 4).<br>• `total_tracks: int` — Número total de cilindros/trilhas calculado.<br>• `is_online: bool` — Indicador de integridade física (`True` online, `False` em falha simulada).<br>• `read_count: int` / `write_count: int` — Contadores operacionais.<br>• `blocks: List[DiskBlock]` — Coleção de blocos gerenciados exclusivamente pela camada de storage. |
| **Atributos de RAIDController** | • `level: RAIDLevel` — Enum (`RAID_0`, `RAID_1`, `RAID_4`, `RAID_5`).<br>• `disks: List[PhysicalDisk]` — Coleção de discos físicos participantes.<br>• `status: RAIDStatus` — Enum de integridade (`OPTIMAL`, `DEGRADED`, `FAILED`).<br>• `logical_capacity: int` — Capacidade útil de blocos exposta ao Filesystem.<br>• `storage_efficiency: float` — Eficiência calculada ($	ext{capacidade útil} / 	ext{capacidade bruta}$). |
| **Responsabilidades** | Distribuir dados em faixas (*striping*), manter espelhos, calcular paridade XOR e reconstruir blocos de discos em falha. |

---

### 4.3. `IORequest`, `IOQueue` e `DiskScheduler`
| Campo | Especificação |
|---|---|
| **Classes** | `IORequest`, `IOQueue`, `DiskScheduler`, `FCFSScheduler`, `SSTFScheduler`, `SCANScheduler`, `CSCANScheduler`, `SeekMetrics`, `SeekStep` |
| **Subsistema** | `io` |
| **Atributos de IORequest** | • `request_id: int` — Identificador sequencial da requisição.<br>• `operation: IOOperationType` — Enum (`READ`, `WRITE`).<br>• `block_id: int` — Endereço do bloco solicitado.<br>• `track: int` — Trilha física resolvida ($\lfloor 	ext{block\_id} / 	ext{sectors\_per\_track} floor$).<br>• `data: Optional[bytes | bytearray]` — Carga binária.<br>• `priority: IOPriority` — Nível de prioridade (`LOW`, `NORMAL`, `HIGH`, `CRITICAL`).<br>• `status: IORequestStatus` — Ciclo de vida (`QUEUED`, `PROCESSING`, `COMPLETED`, `FAILED`). |
| **Atributos de DiskScheduler** | • `initial_head: int` / `current_head: int` — Posição atual do cabeçote mecânico.<br>• `min_track: int` / `max_track: int` — Limites do curso de busca (padrão: 0 a 199).<br>• `direction: DiskDirection` — Sentido do deslocamento (`UP` ou `DOWN`). |
| **Atributos de SeekMetrics** | • `service_order: List[int]` — Ordem determinística de atendimento das trilhas.<br>• `total_seek_distance: int` — Somatório total das trilhas percorridas pelo braço.<br>• `steps: List[SeekStep]` — Histórico detalhado passo a passo da movimentação. |
| **Responsabilidades** | Reordenar a fila de requisições mecânicas para otimizar o tempo de busca e evitar starvation. |

---

### 4.4. `SSDDevice` e `SSDBlock` (Flash Translation Layer & Wear Leveling)
| Campo | Especificação |
|---|---|
| **Classes** | `SSDDevice`, `SSDBlock`, `WearLevelingMode` |
| **Subsistema** | `io.ssd` |
| **Atributos de SSDBlock** | • `physical_id: int` — Endereço físico do bloco (PBA).<br>• `write_count: int` — Total acumulado de ciclos de escrita/apagamento sofridos.<br>• `is_valid: bool` — Flag de validade do dado residente.<br>• `is_free: bool` — Bloco disponível para nova alocação.<br>• `logical_id: Optional[int]` — LBA atualmente mapeado neste PBA. |
| **Atributos de SSDDevice** | • `logical_capacity: int` — Capacidade lógica útil (LBAs visíveis).<br>• `physical_capacity: int` — Capacidade física total incluindo área de *overprovisioning*.<br>• `wear_mode: WearLevelingMode` — Estratégia ativa (`NONE`, `DYNAMIC`, `STATIC`).<br>• `ftl_map: Dict[int, int]` — Tabela de mapeamento lógico-físico (LBA $	o$ PBA).<br>• `static_threshold: int` — Limiar $(\max - \min)$ para disparo de nivelamento estático. |
| **Responsabilidades** | Mapear LBAs para PBAs dinamicamente, redistribuir escritas para minimizar desgaste e calcular métricas estatísticas (desvio padrão e média de desgaste). |

## 5. SUBSISTEMA DE SEGURANÇA E PROTEÇÃO

### 5.1. `User` e Credenciais
| Campo | Especificação |
|---|---|
| **Classe** | `User` |
| **Subsistema** | `security` |
| **Atributos** | • `user_id: int` — UID POSIX (0 para root).<br>• `username: str` — Nome do usuário.<br>• `password_hash: bytes` — Hash derivado por PBKDF2-HMAC-SHA256.<br>• `salt: bytes` — Sal criptográfico individual de 16 bytes (`secrets.token_bytes(16)`).<br>• `iterations: int` — Número de iterações PBKDF2 (padrão: 600.000, configurável por credencial).<br>• `groups: List[str]` — Lista de grupos do usuário.<br>• `privilege_mode: PrivilegeMode` — Enum (`USER_MODE`, `KERNEL_MODE`). |
| **Responsabilidades** | Manter credenciais seguras e histórico de iterações alinhado ao OWASP Cheat Sheet. |

---

### 5.2. `EncryptedPayload` (Estrutura de Criptografia AES-256-GCM)
| Campo | Especificação |
|---|---|
| **Classe** | `EncryptedPayload` |
| **Subsistema** | `security.crypto` |
| **Atributos** | • `nonce: bytes` — Vetor de inicialização/nonce exclusivo de 12 bytes (96 bits).<br>• `tag: bytes` — Tag de autenticação AEAD de 16 bytes (128 bits).<br>• `ciphertext: bytes` — Dados do arquivo cifrados com AES-256.<br>• `key_id: str` — Identificador da chave derivada utilizada. |
| **Layout no Bloco** | O bloco físico armazena o empacotamento: `[12 bytes Nonce] + [16 bytes Tag] + [Ciphertext]`. |
| **Responsabilidades** | Garantir sigilo e autenticidade da carga útil, prevenindo adulteração silenciosa e ataques de repetição. |

---

### 5.3. `IntegrityRecord` (Registro de Integridade Protegido)
| Campo | Especificação |
|---|---|
| **Classe** | `IntegrityRecord` |
| **Subsistema** | `security.integrity` |
| **Atributos** | • `resource_path: str` — Caminho do arquivo monitorado.<br>• `expected_sha256: str` — Hash SHA-256 esperado da carga útil.<br>• `hmac_signature: str` — Assinatura HMAC gerada pelo Kernel com chave raiz protegida.<br>• `last_verified: float` — Timestamp da última validação íntegra. |
| **Responsabilidades** | Prevenir adulterações simultâneas de bloco e metadados: a assinatura HMAC do Kernel detecta se um invasor alterou tanto o bloco quanto o hash de referência no i-node. |

---

## 6. SUBSISTEMA DE GERENCIAMENTO DE MEMÓRIA REAL E VIRTUAL

### 6.1. `PageOrigin` (Enum de Origem Válida de Páginas)
| Nome | Significado | Comportamento no Page Fault |
|---|---|---|
| `PROCESS_IMAGE` | Código executável / dados estáticos do binário. | Carregado do segmento de processo simulado no disco. |
| `ZERO_FILL_ON_DEMAND` | Heap ou pilha virgem (não alocada anteriormente). | Moldura é preenchida diretamente com zeros na RAM (sem I/O de Swap!). |
| `SWAP_STORAGE` | Página que já residiu na RAM e foi descarregada por substituição. | Carregada a partir do slot correspondente da partição de Swap. |

---

### 6.2. `PageTableEntry` (Entrada da Tabela de Páginas)
| Campo | Especificação |
|---|---|
| **Classe** | `PageTableEntry` |
| **Subsistema** | `memory` |
| **Atributos** | • `logical_page: int` — Número da página virtual ($p$).<br>• `frame_id: Optional[int]` — Número da moldura física ($f$) onde reside (`None` se ausente).<br>• `present: bool` — Bit de presença (`True` na RAM; `False` aciona Page Fault).<br>• `dirty: bool` — Bit de modificação (`True` se alterada em RAM desde o carregamento).<br>• `referenced: bool` — Bit de referência para Segunda Chance (Clock).<br>• `last_access: float` — Timestamp de acesso recente para LRU.<br>• `page_origin: PageOrigin` — Origem válida da página para resolução de Page Fault.<br>• `swap_slot_id: Optional[int]` — Número do slot de swap (quando `page_origin == SWAP_STORAGE`). |
| **Responsabilidades** | Mapear o endereço virtual e fornecer metadados para reposição e recuperação de faltas. |

---

### 6.3. `MemorySegment` (Área Reservada Contígua)
| Campo | Especificação |
|---|---|
| **Classe** | `MemorySegment` |
| **Subsistema** | `memory` |
| **Atributos** | • `segment_id: int` — ID do segmento.<br>• `process_name: Optional[str]` — Nome do processo crítico/driver (ex.: `"Kernel_DiskDriver"`).<br>• `start_address: int` — Endereço inicial em KB.<br>• `end_address: int` — Endereço final em KB.<br>• `size: int` — Tamanho em KB.<br>• `status: SegmentStatus` — Enum (`ALLOCATED`, `FREE`). |
| **Responsabilidades** | Representar blocos contíguos de memória do núcleo e diagnosticar fragmentação externa. |

---

### 6.4. `SwapManager`
| Campo | Especificação |
|---|---|
| **Classe** | `SwapManager` |
| **Subsistema** | `memory` / `storage` |
| **Atributos** | • `total_slots: int` — Quantidade de slots de troca disponíveis.<br>• `slot_size: int` — Tamanho do slot (padrão: 4096 bytes).<br>• `slots_in_use: Dict[int, Tuple[int, int]]` — Mapeamento `slot_id -> (pid, logical_page)`.<br>• `block_device: BlockDevicePort` — Dispositivo de blocos onde o swap é persistido. |
| **Responsabilidades** | Alocar e liberar slots de swap e coordenar operações de leitura/escrita de páginas descarregadas via `BlockDevicePort`. |

---

## 7. SUBSISTEMA DE PROCESSOS, THREADS, ESCALONAMENTO, CONCORRÊNCIA E MÉTRICAS (ETAPA 5)

### 7.1. `LogicalClock` e `EventManager` (Infraestrutura Temporal Discreta)
| Campo | Especificação |
|---|---|
| **Classes** | `LogicalClock` (`core.clock`), `SimulationEvent` e `EventManager` (`core.events`) |
| **Atributos de `LogicalClock`** | • `now_ms: int` — Tempo lógico corrente em milissegundos inteiros (`>= 0`, monotônico).<br>• Métodos: `advance_by(delta_ms: int) -> int`, `advance_to(target_ms: int) -> int`, `reset(initial_ms: int = 0) -> None`, `to_dict() -> Dict[str, int]`. |
| **Atributos de `SimulationEvent`** | • `timestamp_ms: int`, `priority: int`, `seq: int` (chave de ordenação `(timestamp_ms, priority, seq)`).<br>• `event_type: SimulationEventType` — Enum: `PROCESS_TERMINATED` (prio 0), `IO_COMPLETION` (1), `MUTEX_WAKEUP` (2), `SLEEP_WAKEUP` (2), `PROCESS_ARRIVAL` (3), `THREAD_ARRIVAL` (3), `QUANTUM_EXPIRE` (4), `SYSCALL_REQUEST` (5), `DISPATCH_RESCHEDULE` (6).<br>• `pid: Optional[int]`, `tid: Optional[int]`, `payload: Dict[str, Any]`, `cancelled: bool`. |
| **Métodos de `EventManager`** | `schedule_at(...)`, `schedule(delay_ms, ...)`, `cancel_event(seq)`, `cancel_for_entity(pid=None, tid=None, event_types=None)`, `peek_next()`, `pop_next()`, `pop_ready_at(now_ms)`, `is_empty()`, `pending_events()`, `clear()`. |

---

### 7.2. `ProcessStateMachine` e `StateTransitionRecord`
| Campo | Especificação |
|---|---|
| **Classes** | `ProcessStateMachine`, `StateTransitionRecord` (`process.state_machine`) |
| **Enum `ProcessState`** | `NEW` (`NOVO`), `READY` (`PRONTO`), `RUNNING` (`EXECUTANDO`), `BLOCKED` (`BLOQUEADO`), `WAITING` (alias legado normalizado para `BLOCKED`), `TERMINATED` (`CONCLUIDO`). |
| **Atributos de `StateTransitionRecord`** | • `entity_id: str` (ex.: `"TID:1"`, `"PID:100"`), `timestamp_ms: int`, `from_state: ProcessState`, `to_state: ProcessState`, `reason: str`. |
| **Responsabilidades** | Validar transições do modelo de 5 estados (`VALID_TRANSITIONS`), rejeitar auto-transições ou transições ilegais com `InvalidStateTransitionException` e registrar o histórico auditável. |

---

### 7.3. `Process` (PCB Estendido), `SimulatedThread` e `WorkloadStep`
| Campo | Especificação |
|---|---|
| **Classes** | `Process` (`process.pcb`), `SimulatedThread` e `WorkloadStep` / alias `SyscallSpec` (`process.thread`) |
| **Novos Atributos de `Process`** | • Preserva todos os atributos da Etapa 4 (`pid`, `name`, `size_bytes`, `process_type`, `owner`, `state`, `page_table`, `segment_id`).<br>• Extensões Etapa 5: `priority: int` (padrão `3`, `>= 1`), `cpu_burst_ms: int` (padrão `0`), `arrival_time_ms: int` (padrão `0`), `io_profile: Any` (padrão `IOProfileType.NONE`), `memory_access_pattern: List[Tuple[int, bool]]`, `start_time_ms: Optional[int]`, `finish_time_ms: Optional[int]`, `threads: Dict[int, SimulatedThread]`, `thread_name_to_tid: Dict[str, int]`.<br>• Propriedades agregadas: `cpu_consumed_ms`, `remaining_burst_ms`, `total_wait_ms`, `total_blocked_ms`. |
| **Atributos de `SimulatedThread`** | • `tid: int`, `pid: int`, `name: str`, `state: ProcessState`, `priority: int` (`>= 1`), `cpu_burst_ms: int`, `cpu_consumed_ms: int`, `quantum_used_ms: int`, `arrival_time_ms: int`, `start_time_ms: Optional[int]`, `finish_time_ms: Optional[int]`, `ready_since_ms: Optional[int]`, `total_wait_ms: int`, `total_blocked_ms: int`, `blocked_since_ms: Optional[int]`, `block_reason: BlockReason`, `blocked_on: Optional[str]`, `held_mutexes: List[str]`, `workload_steps: List[WorkloadStep]`, `memory_access_pattern: List[Tuple[int, bool]]`, `io_profile: Any`. |
| **Atributos de `WorkloadStep`** | • `trigger_cpu_ms: int`, `syscall_type: SyscallType` (`IO_READ`, `IO_WRITE`, `FS_READ`, `FS_WRITE`, `SLEEP_WAIT`, `YIELD`, `MUTEX_LOCK`, `MUTEX_UNLOCK`, `MEMORY_LOAD`, `MEMORY_WRITE`, `EXIT`), `duration_ms: int`, `block_id: Optional[int]`, `path: Optional[str]`, `data: Optional[Union[bytes, str]]`, `mutex_name: Optional[str]`, `logical_page: Optional[int]`, `is_write: bool`, `executed: bool`, `status: str`, `result: Optional[Any]`. |

---

### 7.4. `PriorityRoundRobinScheduler`
| Campo | Especificação |
|---|---|
| **Classe** | `PriorityRoundRobinScheduler` (`process.scheduler`) |
| **Atributos** | • `process_manager: ProcessManager`, `quantum_ms: int` (padrão `4`), `context_switch_overhead_ms: int` (padrão `0`).<br>• `queues: Dict[int, Deque[int]]` — Filas FIFO indexadas por prioridade (`1..5` pré-criadas e expansão dinâmica para inteiros `>= 1`).<br>• `running_tid: Optional[int]`, `last_dispatched_tid: Optional[int]`.<br>• Contadores: `dispatches_total`, `context_switches_total`, `preemptions_total`, `quantum_expirations_total`. |
| **Métodos Principais** | `enqueue_ready(thread, timestamp_ms)`, `select_next()`, `dispatch_next(timestamp_ms)`, `tick_quantum(delta_ms=1)`, `on_quantum_expired(timestamp_ms)`, `preempt_current(timestamp_ms, reason)`, `on_current_suspended()`, `remove(tid)`, `set_quantum(quantum_ms)`, `get_ready_queues()`, `get_stats()`, `format_queues()`, `reset()`. |

---

### 7.5. `IOProfile`, `BlockRecord`, `BlockRegistry` e `SyscallDispatcher`
| Campo | Especificação |
|---|---|
| **Classes** | `IOProfile`, `BlockRecord`, `BlockRegistry`, `SyscallExecutionRecord`, `SyscallDispatcher` (`process.syscalls`) |
| **Atributos de `IOProfile`** | • `profile_type: IOProfileType` (`NONE`, `FIXED`, `PERIODIC`, `RANDOM`).<br>• `interval_cpu_ms: Optional[int]`, `default_duration_ms: int` (`4`), `min_duration_ms: int` (`2`), `max_duration_ms: int` (`6`), `io_probability: float` (`0.25`), `max_random_events: int` (`3`), `seed: int` (`42`), `syscall_type: SyscallType` (`IO_READ`), `block_id: int` (`0`), `fixed_steps: List[WorkloadStep]`. |
| **Atributos de `BlockRecord`** | • `tid: int`, `pid: int`, `thread_name: str`, `process_name: str`, `reason: BlockReason` (`IO_WAIT`, `FS_IO`, `SLEEP_WAIT`, `MUTEX_WAIT`), `resource_id: Optional[str]`, `blocked_at_ms: int`, `expected_unblock_at_ms: Optional[int]`, `unblocked_at_ms: Optional[int]`, `previous_state: ProcessState`, `next_state: Optional[ProcessState]`, `syscall_type: Optional[SyscallType]`. |
| **Responsabilidades** | `SyscallDispatcher` verifica `check_due_syscalls(thread, now_ms)` estritamente por `cpu_consumed_ms`, despacha E/S via `IOManager`/`BlockDevicePort` e VFS via `FileSystemService` + `ExecutionContext`, registra bloqueios em `BlockRegistry` e agenda `IO_COMPLETION`/`SLEEP_WAKEUP`. |

---

### 7.6. `Mutex` e `SynchronizationManager`
| Campo | Especificação |
|---|---|
| **Classes** | `Mutex`, `SynchronizationManager` (`process.sync`) |
| **Atributos de `Mutex`** | • `name: str`, `locked: bool`, `owner_tid: Optional[int]`, `owner_pid: Optional[int]`, `wait_queue: Deque[int]` (fila FIFO de TIDs).<br>• Contadores e auditoria: `acquire_count: int`, `release_count: int`, `contention_count: int`, `history: List[Dict[str, Any]]`. |
| **Métodos de `SynchronizationManager`** | `create_mutex(name)`, `get_mutex(name)`, `get_or_create_mutex(name)`, `list_mutexes()`, `acquire(mutex_name, thread_or_tid, timestamp_ms)`, `release(mutex_name, thread_or_tid, timestamp_ms)`, `release_all_for_thread(tid, timestamp_ms)`, `detect_deadlocks()`, `check_no_progress(has_ready, has_running, has_pending_events)`, `setup_buffer_video_scenario(...)`, `get_status()`, `format_status()`, `clear()`. |

---

### 7.7. `MetricsCollector`, `TimelineEntry`, `GanttSlice`, `FrameAccessRecord` e Relatórios
| Campo | Especificação |
|---|---|
| **Classes** | `TimelineEntry`, `GanttSlice`, `FrameAccessRecord`, `ThreadMetrics`, `ProcessMetrics`, `SimulationMetrics`, `MetricsCollector` (`process.metrics`) |
| **Atributos de `TimelineEntry`** | • `seq: int`, `timestamp_ms: int`, `event_type: str`, `pid: Optional[int]`, `tid: Optional[int]`, `process_name: str`, `thread_name: str`, `state: str`, `priority: Optional[int]`, `cpu_consumed_ms: int`, `quantum_used_ms: int`, `details: str`. |
| **Atributos de `GanttSlice`** | • `start_ms: int`, `end_ms: int`, `pid: Optional[int]`, `tid: Optional[int]`, `process_name: str`, `thread_name: str`, `label: str` (`"EXEC"`, `"IDLE"`, etc.), `is_idle: bool`, propriedade `duration_ms`. |
| **Atributos de `ThreadMetrics` / `ProcessMetrics`** | • `tid`/`pid`, `name`, `state`, `priority`, `cpu_burst_ms`, `arrival_time_ms`, `start_time_ms`, `finish_time_ms`, `cpu_time_ms`, `waiting_time_ms`, `blocked_time_ms`, `turnaround_time_ms`, `response_time_ms`, `syscalls_count`, `io_blocks_count`, `mutex_blocks_count`, `page_hits`, `page_faults` (`ProcessMetrics` inclui `process_type` e `thread_metrics: List[ThreadMetrics]`). |
| **Atributos de `SimulationMetrics`** | • `total_simulation_ms`, `cpu_busy_ms`, `idle_time_ms`, `cpu_utilization_pct`, `context_switches_total`, `dispatches_total`, `preemptions_total`, `syscalls_total`, `io_blocks_total`, `mutex_blocks_total`, `page_hits_total`, `page_faults_total`, `avg_waiting_time_ms`, `avg_turnaround_time_ms`, `completed_processes`, `total_processes`, `throughput_per_sec`, `process_metrics`. |
| **Resumo ao Vivo de Molduras** | `build_frames_summary(memory_manager, process_lookup=None, frame_records=None)` lê diretamente `memory_manager.physical_memory.frames` + `PageTableEntry`, retornando `frame_id`, `occupied`, `pid`, `logical_page`, `state` (`OCUPADA`/`LIVRE`), `last_event` (`HIT`/`PAGE_FAULT`/`N/A`), `last_access`, `dirty`, `referenced` e `algorithm`. |
