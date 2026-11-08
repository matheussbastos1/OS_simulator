# CATÁLOGO DE ESTRUTURAS DE DADOS — OS SIMULATOR

> **Status:** Especificação Oficial (Fase 0)  
> **Objetivo:** Definir com rigor formal todas as entidades, classes, atributos tipados em Python, responsabilidades e relacionamentos entre os subsistemas do simulador.

---

## 1. CONVENÇÕES E DIRETRIZES DE TIPAGEM

1. **Tipos Python Nativos e Dataclasses:** Todas as estruturas devem ser representadas utilizando tipos da biblioteca padrão do Python (`typing`, `dataclasses`, `enum`, `collections`).
2. **Isolamento de Recursos:** Nenhum atributo pode conter ponteiros para o sistema de arquivos ou memória do Windows (`HANDLE`, `HWND`, caminhos de arquivo NTFS no disco C:, ponteiros C types).
3. **Imutabilidade e Encapsulamento:** Identificadores únicos (`id`), tamanhos de blocos e capacidades físicas são imutáveis após a instanciação.

---

## 2. SUBSISTEMA DE SISTEMA DE ARQUIVOS (FILESYSTEM)

### 2.1. `Node` (Nó da Árvore Hierárquica)
| Campo | Especificação |
|---|---|
| **Classe** | `Node` (e subclasses `DirectoryNode`, `FileNode`) |
| **Subsistema** | `filesystem` |
| **Atributos** | • `name: str` — Nome do arquivo ou diretório.<br>• `node_type: NodeType` — Enum (`DIRECTORY`, `FILE`).<br>• `parent: Optional[DirectoryNode]` — Referência ao diretório pai (`None` na raiz `/`).<br>• `children: Dict[str, Node]` — Dicionário `nome -> Node` (vazio para arquivos).<br>• `inode: Inode` — Instância do i-node contendo metadados e blocos.<br>• `created_at: float` — Timestamp simulado de criação.<br>• `modified_at: float` — Timestamp simulado de modificação. |
| **Responsabilidades** | Manter a topologia em árvore do VFS, permitindo travessia por caminhos absolutos e relativos, adição e remoção de nós filhos. |
| **Relacionamentos** | Composição com `Inode`; associação 1:N com nós filhos em `DirectoryNode`. |

---

### 2.2. `Inode` (Estrutura de Metadados e Mapeamento)
| Campo | Especificação |
|---|---|
| **Classe** | `Inode` |
| **Subsistema** | `filesystem` |
| **Atributos** | • `inode_id: int` — Identificador numérico único do i-node na tabela.<br>• `file_size: int` — Tamanho real do conteúdo em bytes.<br>• `permissions: ACL` — Instância de ACL com permissões rwx para proprietário, grupo e outros.<br>• `owner: str` — Nome do usuário proprietário.<br>• `group: str` — Nome do grupo associado.<br>• `allocated_blocks: List[int]` — Lista de IDs de blocos de disco alocados.<br>• `allocation_strategy: AllocationStrategy` — Enum (`CONTIGUOUS`, `LINKED_FAT`, `INDEXED`).<br>• `metadata: Dict[str, Any]` — Dicionário de metadados extras (ex.: flag `is_encrypted`, hash de integridade, número de links).<br>• `index_block_id: Optional[int]` — ID do bloco de índice quando alocação indexada. |
| **Responsabilidades** | Centralizar metadados POSIX, registrar quais blocos físicos pertencem ao arquivo e manter integridade de tamanho vs. alocação. |
| **Relacionamentos** | Referenciado por `Node`; aponta para múltiplos `DiskBlock`; agrega `ACL`. |

---

### 2.3. `DiskBlock` (Bloco Físico Simulado)
| Campo | Especificação |
|---|---|
| **Classe** | `DiskBlock` |
| **Subsistema** | `filesystem` / `io` |
| **Atributos** | • `block_id: int` — Endereço Lógico do Bloco (LBA).<br>• `capacity: int` — Capacidade fixa do bloco em bytes (padrão: `4096` bytes).<br>• `used_space: int` — Bytes efetivamente gravados na carga útil.<br>• `data: bytearray` — Array de bytes em memória simulando o setor de armazenamento.<br>• `owner_inode: Optional[int]` — ID do i-node proprietário (`None` se livre).<br>• `block_status: BlockStatus` — Enum (`FREE`, `ALLOCATED`, `BAD`, `PARITY`).<br>• `checksum: str` — Hash SHA-256 da carga útil para verificação de integridade.<br>• `next_block_id: Optional[int]` — Ponteiro para o próximo bloco (utilizado na Alocação Encadeada / FAT). |
| **Responsabilidades** | Armazenar dados binários isolados na memória do Python, verificar saturação de capacidade e calcular integridade. |
| **Relacionamentos** | Pertence a um `PhysicalDisk` ou `RAIDArray`; referenciado por um `Inode`. |

