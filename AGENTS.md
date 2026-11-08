# GOVERNANÇA, DIRETRIZES E CONTRATOS PARA AGENTES DE IA — OS SIMULATOR

> **Aviso Fundamental para Agentes:** Este documento é a norma suprema de governança do projeto **OS Simulator**. Qualquer agente de IA ou desenvolvedor humano atuando neste repositório deve obrigatoriamente ler, compreender e aderir a todas as regras, contratos de integração e restrições aqui formalizados antes de propor, modificar ou implementar código.

---

## 1. IDENTIDADE E PROPÓSITO DO PROJETO

- **Nome do Projeto:** OS Simulator
- **Repositório Remoto Oficial:** `https://github.com/matheussbastos1/OS_simulator.git`
- **Versão do Antigravity:** 2.29.1 (aplicativo cliente desktop).
- **Sistema Operacional Hospedeiro (Host):** Windows 11 (plataforma de execução física).
- **Sistema Operacional Representado na Simulação (Target/Guest):** Ubuntu Linux (modelo conceitual de comportamento: hierarquia `/`, permissões rwx/octais, usuários/grupos POSIX, i-nodes, paginação, swap).
- **Linguagem de Programação:** Python 3 (versão mínima 3.11+, compatível com Python 3.13).
- **Paradigma de Desenvolvimento:** Orientação a Objetos (OOP) estrita, arquitetura em portas e adaptadores (Hexagonal/Ports and Adapters), baixo acoplamento e alta coesão.
- **Interface Primária de Interação:** Linha de Comando (CLI) e Shell Interativo simulado.
- **Política de Dependências:** Uso preferencial e quase absoluto da **Biblioteca Padrão do Python** (`dataclasses`, `typing`, `abc`, `enum`, `collections`, `hashlib`, `hmac`, `secrets`, `math`, `struct`, `time`). A biblioteca externa `cryptography` fica pré-autorizada exclusivamente para a Etapa 3 (AES-256-GCM), devidamente documentada no ambiente.

### 1.1. Objetivo Acadêmico e Entregas Incrementais
O projeto é um simulador educacional de sistemas operacionais construído incrementalmente em quatro etapas acadêmicas unificadas em uma única arquitetura integrada:
1. **Etapa 1 — Sistema de Arquivos:** Hierarquia VFS, i-nodes, alocações contígua, encadeada (FAT) e indexada, cálculo de fragmentação interna/externa e diagnóstico. Utiliza o adaptador provisório `InMemoryBlockDevice` e a política de autorização provisória `BootstrapSecurityPolicy`.
2. **Etapa 2 — Entrada/Saída (I/O) e RAID:** Gerenciamento de requisições (`IORequest`), escalonamento de braço de disco (FCFS, SSTF, SCAN, C-SCAN), simulação de SSD com Wear Leveling e arranjos RAID (0, 1, 4 e 5 com paridade XOR e recuperação de falha). Substitui o adaptador de bloco por `IOManager` através da mesma porta `BlockDevicePort`.
3. **Etapa 3 — Segurança e Proteção:** Usuários, grupos, autenticação com PBKDF2-HMAC-SHA256 (600.000 iterações e salt criptográfico individual), controle de acesso por listas de controle (ACL) e máscaras rwx/octal, anéis de privilégio (Modo Usuário vs. Modo Kernel), log de auditoria, criptografia AES-256-GCM em repouso e verificação de integridade/antivírus simulado. Substitui `BootstrapSecurityPolicy` pela implementação definitiva do `SecurityManager` via `AuthorizationPort`.
4. **Etapa 4 — Gerenciamento de Memória:** Memória física particionada (área reservada contígua para SO/drivers com compactação `memory_compact` e memória dinâmica paginada), tabelas de páginas, molduras de páginas (frames), MMU e tradução lógica-física, tratamento de falta de página (Page Fault com origens válidas: Imagem, Zero-fill ou Swap), algoritmos de substituição (LRU e Segunda Chance/Clock) e Swap integrado ao subsistema de disco/RAID via `BlockDevicePort`.

