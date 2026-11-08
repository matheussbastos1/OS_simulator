# OS SIMULATOR — SIMULADOR EDUCACIONAL DE SISTEMAS OPERACIONAIS

> **OS Simulator** é um ambiente educacional e laboratório arquitetural modular desenvolvido em **Python 3**, projetado para simular fielmente os componentes fundamentais, fluxos de integração e estruturas de dados de um sistema operacional moderno baseado na arquitetura **Ubuntu Linux**, operando sob a plataforma hospedeira **Windows 11**.

[![Python Version](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/host-Windows%2011-0078D6.svg)](https://www.microsoft.com/windows)
[![Guest OS](https://img.shields.io/badge/target-Ubuntu%20Linux-E95420.svg)](https://ubuntu.com/)

---

## 1. OBJETIVOS ACADÊMICOS E FILOSOFIA DE DESIGN

O propósito primordial do projeto é fornecer uma experiência prática, mensurável e determinística sobre os quatro pilares clássicos da Engenharia de Sistemas Operacionais:

1. **Sistemas de Arquivos (Filesystem):** Hierarquia VFS, metadados POSIX, abstração de i-nodes, estratégias de alocação (Contígua, FAT encadeada e Indexada) e análise de fragmentação interna e externa, operando sobre o contrato `BlockDevicePort`.
2. **Entrada e Saída (I/O) e Armazenamento Confiável:** Gerenciamento de requisições de E/S (`IORequest`), algoritmos de escalonamento mecânico de braço de disco (FCFS, SSTF, SCAN, C-SCAN), simulação de controladores de SSD com *Wear Leveling* e arranjos tolerantes a falhas RAID (RAID 0, RAID 1, RAID 4 e RAID 5 com cálculo de paridade XOR e recuperação de falhas *on-the-fly*).
3. **Segurança e Proteção:** Controle de acesso por identidade e grupos, autenticação com derivação de chave criptográfica e salt individual (PBKDF2-HMAC-SHA256 com 600.000 iterações), matriz de autorização por Listas de Controle de Acesso (ACL) e permissões octais/rwx POSIX, anéis de privilégio (Modo Usuário vs. Modo Kernel), log de auditoria inviolável, integridade com HMAC do Kernel e criptografia AES-256-GCM em repouso.
4. **Gerenciamento de Memória Real e Virtual:** Memória física particionada em Área Reservada Contígua (para SO e drivers, com controle de fragmentação externa e desfragmentação por compactação deslizante `memory_compact --reserved`) e Área Dinâmica Paginada (com MMU, tradução lógica-física, tratamento de falta de página considerando origens válidas: Imagem, Zero-fill ou Swap, políticas de substituição LRU e Segunda Chance/Clock e partição de Swap integrada via `BlockDevicePort`).

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
└── os_simulator/              # Código-fonte modular do sistema (a ser implementado)
    ├── core/                  # Kernel, ExecutionContext, exceptions e portas abstratas
    ├── filesystem/            # VFS, Inode, Node, FAT, Indexação e InMemoryBlockDevice
    ├── io/                    # PhysicalDisk, Escalonadores, RAID 0/1/4/5, SSD e IOManager
    ├── security/              # User, Group, ACL, Auth PBKDF2, AuditLog, AES-GCM e Bootstrap
    ├── memory/                # PhysicalMemory, MMU, PageTable, LRU, Clock e SwapManager
    ├── process/               # Process, PCB, gerenciamento de ciclo de vida
    └── cli/                   # Shell interativo e formatadores visuais
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

# Verificar a branch ativa e comutar para dev
git checkout dev
```

### 6.2. Execução do Shell Interativo (Etapa 1 operacional)
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
| `login` | `login --user carlos` | Segurança e Autenticação |
| `chmod` | `chmod 750 /sistema/config.sys` | Segurança e ACL |
| `encrypt_file` | `encrypt_file /home/carlos/segredo.txt --key "MinhaChave123"` | Segurança e Criptografia (AES-256-GCM) |
| `antivirus_scan` | `antivirus_scan /` | Segurança e Integridade |
| `create_process` | `create_process --name "Kernel_DiskDriver" --size 512KB --type critical` | Processos e Área Reservada Contígua |
| `create_process` | `create_process --name "App_Navegador" --size 10KB --type normal` | Processos e Área Dinâmica Paginada |
| `terminate_process` | `terminate_process --name "Kernel_NetDriver"` | Processos e Memória |
| `memory_status` | `memory_status --reserved` | Gerenciamento de Memória |
| `memory_compact` | `memory_compact --reserved` | Gerenciamento de Memória |
| `translate_address` | `translate_address --process App_Navegador --page 1` | Memória (MMU) |
| `execute_step` | `execute_step --process App_Navegador --instruction "LOAD_DATA Página 2"` | Memória, Page Fault e Swap |

---

## 8. SUÍTE DE TESTES E GROUND TRUTH

A validação de conformidade de cada subsistema utiliza testes automatizados orientados pelos cenários determinísticos formais definidos em `tests/GROUND_TRUTH.md`:

```powershell
# Execução dos testes automatizados via unittest (Python padrão)
python -m unittest discover -s tests -p "test_*.py" -v
```

Cenários homologados:
- **`FS-001` a `FS-003`:** Hierarquias de pastas, i-nodes e cálculo de fragmentação interna (2.048 bytes para 10 KB) e externa (0 bytes no indexado).
- **`IO-001` e `IO-002`:** Escalonamento SSTF com 208 trilhas percorridas e recuperação de disco com falha em RAID 5 via XOR.
- **`SEC-001` a `SEC-003`:** Autenticação PBKDF2 com 600.000 iterações, bloqueio de acesso 750 com auditoria e integridade SHA-256/HMAC.
- **`MEM-001` a `MEM-005`:** Fragmentação externa em área reservada, compactação deslizante, paginação, MMU (`MEM-004A` e `MEM-004B`) e ciclo determinístico de Page Fault e Swap com origens válidas (`MEM-005`).

---

## 9. ROTEIRO DE DEMONSTRAÇÕES FUTURAS

O projeto prevê quatro demonstrações práticas estruturadas a serem entregues sequencialmente com cada etapa:

- **Demonstração 1 (Sistema de Arquivos):** Navegação hierárquica no VFS, criação de arquivos com as três estratégias de alocação via `InMemoryBlockDevice` e relatórios de fragmentação interna e externa.
- **Demonstração 2 (E/S e RAID):** Comparação entre FCFS, SSTF e SCAN com medição de deslocamento; montagem de arranjo RAID 5, injeção de falha física e reconstrução de bloco de dados em tempo real via paridade XOR.
- **Demonstração 3 (Segurança e Proteção):** Fluxo de login com PBKDF2 (600k iterações), tentativa de acesso não autorizado negada por ACL (750), auditoria em tempo real, criptografia AES-256-GCM e varredura de antivírus simulado.
- **Demonstração 4 (Gerenciamento de Memória):** Alocação de processos críticos e desfragmentação contígua via `memory_compact --reserved`, carga de processos paginados, simulação de Page Fault respeitando origens válidas, desalocação de página limpa sem swap e swap-out de página suja via `BlockDevicePort`.

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