---

### 2.4. `FileSystem` (Gerenciador do Sistema de Arquivos)
| Campo | Especificação |
|---|---|
| **Classe** | `FileSystem` |
| **Subsistema** | `filesystem` |
| **Atributos** | • `root: DirectoryNode` — Diretório raiz `/`.<br>• `block_size: int` — Tamanho padrão de bloco em bytes (padrão `4096`).<br>• `total_blocks: int` — Quantidade total de blocos simulados disponíveis.<br>• `inode_table: Dict[int, Inode]` — Tabela indexada de i-nodes ativos.<br>• `allocation_strategy: AllocationStrategy` — Estratégia global corrente de alocação.<br>• `free_block_bitmap: List[bool]` — Bitmap de blocos livres/ocupados.<br>• `fat_table: Dict[int, Optional[int]]` — Tabela de alocação de arquivos (quando no modo FAT). |
| **Responsabilidades** | Administrar o espaço de armazenamento de arquivos, formatar sistema de arquivos, calcular fragmentação interna e externa, e sincronizar metadados. |
| **Relacionamentos** | Agrega `Node`, gerencia `Inode` e orquestra requisições via `IOManager`. |

---

## 3. SUBSISTEMA DE ENTRADA E SAÍDA (I/O) E ARMAZENAMENTO

### 3.1. `PhysicalDisk` (Disco Físico Simulado)
| Campo | Especificação |
|---|---|
| **Classe** | `PhysicalDisk` |
| **Subsistema** | `io` |
| **Atributos** | • `disk_id: int` — Identificador numérico do disco.<br>• `total_blocks: int` — Número total de blocos da unidade.<br>• `tracks: int` — Número de cilindros/trilhas (ex.: 200 trilhas).<br>• `current_head_position: int` — Posição atual do cabeçote de leitura/escrita (número da trilha).<br>• `disk_type: DiskType` — Enum (`HDD`, `SSD`).<br>• `failed: bool` — Flag indicando falha física da unidade.<br>• `blocks: Dict[int, DiskBlock]` — Mapeamento de blocos físicos em memória.<br>• `write_cycles: Dict[int, int]` — Contador de gravações por bloco (para SSD Wear Leveling). |
| **Responsabilidades** | Simular o comportamento eletromecânico (posição do cabeçote, busca de trilha) ou de estado sólido (ciclos de desgaste). |
| **Relacionamentos** | Agrupado dentro de um `RAIDArray` ou gerenciado diretamente pelo `IOManager`. |

---

### 3.2. `RAIDArray` (Controlador de Arranjo Redundante)
| Campo | Especificação |
|---|---|
| **Classe** | `RAIDArray` |
| **Subsistema** | `io` |
| **Atributos** | • `raid_level: RAIDLevel` — Enum (`RAID0`, `RAID1`, `RAID4`, `RAID5`).<br>• `physical_disks: List[PhysicalDisk]` — Lista ordenada de discos físicos que compõem o arranjo.<br>• `stripe_size: int` — Tamanho do stripe em blocos ou bytes.<br>• `parity_blocks: Dict[int, int]` — Mapeamento de endereço de paridade para disco responsável.<br>• `status: RAIDStatus` — Enum (`OPTIMAL`, `DEGRADED`, `FAILED`). |
| **Responsabilidades** | Intercalar blocos lógicos entre discos físicos, calcular e gravar paridade XOR, detectar unidades falhas e reconstruir dados (*rebuild*). |
| **Relacionamentos** | Contém instâncias de `PhysicalDisk`; fornece interface de bloco para o `FileSystem`. |

---

