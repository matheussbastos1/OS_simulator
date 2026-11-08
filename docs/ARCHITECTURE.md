# ESPECIFICAÇÃO ARQUITETURAL DO SISTEMA — OS SIMULATOR

> **Status:** Especificação Oficial (Fase 0)  
> **Objetivo:** Estabelecer a arquitetura holística, contratos de fronteira, fluxos de integração intersubsistemas e controle de estado do OS Simulator.

---

## 1. VISÃO ARQUITETURAL GERAL

O **OS Simulator** é projetado segundo uma arquitetura modular em camadas, orientada a objetos, com baixo acoplamento e alta coesão. Ele reproduz os comportamentos lógicos e mecanismos internos do sistema operacional Ubuntu Linux dentro de um ambiente isolado em memória no Python 3, executado sobre o Windows 11.

A arquitetura organiza-se em cinco camadas lógicas:

1. **Camada de Apresentação (Interface do Usuário):** CLI e Shell Interativo simulado.
2. **Camada de Orquestração do Sistema (Kernel da Simulação):** O objeto central `OperatingSystem` (ou `SimulationKernel`), responsável por manter o estado global, mediar chamadas de sistema (syscalls) e orquestrar a cooperação entre subsistemas.
3. **Camada de Subsistemas de Alto Nível:** Segurança (`SecurityManager`), Sistema de Arquivos Virtual (`VFS` / `FileSystemService`) e Gerenciador de Processos (`ProcessManager`).
4. **Camada de Subsistemas de Baixo Nível / Gerenciamento de Recursos:** Gerenciador de Memória (`MemoryManager` com MMU e Paginador) e Gerenciador de E/S (`IOManager` com Escalonadores e Controladores RAID).
5. **Camada de Infraestrutura Física Simulada (Hardware Abstraction):** Memória Física Simulada (`PhysicalMemory` com área reservada e frames dinâmicos) e Discos Rígidos Físicos Simulados (`PhysicalDisk` com trilhas e blocos de dados).

```mermaid
flowchart TD
    subgraph UI ["Camada de Apresentação"]
        CLI["CLI & Shell Interativo (/bin/sh simulado)"]
    end

    subgraph Core ["Núcleo de Simulação"]
        Kernel["OperatingSystem / SimulationKernel (Estado Global)"]
    end

    subgraph HighLevel ["Subsistemas de Alto Nível"]
        SEC["Subsistema de Segurança (Auth, ACL, Audit)"]
        VFS["Virtual File System & Filesystem (i-nodes, Árvore)"]
        PROC["Gerenciador de Processos (PCB, Escalonamento de Tarefas)"]
    end

    subgraph LowLevel ["Subsistemas de Baixo Nível"]
        MEM["Gerenciador de Memória (MMU, Paginação, Swap)"]
        IO["Gerenciador de E/S (Scheduler, RAID)"]
    end

    subgraph Hardware ["Hardware Simulado em Memória"]
        RAM["PhysicalMemory (Área Reservada + Molduras de Página)"]
        DISKS["PhysicalDisks (Trilhas, Blocos, Controladores)"]
    end

    CLI -->|Comandos e Syscalls| Kernel
    Kernel --> SEC
    Kernel --> VFS
    Kernel --> PROC
    Kernel --> MEM
    Kernel --> IO

    VFS -->|Requisições de Bloco| IO
    PROC -->|Alocação de Espaço| MEM
    MEM -->|Troca de Páginas / Swap| IO
    IO -->|Acesso Físico a Setores| DISKS
    MEM -->|Acesso Físico a Frames| RAM
    SEC -.->|Políticas e Checagens| VFS
    SEC -.->|Políticas de Execução| PROC
```

---

## 2. FRONTEIRAS E RESPONSABILIDADES DOS SUBSISTEMAS

### 2.1. CLI (Command Line Interface)
- **Responsabilidade:** Interpretação léxica e sintática dos comandos do usuário, verificação básica de argumentos, despacho ao `SimulationKernel` e formatação visual dos resultados (tabelas, árvores, mensagens de erro).
- **Fronteira:** Não implementa regras de negócio, não aloca blocos de disco nem molduras de memória diretamente. Apenas consome as interfaces expostas pelo Kernel.