---

## 2. REGRA FUNDAMENTAL: ISOLAMENTO TOTAL DA SIMULAÇÃO

A regra arquitetural inegociável do projeto é o **Isolamento da Simulação**. O OS Simulator deve simular os recursos de hardware e de sistema operacional exclusivamente através de estruturas de dados gerenciadas na memória do interpretador Python.

### 2.1. Vedações Absolutas (O que NUNCA fazer)
É expressamente proibido a qualquer agente ou desenvolvedor:
1. **Sistema de Arquivos Real:** Criar diretórios reais no Windows 11 (como `os.mkdir`, `pathlib.Path.mkdir`) para representar diretórios do sistema simulado (`/sistema`, `/home`, etc.).
2. **Arquivos Reais:** Criar, ler ou gravar arquivos físicos no Windows para armazenar o conteúdo dos arquivos simulados.
3. **Blocos de Disco Físicos:** Usar arquivos no Windows para representar setores ou blocos físicos de disco.
4. **Alocação de Memória Nativa/mmap:** Chamar APIs Win32, `ctypes` ou mapeamento de arquivos em memória real para representar a RAM simulada.
5. **Permissões do Hospedeiro:** Consultar ou invocar ACLs, permissões NTFS ou atributos de segurança do Windows 11 para resolver permissões de usuários simulados.
6. **Swap no Disco Real:** Utilizar arquivos temporários reais do Windows como área de troca (swap).
7. **E/S Real e Temporizações Forçadas:** Utilizar chamadas de disco do Windows ou comandos de sleep do host para simular a rotação ou o movimento do braço do disco, exceto para fins visuais de animação na CLI se parametrizado.
8. **Subprocessos do Host:** Executar comandos nativos do Ubuntu via WSL, Docker, Cygwin ou comandos PowerShell/CMD para delegar operações que deveriam ser processadas pelos algoritmos internos da simulação.

### 2.2. Implementação Exigida (O que DEVE ser feito)
Todos os recursos simulados existem em estruturas de dados puramente em memória mantidas pelo Python:
- **Diretórios e Arquivos:** Objetos das classes `DirectoryNode`, `FileNode` e `Inode` organizados em grafo/árvore.
- **Blocos de Disco:** Objetos `DiskBlock` contendo `bytearray` mantidos e pertencentes exclusivamente à camada de armazenamento (`io`/storage abstraction). O `filesystem` faz referência apenas aos endereços lógicos (`block_id: int`).
- **Discos Físicos e RAID:** Objetos `PhysicalDisk` mantendo coleções indexadas de `DiskTrack` e `DiskBlock`; arranjos `RAIDArray` gerenciando a distribuição lógica dos blocos.
- **Memória RAM:** Objetos `PhysicalMemory` gerenciando segmentos contíguos de memória (`MemorySegment`) e listas de molduras (`Frame`).
- **Tabelas de Páginas:** Objetos `PageTable` contendo instâncias de `PageTableEntry`.
- **Swap:** Armazenamento secundário simulado mantido em estruturas gerenciadas pela classe `SwapManager` operando sobre `BlockDevicePort`.
- **Usuários, Grupos e ACLs:** Objetos `User`, `Group`, `ACL` contendo máscaras binárias/octais de permissão.

---

## 3. PADRÕES DE CÓDIGO E BOAS PRÁTICAS

1. **Princípio da Responsabilidade Única (SRP):** Cada módulo, classe e função deve ter um propósito único e bem delineado.
2. **Separação de Camadas e Portas/Adaptadores:**
   - **Camada de Apresentação (CLI):** Trata comandos digitados conforme sintaxe oficial do professor, valida sintaxe, delega a execução ao Kernel e formata saídas visuais.
   - **Camada de Lógica/Kernel:** Orquestra a execução das operações e media a comunicação entre subsistemas via portas abstratas.
   - **Camada de Infraestrutura Simulada:** Implementa os adaptadores de bloco, escalonadores, memória física e estruturas em RAM.
