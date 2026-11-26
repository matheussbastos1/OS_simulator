# OS SIMULATOR — SIMULADOR EDUCACIONAL DE SISTEMAS OPERACIONAIS

> **OS Simulator** é um ambiente educacional e laboratório arquitetural modular desenvolvido em **Python 3**, projetado para simular fielmente os componentes fundamentais, fluxos de integração e estruturas de dados de um sistema operacional moderno baseado na arquitetura **Ubuntu Linux**, operando sob a plataforma hospedeira **Windows 11**.

[![Python Version](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/host-Windows%2011-0078D6.svg)](https://www.microsoft.com/windows)
[![Guest OS](https://img.shields.io/badge/target-Ubuntu%20Linux-E95420.svg)](https://ubuntu.com/)

---

## 1. OBJETIVOS ACADÊMICOS E FILOSOFIA DE DESIGN

O propósito primordial do projeto é fornecer uma experiência prática, mensurável e determinística sobre os pilares clássicos da Engenharia de Sistemas Operacionais:

1. **Sistemas de Arquivos (Filesystem):** Hierarquia VFS, metadados POSIX, abstração de i-nodes, estratégias de alocação (Contígua, FAT encadeada e Indexada) e análise de fragmentação interna e externa, operando sobre o contrato `BlockDevicePort`.
2. **Entrada e Saída (I/O) e Armazenamento Confiável:** Gerenciamento de requisições de E/S (`IORequest`), algoritmos de escalonamento mecânico de braço de disco (FCFS, SSTF, SCAN, C-SCAN), simulação de controladores de SSD com *Wear Leveling* e arranjos tolerantes a falhas RAID (RAID 0, RAID 1, RAID 4 e RAID 5 com cálculo de paridade XOR e recuperação de falhas *on-the-fly*).
3. **Segurança e Proteção:** Controle de acesso por identidade e grupos, autenticação com derivação de chave criptográfica e salt individual (PBKDF2-HMAC-SHA256 com 600.000 iterações), matriz de autorização por Listas de Controle de Acesso (ACL) e permissões octais/rwx POSIX, anéis de privilégio (Modo Usuário vs. Modo Kernel), log de auditoria inviolável, integridade com HMAC do Kernel e criptografia AES-256-GCM em repouso.
4. **Gerenciamento de Memória Real e Virtual:** Memória física particionada em Área Reservada Contígua (para SO e drivers, com controle de fragmentação externa e desfragmentação por compactação deslizante `memory_compact --reserved`) e Área Dinâmica Paginada (com MMU, tradução lógica-física, tratamento de falta de página considerando origens válidas: Imagem, Zero-fill ou Swap, políticas de substituição LRU e Segunda Chance/Clock e partição de Swap integrada via `BlockDevicePort`).
5. **Processos, Threads, Escalonamento e Concorrência (Etapa 5):** Simulação determinística a eventos discretos (`LogicalClock`, `EventManager`, `ExecutionEngine`), máquina de 5 estados (`NEW`, `READY`, `RUNNING`, `BLOCKED`, `TERMINATED`), threads simuladas (`SimulatedThread`), escalonador preemptivo multinível por prioridade + Round-Robin (`PriorityRoundRobinScheduler`), syscalls por tempo de CPU e perfis de E/S (`IO_READ`/`IO_WRITE`, `FS_READ`/`FS_WRITE`, `SLEEP_WAIT`, `YIELD`, `MUTEX_*`, `MEMORY_*`, `EXIT`), sincronização por mutex FIFO (`SynchronizationManager`), detecção de deadlock por Grafo Wait-For e estagnação, acoplamento à paginação da Etapa 4 e métricas completas (`WT`, `TAT`, `RT`, Timeline e Gantt).

---

## 2. REGRA FUNDAMENTAL: ISOLAMENTO TOTAL DA SIMULAÇÃO

O OS Simulator **não utiliza recursos nativos do Windows 11 para representar o hardware ou os arquivos simulados**:
- **Proibido:** Criar pastas ou arquivos reais no disco rígido do Windows para simular diretórios do Linux.
- **Proibido:** Alocar memória nativa do Windows ou usar chamadas Win32 para simular frames de memória.
- **Proibido:** Utilizar permissões do Windows (NTFS) para simular ACLs de usuários.
- **Proibido:** Fazer chamadas a executáveis do Ubuntu ou WSL para delegar comandos.
- **Arquitetura em Memória:** Todos os discos, trilhas, blocos de dados, nós de diretório, i-nodes, tabelas de páginas, molduras de RAM e partições de swap são **estruturas de dados puras administradas em memória pelo interpretador Python**.

---

## 3. ARQUITETURA GERAL E ESTRUTURA DE DIRETÓRIOS

O projeto segue os princípios de Orientação a Objetos (OOP), responsabilidade única (SRP), desacoplamento por portas e adaptadores (`BlockDevicePort` e `AuthorizationPort`) e orquestração central pelo `SimulationKernel`.

```text
OS_simulator/
├── AGENTS.md                  # Regras de governança, restrições e contratos para agentes
├── PLAN.md                    # Roadmap detalhado de execução e controle das 5 fases
├── README.md                  # Este documento (visão geral, instalação e manual)
├── .gitignore                 # Filtros de arquivos transientes do Python e ambiente
│
├── docs/                      # Especificações formais de engenharia
│   ├── ARCHITECTURE.md        # Arquitetura detalhada, camadas e diagramas Mermaid
│   ├── DATA_STRUCTURES.md     # Catálogo tipado de classes e entidades da simulação
│   ├── ALGORITHMS.md          # Contratos matemáticos e lógicos dos algoritmos
│   └── CLI_AND_OUTPUTS.md     # Dicionário da CLI e padrões visuais oficiais
│
├── tests/                     # Testes determinísticos e verificação de conformidade
│   └── GROUND_TRUTH.md        # Casos de teste de referência oficial (Ground Truth)
│
└── os_simulator/              # Código-fonte modular do sistema
    ├── core/                  # Kernel, LogicalClock, EventManager, ExecutionContext, exceptions e portas
    ├── filesystem/            # VFS, Inode, Node, FAT, Indexação e serviço de arquivos
    ├── storage/               # InMemoryBlockDevice, PhysicalDisk, RAID 0/1/4/5 e IOBlockDeviceAdapter
    ├── io/                    # IOManager, escalonadores de disco (FCFS/SSTF/SCAN/C-SCAN) e SSD
    ├── security/              # User, Group, ACL, Auth PBKDF2, AuditLog, AES-GCM e integridade
    ├── memory/                # PhysicalMemory, MMU, PageTable, LRU, Clock e SwapManager
    ├── process/               # Process, SimulatedThread, StateMachine, Scheduler, Syscalls, Sync, Metrics e ExecutionEngine
    └── cli/                   # Shell interativo, parser e handlers das Etapas 1 a 5
```

---

## 4. ESTRATÉGIA DE GOVERNANÇA GIT E BRANCHES

O desenvolvimento é rigorosamente incremental. Cada etapa é isolada em sua própria branch de funcionalidade (*feature branch*), submetida à validação contra os cenários do `tests/GROUND_TRUTH.md`, comutada por *Conventional Commits* e integrada à branch de desenvolvimento contínuo `dev`:

- `main`: Branch de lançamentos oficiais consolidados.
- `dev`: Branch padrão de integração contínua das etapas aprovadas.
- `feature/fase-0-documentacao`: Fase 0 (Governança e Arquitetura Inicial).
- `fix/fase-0-consistencia`: Fase 0.1 (Auditoria de Consistência e Portas/Adaptadores).
- `feature/etapa-1-filesystem`: Etapa 1 (Sistema de Arquivos).
- `feature/etapa-2-io-raid`: Etapa 2 (E/S, Escalonamento e RAID).
- `feature/etapa-3-security`: Etapa 3 (Segurança, ACL e Proteção).
- `feature/etapa-4-memory`: Etapa 4 (Gerenciamento de Memória Real e Virtual).
- `feat/etapa-5-processos-concorrencia`: Etapa 5 (Processos, Threads, Escalonamento Prioridade+RR, Syscalls, Mutex/Deadlock e Métricas).

---

## 5. PRÉ-REQUISITOS E AMBIENTE DE DESENVOLVIMENTO

- **Sistema Hospedeiro:** Windows 11 (64-bit).
- **Interpretador:** Python 3.11, 3.12 ou 3.13 (Python 3.13 recomendado).
- **Shell do Sistema:** Windows PowerShell ou PowerShell Core (pwsh).
- **Controle de Versão:** Git 2.40+.
- **Dependências Externas:** Prioridade total à biblioteca padrão do Python (`dataclasses`, `typing`, `hashlib`, `hmac`, `secrets`, etc.). Biblioteca `cryptography` autorizada exclusivamente para a Etapa 3 (AES-256-GCM).

---

## 6. INSTRUÇÕES DE INSTALAÇÃO E EXECUÇÃO (POWERSHELL)

### 6.1. Clonagem e Configuração do Repositório
Abra o **PowerShell** no Windows 11 e execute:

```powershell
# Clonar o repositório
git clone https://github.com/matheussbastos1/OS_simulator.git

# Acessar a pasta do projeto
cd "OS_simulator"

# Instalar dependências da Etapa 3 (biblioteca cryptography para AES-256-GCM)
pip install -r requirements.txt
```

### 6.2. Execução do Shell Interativo (Etapas 1, 2, 3, 4 e 5 operacionais)
```powershell
# Iniciar o simulador interativo via Python
python -m os_simulator.cli
```

Ao iniciar, o prompt do shell simulado será apresentado:
```text
Iniciando OS Simulator (Ubuntu Linux sobre Windows 11)...
Kernel inicializado com sucesso. Digite 'help' para comandos.

[root@ubuntu-simulator:/]# 
```

---

## 7. COMANDOS DISPONÍVEIS NA CLI SIMULADA (SINTAXE OFICIAL)

| Comando | Sintaxe Oficial de Referência | Subsistema Responsável |
|---|---|---|
| `mkdir` | `mkdir /sistema` | Sistema de Arquivos (VFS) |
| `create` | `create /sistema/logs/app.log --size 10KB` | Sistema de Arquivos (`BlockDevicePort`) |
| `write_file` | `write_file /sistema/logs/app.log "Novo Registro"` | Integração Auth $\to$ FS $\to$ BlockDevice |
| `read_file` | `read_file /sistema/logs/app.log` | Integração Auth $\to$ FS $\to$ BlockDevice |
| `fs_status` | `fs_status --details` | Sistema de Arquivos |
| `io_status` | `io_status` | Gerenciamento de E/S (`IOManager`) |
| `io_scheduler` | `io_scheduler --set scan` | Escalonamento de Disco (FCFS, SSTF, SCAN, C-SCAN) |
| `io_benchmark` | `io_benchmark --queue 98,183,37,122,14 --head 53` | Benchmark Comparativo de Cabeçote |
| `ssd_status` | `ssd_status --mode static` | SSD, FTL e Wear Leveling |
| `raid_status` | `raid_status` | Diagnóstico de Arranjos RAID (0, 1, 4, 5) |
| `raid_fail` | `raid_fail --disk 1` | Injeção de Falha Física em Disco Membro |
| `raid_rebuild` | `raid_rebuild --disk 1` | Reconstrução Online via Paridade XOR |
| `raid_init` | `raid_init --level 5 --disks 4` | Configuração Interativa de RAID |
| `login` | `login --user carlos [--password <senha>]` | Autenticação Segura (PBKDF2-HMAC-SHA256, 600k iterações) |
| `logout` | `logout` | Encerramento de Sessão e Limpeza de Contexto |
| `whoami` | `whoami` | Consulta de Usuário Ativo, Grupos e Anel de Privilégio |
| `groups` | `groups [<usuario>]` | Consulta de Grupos do Usuário Ativo ou Alvo |
| `useradd` | `useradd <nome> [--group <grp>] [--password <senha>]` | Cadastro de Usuário e Inicialização de Salt/Hash |
| `userdel` | `userdel <nome>` | Remoção de Usuário (Proteção contra remoção do root) |
| `usermod` | `usermod <nome> [--group <grp>] [--append-groups <g1,g2>]` | Modificação de Associação a Grupos e Credenciais |
| `groupadd` | `groupadd <nome>` | Cadastro de Novo Grupo POSIX |
| `groupdel` | `groupdel <nome>` | Remoção de Grupo (Proteção de grupos essenciais) |
| `chmod` | `chmod 750 /sistema/config.sys` | Controle de Acesso por ACL (Octal e Simbólico) |
| `chown` | `chown root:admin /sistema/config.sys` | Transferência de Propriedade e Grupo |
| `chgrp` | `chgrp admin /sistema/config.sys` | Alteração de Grupo Proprietário |
| `security_status` | `security_status` | Diagnóstico Global do Subsistema de Segurança |
| `encrypt_file` | `encrypt_file /home/carlos/segredo.txt --key "MinhaChave123"` | Criptografia Real em Repouso (AES-256-GCM, Nonce 12B, Tag 16B) |
| `decrypt_file` | `decrypt_file /home/carlos/segredo.txt --key "MinhaChave123"` | Descriptografia com Validação de Integridade/Tag AEAD |
| `antivirus_scan` | `antivirus_scan /` | Varredura Recursiva de Assinaturas e Hashes Físicos |
| `integrity_check`| `integrity_check [--register] <caminho>` | Auditoria e Registro de Linha de Base Assinada pelo Kernel |
| `audit_log` | `audit_log [--user <u_id>] [--type <evento>]` | Consulta Estruturada de Trilha de Auditoria |
| `create_process` | `create_process --name "Kernel_DiskDriver" --size 512KB --type critical` | Processos e Área Reservada Contígua |
| `create_process` | `create_process --name "App_Navegador" --size 10KB --type normal` | Processos e Área Dinâmica Paginada |
| `terminate_process` | `terminate_process --name "Kernel_NetDriver"` | Processos e Memória |
| `memory_status` | `memory_status [--reserved]` | Diagnóstico de Memória Reservada, Dinâmica e Swap |
| `memory_compact` | `memory_compact --reserved` | Desfragmentação Deslizante da Área Reservada |
| `translate_address` | `translate_address --process App_Navegador --page 1` | Tradução de Endereço Lógico/Virtual via MMU |
| `execute_step` | `execute_step --process App_Navegador --instruction "LOAD_DATA Página 2"` | Execução de Instrução, Page Fault e Swap |
| `page_replacement` | `page_replacement --algorithm second_chance` | Seleção de Algoritmo de Reposição (LRU / Segunda Chance) |
| `page_table` | `page_table --process App_Navegador` | Consulta de Tabela de Páginas e Fragmentação Interna |
| `memory_map` | `memory_map` | Mapa Visual Unificado de Memória Física e Molduras |
| `create_process` (Etapa 5) | `create_process --name App --size 8KB --priority 2 --burst 6 --io-profile periodic --io-every 2 --io-duration 3 --pages 0,1` | Criação com Escalonamento, E/S e Padrão de Páginas |
| `ps` / `process_status` | `ps [--all]` / `process_status [--all]` | Listagem de Processos, Threads, Estados e Bloqueios |
| `process_admit` | `process_admit --process <nome\|pid>` | Admissão Manual de Processo `NEW` $\to$ `READY` |
| `thread_create` | `thread_create --process App --name worker --priority 2 --burst 4` | Criação de Thread Simulada Escalonável |
| `thread_status` | `thread_status [--process App] [--active]` | Status Detalhado das Threads Simuladas |
| `sched_config` | `sched_config [--algorithm priority_rr] [--quantum 4] [--seed 42]` | Configuração de Quantum e Seed do Escalonador |
| `sched_status` | `sched_status` | Estado das Filas por Prioridade, Thread `RUNNING` e Bloqueios |
| `sched_step` | `sched_step [--ms 2]` | Avanço Determinístico por Milissegundos Lógicos |
| `sched_run` | `sched_run [--max-ms 20] [--until-process P] [--until-event EV]` | Execução Discreta até Conclusão ou Condição de Parada |
| `process_syscall` | `process_syscall --process App --type io_read --at-cpu 2 --duration 3 --block 0` | Agendamento ou Execução Imediata (`--now`) de Syscall |
| `mutex_create` | `mutex_create [--name] Buffer_Video` | Criação de Mutex para Sincronização |
| `mutex_lock` / `mutex_unlock` | `mutex_lock --mutex M --process P [--thread T]` | Aquisição/Liberação com Fila FIFO e Handoff Imediato |
| `mutex_status` | `mutex_status` | Diagnóstico de Mutexes, Donos, Filas FIFO e Ciclos |
| `mutex_demo` | `mutex_demo --scenario buffer_video --quantum 2` | Demonstração Produtor/Consumidor `Buffer_Video` |
| `deadlock_check` | `deadlock_check` | Detecção de Deadlock (Wait-For Graph) e Estagnação |
| `memory_frames` | `memory_frames` | Resumo ao Vivo das Molduras Físicas Sincronizado |
| `sim_metrics` | `sim_metrics` | Métricas de Execução (`WT`, `TAT`, `RT`, CPU %, Faults) |
| `sim_timeline` | `sim_timeline [--limit 10] [--gantt]` | Linha do Tempo Cronológica e Diagrama de Gantt |
| `sim_reset` | `sim_reset` | Reinicialização do Relógio, Filas, Mutexes e Métricas |


---

## 8. SUÍTE DE TESTES E GROUND TRUTH

A validação de conformidade de cada subsistema utiliza testes automatizados orientados pelos cenários determinísticos formais definidos em `tests/GROUND_TRUTH.md`:

```powershell
# Execução completa dos testes automatizados (Etapas 1 a 5 — 274 testes via unittest)
python -m unittest discover -s tests -p "test_*.py"

# Execução com saída detalhada ou foco na Etapa 5
python -m unittest discover -s tests -p "test_*.py" -v
python -m unittest tests/test_process_state_machine.py tests/test_process_scheduler.py tests/test_process_syscalls_io.py tests/test_process_concurrency_mutex.py tests/test_process_metrics_timeline.py tests/test_process_memory_integration.py tests/test_cli_process_commands.py -v
```

Cenários homologados:
- **`FS-001` a `FS-004`:** Hierarquias de pastas, i-nodes, atomicidade de gravação e cálculo de fragmentação interna (2.048 bytes para 10 KB) e externa (0 bytes no indexado).
- **`IO-001` e `IO-002`:** Escalonamento SSTF com 208 trilhas percorridas e recuperação de disco com falha em RAID 5 via XOR.
- **`SEC-001` a `SEC-003`:** Autenticação PBKDF2 com 600.000 iterações, bloqueio de acesso 750 com auditoria e integridade SHA-256/HMAC.
- **`MEM-001` a `MEM-005`:** Fragmentação externa em área reservada, compactação deslizante, paginação, MMU (`MEM-004A` e `MEM-004B`) e ciclo determinístico de Page Fault e Swap com origens válidas (`MEM-005`).
- **`PROC-001` a `PROC-005`:** Preempção por prioridade e rotação Round-Robin, syscalls por tempo de CPU (`cpu_consumed_ms`), exclusão mútua `Buffer_Video`, detecção de deadlock Wait-For / estagnação e execução acoplada à paginação/swap com invariantes de métricas (`TAT == CPU + WT + BLK`).

---

## 9. ROTEIRO DE DEMONSTRAÇÕES

O projeto entrega cinco demonstrações práticas estruturadas correspondentes às cinco etapas:

- **Demonstração 1 (Sistema de Arquivos):** Navegação hierárquica no VFS, criação de arquivos com as três estratégias de alocação via `InMemoryBlockDevice` e relatórios de fragmentação interna e externa.
- **Demonstração 2 (E/S e RAID):** Comparação entre FCFS, SSTF e SCAN com medição de deslocamento; montagem de arranjo RAID 5, injeção de falha física e reconstrução de bloco de dados em tempo real via paridade XOR.
- **Demonstração 3 (Segurança e Proteção):** Fluxo de login com PBKDF2 (600k iterações), tentativa de acesso não autorizado negada por ACL (750), auditoria em tempo real, criptografia AES-256-GCM e varredura de antivírus simulado.
- **Demonstração 4 (Gerenciamento de Memória):** Alocação de processos críticos e desfragmentação contígua via `memory_compact --reserved`, carga de processos paginados, simulação de Page Fault respeitando origens válidas, desalocação de página limpa sem swap e swap-out de página suja via `BlockDevicePort`.
- **Demonstração 5 (Processos, Threads, Escalonamento e Concorrência):** Configuração `sched_config --quantum 2`, criação de processos com `--priority`, `--burst`, `--arrival`, `--io-profile` e `--pages`, execução passo a passo (`sched_step`) e completa (`sched_run`), demonstração `mutex_demo --scenario buffer_video`, inspeção de molduras ao vivo (`memory_frames`), métricas (`sim_metrics`) e diagrama de Gantt (`sim_timeline --gantt`).

---

## 10. DOCUMENTAÇÃO TÉCNICA DE REFERÊNCIA

Para detalhes exatos de arquitetura, algoritmos e estruturas de dados, consulte a documentação oficial:
- [Governança e Regras para Agentes (AGENTS.md)](file:///c:/Users/Eduardo/OS%20simulator/AGENTS.md)
- [Roadmap de Execução (PLAN.md)](file:///c:/Users/Eduardo/OS%20simulator/PLAN.md)
- [Arquitetura e Fluxos de Integração (docs/ARCHITECTURE.md)](file:///c:/Users/Eduardo/OS%20simulator/docs/ARCHITECTURE.md)
- [Catálogo de Estruturas de Dados (docs/DATA_STRUCTURES.md)](file:///c:/Users/Eduardo/OS%20simulator/docs/DATA_STRUCTURES.md)
- [Contratos Algorítmicos e Fórmulas (docs/ALGORITHMS.md)](file:///c:/Users/Eduardo/OS%20simulator/docs/ALGORITHMS.md)
- [Dicionário da CLI e Saídas Oficiais (docs/CLI_AND_OUTPUTS.md)](file:///c:/Users/Eduardo/OS%20simulator/docs/CLI_AND_OUTPUTS.md)
- [Ground Truth e Casos de Teste (tests/GROUND_TRUTH.md)](file:///c:/Users/Eduardo/OS%20simulator/tests/GROUND_TRUTH.md)