### 3.3. `IORequest` (Requisição de E/S)
| Campo | Especificação |
|---|---|
| **Classe** | `IORequest` |
| **Subsistema** | `io` |
| **Atributos** | • `request_id: int` — Identificador sequencial da requisição.<br>• `operation_type: IOOperationType` — Enum (`READ`, `WRITE`).<br>• `target_block: int` — Bloco LBA de destino.<br>• `target_track: int` — Trilha física onde o bloco reside.<br>• `data: Optional[bytearray]` — Carga útil a ser gravada (ou buffer a preencher).<br>• `priority: IOPriority` — Enum (`LOW`, `NORMAL`, `HIGH`, `KERNEL`).<br>• `status: IORequestStatus` — Enum (`PENDING`, `PROCESSING`, `COMPLETED`, `FAILED`).<br>• `timestamp: float` — Momento da criação da requisição. |
| **Responsabilidades** | Encapsular os parâmetros de uma operação de leitura/escrita para enfileiramento e escalonamento. |
| **Relacionamentos** | Inserido na fila de `DiskScheduler`. |

---

### 3.4. `DiskScheduler` (Escalonador de Disco)
| Campo | Especificação |
|---|---|
| **Classe** | `DiskScheduler` |
| **Subsistema** | `io` |
| **Atributos** | • `algorithm: SchedulingAlgorithm` — Enum (`FCFS`, `SSTF`, `SCAN`, `CSCAN`).<br>• `request_queue: List[IORequest]` — Fila de requisições pendentes.<br>• `total_head_movement: int` — Acumulador da distância total percorrida pelo cabeçote (em trilhas).<br>• `current_direction: ScanDirection` — Enum (`UP`, `DOWN`) para algoritmos SCAN/C-SCAN. |
| **Responsabilidades** | Reordenar a fila de requisições segundo o algoritmo selecionado visando otimizar a movimentação mecânica. |
| **Relacionamentos** | Opera sobre requisições `IORequest` e atualiza a posição do cabeçote em `PhysicalDisk`. |

---

## 4. SUBSISTEMA DE SEGURANÇA E PROTEÇÃO

### 4.1. `User` e `Group` (Identidades do Sistema)
| Campo | Especificação |
|---|---|
| **Classes** | `User`, `Group` |
| **Subsistema** | `security` |
| **Atributos de User** | • `user_id: int` — UID POSIX simulado (0 para root).<br>• `username: str` — Nome do usuário.<br>• `password_hash: bytes` — Hash criptográfico da senha gerado por PBKDF2.<br>• `salt: bytes` — Sal de 16 ou 32 bytes gerado por `secrets.token_bytes`.<br>• `groups: List[str]` — Lista de nomes de grupos aos quais o usuário pertence.<br>• `privilege_mode: PrivilegeMode` — Enum (`USER_MODE`, `KERNEL_MODE`). |
| **Atributos de Group** | • `group_id: int` — GID numérico.<br>• `group_name: str` — Nome do grupo (ex.: `admin`, `devs`, `users`).<br>• `members: List[str]` — Lista de nomes de usuários membros do grupo. |
| **Responsabilidades** | Manter a identidade, credenciais seguras e escopo de grupos de cada usuário. |
| **Relacionamentos** | `User` associado a múltiplos `Group`; referenciados em `ACL` e `AuditEntry`. |

---

### 4.2. `ACL` (Lista de Controle de Acesso POSIX)
| Campo | Especificação |
|---|---|
| **Classe** | `ACL` |
| **Subsistema** | `security` |
| **Atributos** | • `owner_permissions: int` — Máscara binária de 3 bits para proprietário (`r=4, w=2, x=1`).<br>• `group_permissions: int` — Máscara binária de 3 bits para o grupo.<br>• `others_permissions: int` — Máscara binária de 3 bits para outros usuários.<br>• `octal_representation: str` — String de 3 dígitos (ex.: `"755"`, `"750"`, `"644"`). |
| **Responsabilidades** | Validar permissões de leitura, escrita e execução para um dado usuário/grupo, converter representações textuais, simbólicas e numéricas octais. |
| **Relacionamentos** | Integrada a cada `Inode`. |

---