3. **Tipagem Estrita (Type Hints):** Uso obrigatório de anotações de tipo completas em assinaturas de funções, atributos de classe e retornos.
4. **Documentação de Código:** Docstrings detalhadas (padrão Google ou Sphinx) em todas as classes, métodos públicos e módulos.
5. **Tratamento Explícito de Exceções:** Hierarquia de exceções personalizadas herdando de `OSSimulatorException`. Proibido capturar genericamente `except Exception:`.
6. **Convenção de Nomenclatura:**
   - **Código (inglês):** Classes em `PascalCase`, métodos e variáveis em `snake_case`, constantes em `UPPER_SNAKE_CASE`.
   - **Interface e Mensagens da CLI (português):** Mensagens de console, diagnósticos, relatórios e saídas de erro devem ser formatadas em português, preservando os termos técnicos universais de SO (ex.: *i-node*, *page fault*, *frame*, *cluster*, *swap*, *wear leveling*, *parity*, *ACL*).

---

## 4. ESTRUTURA MODULAR DE PACOTES E PORTAS DE INTEGRAÇÃO

```text
os_simulator/
├── __init__.py
├── core/
│   ├── __init__.py
│   ├── kernel.py             # Orquestrador central e estado compartilhado da simulação
│   ├── exceptions.py         # Hierarquia completa de exceções
│   ├── types.py              # Enums globais, type aliases e constantes fundamentais
│   ├── ports.py              # Interfaces abstratas: BlockDevicePort, AuthorizationPort
│   └── context.py            # ExecutionContext (sessão ativa, usuário corrente, cwd)
├── filesystem/
│   ├── __init__.py
│   ├── node.py               # Node, DirectoryNode, FileNode
│   ├── inode.py              # Inode e metadados POSIX
│   ├── vfs.py                # Virtual File System (resolução de caminhos relativos/absolutos)
│   ├── allocation.py         # Estratégias: Contígua, Encadeada (FAT), Indexada
│   ├── service.py            # FileSystemService (operações CRUD simuladas)
│   └── adapters.py           # InMemoryBlockDevice (adaptador provisório da Etapa 1)
├── io/
│   ├── __init__.py
│   ├── disk_block.py         # DiskBlock (propriedade exclusiva da camada de storage)
│   ├── physical_disk.py      # PhysicalDisk e simulação de trilhas/cabeçote
│   ├── io_request.py         # IORequest, enums de operação e prioridade
│   ├── scheduler.py          # Escalonadores de braço: FCFS, SSTF, SCAN, C-SCAN
│   ├── ssd.py                # Simulação de SSD e controlador com Wear Leveling
│   ├── raid.py               # RAIDArray (RAID 0, 1, 4, 5), paridade XOR e rebuild
│   ├── service.py            # IOManager (implementação de BlockDevicePort na Etapa 2)
│   └── adapter.py            # IOBlockDeviceAdapter
├── security/
│   ├── __init__.py
│   ├── bootstrap.py          # BootstrapSecurityPolicy (adaptador provisório Etapas 1 e 2)
│   ├── user.py               # User, Group e contextos de credenciais
│   ├── acl.py                # ACL, permissões rwx e conversões octais (0o755, etc.)
│   ├── auth.py               # AuthenticationService (PBKDF2-HMAC-SHA256, 600k iterações)
│   ├── audit.py              # AuditLog e eventos de conformidade/acesso
│   ├── crypto.py             # Criptografia AES-256-GCM em repouso
│   ├── integrity.py          # Checagem de integridade SHA-256 e antivírus simulado
│   └── service.py            # SecurityManager (implementação definitiva de AuthorizationPort)
├── memory/
│   ├── __init__.py
│   ├── segment.py            # MemorySegment (alocação contígua reservada e fragmentação externa)
│   ├── compaction.py         # Algoritmo de compactação (memory_compact)
│   ├── paging.py             # PageTable, PageTableEntry, Frame e PhysicalMemory
│   ├── mmu.py                # Tradução lógica-física e detecção de Page Fault
│   ├── replacement.py        # Políticas de substituição: LRU e Segunda Chance (Clock)
│   ├── swap.py               # SwapManager integrado via BlockDevicePort
│   └── service.py            # MemoryManager (orquestração de memória física e virtual)
├── process/
│   ├── __init__.py
│   ├── pcb.py                # Process Control Block (PCB) e estados de processo
│   └── manager.py            # ProcessManager (ciclo de vida: create, execute, terminate)
└── cli/
    ├── __init__.py
    ├── shell.py              # Loop interativo REPL
    ├── parser.py             # Tokenizador compatível com sintaxe oficial do professor
    ├── formatters.py         # Formatadores visuais de saída conforme especificações
    └── commands/             # Handlers individuais dos comandos da CLI
```