### 2.2. Virtual File System (VFS)
- **Responsabilidade:** Abstração de caminhos absolutos e relativos, normalização de caminhos (`/sistema/../logs`), resolução hierárquica a partir da raiz `/` ou do diretório corrente de trabalho (CWD), e localização de nós.
- **Fronteira:** O VFS não define o formato de alocação de blocos; ele localiza o `Node` e seu `Inode`, delegando as operações físicas de blocos ao `FileSystemService`.

### 2.3. Filesystem Service
- **Responsabilidade:** Criação, leitura, atualização e remoção de arquivos e diretórios; gerenciamento da tabela de i-nodes; cálculo de tamanho real vs. tamanho alocado; execução das estratégias de alocação (Contígua, FAT e Indexada) e métricas de fragmentação.
- **Fronteira:** Comunica-se com o subsistema de E/S para leitura e escrita de blocos. Não movimenta o braço do disco diretamente.

### 2.4. I/O Manager & Disk Scheduler
- **Responsabilidade:** Recebimento e enfileiramento de requisições de E/S (`IORequest`), execução de algoritmos de escalonamento de braço (FCFS, SSTF, SCAN, C-SCAN), cálculo de tempo de busca e distância percorrida pelo cabeçote, e controle de SSD com Wear Leveling.
- **Fronteira:** Não sabe o conteúdo semântico do arquivo; lida exclusivamente com identificadores de bloco lógico/físico, trilhas e operações de leitura/escrita.

### 2.5. RAID Controller
- **Responsabilidade:** Mapeamento de blocos lógicos do sistema de arquivos em blocos físicos de múltiplos `PhysicalDisk`. Implementa distribuição de blocos (*striping*), espelhamento (*mirroring*), cálculo de paridade XOR (RAID 4 e RAID 5) e reconstrução em caso de falha de unidade física.
- **Fronteira:** Atua como intermediário transparente entre o escalonador de E/S e os discos físicos.

### 2.6. Security Manager
- **Responsabilidade:** Autenticação de credenciais de usuários via derivação de chave segura (PBKDF2-HMAC-SHA256), gerenciamento de identidades e grupos, avaliação de matriz de controle de acesso (ACL rwx e octal), aplicação de restrições de Modo Usuário vs. Modo Kernel, registro de eventos de auditoria invioláveis, criptografia de payloads e verificação de integridade/antivírus.
- **Fronteira:** Intercepta chamadas de sistema antes da execução de operações de I/O, VFS ou processos.

### 2.7. Process Manager
- **Responsabilidade:** Criação e manutenção do ciclo de vida de processos (PCBs), transição de estados (READY, RUNNING, BLOCKED, TERMINATED), atribuição de PID e requisição de alocação de espaço ao `MemoryManager`.
- **Fronteira:** Não gerencia a tradução de endereços físicos; delega toda a infraestrutura de endereçamento e molduras à MMU e ao `MemoryManager`.

### 2.8. Memory Manager & MMU
- **Responsabilidade:** Administração da Memória Física Simulada.
  - *Área Reservada Contígua:* Alocação de processos críticos do sistema, controle de segmentos contíguos, cálculo de fragmentação externa e algoritmo de compactação `memory_compact`.
  - *Área Dinâmica Paginada:* Criação de `PageTable`, gerenciamento de `Frame`, tradução de endereços virtuais via MMU, tratamento de `PageFaultException`, execução de substituição de páginas (LRU e Segunda Chance/Clock) e comunicação com o `SwapManager`.
- **Fronteira:** Utiliza o subsistema de E/S para realizar operações de troca com a partição de Swap.

---

## 3. DIAGRAMAS DE FLUXO DE INTEGRAÇÃO

### 3.1. Fluxo de Gravação de Arquivo (`write_file`)