### 4.3. `SecurityManager` e `AuditLog`
| Campo | Especificação |
|---|---|
| **Classes** | `SecurityManager`, `AuditLog`, `AuditEntry` |
| **Subsistema** | `security` |
| **Atributos de SecurityManager** | • `users: Dict[str, User]` — Base de usuários registrados.<br>• `groups: Dict[str, Group]` — Base de grupos registrados.<br>• `audit_log: AuditLog` — Instância do gerenciador de logs de auditoria.<br>• `active_user: Optional[User]` — Usuário com sessão ativa no simulador. |
| **Atributos de AuditEntry** | • `event_id: int` — ID sequencial do log.<br>• `timestamp: float` — Timestamp do evento.<br>• `event_type: AuditEventType` — Enum (`LOGIN_SUCCESS`, `LOGIN_FAIL`, `ACCESS_DENIED`, `FILE_WRITE`, etc.).<br>• `username: str` — Usuário envolvido.<br>• `target_resource: str` — Recurso alvo da ação.<br>• `details: str` — Descrição do evento e resultado. |
| **Responsabilidades** | Controlar sessões ativas, autenticar logins, fiscalizar ACLs e garantir trilha de auditoria inviolável. |
| **Relacionamentos** | Interage com todos os subsistemas através do Kernel. |

---

## 5. SUBSISTEMA DE GERENCIAMENTO DE MEMÓRIA

### 5.1. `MemorySegment` (Segmento da Área Reservada Contígua)
| Campo | Especificação |
|---|---|
| **Classe** | `MemorySegment` |
| **Subsistema** | `memory` |
| **Atributos** | • `segment_id: int` — Identificador único do segmento.<br>• `process_id: Optional[int]` — PID associado (`None` se o segmento for um bloco livre / buraco).<br>• `process_name: Optional[str]` — Nome do driver ou processo crítico.<br>• `start_address: int` — Endereço inicial em bytes ou KB na área reservada.<br>• `end_address: int` — Endereço final do segmento.<br>• `size: int` — Tamanho do segmento em KB.<br>• `status: SegmentStatus` — Enum (`FREE`, `ALLOCATED`). |
| **Responsabilidades** | Representar blocos contíguos de memória do núcleo e drivers; quantificar fragmentação externa. |
| **Relacionamentos** | Pertence à lista de segmentos da Área Reservada de `PhysicalMemory`. |

---

### 5.2. `PageTable` e `PageTableEntry` (Paginação Dinâmica)
| Campo | Especificação |
|---|---|
| **Classes** | `PageTable`, `PageTableEntry` |
| **Subsistema** | `memory` |
| **Atributos de PageTableEntry** | • `logical_page: int` — Número da página virtual ($p$).<br>• `frame_id: Optional[int]` — Número da moldura física ($f$) onde a página reside (`None` se em swap).<br>• `present: bool` — Bit de presença (`True` na RAM, `False` falta de página / swap).<br>• `dirty: bool` — Bit de modificação (`True` se alterada em RAM desde o carregamento).<br>• `referenced: bool` — Bit de referência para o algoritmo de Segunda Chance.<br>• `last_access: float` — Timestamp de acesso recente para o algoritmo LRU. |
| **Atributos de PageTable** | • `process_id: int` — PID do processo proprietário da tabela.<br>• `entries: Dict[int, PageTableEntry]` — Mapeamento $p \to \text{PageTableEntry}$. |
| **Responsabilidades** | Manter o estado de mapeamento de memória virtual de cada processo e viabilizar algoritmos de reposição. |
| **Relacionamentos** | Pertence a um `Process`; referencia instâncias de `Frame`. |

---

### 5.3. `Frame` (Moldura de Memória Física)
| Campo | Especificação |
|---|---|
| **Classe** | `Frame` |
| **Subsistema** | `memory` |
| **Atributos** | • `frame_id: int` — Número identificador da moldura física na RAM dinâmica.<br>• `start_address: int` — Endereço físico base da moldura em bytes.<br>• `size: int` — Tamanho da moldura (padrão: `4096` bytes).<br>• `page_id: Optional[int]` — Página lógica atualmente hospedada.<br>• `process_id: Optional[int]` — PID do processo ocupante (`None` se livre).<br>• `occupied: bool` — Flag de ocupação da moldura.<br>• `data: bytearray` — Armazenamento binário do conteúdo da página na RAM física simulada. |
| **Responsabilidades** | Hospedar uma página física de memória em tempo de execução. |
| **Relacionamentos** | Gerenciado pela lista de molduras de `PhysicalMemory`. |