---

## 5. CONTRATOS DE INTEGRAÇÃO MULTI-SUBSISTEMA VIA PORTAS E ADAPTADORES

O OS Simulator desacopla as dependências temporais entre fases através de duas portas fundamentais:
1. `BlockDevicePort`: Abstração de armazenamento de blocos.
   - **Etapa 1:** Implementada por `InMemoryBlockDevice` (opera sobre array de blocos em RAM).
   - **Etapa 2:** Implementada por `IOBlockDeviceAdapter` conectado ao `IOManager`, `DiskScheduler` e `RAIDController`.
   - **Etapa 4:** Utilizada pelo `SwapManager` para leitura e gravação de páginas trocadas.
2. `AuthorizationPort`: Abstração de fiscalização de segurança.
   - **Etapas 1 e 2:** Implementada por `BootstrapSecurityPolicy` (permite todas as operações ou simula contexto `root` sem exigir senhas/ACL prematuras).
   - **Etapa 3:** Substituída pelo `SecurityManager` definitivo (PBKDF2, ACLs, anéis de privilégio e auditoria), sem demandar alteração no código central do Filesystem.

### Contrato 1: `write_file <caminho> "<conteudo>"`
1. **CLI:** Interpreta o comando e extrai caminho e payload.
2. **Security (`AuthorizationPort`):**
   - *Etapas 1 e 2:* `BootstrapSecurityPolicy.check_write(context, path)` aprova como contexto inicial de sistema.
   - *Etapa 3+:* `SecurityManager.check_write(context, path)` valida ACL e registra no `AuditLog`.
3. **VFS (`VirtualFileSystem`):** Resolve o caminho canônico a partir do CWD.
4. **Filesystem (`FileSystemService`):** Localiza ou cria o `Inode`. Determina o número de blocos necessários e aloca via estratégia ativa (Contígua, FAT ou Indexada).
5. **Security (Criptografia — Etapa 3):** Se criptografado, aplica AES-256-GCM com nonce exclusivo e tag de autenticação.
6. **Armazenamento (`BlockDevicePort`):**
   - *Etapa 1:* `InMemoryBlockDevice.write_block(block_id, data)`.
   - *Etapa 2+:* Despachado como `IORequest`, enfileirado no `DiskScheduler`, distribuído pelo `RAIDController` (com cálculo XOR) e gravado no `PhysicalDisk`.

### Contrato 2: `read_file <caminho>`
1. **CLI:** Recebe a solicitação.
2. **Security (`AuthorizationPort`):** Valida permissão de leitura (`check_read`).
3. **VFS & Filesystem:** Resolve caminho e consulta tabela de blocos do `Inode`.
4. **Armazenamento (`BlockDevicePort`):**
   - *Etapa 1:* `InMemoryBlockDevice.read_block(block_id)`.
   - *Etapa 2+:* Despacha `IORequest`, processa no escalonador de disco e lê do RAID (executando reconstrução XOR on-the-fly se disco em falha).