O fluxo demonstra a integração completa ponta a ponta desde a digitação do comando até a gravação nos discos físicos:

```mermaid
sequenceDiagram
    autonumber
    actor User as Usuário (CLI)
    participant CLI as CLI Layer
    participant Kernel as SimulationKernel
    participant SEC as SecurityManager
    participant VFS as VirtualFileSystem
    participant FS as FileSystemService
    participant IO as IOManager / Scheduler
    participant RAID as RAIDController
    participant Disk as PhysicalDisks

    User->>CLI: write_file /sistema/logs/app.log "Dados de log"
    CLI->>Kernel: dispatch(write_file, args, active_user)
    Kernel->>SEC: check_permission(active_user, path, ACCESS_WRITE)
    alt Permissão Negada
        SEC->>Kernel: PermissionDeniedException
        Kernel->>SEC: log_audit(EVENT_ACCESS_DENIED)
        Kernel->>CLI: Exibe erro de acesso negado
    else Permissão Concedida
        SEC->>Kernel: AccessGranted
        Kernel->>VFS: resolve_path("/sistema/logs/app.log")
        VFS->>FS: get_or_create_inode(path)
        FS->>FS: allocate_blocks(content_size, strategy)
        opt Arquivo Criptografado
            FS->>SEC: encrypt_payload(data, key)
            SEC-->>FS: encrypted_data
        end
        loop Para cada bloco a ser gravado
            FS->>IO: submit_request(IORequest(WRITE, block_id, track, data))
            IO->>IO: enqueue_and_schedule(request)
            IO->>RAID: dispatch_to_array(block_id, data)
            RAID->>RAID: calculate_parity_xor(stripe)
            RAID->>Disk: write_physical_block(disk_id, track, block_data)
            Disk-->>RAID: write_ack
            RAID-->>IO: io_complete
        end
        FS->>FS: update_inode_metadata(size, blocks, mtime)
        Kernel->>SEC: log_audit(EVENT_FILE_WRITTEN)
        Kernel-->>CLI: Sucesso (blocos alocados, fragmentação calculada)
        CLI-->>User: Relatório de confirmação
    end
```

---

### 3.2. Fluxo de Leitura de Arquivo (`read_file`)

```mermaid
sequenceDiagram
    autonumber
    actor User as Usuário (CLI)
    participant CLI as CLI Layer
    participant Kernel as SimulationKernel
    participant SEC as SecurityManager
    participant VFS as VirtualFileSystem
    participant FS as FileSystemService
    participant IO as IOManager
    participant RAID as RAIDController
    participant Disk as PhysicalDisks

    User->>CLI: read_file /sistema/config.sys
    CLI->>Kernel: dispatch(read_file, path, active_user)
    Kernel->>SEC: check_permission(active_user, path, ACCESS_READ)
    alt Permissão Negada (ex: Carlos sem privilégio em 750)
        SEC->>SEC: log_audit(EVENT_READ_DENIED, path, active_user)
        SEC-->>Kernel: PermissionDeniedException
        Kernel-->>CLI: Erro: Permissão negada para leitura
        CLI-->>User: Exibe mensagem de erro e aborta
    else Permissão Concedida
        SEC-->>Kernel: OK
        Kernel->>VFS: resolve_path(path)
        VFS->>FS: read_inode_data(inode)
        loop Para cada bloco do i-node
            FS->>IO: read_request(IORequest(READ, block_id))
            IO->>RAID: read_block(block_id)
            alt Disco Físico Operacional
                RAID->>Disk: read_physical_block(disk_id, block_id)
                Disk-->>RAID: raw_block_data
            else Disco Físico com Falha (ex: Disco 2 offline em RAID 5)
                RAID->>Disk: read_surviving_blocks(other_disks)
                Disk-->>RAID: surviving_blocks_and_parity
                RAID->>RAID: reconstruct_block_via_xor()
            end
            RAID-->>IO: block_data
            IO-->>FS: block_data
        end
        opt Arquivo Criptografado
            FS->>SEC: decrypt_payload(raw_data)
            SEC-->>FS: decrypted_data
        end
        FS->>SEC: verify_integrity_hash(data, stored_hash)
        Kernel-->>CLI: Retorna conteúdo e diagnóstico de leitura
        CLI-->>User: Exibe o conteúdo do arquivo
    end
```

