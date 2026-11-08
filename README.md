# OS SIMULATOR — SIMULADOR EDUCACIONAL DE SISTEMAS OPERACIONAIS

> **OS Simulator** é um ambiente educacional e laboratório arquitetural modular desenvolvido em **Python 3**, projetado para simular fielmente os componentes fundamentais, fluxos de integração e estruturas de dados de um sistema operacional moderno baseado na arquitetura **Ubuntu Linux**, operando sob a plataforma hospedeira **Windows 11**.

[![Python Version](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/host-Windows%2011-0078D6.svg)](https://www.microsoft.com/windows)
[![Guest OS](https://img.shields.io/badge/target-Ubuntu%20Linux-E95420.svg)](https://ubuntu.com/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## 1. OBJETIVOS ACADÊMICOS E FILOSOFIA DE DESIGN

O propósito primordial do projeto é fornecer uma experiência prática, mensurável e determinística sobre os quatro pilares clássicos da Engenharia de Sistemas Operacionais:

1. **Sistemas de Arquivos (Filesystem):** Hierarquia VFS, metadados POSIX, abstração de i-nodes, estratégias de alocação (Contígua, FAT encadeada e Indexada) e análise de fragmentação interna e externa.
2. **Entrada e Saída (I/O) e Armazenamento Confiável:** Gerenciamento de requisições de E/S, algoritmos de escalonamento mecânico de braço de disco (FCFS, SSTF, SCAN, C-SCAN), simulação de controladores de SSD com *Wear Leveling* e arranjos tolerantes a falhas RAID (RAID 0, RAID 1, RAID 4 e RAID 5 com cálculo de paridade XOR e recuperação de falhas *on-the-fly*).
3. **Segurança e Proteção:** Controle de acesso por identidade e grupos, autenticação com derivação de chave criptográfica e salt aleatório (PBKDF2-HMAC-SHA256), matriz de autorização por Listas de Controle de Acesso (ACL) e permissões octais/rwx POSIX, separação rigorosa de anéis de privilégio (Modo Usuário vs. Modo Kernel), log de auditoria inviolável, integridade de blocos via SHA-256 e antivírus simulado.
4. **Gerenciamento de Memória Real e Virtual:** Memória física particionada em Área Reservada Contígua (para SO e drivers, com controle de fragmentação externa e desfragmentação por compactação deslizante `memory_compact`) e Área Dinâmica Paginada (com MMU, tradução lógica-física, tratamento de interrupções de falta de página / *Page Fault*, políticas de substituição LRU e Segunda Chance/Clock e partição de Swap integrada ao armazenamento secundário simulado).

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

O projeto segue estritamente os princípios de Orientação a Objetos (OOP), responsabilidade única (SRP), desacoplamento por injeção de dependências e comunicação por contratos explícitos mediados pelo `SimulationKernel`.

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
    ├── core/                  # Kernel da simulação, estado global e exceções
    ├── filesystem/            # VFS, Inode, Node, FAT, Indexação
    ├── io/                    # PhysicalDisk, Escalonadores, RAID 0/1/4/5, SSD
    ├── security/              # User, Group, ACL, Auth PBKDF2, AuditLog, Crypto
    ├── memory/                # PhysicalMemory, MMU, PageTable, LRU, Clock, Swap
    ├── process/               # Process, PCB, gerenciamento de ciclo de vida
    └── cli/                   # Shell interativo e formatadores visuais
```

---

## 4. ESTRATÉGIA DE GOVERNANÇA GIT E BRANCHES

O desenvolvimento é rigorosamente incremental. Cada etapa é isolada em sua própria branch de funcionalidade (*feature branch*), submetida à validação contra os cenários do `tests/GROUND_TRUTH.md`, comutada por *Conventional Commits* e integrada à branch de desenvolvimento contínuo `dev`:

- `main`: Branch de lançamentos oficiais consolidados.
- `dev`: Branch de integração contínua das etapas aprovadas.
- `feature/fase-0-documentacao`: Fase 0 (Governança e Arquitetura).
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
- **Dependências Externas:** Nenhuma dependência externa obrigatória; o simulador utiliza exclusivamente a biblioteca padrão do Python.

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

### 6.2. Execução do Shell Interativo (Após implementação das etapas)
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

## 7. COMANDOS DISPONÍVEIS NA CLI SIMULADA

| Comando | Sintaxe Exemplo | Subsistema Responsável |
|---|---|---|
| `mkdir` | `mkdir /sistema/logs` | Sistema de Arquivos (VFS) |
| `create` | `create /sistema/logs/app.log --strategy=indexed` | Sistema de Arquivos |
| `write_file` | `write_file /sistema/logs/app.log "Dados de teste"` | Integração Seg $\to$ FS $\to$ IO $\to$ RAID |
| `read_file` | `read_file /sistema/logs/app.log` | Integração Seg $\to$ FS $\to$ IO |
| `fs_status` | `fs_status` | Sistema de Arquivos |
| `login` | `login carlos` | Segurança e Autenticação |
| `chmod` | `chmod 750 /sistema/config.sys` | Segurança e ACL |
| `encrypt_file` | `encrypt_file /sistema/senhas.txt` | Segurança e Criptografia |
| `antivirus_scan` | `antivirus_scan /sistema` | Segurança e Integridade |
| `create_process` | `create_process Kernel_NetDriver 1024 --reserved` | Processos e Memória |
| `terminate_process` | `terminate_process 102` | Processos e Memória |
| `memory_status` | `memory_status` | Gerenciamento de Memória |
| `memory_compact` | `memory_compact` | Gerenciamento de Memória |
| `translate_address` | `translate_address 103 4100` | Memória (MMU) |
| `execute_step` | `execute_step 103 4100` | Memória, Page Fault e Swap |

---

## 8. SUÍTE DE TESTES E GROUND TRUTH

A validação de conformidade de cada subsistema utiliza testes automatizados orientados pelos cenários determinísticos formais definidos em `tests/GROUND_TRUTH.md`:

```powershell
# Execução dos testes automatizados via unittest (Python padrão)
python -m unittest discover -s tests -p "test_*.py" -v
```

Cenários homologados:
- **`FS-001` a `FS-003`:** Hierarquias de pastas, i-nodes e cálculo de fragmentação interna/externa.
- **`IO-001` e `IO-002`:** Escalonamento SSTF com 208 trilhas percorridas e recuperação de disco com falha em RAID 5 via XOR.
- **`SEC-001` a `SEC-003`:** Autenticação PBKDF2 com salt, bloqueio de acesso 750 com auditoria e integridade SHA-256.
- **`MEM-001` a `MEM-005`:** Fragmentação externa em área reservada, compactação deslizante, paginação, MMU e substituição LRU com Swap.

---

## 9. ROTEIRO DE DEMONSTRAÇÕES FUTURAS

O projeto prevê quatro demonstrações práticas estruturadas a serem entregues sequencialmente com cada etapa:

- **Demonstração 1 (Sistema de Arquivos):** Navegação hierárquica completa no VFS, criação de arquivos com as três estratégias de alocação e exibição de diagnósticos de fragmentação interna e externa.
- **Demonstração 2 (E/S e RAID):** Simulação de múltiplos acessos a trilhas com comparação visual entre FCFS, SSTF e SCAN; montagem de arranjo RAID 5, injeção deliberada de falha de disco e reconstrução de bloco de dados em tempo real via paridade XOR.
- **Demonstração 3 (Segurança e Proteção):** Fluxo de login de usuários, tentativa de acesso proibido com acionamento de bloqueio por ACL, inspeção da trilha de auditoria e varredura de integridade com antivírus simulado.
- **Demonstração 4 (Gerenciamento de Memória):** Alocação e desfragmentação da Área Reservada (`memory_compact`), carga de processos com criação de Page Tables, simulação de Page Fault, desalocação de página vítima com política LRU e descarregamento para o Swap simulado.

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