5. **Security (Criptografia / Integridade — Etapa 3):** Descriptografa AES-256-GCM e valida integridade SHA-256.
6. **CLI:** Exibe o conteúdo decodificado.

### Contrato 3: `create_process --name <nome> --size <tam> --type <critical|normal>`
1. **Security (`AuthorizationPort`):** Verifica se possui privilégios administrativos para processos `--type critical` (área reservada).
2. **Process Manager:** Instancia o `Process` (PCB) no estado `READY`.
3. **Memory Manager:**
   - Se `--type critical`: Aloca `MemorySegment` contíguo na Área Reservada via First-Fit / Best-Fit. Notifica fragmentação externa se necessário.
   - Se `--type normal`: Calcula páginas necessárias ($\lceil \text{tamanho} / \text{page\_size} \rceil$), aloca `PageTable` e mapeia molduras livres (`Frame`).

### Contrato 4: `terminate_process --name <nome>` (ou `--pid <pid>`)
1. **Process Manager:** Atualiza estado do processo para `TERMINATED`.
2. **Memory Manager:** Libera segmentos contíguos da Área Reservada ou desocupa frames e slots de Swap associados, restaurando a disponibilidade de memória física.
3. **Security:** Registra encerramento no log de auditoria.

### Contrato 5: `execute_step --process <nome> --instruction <instrucao>` / Falta de Página
1. **MMU:** Decompõe endereço em Página Lógica ($p$) e Deslocamento ($d$).
2. **Page Table Lookup:** Consulta `PageTableEntry` para a página $p$.
3. **Page Fault Handling:** Se `present == False`:
   - Interrompe instrução e emite sinal de `PageFaultException`.
   - Localiza moldura livre na RAM dinâmica. Se cheia, aciona substituição (LRU ou Segunda Chance).
   - Vítima limpa (`dirty == False`): pode ser descartada se houver origem recuperável.
   - Vítima modificada (`dirty == True`): gravada na partição de Swap via `BlockDevicePort`.
   - Carrega a página solicitada a partir de sua **origem válida**:
     - *Imagem inicial do processo:* se for segmento de código/dados imutáveis.
     - *Zero-fill-on-demand:* se for heap/stack virgem (inicializado com zeros na moldura, sem I/O de Swap!).
     - *Slot de Swap:* se a página tiver sido previamente descarregada para o Swap.
   - Atualiza `PageTableEntry`: `present = True`, `frame_id = frame`, `referenced = True`.
4. **Tradução:** Calcula endereço físico: $( \text{frame\_id} \times \text{frame\_size} ) + d$.

---

## 6. PROTOCOLO DE TRABALHO PARA AGENTES E DESENVOLVEDORES

Ao receber uma ordem de desenvolvimento em qualquer etapa:

1. **Leitura Obrigatória:** Consultar este `AGENTS.md`, o roadmap em `PLAN.md` e a documentação técnica correspondente em `docs/`.
2. **Verificação de Escopo:** Trabalhar exclusivamente na branch da respectiva etapa (`feature/etapa-X-...` ou `fix/...`). Nunca misturar implementações de fases distintas.
3. **Sem Mudanças Unilaterais:** É proibido alterar os contratos arquiteturais ou assinaturas de métodos base sem atualizar formalmente a documentação e justificar a modificação.
4. **Testes e Ground Truth:** Todo código implementado deve passar obrigatoriamente pelos cenários de teste descritos em `tests/GROUND_TRUTH.md`.
5. **Git e Commits:** Utilizar estritamente o padrão **Conventional Commits** (ex.: `fix(docs): refine phase 0 architecture`). Nunca realizar commits vazios nem usar `--force`.
6. **Preservação de Integridade:** Não inserir credenciais, dados sensíveis ou caminhos absolutos locais do Windows 11 no código.
