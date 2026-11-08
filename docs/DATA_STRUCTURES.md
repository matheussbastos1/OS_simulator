# CATÁLOGO DE ESTRUTURAS DE DADOS — OS SIMULATOR

> **Status:** Especificação Oficial Consolidada (Fase 0.1)  
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
| **Métodos Obrigatórios** | • `read_block(block_id: int) -> bytearray` — Lê o conteúdo do bloco informado.<br>• `write_block(block_id: int, data: bytearray) -> None` — Grava dados no bloco.<br>• `allocate_block() -> int` — Reserva um bloco livre e retorna seu ID numérico.<br>• `free_block(block_id: int) -> None` — Libera o bloco para reutilização.<br>• `get_capacity() -> int` — Retorna a capacidade total em blocos.<br>• `get_free_count() -> int` — Retorna o número de blocos atualmente livres.<br>• `is_available(block_id: int) -> bool` — Verifica se o bloco é válido e operacional. |
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

### 4.2. `PhysicalDisk` e `RAIDArray`
| Campo | Especificação |
|---|---|
| **Classes** | `PhysicalDisk`, `RAIDArray` |
| **Subsistema** | `io` |
| **Atributos de PhysicalDisk** | • `disk_id: int` — Identificador numérico do disco.<br>• `total_blocks: int` — Total de blocos do disco.<br>• `tracks: int` — Total de cilindros/trilhas (padrão: 200).<br>• `current_head_position: int` — Trilha atual do cabeçote.<br>• `disk_type: DiskType` — Enum (`HDD`, `SSD`).<br>• `failed: bool` — Flag de falha física simulada.<br>• `blocks: Dict[int, DiskBlock]` — Coleção de blocos físicos mantidos na unidade.<br>• `write_cycles: Dict[int, int]` — Contador de escritas para SSD Wear Leveling. |
| **Atributos de RAIDArray** | • `raid_level: RAIDLevel` — Enum (`RAID0`, `RAID1`, `RAID4`, `RAID5`).<br>• `physical_disks: List[PhysicalDisk]` — Discos integrantes do arranjo.<br>• `stripe_size: int` — Tamanho do stripe (padrão: 1 bloco = 4096 bytes).<br>• `status: RAIDStatus` — Enum (`OPTIMAL`, `DEGRADED`, `FAILED`). |
| **Responsabilidades** | Simular a movimentação mecânica de cabeçote, cálculo de desgaste, paridade XOR e reconstrução transparente de blocos. |

---

### 4.3. `IORequest` e `DiskScheduler`
| Campo | Especificação |
|---|---|
| **Classes** | `IORequest`, `DiskScheduler` |
| **Subsistema** | `io` |
| **Atributos de IORequest** | • `request_id: int` — ID sequencial da requisição.<br>• `operation_type: IOOperationType` — Enum (`READ`, `WRITE`).<br>• `target_block: int` — Bloco de destino.<br>• `target_track: int` — Trilha física onde o bloco reside.<br>• `data: Optional[bytearray]` — Carga útil de dados.<br>• `priority: IOPriority` — Enum (`LOW`, `NORMAL`, `HIGH`, `KERNEL`).<br>• `status: IORequestStatus` — Enum (`PENDING`, `COMPLETED`, `FAILED`). |
| **Atributos de DiskScheduler** | • `algorithm: SchedulingAlgorithm` — Enum (`FCFS`, `SSTF`, `SCAN`, `CSCAN`).<br>• `request_queue: List[IORequest]` — Fila de requisições pendentes.<br>• `total_head_movement: int` — Acumulador da distância percorrida pelo braço em trilhas. |
| **Responsabilidades** | Reordenar a fila de requisições mecânicas para minimizar o deslocamento do cabeçote. |

---

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