---

### 5.4. `MemoryManager` e `SwapManager`
| Campo | Especificação |
|---|---|
| **Classes** | `MemoryManager`, `SwapManager` |
| **Subsistema** | `memory` |
| **Atributos de MemoryManager** | • `reserved_memory_size: int` — Tamanho total da área reservada (padrão `4096` KB / 4 MB).<br>• `dynamic_memory_size: int` — Tamanho total da área paginada em frames.<br>• `reserved_segments: List[MemorySegment]` — Lista de segmentos da área reservada.<br>• `page_tables: Dict[int, PageTable]` — Tabelas de páginas ativas por PID.<br>• `frames: List[Frame]` — Conjunto de molduras de memória da área dinâmica.<br>• `replacement_algorithm: ReplacementAlgorithm` — Enum (`LRU`, `SECOND_CHANCE`).<br>• `swap_manager: SwapManager` — Subsistema de área de troca secundária. |
| **Atributos de SwapManager** | • `total_swap_slots: int` — Total de slots de troca disponíveis.<br>• `swap_table: Dict[Tuple[int, int], int]` — Mapeamento `(pid, page_id) -> slot_id`.<br>• `swap_storage: Dict[int, bytearray]` — Carga binária de páginas descarregadas da RAM. |
| **Responsabilidades** | Tradução de endereços virtuais, detecção e resolução de Page Fault, execução de substituição de páginas e desfragmentação via `memory_compact`. |
| **Relacionamentos** | Orquestra `PhysicalMemory`, `PageTable`, interage com `IOManager` para swapping. |

---

## 6. SUBSISTEMA DE PROCESSOS E CONTROLE DE EXECUÇÃO

### 6.1. `Process` (Process Control Block — PCB)
| Campo | Especificação |
|---|---|
| **Classe** | `Process` |
| **Subsistema** | `process` |
| **Atributos** | • `pid: int` — Process ID sequencial.<br>• `name: str` — Nome identificador do processo ou driver.<br>• `size: int` — Tamanho de memória solicitado (em KB ou bytes).<br>• `state: ProcessState` — Enum (`NEW`, `READY`, `RUNNING`, `BLOCKED`, `TERMINATED`).<br>• `is_reserved: bool` — Flag indicando se é processo crítico alocado na Área Reservada Contígua.<br>• `page_table: Optional[PageTable]` — Tabela de páginas associada (se dinâmico).<br>• `segment_id: Optional[int]` — ID do segmento de memória reservada (se contíguo).<br>• `cpu_time: int` — Ciclos de execução consumidos. |
| **Responsabilidades** | Manter o estado do processo simulado para controle de ciclo de vida. |
| **Relacionamentos** | Gerenciado por `ProcessManager`; possui recursos em `MemoryManager`. |

---

## 7. SUBSISTEMA DE INTERFACE CLI E CONTEXTO DE EXECUÇÃO

### 7.1. `CommandContext` e `CommandResult`
| Campo | Especificação |
|---|---|
| **Classes** | `CommandContext`, `CommandResult` |
| **Subsistema** | `cli` |
| **Atributos de CommandContext** | • `raw_input: str` — Linha digitada no shell.<br>• `command_name: str` — Nome do comando identificado.<br>• `args: List[str]` — Argumentos posicionais.<br>• `flags: Dict[str, Any]` — Argumentos nomeados/flags (ex.: `--reserved`, `-l`).<br>• `active_user: User` — Usuário da sessão corrente.<br>• `cwd: str` — Diretório de trabalho atual no VFS. |
| **Atributos de CommandResult** | • `success: bool` — `True` em caso de sucesso; `False` em erro.<br>• `output_message: str` — Texto formatado de saída para o terminal.<br>• `error_message: Optional[str]` — Mensagem detalhada de falha ou exceção.<br>• `data_payload: Optional[Dict[str, Any]]` — Dados estruturados resultantes da operação para validação programática. |
| **Responsabilidades** | Desacoplar a interpretação de comandos da lógica do Kernel e padronizar o envio de respostas. |
| **Relacionamentos** | Produzido pelo `CommandParser`; consumido pelo `Shell` e pelos comandos. |