---

### 3.3. Fluxo de Autenticação e Autorização

```mermaid
sequenceDiagram
    autonumber
    actor User as Usuário
    participant CLI as CLI Layer
    participant Kernel as SimulationKernel
    participant SEC as SecurityManager
    participant Audit as AuditLog

    User->>CLI: login carlos
    CLI->>CLI: Solicita senha (input seguro)
    CLI->>Kernel: authenticate("carlos", "senha123")
    Kernel->>SEC: verify_credentials("carlos", "senha123")
    SEC->>SEC: retrieve_user_record("carlos")
    SEC->>SEC: derive_hash = PBKDF2(input_password, stored_salt)
    SEC->>SEC: hmac.compare_digest(derive_hash, stored_password_hash)
    alt Hash Correto
        SEC->>SEC: set_active_session("carlos", user_groups, user_mode)
        SEC->>Audit: log(EVENT_LOGIN_SUCCESS, "carlos")
        SEC-->>Kernel: AuthenticationSuccess(User)
        Kernel-->>CLI: Sucesso: Sessão iniciada como carlos
    else Senha Inválida ou Usuário Inexistente
        SEC->>Audit: log(EVENT_LOGIN_FAILURE, "carlos")
        SEC-->>Kernel: AuthenticationFailedException
        Kernel-->>CLI: Erro: Falha de autenticação
    end
```

---

### 3.4. Fluxo de Criação e Encerramento de Processos

```mermaid
sequenceDiagram
    autonumber
    actor User as Operador / CLI
    participant Kernel as SimulationKernel
    participant PROC as ProcessManager
    participant MEM as MemoryManager
    participant RAM as PhysicalMemory

    User->>Kernel: create_process("Kernel_NetDriver", size=1024KB, is_reserved=True)
    Kernel->>PROC: allocate_pcb("Kernel_NetDriver", is_reserved=True)
    PROC->>MEM: allocate_process_memory(pid, size, is_reserved=True)
    alt Segmento Reservado (Memória Contígua)
        MEM->>RAM: find_contiguous_free_segment(size)
        alt Espaço Contíguo Disponível
            RAM-->>MEM: MemorySegment(start, end, size)
            MEM-->>PROC: MemoryAllocated
            PROC-->>Kernel: ProcessReady(pid=102)
        else Fragmentação Externa Impede Alocação Contígua
            RAM-->>MEM: OutOfContiguousMemoryException(fragmented=True)
            MEM-->>Kernel: Requer Compactação (memory_compact)
        end
    else Processo de Usuário Dinâmico (Memória Paginada)
        MEM->>MEM: calculate_pages_needed(size, page_size=4KB)
        MEM->>RAM: allocate_free_frames(page_count)
        MEM->>MEM: build_page_table(pid, allocated_frames)
        MEM-->>PROC: ProcessReady(pid=103)
    end

    Note over User, RAM: Encerramento de Processo
    User->>Kernel: terminate_process(pid=102)
    Kernel->>PROC: mark_terminated(pid=102)
    PROC->>MEM: free_process_memory(pid=102)
    MEM->>RAM: release_segments_or_frames(pid=102)
    RAM-->>MEM: memory_freed
    MEM-->>Kernel: ProcessTerminatedSuccess
```

---

### 3.5. Fluxo de Tradução de Endereços, Page Fault e Swap

```mermaid
sequenceDiagram
    autonumber
    actor CPU as CPU / Instrução Simulada
    participant MMU as MMU
    participant PT as PageTable
    participant MEM as MemoryManager
    participant Repl as PageReplacementPolicy (LRU)
    participant Swap as SwapManager
    participant IO as IOManager
    participant RAM as PhysicalMemory

    CPU->>MMU: translate(virtual_address=4100)
    MMU->>MMU: Decompor: page_num = 4100 // 4096 = 1, offset = 4100 % 4096 = 4
    MMU->>PT: get_entry(page_num=1)
    PT-->>MMU: PageTableEntry(page=1, frame=None, present=False)

    alt Page Fault Detectado!
        MMU->>MEM: trigger_page_fault(pid, page_num=1)
        MEM->>RAM: get_free_frame()
        alt Sem Frames Livres na RAM Física
            RAM-->>MEM: None (RAM Cheia)
            MEM->>Repl: select_victim_frame()
            Repl-->>MEM: victim_entry (ex: page=0 do frame 4, dirty=True)
            opt Vítima Modificada (bit dirty == True)
                MEM->>Swap: swap_out(victim_entry)
                Swap->>IO: write_swap_block(victim_data)
                IO-->>Swap: written
            end
            MEM->>PT: update_victim_entry(present=False, frame=None)
            MEM->>RAM: assign_frame_to_new_page(frame=4)
        else Moldura Livre Encontrada
            RAM-->>MEM: frame_id=4
        end
        MEM->>Swap: swap_in(pid, page_num=1)
        Swap->>IO: read_swap_block(page_num)
        IO-->>Swap: page_data
        Swap-->>MEM: page_data
        MEM->>RAM: load_data_into_frame(frame_id=4, page_data)
        MEM->>PT: update_entry(page=1, frame_id=4, present=True, dirty=False, referenced=True)
        MEM-->>MMU: PageFaultResolved
    end

    MMU->>PT: get_entry(page_num=1)
    PT-->>MMU: PageTableEntry(page=1, frame=4, present=True)
    MMU->>MMU: physical_address = (4 * 4096) + 4 = 16388
    MMU-->>CPU: physical_address = 16388
```

---

## 4. GERENCIAMENTO DE DEPENDÊNCIAS ENTRE MÓDULOS

Para manter acoplamento fraco e prevenir dependências circulares:
1. **Regra de Direcionalidade:** Pacotes de alto nível podem importar tipos e interfaces de pacotes de nível inferior; o inverso é terminantemente proibido.
   - `cli` $\to$ `core`, `types`
   - `core` $\to$ `filesystem`, `io`, `security`, `memory`, `process`
   - `filesystem` $\to$ `io` (via `IOManagerInterface`), `security` (via `SecurityCheckerInterface`)
   - `memory` $\to$ `io` (para Swap via `SwapIOInterface`), `process` (apenas para referências de PID)
2. **Injeção de Dependências:** O subsistema `core.kernel.SimulationKernel` atua como agregador e injetor. Serviços como `IOManager` e `SecurityManager` são passados como dependências para o `FileSystemService` e `MemoryManager` durante a inicialização do Kernel.

---

## 5. ESTADO GLOBAL DA SIMULAÇÃO: O `SimulationKernel`

O `SimulationKernel` (ou `OperatingSystem`) é a classe singleton/container que mantém a integridade do estado global. Ele possui a seguinte responsabilidade:

```python
class SimulationKernel:
    """Contêiner central de orquestração do OS Simulator."""

    def __init__(self, config: SystemConfiguration):
        self.security_manager: SecurityManager
        self.vfs: VirtualFileSystem
        self.filesystem_service: FileSystemService
        self.io_manager: IOManager
        self.raid_controller: RAIDController
        self.memory_manager: MemoryManager
        self.process_manager: ProcessManager
        self.audit_log: AuditLog
        self.current_user: User
        self.current_working_directory: str
        self.is_running: bool

    def boot(self) -> None:
        """Inicializa todos os subsistemas em sequência segura."""
        ...

    def execute_syscall(self, syscall_name: str, **kwargs) -> Any:
        """Ponto de entrada único para chamadas privilegiadas da CLI."""
        ...
```

Esta arquitetura garante que nenhum subsistema manipule o estado de outro de forma arbitrária, mantendo toda a rastreabilidade sob o Kernel e o log de auditoria.
